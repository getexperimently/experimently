"""No page sends a reader to the API docs at `/docs` or `/redoc` (#492).

`backend/app/main.py` builds the app with `docs_url=None, redoc_url=None` and
serves Swagger UI at `/api/v1/docs` and ReDoc at `/api/v1/redoc`, so
`http://localhost:8000/docs` answers 404. Several pages linked there anyway.

The rule: in every Markdown page of the repository, a `host:port/docs` or
`host:port/redoc` link is refused, for any host and port, with or without a
scheme. `/docs` on a dashboard port (3000, 3100) is allowed, because the
dashboard serves its own documentation hub at `/docs`.

Out of scope: `CHANGELOG.md` files, which record what a release said at the
time and are not rewritten. Shell scripts are not pages; `demo/setup-local.sh`
is fixed in #491.

Walks the filesystem rather than asking git, so it also runs in the
`core_build.sh` copy, which has no `.git`.
"""

from __future__ import annotations

import itertools
import os
import re
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]

#: host:port followed by /docs or /redoc as a whole path segment.
STALE = re.compile(
    r"\b(?P<host>localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])"
    r":(?P<port>\d{1,5})/(?P<path>docs|redoc)(?![\w-])"
)

#: The dashboard serves a documentation hub at /docs on these ports.
DASHBOARD_PORTS = frozenset({"3000", "3100"})

SKIPPED_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "venv",
        ".venv",
        "site",
        "__pycache__",
        ".next",
        "worktrees",
    }
)

#: Lines in the root CLAUDE.md, which only the founder edits. Each entry is
#: the exact line; once it is fixed, `test_every_allowance_is_still_needed`
#: fails and the entry is deleted. Nothing else is allowed.
FOUNDER_ONLY = {
    "CLAUDE.md": {"- API Documentation: http://localhost:8000/docs"},
}


def stale_links(text: str) -> List[Tuple[int, str]]:
    """(line number, line) for each line holding a link to /docs or /redoc."""
    found = []
    for number, line in zip(itertools.count(1), text.splitlines()):
        for match in STALE.finditer(line):
            if match["path"] == "docs" and match["port"] in DASHBOARD_PORTS:
                continue
            found.append((number, line))
            break
    return found


def pages(root: Path) -> Iterator[Path]:
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if d not in SKIPPED_DIRS)
        for name in sorted(files):
            if name.endswith(".md") and name != "CHANGELOG.md":
                yield Path(directory) / name


def offenders(root: Path) -> List[str]:
    out = []
    for page in pages(root):
        rel = page.relative_to(root).as_posix()
        allowed = FOUNDER_ONLY.get(rel, set())
        text = page.read_text(encoding="utf-8", errors="replace")
        for number, line in stale_links(text):
            if line.strip() not in allowed:
                out.append(f"{rel}:{number}: {line.strip()}")
    return out


def test_no_page_links_to_the_api_docs_at_the_old_path():
    found = offenders(REPO_ROOT)
    assert not found, (
        "the API docs are at /api/v1/docs and /api/v1/redoc; /docs and /redoc "
        "answer 404:\n" + "\n".join(found)
    )


def test_every_allowance_is_still_needed():
    for rel, lines in FOUNDER_ONLY.items():
        path = REPO_ROOT / rel
        present = {
            line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        }
        gone = lines - present
        assert not gone, (
            f"{rel} no longer has these lines; delete them from FOUNDER_ONLY: {gone}"
        )


def test_the_served_paths_are_the_ones_the_pages_name():
    main = (REPO_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert "docs_url=None" in main
    assert "redoc_url=None" in main
    assert '@app.get("/api/v1/docs"' in main
    assert '@app.get("/api/v1/redoc"' in main


@pytest.mark.parametrize(
    "line",
    [
        "The docs are at http://localhost:8000/docs.",
        "[API Reference](http://localhost:8000/docs#/Workspaces)",
        "`localhost:8000/docs` uses for its **Authorize** button.",
        "http://127.0.0.1:8001/redoc",
        "see localhost:3000/redoc",
        "http://0.0.0.0:8000/docs",
    ],
)
def test_an_old_link_is_refused(line):
    assert stale_links(line)


@pytest.mark.parametrize(
    "line",
    [
        "http://localhost:8000/api/v1/docs",
        "http://localhost:8000/api/v1/redoc",
        "http://localhost:8000/api/v1/docs#/monitoring",
        "the dashboard hub at http://localhost:3000/docs",
        "http://localhost:3100/docs",
        "http://localhost:8000/docs-site",
        "https://nextjs.org/docs",
    ],
)
def test_a_current_link_is_allowed(line):
    assert not stale_links(line)


def test_a_changelog_is_not_checked(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("- linked http://localhost:8000/docs\n")
    (tmp_path / "sdk").mkdir()
    (tmp_path / "sdk" / "CHANGELOG.md").write_text("http://localhost:8000/redoc\n")
    assert offenders(tmp_path) == []


def test_a_page_with_an_old_link_is_found(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(
        "intro\nsee http://localhost:8000/docs\n"
    )
    assert offenders(tmp_path) == ["docs/page.md:2: see http://localhost:8000/docs"]
