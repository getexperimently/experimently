"""Walk one journey in a browser, one log line per step.

Steps run in order. A step that fails stops the guide: every later step is NOT
RUN (``earlier-step-failed``). A step whose journey file declares ``not_run``
is NOT RUN with that reason, and ``ref: doc-examples`` is NOT RUN
(``doc-examples``): Doc Examples runs those blocks. Nothing is skipped.

Elements are found only by role and accessible name, or by label, with exact
matching. Waiting is Playwright's own: an action waits for its element and an
expectation retries until it holds or ``DOCS_JOURNEY_TIMEOUT_MS`` (default
10000) passes. No step sleeps; the crawl's one re-ask and the sign-in pacer
(``pacer.py``: no faster than the stack's 10 sign-ins a minute, the step that
waited saying so) are the only waits that are not Playwright's own.

Files, under ``<run dir>/<journey>/``: ``NN-<step>.expected.aria.yml`` (the
expected ARIA snapshot, written before the step runs), ``NN-<step>.png`` and
``NN-<step>.aria.yml`` (the screen and its ARIA snapshot, after the step, or
when it fails), ``NN-<step>.api.json`` (an api step's status and the values at
its expected JSON paths), ``NN-<step>.expected.json`` (a ``crawl: nav`` step's
pages, URLs and headings, read from the site's source before the step runs),
``NN-<step>.crawl.json`` (what a crawl saw, and what differed),
``NN-<step>.observed.json`` (what a step that keeps no screen saw when it
failed: a ``keep`` step, or one with ``snapshot: false``). A ``video: true``
journey is recorded to ``videos/<journey>.webm`` (1280x720) unless
``DOCS_JOURNEY_RECORD_VIDEO=0``.

Nothing a run makes up or keeps is written (``redaction.py``): every text above
goes through the run's redactor, a screenshot masks any element whose text
holds a value the journey keeps, an api step's value at a credential's JSON
path is written as ``(redacted)``, and a journey that has a secret is never
recorded.

A ``traffic`` step writes ``NN-<step>.expected.json`` (the population chosen,
written before it is sent) and ``NN-<step>.traffic.json`` (what was sent and
answered, in counts). Values an api step saves (``values.py``) are the
journey's own, cleared when the next journey starts; a value saved as a secret
is kept with the journey's other secrets and goes to the redactor.

The two crawls visit the nav pages once per journey and share what they saw.
A page or link that answers 5xx or nothing is asked once more,
``site.RETRY_SECONDS`` later (``site.py`` says why); with the sign-in pacer,
that is the only wait here that is not Playwright's own.
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

from docs_runner import pacer as pacing
from docs_runner import redaction, registry, site, values
from docs_runner import traffic as population
from docs_runner.checks import (
    StepFailed,
    agrees,
    describe_action,
    describe_expect,
    json_at,
    one_line,
    parse_number,
    same_json,
    within,
)
from docs_runner.guide import Guide
from docs_runner.log import FAIL, NOT_RUN, PASS, STRUCTURAL_ONLY, Log, Record
from docs_runner.model import LOCAL_URL, SEARCH_TOP, Cell, Journey, Named, Oracle, Step
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
        #: The run's sign-ins, paced to the stack's limit (``pacer.py``).
        self.pacer = pacing.SignInPacer()
        #: Seconds the current step waited for the sign-in limit.
        self.waited = 0.0
        #: Every value the run makes up, keeps or signs in for; never written.
        self.redactor = redaction.Redactor()
        #: The current journey's passwords and kept values, by name.
        self.secrets: Dict[str, str] = {}
        #: The current journey's saved values (``values.py``), by name.
        self.values: Dict[str, str] = {}
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
            self.waited += self.pacer.wait()
            self.pacer.record()
            answer = api.post(
                pacing.SIGN_IN_PATH, data={"email": email, "password": password}
            )
            if answer.status != 200:
                raise StepFailed(f"signing in as {caller} answered {answer.status}")
            self.tokens[key] = answer.json()["access_token"]
            self.redactor.add(self.tokens[key])
        return {"Authorization": f"Bearer {self.tokens[key]}"}

    def _note_sign_in(self, request) -> None:
        """Record each sign-in the browser sends, whatever sent it."""
        if (
            request.method == "POST"
            and urlparse(request.url).path == pacing.SIGN_IN_PATH
        ):
            self.pacer.record()

    def _secret(self, name: str) -> str:
        if name not in self.secrets:
            raise StepFailed(f"no secret saved or kept as {name!r}")
        return self.secrets[name]

    @staticmethod
    def _oracle(oracle: Oracle) -> float:
        return float(ORACLES[oracle.name](**oracle.args))

    def _api_step(
        self, step: Step, running: Running, api, journey_id: str, number: int
    ):
        call = step.do.api
        try:
            path = values.substitute(call.path, self.values)
            body = values.substitute_in(call.body, self.values)
        except KeyError as error:
            raise StepFailed(str(error.args[0])) from None
        headers = self._headers(running, call.as_, api)
        if call.key is not None:
            headers = {"X-API-Key": self._secret(call.key)}
        answer = api.fetch(path, method=call.method, headers=headers, data=body)
        expect_ = step.expect
        seen: Dict[str, Any] = {"status": answer.status}
        problems: List[str] = []
        if expect_.status is not None and answer.status != expect_.status:
            problems.append(f"status {answer.status}, expected {expect_.status}")
        document = None
        if expect_.json_ or expect_.computed or step.save:
            try:
                document = answer.json()
            except (PlaywrightError, ValueError):
                problems.append("the answer is not JSON")
        secret_paths = {s.path for s in (step.save or {}).values() if s.secret}
        for path, wanted in (expect_.json_ or {}).items():
            try:
                value = json_at(document, path)
            except KeyError:
                seen[path] = "(absent)"
                problems.append(f"json {path} absent")
                continue
            shown = value
            if path in secret_paths:
                shown = redaction.REDACTED
            elif redaction.redacted_path(path) and not same_json(value, wanted):
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
        for path, computed in (expect_.computed or {}).items():
            oracle = self._oracle(computed.oracle)
            try:
                value = json_at(document, path)
            except KeyError:
                seen[path] = "(absent)"
                problems.append(f"json {path} absent")
                continue
            seen[path] = {"value": value, "oracle": oracle, "rel": computed.rel}
            if not within(value, oracle, computed.rel):
                problems.append(
                    f"json {path} = {json.dumps(value)}; {computed.oracle.name}"
                    f" gives {oracle!r}"
                )
        for name, save in (step.save or {}).items():
            try:
                value = json_at(document, save.path)
            except KeyError:
                problems.append(
                    f"json {save.path} absent, so nothing is saved as {name}"
                )
                continue
            if save.secret:
                if not isinstance(value, str) or len(value) < redaction.MIN_LENGTH:
                    problems.append(f"json {save.path} is not a key to keep as {name}")
                    continue
                self.redactor.add(value)
                self.secrets[name] = value
                seen[save.path] = redaction.REDACTED
                continue
            try:
                self.values[name] = values.as_text(value)
            except ValueError as error:
                problems.append(
                    f"json {save.path}: {error}, so nothing is saved as {name}"
                )
        snapshot = self._write(
            self._name(journey_id, number, step, ".api.json"),
            json.dumps(seen, indent=2, ensure_ascii=False) + "\n",
        )
        observed = "; ".join(problems) if problems else f"status {answer.status}"
        if problems:
            raise _Failed(one_line(self.redactor.redact(observed)), snapshot)
        return one_line(observed), snapshot

    def _traffic_step(
        self, step: Step, running: Running, api, journey_id: str, number: int
    ) -> Tuple[str, str]:
        """Send the chosen population (``traffic.py``); the check is the sending."""
        plan = step.do.traffic
        name = self._name(journey_id, number, step, ".traffic.json")
        experiment_id = self.values.get(plan.experiment)
        if experiment_id is None:
            raise StepFailed(f"no value saved as {plan.experiment!r}")
        key = self._secret(plan.key)
        answer = api.get(
            f"/api/v1/experiments/{experiment_id}",
            headers=self._headers(running, plan.as_, api),
        )
        if answer.status != 200:
            raise StepFailed(f"reading the experiment answered {answer.status}")
        experiment = answer.json()
        try:
            experiment_key = str(experiment["key"])
            allocations = [
                (str(v["name"]), int(v["traffic_allocation"]))
                for v in experiment["variants"]
            ]
        except (KeyError, TypeError, ValueError):
            raise StepFailed(
                "the experiment's key or variants could not be read"
            ) from None
        try:
            chosen = population.choose(
                experiment_key,
                allocations,
                {variant: p.assigned for variant, p in plan.variants.items()},
                plan.users,
            )
        except population.TrafficError as error:
            raise StepFailed(str(error)) from None

        def fetch(method: str, path: str, body: Optional[Dict[str, Any]]):
            sent = api.fetch(path, method=method, headers={"X-API-Key": key}, data=body)
            try:
                document = sent.json()
            except (PlaywrightError, ValueError):
                document = None
            return sent.status, document

        outcome = population.send(
            fetch,
            experiment_key=experiment_key,
            event=plan.event,
            chosen=chosen,
            converted={variant: p.converted for variant, p in plan.variants.items()},
            prefix=plan.users,
        )
        snapshot = self._write(
            name, json.dumps(outcome.record(), indent=2, ensure_ascii=False) + "\n"
        )
        if outcome.problems:
            raise _Failed(
                one_line(
                    f"{len(outcome.problems)} problem(s) in {outcome.requests}"
                    " requests: " + "; ".join(outcome.problems[:3])
                ),
                snapshot,
            )
        sent = "; ".join(
            f"{variant} {counts['as_chosen']} assigned as chosen,"
            f" {counts['converted']} converted"
            for variant, counts in outcome.variants.items()
        )
        return f"{outcome.requests} requests: {sent}", snapshot

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
                target = values.substitute(do.goto, self.values)
                return page.goto(urljoin(running.base_url, target.lstrip("/")))
            if do.open is not None:
                return page.goto(target)
            if do.click is not None:
                if (
                    do.click.role == "button"
                    and do.click.name in pacing.SIGN_IN_BUTTONS
                ):
                    self.waited += self.pacer.wait()
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
        except KeyError as error:
            raise StepFailed(str(error.args[0])) from None
        return None

    def _keep_step(self, step: Step, page: Page) -> str:
        """Read the one element's text and keep it; never written, only its length."""
        keep = step.do.keep
        within = keep.within
        if within is not None:
            element = page.get_by_role(
                within.role, name=within.name, exact=True
            ).get_by_role(keep.role)
            where = f'the {keep.role} in the {within.role} "{within.name}"'
        else:
            element = page.get_by_role(keep.role).filter(
                has_text=re.compile("^" + re.escape(keep.prefix))
            )
            where = f'the {keep.role} starting "{keep.prefix}"'
        self._holds(
            lambda: expect(element).to_have_count(1),
            f"not exactly one: {where}",
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
    def _holds(check, failure) -> None:
        """Run a Playwright expectation; a failure says *failure*, not the call log.

        *failure* is the line, or a function that writes it when the
        expectation has failed: a line naming where the page is must be
        written then, not before the expectation's wait began.
        """
        try:
            check()
        except AssertionError:
            raise StepFailed(failure() if callable(failure) else failure) from None

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
    def _open(page: Page, url: str) -> Tuple[Optional[int], str]:
        """(the navigation's status, or None; the error, or "")."""
        try:
            response = page.goto(url, wait_until="domcontentloaded")
        except PlaywrightError as error:
            return None, one_line(error, 160)
        return (response.status if response is not None else None), ""

    def _visit(self, page: Page, url: str, base: str) -> Dict[str, Any]:
        """Open one page of the site: its status, where it ended, its heading, its links.

        A page that answers 5xx or nothing is opened once more, after
        ``site.RETRY_SECONDS`` (``site.open_page`` says why).
        """
        opened = site.open_page(url, lambda target: self._open(page, target))
        if opened.error:
            return {
                "url": url,
                "status": None,
                "error": opened.error,
                "retried": opened.retried,
            }
        final = page.url
        headings = page.get_by_role("main").get_by_role("heading", level=1)
        heading = headings.first.inner_text() if headings.count() else None
        hrefs = page.locator("a[href]").evaluate_all(
            "links => links.map(link => link.href)"
        )
        return {
            "url": "/" + site.on_site(base, url),
            "status": opened.status,
            "final": "/" + site.on_site(base, site.strip(final)),
            "on_site": site.within(final, base),
            "heading": site.normalise(heading) if heading is not None else None,
            "links": site.site_links(hrefs, base),
            "retried": opened.retried,
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
            asked_twice = sum(1 for visit in seen.values() if visit.get("retried"))
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
            asked_twice = sum(1 for r in resolved if r.retried)
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
        observed = site.crawl_text(
            checked, what, problems, asked_twice, running.source_ref
        )
        if problems:
            raise _Failed(one_line(observed), snapshot)
        if not checked:
            raise _Failed(f"no {what} to check", snapshot)
        return observed, snapshot

    def _browser_step(self, step: Step, page: Page, running: Running) -> str:
        response = self._act(step, page, running)
        wanted = step.expect

        def here() -> str:
            # The document's own location. Measured 2026-10-06 on the
            # dashboard's development server: seconds after Log out, page.url
            # still read /admin/users while location was /login?next=...
            try:
                return str(page.evaluate("location.pathname")) or "/"
            except PlaywrightError:
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
                lambda: f"at {here()}, not {wanted.url}",
            )
        for named in wanted.visible or []:
            self._holds(
                lambda named=named: expect(self._role(page, named)).to_be_visible(),
                lambda named=named: (
                    f'no {named.role} "{named.name}" visible at {here()}'
                ),
            )
        if wanted.text is not None:
            self._holds(
                lambda: expect(
                    page.get_by_text(wanted.text, exact=True).first
                ).to_be_visible(),
                lambda: f'no text "{wanted.text}" visible at {here()}',
            )
        if wanted.number is not None:
            number = wanted.number
            element = self._role(page, number.locator)
            self._holds(
                lambda: expect(element).to_be_visible(),
                lambda: (
                    f'no {number.locator.role} "{number.locator.name}"'
                    f" visible at {here()}"
                ),
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
                lambda: (
                    f"the screen at {here()} does not match its expected ARIA snapshot"
                ),
            )
        shown_cells = []
        for cell in wanted.cells or []:
            text = self._cell_text(page, cell, here())
            oracle = self._oracle(cell.oracle)
            if not agrees(text, oracle):
                raise StepFailed(
                    f'the {cell.column} of the row "{cell.row}" shows'
                    f" {one_line(text, 40)!r}; {cell.oracle.name} gives {oracle:.6g}"
                )
            shown_cells.append(f"{cell.column} {one_line(text, 40)}")
        observed = f"at {here()}"
        if shown_cells:
            observed += " (" + ", ".join(shown_cells) + ", each its oracle's)"
        if response is not None:
            observed += f" (status {response.status})"
        return observed

    def _cell_text(self, page: Page, cell: Cell, here: str) -> str:
        """The text of the cell under ``cell.column`` in the one row reading ``cell.row``."""
        header = page.get_by_role("columnheader", name=cell.column, exact=True)
        self._holds(
            lambda: expect(header).to_have_count(1),
            f'not one column headed "{cell.column}" at {here}',
        )
        row = (
            page.get_by_role("table")
            .filter(has=header)
            .get_by_role("row")
            .filter(has=page.get_by_role("cell", name=cell.row, exact=True))
        )
        self._holds(
            lambda: expect(row).to_have_count(1),
            f'not one row with a cell "{cell.row}" under "{cell.column}" at {here}',
        )
        index = header.evaluate("th => th.cellIndex")
        text = row.evaluate(
            "(tr, i) => tr.cells[i] ? tr.cells[i].innerText : null", index
        )
        if text is None:
            raise StepFailed(f'the row "{cell.row}" has no cell under "{cell.column}"')
        return str(text)

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
        self.values = {}
        context = self.browser.new_context(**options)
        context.set_default_timeout(settings.timeout_ms)
        page = context.new_page()
        page.on("request", self._note_sign_in)
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
        elif step.do.crawl == "links" or step.do.kind == "keep":
            expected_snapshot = STRUCTURAL_ONLY
        elif step.do.traffic is not None:
            chosen = {
                variant: {"assigned": p.assigned, "converted": p.converted}
                for variant, p in step.do.traffic.variants.items()
            }
            expected_snapshot = self._write(
                self._name(journey_id, number, step, ".expected.json"),
                json.dumps(
                    {"event": step.do.traffic.event, "variants": chosen}, indent=2
                )
                + "\n",
            )
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
        self.waited = 0.0
        try:
            if step.do.kind == "api":
                observed, snapshot = self._api_step(
                    step, running, api, journey_id, number
                )
            elif step.do.kind == "traffic":
                observed, snapshot = self._traffic_step(
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
                suffix = {"crawl": ".crawl.json", "traffic": ".traffic.json"}.get(
                    step.do.kind, ".api.json"
                )
                snapshot = self._write(
                    self._name(journey_id, number, step, suffix),
                    json.dumps({"error": observed}, indent=2) + "\n",
                )
        ms = int((time.monotonic() - started) * 1000)
        if self.waited:
            observed = f"{observed}; waited {self.waited:.0f} s for the sign-in limit"
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
