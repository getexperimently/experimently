"""The docs describe a password reset the product actually offers (#714).

``docs/auth/auth-user-guide.md`` used to walk the reader through a dashboard
reset: click "Forgot Password" on the login page, enter an emailed code on a
reset page. The dashboard has no such page under any ``AUTH_PROVIDER``: the
login page's "Forgot password?" says "Ask an administrator to reset it", and
no dashboard source calls ``/auth/forgot-password`` or ``/auth/reset-password``.

Pinned here, reading files only (no git, no app), so it runs on a docs-only
pull request through ``backend/tests/unit/docs/`` and in the
``core_build.sh`` copy:

* while no dashboard source (``frontend/src``, ``modules/frontend/src``,
  tests excluded) calls either reset route, no page under ``docs/`` tells
  the reader to click a "Forgot Password" link or use a reset page. When a
  reset page is built, the first half turns false and the sweep stops;
* the guide's "Password Reset Process" names the paths that do work: the
  admin password route for ``local``, and for ``cognito`` the
  ``admin-set-user-password --permanent`` command and the two API routes.

A sweep, not a proof: a new wording of the same false claim is not caught.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS = REPO_ROOT / "docs"
GUIDE = DOCS / "auth" / "auth-user-guide.md"
DASHBOARD_SOURCES = (
    REPO_ROOT / "frontend" / "src",
    REPO_ROOT / "modules" / "frontend" / "src",
)

RESET_ROUTE = re.compile(r"/auth/(forgot|reset)-password")

#: Phrasings of a dashboard self-service reset. Matched case-insensitively
#: against each page with whitespace collapsed and ``*`` removed.
DASHBOARD_RESET_CLAIMS = (
    r"click[^.]{0,30}forgot password",
    r"forgot password\W{0,3} (link|button) on the login",
    r"on the (password )?reset page",
    r"reset (page|form) (in|on) the dashboard",
)


def _dashboard_files() -> List[Path]:
    files: List[Path] = []
    for root in DASHBOARD_SOURCES:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
                continue
            parts = set(path.relative_to(root).parts)
            if parts & {"tests", "__tests__", "node_modules"} or ".test." in path.name:
                continue
            files.append(path)
    return files


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").replace("*", "").split()).lower()


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n### ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def test_the_dashboard_has_no_reset_page() -> None:
    files = _dashboard_files()
    if not files:
        pytest.skip("this tree has no dashboard sources")
    callers = [
        str(p.relative_to(REPO_ROOT))
        for p in files
        if RESET_ROUTE.search(p.read_text("utf-8"))
    ]
    assert not callers, (
        f"the dashboard now calls a reset route ({callers}); update "
        "docs/auth/auth-user-guide.md and this test"
    )


def test_no_page_describes_a_dashboard_reset_page() -> None:
    files = _dashboard_files()
    if not files or any(RESET_ROUTE.search(p.read_text("utf-8")) for p in files):
        pytest.skip(
            "the dashboard has a reset page, or this tree has no dashboard sources"
        )
    hits = []
    for page in sorted(DOCS.rglob("*.md")):
        text = _flat(page)
        for pattern in DASHBOARD_RESET_CLAIMS:
            match = re.search(pattern, text)
            if match:
                hits.append(f"{page.relative_to(REPO_ROOT)}: {match.group(0)!r}")
    assert not hits, "the dashboard has no reset page:\n" + "\n".join(hits)


def test_the_guide_names_the_resets_that_work() -> None:
    section = _section(GUIDE.read_text(encoding="utf-8"), "### Password Reset Process")
    for needle in (
        "AUTH_PROVIDER=local",
        "/api/v1/admin/users/",
        "AUTH_PROVIDER=cognito",
        "admin-set-user-password",
        "--permanent",
        "../cognito_integration.md#adding-a-user",
        "POST /api/v1/auth/forgot-password",
        "POST /api/v1/auth/reset-password",
        "#changing-your-password",
    ):
        assert needle in section, f"'Password Reset Process' no longer names {needle!r}"
