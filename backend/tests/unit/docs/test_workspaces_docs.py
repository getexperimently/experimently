"""The workspaces docs describe workspaces as grouping, which is what the code does.

The workspace pages used to describe workspaces as something they are not:
"the top-level isolation boundary", with experiments, flags and API keys
"invisible to users who are not workspace members", and workspace API keys for
use "in the SDK". On main:

* Experiments and feature flags are not created inside a workspace, and no
  core route reads workspace membership: who can see or change them is decided
  by the platform role (`backend/app/core/permissions.py`). The workspace
  routes (`modules/backend/app/api/v1/endpoints/workspaces.py`) check
  membership and workspace role for the workspace's own settings, members,
  invites and keys, and nothing else.
* Every SDK, tracking and flag-evaluation route authenticates with
  `deps.get_api_key`, which looks up the platform `APIKey` table only, so a
  workspace key is answered 401 there.

This test forbids the phrasings that were removed (and close variants) and
requires the pages to say what is true. It is a sweep, not a proof: a new
wording of the same claim is not caught; review is. When the code changes -- a
workspace key accepted by the SDK routes, or experiments scoped to a
workspace -- change the docs and this test together.

Reads only files; no git and no `modules` import, so it runs the same in
`scripts/core_build.sh`'s copy (no `.git`, no `modules/`). It is in the
docs-only gate's "Docs content tests" through its directory,
`backend/tests/unit/docs/`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKSPACE_DOCS = REPO_ROOT / "docs" / "workspaces"
OVERVIEW = WORKSPACE_DOCS / "overview.md"
QUICKSTART = WORKSPACE_DOCS / "quickstart.md"

#: Every file that describes the workspaces module to a reader. The OpenAPI
#: snapshot carries the module's tag description, which the API docs page shows.
SWEPT: Tuple[Path, ...] = (
    OVERVIEW,
    QUICKSTART,
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "getting-started" / "modules.md",
    REPO_ROOT / "docs" / "api" / "openapi-v1.full.json",
)

#: (pattern, why it is false). Matched case-insensitively against the text
#: with markup dropped and whitespace collapsed, so a wrapped line still matches.
FALSE_CLAIMS: Tuple[Tuple[str, str], ...] = (
    (r"isolation boundary", "workspaces do not limit access to experiments or flags"),
    (r"invisible to (users|anyone|members)", "platform roles decide visibility"),
    (r"isolated (project )?namespace", "experiments and flags are not in a workspace"),
    (r"independent namespace", "experiments and flags are not in a workspace"),
    (r"multiple tenants on one instance", "one installation is one tenant"),
    (r"multi-tenant", "one installation is one tenant"),
    (r"without interfering with each other", "workspaces do not separate teams' data"),
    (
        r"workspace-scoped api (in|for) the sdk",
        "the SDK routes do not accept a workspace key",
    ),
    (r"use the workspace-scoped api", "the SDK routes do not accept a workspace key"),
    (
        r"(?<!not yet )(?<!not )accepted by the sdk",
        "the SDK routes do not accept a workspace key",
    ),
)

_DROP = re.compile(r"[*`_]")


def _flatten(text: str) -> str:
    """Lower-case, emphasis and code markup dropped, whitespace collapsed."""
    return re.sub(r"\s+", " ", _DROP.sub("", text)).lower()


def _section(path: Path, heading: str) -> str:
    """The flattened body of the level-2 section titled *heading*."""
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S
    )
    assert match, f"{path.relative_to(REPO_ROOT)} has no '## {heading}' section"
    return _flatten(match.group(1))


def test_swept_files_exist() -> None:
    """A renamed or deleted page must not turn the sweep into a no-op."""
    missing = [str(p.relative_to(REPO_ROOT)) for p in SWEPT if not p.is_file()]
    assert not missing, f"swept files are missing: {missing}"


def test_no_page_describes_workspaces_as_an_access_boundary() -> None:
    hits: List[str] = []
    for path in SWEPT:
        flat = _flatten(path.read_text(encoding="utf-8"))
        for pattern, why in FALSE_CLAIMS:
            for match in re.finditer(pattern, flat):
                start = max(0, match.start() - 60)
                hits.append(
                    f"{path.relative_to(REPO_ROOT)}: '...{flat[start : match.end() + 40]}...'"
                    f" -- false: {why}"
                )
    assert not hits, "workspace docs claim more than the code does:\n" + "\n".join(hits)


def test_overview_says_access_is_by_platform_role() -> None:
    body = _section(OVERVIEW, "What Are Workspaces?")
    assert (
        "workspaces do not decide which experiments, feature flags or api keys "
        "a user can see or change" in body
    ), body
    assert "platform role" in body, body


def test_overview_api_keys_section_says_the_sdk_does_not_accept_them() -> None:
    body = _section(OVERVIEW, "Workspace API Keys")
    # The sentence, not just the admonition's title, which says it too.
    assert (
        "workspace api keys are not yet accepted by the sdk, tracking or flag "
        "evaluation endpoints" in body
    ), body
    assert "401" in body, body
    assert "use a platform api key" in body, body


def test_quickstart_says_the_sdk_does_not_accept_workspace_keys() -> None:
    body = _section(QUICKSTART, "3. Create a Workspace API Key")
    assert (
        "workspace api keys are not yet accepted by the sdk, tracking or flag "
        "evaluation endpoints" in body
    ), body
    sdk = _section(QUICKSTART, "4. Connect an SDK with a Platform API Key")
    assert "platform api key" in sdk, sdk
    # The SDK step must not carry a workspace key (they start `ep_live_`, which
    # flattens to `eplive`).
    assert "eplive" not in sdk, sdk
