"""The docs-journey runner's pytest session (#939).

One test per journey file in ``journeys/``, in the order of their stack and
profile so each stack comes up once. Run it from the repository root, in an
environment with ``tests/acceptance/requirements.txt`` installed and Chromium
installed for Playwright (``python -m playwright install chromium``)::

    DOCS_JOURNEY_RUN_DIR=/tmp/docs-run \\
        python -m pytest -c tests/acceptance/docs/pytest.ini tests/acceptance/docs

This directory is its own pytest root (``pytest.ini``): the repository's root
``conftest.py`` and ``backend`` are not loaded, and nothing is imported from the
product.

Environment:

* ``DOCS_JOURNEY_RUN_DIR``: where everything the run writes goes (the results
  log ``results.jsonl``, a report per guide as ``<journey>.md`` and
  ``<journey>.html``, ``summary.md``, the screenshots and snapshots, the
  videos, each stack's output under ``stacks/``). Refused inside the
  repository, so the runner writes nothing into the tree (Python's own
  ``__pycache__`` aside: ``PYTHONDONTWRITEBYTECODE=1`` keeps that out too;
  marketing-local's build is the other exception, see ``stacks.py``). Unset, a
  new temporary directory, named at the end of the run.
* ``DOCS_JOURNEY_RUN_ID``, ``DOCS_JOURNEY_SHA``: written on every log line;
  by default ``GITHUB_RUN_ID`` and ``GITHUB_SHA``, else ``local`` and
  ``unknown`` (no git is run).
* ``DOCS_JOURNEY_TIMEOUT_MS`` (10000), ``DOCS_JOURNEY_RECORD_VIDEO`` (``1``;
  ``0`` records none), ``DOCS_JOURNEY_HEADED`` (``1`` shows the browser),
  ``DOCS_JOURNEY_KEEP_STACKS`` (``1`` leaves the stacks up at the end).
* The stacks' own settings: ``docs_runner/stacks.py``.

A step that cannot run is reported NOT RUN with a reason from
``docs_runner/registry.py``. Nothing here may skip: pytest's skip and xfail are
banned in this directory by ``ruff.toml``, and a run in which any test or
collector was skipped anyway exits 1. A retry plugin is refused at start.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import List, Optional

import pytest
import yaml

from docs_runner import guide as guides
from docs_runner import report
from docs_runner.loader import Refused, context_for, load
from docs_runner.log import FAIL, Log, run_directory
from docs_runner.stacks import STACK_CLASSES, StackError

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
JOURNEYS = HERE / "journeys"

RETRY_PLUGINS = ("rerunfailures", "flaky", "pytest_retry", "retry")
STACK_FIXTURES = {
    "compose-dev": "compose_dev_stack",
    "docs-local": "docs_local_stack",
    "docs-published": "docs_published_stack",
    "marketing-local": "marketing_local_stack",
}

RUNS = pytest.StashKey[List[report.GuideRun]]()
SKIPPED = pytest.StashKey[List[str]]()
REPORT_PROBLEMS = pytest.StashKey[List[str]]()
RUN_DIR = pytest.StashKey[Path]()


def pytest_configure(config: pytest.Config) -> None:
    for name in RETRY_PLUGINS:
        if config.pluginmanager.has_plugin(name):
            raise pytest.UsageError(
                f"the {name} plugin is loaded; the docs journeys never retry a step"
            )
    config.stash[RUNS] = []
    config.stash[SKIPPED] = []
    config.stash[REPORT_PROBLEMS] = []
    try:
        config.stash[RUN_DIR] = run_directory(os.environ, REPO_ROOT)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from None
    config.pluginmanager.register(SkipWatch(config), "docs-journeys-skip-watch")


class SkipWatch:
    """Notes every skipped collector and test: here a skip is a failure."""

    def __init__(self, config: pytest.Config):
        self.skipped = config.stash[SKIPPED]

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid or "(collection)")

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid)


def _order(path: Path) -> tuple:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        data = None
    if not isinstance(data, dict):
        return ("", "", path.name)
    return (str(data.get("stack", "")), str(data.get("profile", "")), path.name)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "journey_file" in metafunc.fixturenames:
        files = sorted(JOURNEYS.glob("*.yaml"), key=_order)
        metafunc.parametrize("journey_file", files, ids=[path.stem for path in files])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
class RunSettings:
    def __init__(self, config: pytest.Config):
        environ = os.environ
        self.run_dir: Path = config.stash[RUN_DIR]
        self.run_id = environ.get("DOCS_JOURNEY_RUN_ID") or environ.get(
            "GITHUB_RUN_ID", "local"
        )
        self.sha = environ.get("DOCS_JOURNEY_SHA") or environ.get(
            "GITHUB_SHA", "unknown"
        )
        self.timeout_ms = int(environ.get("DOCS_JOURNEY_TIMEOUT_MS", "10000"))
        self.record_video = environ.get("DOCS_JOURNEY_RECORD_VIDEO", "1") not in (
            "0",
            "false",
        )
        self.headed = environ.get("DOCS_JOURNEY_HEADED") == "1"
        self.keep_stacks = environ.get("DOCS_JOURNEY_KEEP_STACKS") == "1"


@pytest.fixture(scope="session")
def run_settings(pytestconfig: pytest.Config) -> RunSettings:
    return RunSettings(pytestconfig)


def _stack_fixture(stack: str):
    @pytest.fixture(scope="session", name=STACK_FIXTURES[stack])
    def fixture(run_settings: RunSettings):
        instance = STACK_CLASSES[stack](
            REPO_ROOT, run_settings.run_dir / "stacks", os.environ
        )
        yield instance
        if not run_settings.keep_stacks:
            instance.down()

    return fixture


compose_dev_stack = _stack_fixture("compose-dev")
docs_local_stack = _stack_fixture("docs-local")
docs_published_stack = _stack_fixture("docs-published")
marketing_local_stack = _stack_fixture("marketing-local")


@pytest.fixture(scope="session")
def playwright_session():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as handle:
        yield handle


@pytest.fixture(scope="session")
def browser(playwright_session, run_settings: RunSettings):
    instance = playwright_session.chromium.launch(headless=not run_settings.headed)
    yield instance
    instance.close()


@pytest.fixture(scope="session")
def journey_runner(playwright_session, browser, run_settings: RunSettings):
    from docs_runner.execute import JourneyRunner, Settings

    return JourneyRunner(
        playwright_session,
        browser,
        Log(run_settings.run_dir / "results.jsonl"),
        Settings(
            run_dir=run_settings.run_dir,
            run_id=run_settings.run_id,
            sha=run_settings.sha,
            timeout_ms=run_settings.timeout_ms,
            record_video=run_settings.record_video,
        ),
    )


# ---------------------------------------------------------------------------
# One journey
# ---------------------------------------------------------------------------
def _title(guide_path: str) -> str:
    try:
        return guides.load(REPO_ROOT / "docs", guide_path).title
    except OSError:
        return guide_path


def walk(journey_file: Path, request: pytest.FixtureRequest) -> report.GuideRun:
    """Load, bring up the stack, run the steps; the outcome is kept for the report."""
    runs = request.config.stash[RUNS]
    journey_id = journey_file.stem
    try:
        journey = load(journey_file, context_for(REPO_ROOT))
    except Refused as refused:
        data = yaml.safe_load(journey_file.read_text(encoding="utf-8")) or {}
        guide_path = str(data.get("guide", "")) if isinstance(data, dict) else ""
        outcome = report.GuideRun(
            journey=journey_id,
            guide=guide_path or "(unknown)",
            title=_title(guide_path) if guide_path else journey_id,
            stack=str(data.get("stack", "")) if isinstance(data, dict) else "",
            refused=tuple(refused.problems),
        )
        runs.append(outcome)
        pytest.fail(str(refused), pytrace=False)
    guide = guides.load(REPO_ROOT / "docs", journey.guide)
    try:
        stack = request.getfixturevalue(STACK_FIXTURES[journey.stack])
        running = stack.up(journey.profile)
    except StackError as error:
        outcome = report.GuideRun(
            journey=journey_id,
            guide=journey.guide,
            title=guide.title,
            stack=journey.stack,
            error=str(error),
        )
        runs.append(outcome)
        pytest.fail(f"{journey_id}: {error}", pytrace=False)
    runner = request.getfixturevalue("journey_runner")
    records = runner.run(journey, journey_id, running, guide)
    outcome = report.GuideRun(
        journey=journey_id,
        guide=journey.guide,
        title=guide.title,
        stack=journey.stack,
        records=tuple(records),
    )
    runs.append(outcome)
    return outcome


@pytest.fixture
def walk_journey(request: pytest.FixtureRequest):
    """``walk`` for this test: ``walk_journey(path)`` returns the GuideRun."""
    return lambda journey_file: walk(journey_file, request)


# ---------------------------------------------------------------------------
# The end of the run: the reports, and no skip reads as green
# ---------------------------------------------------------------------------
def write_reports(
    runs: List[report.GuideRun], run_dir: Path, sha: str, date: str
) -> Optional[str]:
    """Write every report; the first ReportError's message, or None."""
    problem = None
    for outcome in runs:
        try:
            (run_dir / f"{outcome.journey}.md").write_text(
                report.guide_markdown(outcome, run_dir, date=date, sha=sha),
                encoding="utf-8",
            )
            (run_dir / f"{outcome.journey}.html").write_text(
                report.guide_html(outcome, run_dir, date=date, sha=sha),
                encoding="utf-8",
            )
        except report.ReportError as error:
            problem = problem or str(error)
    inventory = context_for(REPO_ROOT).inventory
    (run_dir / "summary.md").write_text(
        report.summary_markdown(runs, inventory, date=date, sha=sha), encoding="utf-8"
    )
    return problem


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    sha = os.environ.get("DOCS_JOURNEY_SHA") or os.environ.get("GITHUB_SHA", "unknown")
    date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    problem = write_reports(config.stash[RUNS], config.stash[RUN_DIR], sha, date)
    if problem is not None:
        config.stash[REPORT_PROBLEMS].append(problem)
    if config.stash[SKIPPED] or config.stash[REPORT_PROBLEMS]:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    runs = config.stash[RUNS]
    failed = [o.journey for o in runs if report.verdict(o).word == FAIL]
    terminalreporter.write_line(
        f"docs journeys: {len(runs)} run, {len(failed)} failed;"
        f" results in {config.stash[RUN_DIR]}"
    )
    for problem in config.stash[REPORT_PROBLEMS]:
        terminalreporter.write_line(f"docs journeys: report refused: {problem}")
    for nodeid in config.stash[SKIPPED]:
        terminalreporter.write_line(
            f"docs journeys: {nodeid} was skipped; nothing here may skip, so the"
            " run fails"
        )
