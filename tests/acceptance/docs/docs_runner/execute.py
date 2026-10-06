"""Walk one journey in a browser, one log line per step.

Steps run in order. A step that fails stops the guide: every later step is NOT
RUN (``earlier-step-failed``). A step whose journey file declares ``not_run``
is NOT RUN with that reason, and ``ref: doc-examples`` is NOT RUN
(``doc-examples``): Doc Examples runs those blocks. Nothing is skipped.

Elements are found only by role and accessible name, or by label, with exact
matching. Waiting is Playwright's own: an action waits for its element and an
expectation retries until it holds or ``DOCS_JOURNEY_TIMEOUT_MS`` (default
10000) passes. There is no fixed sleep anywhere.

Files, under ``<run dir>/<journey>/``: ``NN-<step>.expected.aria.yml`` (the
expected ARIA snapshot, written before the step runs), ``NN-<step>.png`` and
``NN-<step>.aria.yml`` (the screen and its ARIA snapshot, after the step, or
when it fails), ``NN-<step>.api.json`` (an api step's status and the values at
its expected JSON paths). A ``video: true`` journey is recorded to
``videos/<journey>.webm`` (1280x720) unless ``DOCS_JOURNEY_RECORD_VIDEO=0``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, Page, Playwright, expect
from playwright.sync_api import Error as PlaywrightError

from docs_runner import registry
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
from docs_runner.model import Journey, Named, Step
from docs_runner.oracles import ORACLES
from docs_runner.stacks import Running

VIEWPORT = {"width": 1280, "height": 720}


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
        expect.set_options(timeout=settings.timeout_ms)

    # -- files -------------------------------------------------------------
    def _name(self, journey_id: str, number: int, step: Step, suffix: str) -> str:
        return f"{journey_id}/{number:02d}-{step.id}{suffix}"

    def _write(self, name: str, text: str) -> str:
        path = self.settings.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return name

    def _screen(self, page: Page, journey_id: str, number: int, step: Step) -> str:
        name = self._name(journey_id, number, step, ".png")
        path = self.settings.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(path))
            aria = page.locator("body").aria_snapshot()
        except PlaywrightError as error:
            aria = f"(no ARIA snapshot: {one_line(error)})"
        self._write(self._name(journey_id, number, step, ".aria.yml"), aria + "\n")
        return name if path.is_file() else ""

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
                seen[path] = value
                if not same_json(value, wanted):
                    problems.append(f"json {path} = {json.dumps(value)}")
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

    def _act(self, step: Step, page: Page, running: Running):
        """Do the step's action; the navigation's response for a goto."""
        do = step.do
        try:
            if do.goto is not None:
                return page.goto(urljoin(running.base_url, do.goto.lstrip("/")))
            if do.click is not None:
                self._role(page, do.click).click()
            elif do.fill is not None:
                page.get_by_label(do.fill.label, exact=True).fill(do.fill.value)
            elif do.select is not None:
                page.get_by_label(do.select.label, exact=True).select_option(
                    label=do.select.option
                )
        except PlaywrightError as error:
            raise StepFailed(
                f"could not {describe_action(step)}: {one_line(error, 160)}"
            ) from None
        return None

    @staticmethod
    def _holds(check, failure: str) -> None:
        """Run a Playwright expectation; a failure says *failure*, not the call log."""
        try:
            check()
        except AssertionError:
            raise StepFailed(failure) from None

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
            url = urljoin(running.base_url, wanted.url.lstrip("/"))
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
        if journey.video and settings.record_video:
            options.update(record_video_dir=str(video_dir), record_video_size=VIEWPORT)
        context = self.browser.new_context(**options)
        context.set_default_timeout(settings.timeout_ms)
        page = context.new_page()
        api = None
        if running.api_url:
            api = self.playwright.request.new_context(base_url=running.api_url)
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

    def _step(
        self,
        journey: Journey,
        journey_id: str,
        number: int,
        step: Step,
        running: Running,
        page: Page,
        api,
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
            else:
                observed = self._browser_step(step, page, running)
                if step.takes_screenshot:
                    snapshot = self._screen(page, journey_id, number, step)
            result = PASS
        except _Failed as failure:
            observed, snapshot, result = failure.observed, failure.snapshot, FAIL
        except (AssertionError, PlaywrightError, KeyError) as error:
            observed, result = one_line(error) or type(error).__name__, FAIL
            if step.in_browser:
                snapshot = self._screen(page, journey_id, number, step)
            else:
                snapshot = self._write(
                    self._name(journey_id, number, step, ".api.json"),
                    json.dumps({"error": observed}, indent=2) + "\n",
                )
        ms = int((time.monotonic() - started) * 1000)
        return Record(
            **base,
            result=result,
            reason="",
            observed=observed,
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
