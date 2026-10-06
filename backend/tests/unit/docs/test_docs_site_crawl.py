"""The docs-site crawl as ``execute`` runs it, on a fake page and a fake request context.

``tests/acceptance/docs/docs_runner/execute.py`` drives Playwright, which the
unit job does not install, so its crawl was never run by any test and one
night's 503 from GitHub Pages was the first time its re-ask ran (run
37477614389). ``execute`` is imported here against a stand-in for
``playwright.sync_api`` (the names it imports, no browser), and ``_crawl_step``
runs its real code on a page that answers from a table: what a page or link
that answers 5xx or nothing is asked, what the crawl then says about it, and
which ref it says it compared the site with. The rule itself, without the
crawl around it, is ``site.open_page`` and ``site.resolve``, tested in
``test_docs_journey_runner.py``.

Temporary files only: no browser, no network, no sleep.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER_ROOT = REPO_ROOT / "tests" / "acceptance" / "docs"
if str(RUNNER_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNNER_ROOT))

from docs_runner import site, stacks

BASE = "https://example.github.io/sample/"
REF = "v0.25.1"
HOME = BASE
GUIDE = BASE + "guides/sample/"
MKDOCS = """site_name: Sample
site_url: https://example.github.io/sample
docs_dir: docs
nav:
  - Home: README.md
  - Sample: guides/sample.md
