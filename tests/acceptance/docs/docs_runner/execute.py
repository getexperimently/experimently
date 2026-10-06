"""Walk one journey in a browser, one log line per step.

Steps run in order. A step that fails stops the guide: every later step is NOT
RUN (``earlier-step-failed``). A step whose journey file declares ``not_run``
is NOT RUN with that reason, and ``ref: doc-examples`` is NOT RUN
(``doc-examples``): Doc Examples runs those blocks. Nothing is skipped.

Elements are found only by role and accessible name, or by label, with exact
matching. Waiting is Playwright's own: an action waits for its element and an
expectation retries until it holds or ``DOCS_JOURNEY_TIMEOUT_MS`` (default
10000) passes. No step sleeps; the crawl's one re-ask is below.

Files, under ``<run dir>/<journey>/``: ``NN-<step>.expected.aria.yml`` (the
expected ARIA snapshot, written before the step runs), ``NN-<step>.png`` and
``NN-<step>.aria.yml`` (the screen and its ARIA snapshot, after the step, or
when it fails), ``NN-<step>.api.json`` (an api step's status and the values at
its expected JSON paths), ``NN-<step>.expected.json`` (a ``crawl: nav`` step's
pages, URLs and headings, read from the site's source before the step runs),
``NN-<step>.crawl.json`` (what a crawl saw, and what differed) and
``NN-<step>.observed.json`` (what a step that keeps no screen saw when it
failed: a ``keep`` step, or one with ``snapshot: false``). A ``video: true``
journey is recorded to ``videos/<journey>.webm`` (1280x720) unless
``DOCS_JOURNEY_RECORD_VIDEO=0``.

Nothing a run makes up or keeps is written (``redaction.py``): every text above
goes through the run's redactor, a screenshot masks any element whose text
holds a value the journey keeps, an api step's value at a credential's JSON
path is written as ``(redacted)``, and a journey that has a secret is never
recorded.

The two crawls visit the nav pages once per journey and share what they saw.
A page or link that answers 5xx or nothing is asked once more,
``site.RETRY_SECONDS`` later (``site.py`` says why); that is the only wait
here that is not Playwright's own.
A search starts from the site's home page, so the results it reads are its
own: the site's search box is MkDocs Material's (a textbox named "Search"),
and its results are read once the count above them is shown.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, Page, Playwright, expect
from playwright.sync_api import Error as PlaywrightError

from docs_runner import redaction, registry, site
from docs_runner.checks import (
    StepFailed,
    describe_action,
    describe_expect,
    json_at,
    one_line,
    parse_number,
    same_json,
)
from docs_runner.guide import Guide
from docs_runner.log import FAIL, NOT_RUN, PASS, STRUCTURAL_ONLY, Log, Record
from docs_runner.model import LOCAL_URL, SEARCH_TOP, Journey, Named, Step
from docs_runner.oracles import ORACLES
from docs_runner.stacks import Running

VIEWPORT = {"width": 1280, "height": 720}
#: The count MkDocs Material shows above the search results once they are in.
SEARCH_COUNT = re.compile(r"^(?:No|[0-9]+) matching documents?$")


@dataclass
class Settings:
    run_dir: Path
    run_id: str
    sha: str
    timeout_ms: int = 10000
    record_video: bool = True


class JourneyRunner:
    """Runs journeys with one browser and the Playwright request API."""

    def __init__(
        self, playwright: Playwright, browser: Browser, log: Log, settings: Settings
    ):
        self.playwright = playwright
        self.browser = browser
        self.log = log
        self.settings = settings
        self.tokens: Dict[Tuple[str, str], str] = {}
        #: Every value the run makes up, keeps or signs in for; never written.
        self.redactor = redaction.Redactor()
        #: The current journey's passwords and kept values, by name.
        self.secrets: Dict[str, str] = {}
        #: What the crawls saw, per site and source: (nav pages, visit per page).
        self.visits: Dict[
            Tuple[str, str], Tuple[List[site.NavPage], Dict[str, Any]]
        ] = {}
        expect.set_options(timeout=settings.timeout_ms)

    # -- files -------------------------------------------------------------
    def _name(self, journey_id: str, number: int, step: Step, suffix: str) -> str:
        return f"{journey_id}/{number:02d}-{step.id}{suffix}"

    def _write(self, name: str, text: str) -> str:
        path = self.settings.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.redactor.redact(text), encoding="utf-8")
        return name

    def _screen(self, page: Page, journey_id: str, number: int, step: Step) -> str:
        name = self._name(journey_id, number, step, ".png")
        path = self.settings.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(
                path=str(path),
                mask=[page.get_by_text(value) for value in self.secrets.values()],
            )
            aria = page.locator("body").aria_snapshot()
        except PlaywrightError as error:
            aria = f"(no ARIA snapshot: {one_line(error)})"
        self._write(self._name(journey_id, number, step, ".aria.yml"), aria + "\n")
        return name if path.is_file() else ""

    def _no_screen(
        self, journey_id: str, number: int, step: Step, observed: str
    ) -> str:
        """What a failed step that keeps no screen saw, as text."""
        why = step.snapshot_reason or "a keep step keeps no screen"
        return self._write(
            self._name(journey_id, number, step, ".observed.json"),
            json.dumps({"error": observed, "screen": f"not kept: {why}"}, indent=2)
            + "\n",
        )

    # -- the API -----------------------------------------------------------
    def _headers(self, running: Running, caller: str, api) -> Dict[str, str]:
        if caller == "anonymous":
            return {}
        key = (running.api_url, caller)
        if key not in self.tokens:
            email, password = running.accounts[caller]
            answer = api.post(
                "/api/v1/auth/login", data={"email": email, "password": password}
            )
            if answer.status != 200:
                raise StepFailed(f"signing in as {caller} answered {answer.status}")
            self.tokens[key] = answer.json()["access_token"]
            self.redactor.add(self.tokens[key])
        return {"Authorization": f"Bearer {self.tokens[key]}"}

    def _api_step(
        self, step: Step, running: Running, api, journey_id: str, number: int
    ):
        call = step.do.api
        answer = api.fetch(
            call.path,
            method=call.method,
            headers=self._headers(running, call.as_, api),
            data=call.body,
        )
        seen: Dict[str, Any] = {"status": answer.status}
        problems: List[str] = []
        if step.expect.status is not None and answer.status != step.expect.status:
            problems.append(f"status {answer.status}, expected {step.expect.status}")
        if step.expect.json_:
            try:
                document = answer.json()
            except (PlaywrightError, ValueError):
                document = None
                problems.append("the answer is not JSON")
            for path, wanted in step.expect.json_.items():
                try:
                    value = json_at(document, path)
                except KeyError:
                    seen[path] = "(absent)"
                    problems.append(f"json {path} absent")
                    continue
                shown = value
                if redaction.redacted_path(path) and not same_json(value, wanted):
                    shown = redaction.REDACTED
                    if (
                        redaction.credential_path(path)
                        and isinstance(value, str)
                        and len(value) >= redaction.MIN_LENGTH
                    ):
                        self.redactor.add(value)
                seen[path] = shown
                if not same_json(value, wanted):
                    problems.append(f"json {path} = {json.dumps(shown)}")
        snapshot = self._write(
            self._name(journey_id, number, step, ".api.json"),
            json.dumps(seen, indent=2, ensure_ascii=False) + "\n",
        )
        observed = "; ".join(problems) if problems else f"status {answer.status}"
        if problems:
            raise _Failed(one_line(observed), snapshot)
        return one_line(observed), snapshot

    # -- the browser -------------------------------------------------------
    @staticmethod
    def _role(page: Page, named: Named):
        return page.get_by_role(named.role, name=named.name, exact=True).first

    @staticmethod
    def _published(running: Running, url: str) -> str:
        """Where the guide's *url* is on this stack, or StepFailed when nowhere."""
        match = LOCAL_URL.match(url)
        port = int(match["port"]) if match else 0
        if port not in running.published:
            served = ", ".join(str(p) for p in sorted(running.published)) or "none"
            raise StepFailed(
                f"{url}: the stack serves nothing on port {port} by default"
                f" (docker-compose.yml's default ports here: {served})"
            )
        return running.published[port] + (match["path"] or "/")

    def _act(self, step: Step, page: Page, running: Running):
        """Do the step's action; the navigation's response for a goto or an open."""
        do = step.do
        if do.open is not None:
            target = self._published(running, do.open)
        try:
            if do.goto is not None:
                return page.goto(urljoin(running.base_url, do.goto.lstrip("/")))
            if do.open is not None:
                return page.goto(target)
            if do.click is not None:
                self._role(page, do.click).click()
            elif do.fill is not None:
                value = do.fill.value
                if do.fill.secret is not None:
                    value = self.secrets[do.fill.secret]
                page.get_by_label(do.fill.label, exact=True).fill(value)
            elif do.select is not None:
                page.get_by_label(do.select.label, exact=True).select_option(
                    label=do.select.option
                )
            elif do.search is not None:
                page.goto(running.base_url)
                page.get_by_role("textbox", name="Search", exact=True).fill(do.search)
        except PlaywrightError as error:
            raise StepFailed(
                f"could not {describe_action(step)}: {one_line(error, 160)}"
            ) from None
        return None

    def _keep_step(self, step: Step, page: Page) -> str:
        """Read the one element's text and keep it; never written, only its length."""
        keep = step.do.keep
        within = keep.within
        element = page.get_by_role(
            within.role, name=within.name, exact=True
        ).get_by_role(keep.role)
        where = f'the {keep.role} in the {within.role} "{within.name}"'
        self._holds(
            lambda: expect(element).to_have_count(1),
            f'not exactly one {keep.role} in the {within.role} "{within.name}"',
        )
        try:
            value = element.inner_text().strip()
        except PlaywrightError as error:
            raise StepFailed(
                f"could not read {where}: {one_line(error, 160)}"
            ) from None
        if len(value) < redaction.MIN_LENGTH:
            raise StepFailed(
                f"{where} holds {len(value)} characters, fewer than"
                f" {redaction.MIN_LENGTH}"
            )
        self.redactor.add(value)
        self.secrets[keep.secret] = value
        return f"kept {where} as {keep.secret} ({len(value)} characters)"

    @staticmethod
    def _holds(check, failure: str) -> None:
        """Run a Playwright expectation; a failure says *failure*, not the call log."""
        try:
            check()
        except AssertionError:
            raise StepFailed(failure) from None

    def _search_step(self, step: Step, page: Page, running: Running) -> str:
        self._act(step, page, running)
        query, wanted = step.do.search, step.expect.found
        self._holds(
            lambda: expect(page.locator(".md-search-result__meta")).to_have_text(
                SEARCH_COUNT
            ),
            f'searching for "{query}" showed no results count',
        )
        results = page.locator(
            "li.md-search-result__item > a.md-search-result__link"
        ).evaluate_all("links => links.map(link => link.href)")
        place = site.rank(results, running.base_url, wanted)
        if place is None or place > SEARCH_TOP:
            shown = ", ".join(
                "/" + site.on_site(running.base_url, site.strip(url))
                for url in results[:SEARCH_TOP]
            )
            raise StepFailed(
                f'searching for "{query}": {wanted} is not among the first'
                f" {SEARCH_TOP} results ({shown or 'none'})"
            )
        return f'searching for "{query}": {wanted} is result {place} of {len(results)}'

    # -- the documentation site --------------------------------------------
    @staticmethod
    def _open(page: Page, url: str):
        """(the navigation's response, or None; the error, or "")."""
        try:
            return page.goto(url, wait_until="domcontentloaded"), ""
        except PlaywrightError as error:
            return None, one_line(error, 160)

    def _visit(self, page: Page, url: str, base: str) -> Dict[str, Any]:
        """Open one page of the site: its status, where it ended, its heading, its links.

        A page that answers 5xx or nothing is opened once more, after
        ``site.RETRY_SECONDS`` (``site.py`` says why).
        """
        response, error = self._open(page, url)
        retried = site.transient(response.status if response is not None else None)
        if retried:
            time.sleep(site.RETRY_SECONDS)
            response, error = self._open(page, url)
        if error:
            return {"url": url, "status": None, "error": error, "retried": retried}
        final = page.url
        headings = page.get_by_role("main").get_by_role("heading", level=1)
        heading = headings.first.inner_text() if headings.count() else None
        hrefs = page.locator("a[href]").evaluate_all(
            "links => links.map(link => link.href)"
        )
        return {
            "url": "/" + site.on_site(base, url),
            "status": response.status if response is not None else None,
            "final": "/" + site.on_site(base, site.strip(final)),
            "on_site": site.within(final, base),
            "heading": site.normalise(heading) if heading is not None else None,
            "links": site.site_links(hrefs, base),
            "retried": retried,
        }

    def _site_visits(self, page: Page, running: Running):
        """The nav pages of the site's source, and what was seen at each; once per site."""
        if running.source is None:
            raise StepFailed(f"the {running.name} stack names no site source")
        key = (running.base_url, str(running.source))
        if key not in self.visits:
            pages = site.nav_pages(site.Source(running.source))
            seen = {
                nav.path: self._visit(
                    page, urljoin(running.base_url, nav.url), running.base_url
                )
                for nav in pages
            }
            self.visits[key] = (pages, seen)
        return self.visits[key]

    def _expected_nav(self, running: Running, name: str) -> str:
        """Write what ``crawl: nav`` expects, from the source, before it runs."""
        if running.source is None:
            return STRUCTURAL_ONLY
        try:
            pages = site.nav_pages(site.Source(running.source))
        except site.SiteError:
            return STRUCTURAL_ONLY
        rows = [
            {"page": p.path, "url": "/" + p.url, "heading": p.heading} for p in pages
        ]
        return self._write(name, json.dumps(rows, indent=2, ensure_ascii=False) + "\n")

    def _crawl_step(
        self,
        step: Step,
        page: Page,
        running: Running,
        request,
        journey_id: str,
        number: int,
    ) -> Tuple[str, str]:
        name = self._name(journey_id, number, step, ".crawl.json")
        try:
            pages, seen = self._site_visits(page, running)
        except site.SiteError as error:
            raise _Failed(
                one_line(error),
                self._write(name, json.dumps({"error": str(error)}) + "\n"),
            ) from None
        if step.do.crawl == "nav":
            problems = site.compare_headings(pages, seen)
            checked, what = len(pages), "nav pages"
            record: Dict[str, Any] = {
                "problems": problems,
                "seen": {
                    path: {k: v for k, v in visit.items() if k != "links"}
                    for path, visit in seen.items()
                },
            }
        else:
            source = site.Source(running.source)
            written = site.site_url(source) or running.base_url
            links: Dict[str, str] = {}
            for nav in pages:
                for link in seen[nav.path].get("links", []):
                    links.setdefault(link, "/" + nav.url)
            for path, link in site.absolute_links(source, [nav.path for nav in pages]):
                links.setdefault(
                    site.to_stack(link, written, running.base_url), f"{path} (source)"
                )

            def fetch(url: str) -> Tuple[int, str]:
                answer = request.get(url, max_redirects=0)
                return answer.status, answer.headers.get("location", "")

            resolved = [site.resolve(link, running.base_url, fetch) for link in links]
            problems = [
                f"/{site.on_site(running.base_url, r.link)} (on {links[r.link]}): {r.problem}"
                for r in resolved
                if r.problem
            ]
            checked, what = len(links), "links to the site"
            record = {
                "problems": problems,
                "links": {
                    "/" + site.on_site(running.base_url, r.link): {
                        "on": links[r.link],
                        "status": r.status,
                        "retried": r.retried,
                    }
                    for r in resolved
                },
            }
        snapshot = self._write(
            name,
            json.dumps({"checked": checked, **record}, indent=2, ensure_ascii=False)
            + "\n",
        )
        if problems:
            raise _Failed(
                one_line(
                    f"{len(problems)} of {checked} {what}: " + "; ".join(problems)
                ),
                snapshot,
            )
        if not checked:
            raise _Failed(f"no {what} to check", snapshot)
        return f"{checked} {what}, every one as expected", snapshot

    def _browser_step(self, step: Step, page: Page, running: Running) -> str:
        response = self._act(step, page, running)
        wanted = step.expect

        def here() -> str:
            return urlparse(page.url).path or "/"

        if wanted.status is not None:
            status = response.status if response is not None else None
            if status != wanted.status:
                raise StepFailed(f"status {status}, expected {wanted.status}")
        if wanted.url is not None:
            base = running.base_url
            if step.do.open is not None:
                opened = urlparse(page.url)
                base = f"{opened.scheme}://{opened.netloc}/"
            url = urljoin(base, wanted.url.lstrip("/"))
            self._holds(
                lambda: expect(page).to_have_url(url),
                f"at {here()}, not {wanted.url}",
            )
        for named in wanted.visible or []:
            self._holds(
                lambda named=named: expect(self._role(page, named)).to_be_visible(),
                f'no {named.role} "{named.name}" visible at {here()}',
            )
        if wanted.text is not None:
            self._holds(
                lambda: expect(
                    page.get_by_text(wanted.text, exact=True).first
                ).to_be_visible(),
                f'no text "{wanted.text}" visible at {here()}',
            )
        if wanted.number is not None:
            number = wanted.number
            element = self._role(page, number.locator)
            self._holds(
                lambda: expect(element).to_be_visible(),
                f'no {number.locator.role} "{number.locator.name}" visible at {here()}',
            )
            shown = parse_number(element.inner_text())
            oracle = ORACLES[number.oracle.name](**number.oracle.args)
            if shown != oracle:
                raise StepFailed(f"shows {shown:g}; the oracle gives {oracle:g}")
        if wanted.aria is not None:
            self._holds(
                lambda: expect(page.locator("body")).to_match_aria_snapshot(
                    wanted.aria
                ),
                f"the screen at {here()} does not match its expected ARIA snapshot",
            )
        observed = f"at {here()}"
        if response is not None:
            observed += f" (status {response.status})"
        return observed

    # -- one journey -------------------------------------------------------
    def run(
        self, journey: Journey, journey_id: str, running: Running, guide: Guide
    ) -> List[Record]:
        settings = self.settings
        options: Dict[str, Any] = {"viewport": VIEWPORT}
        video_dir = settings.run_dir / "videos" / journey_id
        self.secrets = {}
        for name in journey.passwords:
            self.secrets[name] = redaction.make_password()
            self.redactor.add(self.secrets[name])
        if journey.video and settings.record_video and not journey.has_secrets:
            options.update(record_video_dir=str(video_dir), record_video_size=VIEWPORT)
        context = self.browser.new_context(**options)
        context.set_default_timeout(settings.timeout_ms)
        page = context.new_page()
        api = None
        if running.api_url:
            api = self.playwright.request.new_context(base_url=running.api_url)
        request = None
        if running.source is not None:
            request = self.playwright.request.new_context()
        anchors = guide.anchors
        records: List[Record] = []
        failed = False
        try:
            for number, step in enumerate(journey.steps, 1):
                record = self._step(
                    journey,
                    journey_id,
                    number,
                    step,
                    running,
                    page,
                    api,
                    request,
                    anchors,
                    failed,
                )
                failed = failed or record.result == FAIL
                self.log.write(record)
                records.append(record)
        finally:
            video = page.video
            context.close()
            if api is not None:
                api.dispose()
            if request is not None:
                request.dispose()
            if video is not None:
                self._keep_video(video, journey_id)
        return records

    def _keep_video(self, video, journey_id: str) -> None:
        try:
            source = Path(video.path())
        except PlaywrightError:
            return
        target = self.settings.run_dir / "videos" / f"{journey_id}.webm"
        if source.is_file():
            source.replace(target)
            try:
                source.parent.rmdir()
            except OSError:
                pass

    def _step(
        self,
        journey: Journey,
        journey_id: str,
        number: int,
        step: Step,
        running: Running,
        page: Page,
        api,
        request,
        anchors: Dict[str, str],
        failed: bool,
    ) -> Record:
        expected_snapshot = ""
        if step.expect is not None:
            expected_snapshot = STRUCTURAL_ONLY
            if step.expect.aria is not None:
                expected_snapshot = self._write(
                    self._name(journey_id, number, step, ".expected.aria.yml"),
                    step.expect.aria.rstrip("\n") + "\n",
                )
        elif step.do.crawl == "nav":
            expected_snapshot = self._expected_nav(
                running, self._name(journey_id, number, step, ".expected.json")
            )
        elif step.do.crawl == "links":
            expected_snapshot = STRUCTURAL_ONLY
        base = {
            "run": self.settings.run_id,
            "sha": self.settings.sha,
            "stack": journey.stack,
            "guide": journey.guide,
            "step": number,
            "step_id": step.id,
            "heading": anchors.get(step.doc) or step.doc,
            "action": describe_action(step),
            "expected": describe_expect(step),
            "failure_signature": step.fail,
            "expected_snapshot": expected_snapshot,
        }
        reason = ""
        if failed:
            reason = registry.EARLIER_STEP_FAILED
        elif step.not_run is not None:
            reason = step.not_run
        elif step.do.kind == "ref":
            reason = registry.DOC_EXAMPLES
        if reason:
            return Record(
                **base, result=NOT_RUN, reason=reason, observed="", snapshot="", ms=0
            )
        started = time.monotonic()
        snapshot = ""
        try:
            if step.do.kind == "api":
                observed, snapshot = self._api_step(
                    step, running, api, journey_id, number
                )
            elif step.do.kind == "crawl":
                observed, snapshot = self._crawl_step(
                    step, page, running, request, journey_id, number
                )
            elif step.do.kind == "keep":
                observed = self._keep_step(step, page)
            else:
                if step.do.kind == "search":
                    observed = self._search_step(step, page, running)
                else:
                    observed = self._browser_step(step, page, running)
                if step.takes_screenshot:
                    snapshot = self._screen(page, journey_id, number, step)
            result = PASS
        except _Failed as failure:
            observed, snapshot, result = failure.observed, failure.snapshot, FAIL
        except (AssertionError, PlaywrightError, KeyError) as error:
            observed = self.redactor.redact(one_line(error) or type(error).__name__)
            result = FAIL
            if step.takes_screenshot:
                snapshot = self._screen(page, journey_id, number, step)
            elif step.in_browser:
                snapshot = self._no_screen(journey_id, number, step, observed)
            else:
                suffix = ".crawl.json" if step.do.kind == "crawl" else ".api.json"
                snapshot = self._write(
                    self._name(journey_id, number, step, suffix),
                    json.dumps({"error": observed}, indent=2) + "\n",
                )
        ms = int((time.monotonic() - started) * 1000)
        return Record(
            **base,
            result=result,
            reason="",
            observed=self.redactor.redact(observed),
            snapshot=snapshot,
            ms=ms,
        )


class _Failed(Exception):
    def __init__(self, observed: str, snapshot: str):
        super().__init__(observed)
        self.observed = observed
        self.snapshot = snapshot


def first_failure(records: List[Record]) -> Optional[Record]:
    return next((record for record in records if record.result == FAIL), None)
