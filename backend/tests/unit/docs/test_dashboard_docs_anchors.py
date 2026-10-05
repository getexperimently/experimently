"""Every `docsUrl('page', 'anchor')` link in the dashboard lands on a heading.

`test_dashboard_docs_links.py` checks that each linked page exists; it ignores
the anchor. A heading renamed in the docs then sends the reader to the top of
a long page (user-guide.md is about 600 lines) with nothing failing. This test
reads the anchored calls in non-test `frontend/src` and checks each anchor is
the slug of a heading in its page, as MkDocs' `toc` and GitHub both build it
for the headings these pages use: lower case, punctuation dropped, spaces to
hyphens.

It lives in backend/tests/unit/docs/, so a pull request that changes docs/
alone runs it (the "Docs content tests" step collects this directory). Reads
files only; no Node, no git.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS_ROOT = REPO_ROOT / "docs"
SRC_ROOT = REPO_ROOT / "frontend" / "src"

#: `docsUrl('page', 'anchor')` with single-quoted literals, as the dashboard writes them.
CALL = re.compile(r"docsUrl\(\s*'([^']*)'\s*,\s*'([^']*)'")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
SKIPPED_DIRS = {"tests", "__mocks__", "node_modules"}

#: Anchored links known to exist when this test was written; the scan must
#: still find each one, so a scan that silently finds nothing fails.
KNOWN = {
    (
        "components/results/ResultsDashboard/SrmNotice.tsx",
        "guides/user-guide",
        "sample-ratio-check",
    ),
    ("components/experiments/TargetingSection.tsx", "api/endpoints", "targeting-rules"),
}


def slug(heading: str) -> str:
    """The anchor MkDocs' default slugify and GitHub give a plain heading."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return re.sub(r"\s", "-", text)


def anchored_calls() -> List[Tuple[str, str, str]]:
    calls: List[Tuple[str, str, str]] = []
    for path in sorted(SRC_ROOT.rglob("*.ts*")):
        rel = path.relative_to(SRC_ROOT)
        if SKIPPED_DIRS.intersection(rel.parts) or re.search(
            r"\.test\.tsx?$", path.name
        ):
            continue
        if path.suffix not in (".ts", ".tsx"):
            continue
        for page, anchor in CALL.findall(path.read_text(encoding="utf-8")):
            calls.append((rel.as_posix(), page, anchor))
    return calls


def heading_slugs(page: str) -> set:
    text = (DOCS_ROOT / f"{page}.md").read_text(encoding="utf-8")
    text = re.sub(r"^```.*?^```", "", text, flags=re.MULTILINE | re.DOTALL)
    return {slug(h) for h in HEADING.findall(text)}


def test_the_scan_finds_the_known_anchored_links():
    assert KNOWN <= set(anchored_calls()), (
        f"the scan missed {sorted(KNOWN - set(anchored_calls()))}: it is broken, not clean"
    )


@pytest.mark.parametrize(
    "source,page,anchor",
    anchored_calls(),
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_the_anchor_is_a_heading_of_its_page(source, page, anchor):
    assert (DOCS_ROOT / f"{page}.md").is_file(), (
        f"{source}: docs/{page}.md does not exist"
    )
    assert anchor in heading_slugs(page), (
        f"{source}: docsUrl('{page}', '{anchor}') -> no heading in docs/{page}.md has the "
        f"anchor #{anchor}"
    )


@pytest.mark.parametrize(
    "heading,expected",
    [
        ("Sample Ratio Check", "sample-ratio-check"),
        ("Targeting Rules", "targeting-rules"),
        (
            "Sequential Testing — Stop Experiments Early",
            "sequential-testing--stop-experiments-early",
        ),
    ],
)
def test_slug_matches_the_rule(heading, expected):
    assert slug(heading) == expected