"""


class PlaywrightError(Exception):
    """Stands in for ``playwright.sync_api.Error``."""


@pytest.fixture
def execute(monkeypatch):
    """``docs_runner.execute``, imported against a stand-in ``playwright.sync_api``."""
    api = types.ModuleType("playwright.sync_api")
    api.Browser = api.Page = api.Playwright = object
    api.Error = PlaywrightError
    api.expect = SimpleNamespace(set_options=lambda **options: None)
    package = types.ModuleType("playwright")
    package.sync_api = api
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    monkeypatch.delitem(sys.modules, "docs_runner.execute", raising=False)
    module = importlib.import_module("docs_runner.execute")
    yield module
    sys.modules.pop("docs_runner.execute", None)
    runner = sys.modules.get("docs_runner")
    if runner is not None and hasattr(runner, "execute"):
        delattr(runner, "execute")


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    """The re-ask waits ``site.RETRY_SECONDS``; a test does not."""
    monkeypatch.setattr(site, "RETRY_SECONDS", 0.0)


class FakePage:
    """What ``_visit`` asks of a page: ``answers`` maps a URL to what each
    attempt gives (a status, or an error), ``links`` a URL to the hrefs on it."""

    def __init__(self, answers: Dict[str, List[Any]], links=None):
        self.answers = {url: list(given) for url, given in answers.items()}
        self.links = links or {}
        self.url = ""
        self.opened: List[str] = []

    def goto(self, url, wait_until=None):
        self.opened.append(url)
        answer = self.answers[url].pop(0)
        if isinstance(answer, Exception):
            raise answer
        self.url = url
        return SimpleNamespace(status=answer)

    # The heading and the links, as the page's locators give them.
    def get_by_role(self, role, **options):
        return self

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def inner_text(self):
        return "Home page" if self.url == HOME else "Sample guide"

    def locator(self, selector):
        return self

    def evaluate_all(self, script):
        return list(self.links.get(self.url, []))


class FakeRequest:
    """``request.get(url, max_redirects=0)`` for the links crawl."""

    def __init__(self, answers: Dict[str, List[Any]]):
        self.answers = {url: list(given) for url, given in answers.items()}
        self.asked: List[str] = []

    def get(self, url, max_redirects=0):
        self.asked.append(url)
        answer = self.answers[url].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(status=answer, headers={})


def _source(root: Path) -> Path:
    (root / "docs" / "guides").mkdir(parents=True)
    (root / "mkdocs.yml").write_text(MKDOCS)
    (root / "docs" / "README.md").write_text("# Home page\n\nWords.\n")
    (root / "docs" / "guides" / "sample.md").write_text("# Sample guide\n\nWords.\n")
    return root


def _runner(execute, tmp_path: Path):
    settings = execute.Settings(run_dir=tmp_path / "run", run_id="1", sha="abc")
    return execute.JourneyRunner(None, None, None, settings)


def _crawl(execute, tmp_path: Path, kind: str, page, request=None, ref=REF):
    """Run the crawl step *kind* ("nav" or "links"): (observed, or the failure's)."""
    running = stacks.Running(
        name="docs-published",
        base_url=BASE,
        source=_source(tmp_path / "source"),
        source_ref=ref,
    )
    step = SimpleNamespace(id=f"crawl-{kind}", do=SimpleNamespace(crawl=kind))
    runner = _runner(execute, tmp_path)
    try:
        return runner._crawl_step(step, page, running, request, "docs-site", 2)[0]
    except execute._Failed as failure:
        return failure.observed


def test_a_nav_crawl_where_every_page_answers_names_what_it_compared_with(
    execute, tmp_path
):
    page = FakePage({HOME: [200], GUIDE: [200]})
    observed = _crawl(execute, tmp_path, "nav", page)
    assert observed == f"2 nav pages, every one as expected against {REF}"
    assert page.opened == [HOME, GUIDE]


def test_a_page_that_answers_503_once_is_asked_again_and_the_crawl_says_so(
    execute, tmp_path
):
    page = FakePage({HOME: [200], GUIDE: [503, 200]})
    observed = _crawl(execute, tmp_path, "nav", page)
    assert (
        observed == f"2 nav pages, every one as expected against {REF} (1 asked twice)"
    )
    assert page.opened == [HOME, GUIDE, GUIDE]


def test_a_page_that_answers_nothing_once_is_asked_again(execute, tmp_path):
    page = FakePage({HOME: [PlaywrightError("net::ERR_CONNECTION_RESET"), 200]})
    page.answers[GUIDE] = [200]
    observed = _crawl(execute, tmp_path, "nav", page)
    assert observed.endswith("(1 asked twice)")
    assert page.opened == [HOME, HOME, GUIDE]


def test_a_page_that_answers_503_twice_is_a_finding(execute, tmp_path):
    page = FakePage({HOME: [200], GUIDE: [503, 503]})
    observed = _crawl(execute, tmp_path, "nav", page)
    assert observed == (
        f"1 of 2 nav pages against {REF} (1 asked twice):"
        " guides/sample.md (/guides/sample/): answered 503"
    )
    assert page.opened == [HOME, GUIDE, GUIDE]


def test_a_page_that_answers_404_is_not_asked_again(execute, tmp_path):
    page = FakePage({HOME: [200], GUIDE: [404]})
    observed = _crawl(execute, tmp_path, "nav", page)
    assert observed == (
        f"1 of 2 nav pages against {REF}:"
        " guides/sample.md (/guides/sample/): answered 404"
    )
    assert page.opened == [HOME, GUIDE]


def test_a_crawl_that_compared_the_site_with_a_checkout_names_no_ref(execute, tmp_path):
    page = FakePage({HOME: [200], GUIDE: [200]})
    observed = _crawl(execute, tmp_path, "nav", page, ref="")
    assert observed == "2 nav pages, every one as expected"


def _links_page(*, guide_answers=(200,)):
    return FakePage(
        {HOME: [200], GUIDE: list(guide_answers)},
        links={HOME: [GUIDE, "https://elsewhere.example/x"]},
    )


def test_a_link_that_answers_503_once_is_asked_again_and_the_crawl_says_so(
    execute, tmp_path
):
    page = _links_page()
    request = FakeRequest({GUIDE: [503, 200]})
    observed = _crawl(execute, tmp_path, "links", page, request)
    assert (
        observed
        == f"1 links to the site, every one as expected against {REF} (1 asked twice)"
    )
    assert request.asked == [GUIDE, GUIDE]


def test_a_link_that_answers_503_twice_is_a_finding(execute, tmp_path):
    request = FakeRequest({GUIDE: [503, 503]})
    observed = _crawl(execute, tmp_path, "links", _links_page(), request)
    assert observed == (
        f"1 of 1 links to the site against {REF} (1 asked twice):"
        " /guides/sample/ (on /): answered 503"
    )


def test_a_link_that_answers_404_is_not_asked_again(execute, tmp_path):
    request = FakeRequest({GUIDE: [404]})
    observed = _crawl(execute, tmp_path, "links", _links_page(), request)
    assert observed == (
        f"1 of 1 links to the site against {REF}: /guides/sample/ (on /): answered 404"
    )
    assert request.asked == [GUIDE]


def test_the_crawl_uses_site_open_page_and_has_no_sleep_of_its_own():
    """Two copies of the re-ask could drift apart: ``execute`` calls
    ``site.open_page`` and does not wait itself."""
    source = (RUNNER_ROOT / "docs_runner" / "execute.py").read_text(encoding="utf-8")
    calls_open_page = "site.open_page(" in source
    sleeps_itself = "time.sleep" in source
    assert calls_open_page, "execute.py does not call site.open_page"
    assert not sleeps_itself, "execute.py waits on its own: time.sleep"
