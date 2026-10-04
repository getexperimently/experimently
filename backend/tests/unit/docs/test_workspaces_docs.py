"""The workspaces docs describe workspaces as grouping, which is what the code does.

The workspace pages used to describe workspaces as something they are not:
"the top-level isolation boundary", with experiments, flags and API keys
"invisible to users who are not workspace members", and workspace API keys for
use "in the SDK". On main:

* Experiments and feature flags are not created inside a workspace, and no
  core route reads workspace membership: who can see or change them is decided
  by the platform role (`backend/app/core/permissions.py`). The workspace
  routes (`modules/backend/app/api/v1/endpoints/workspaces.py`) check
  membership and workspace role for the workspace's own settings, members and
  invites, and nothing else.
* Workspaces issue no API keys and have no plan and no limits (#263, #264):
  the key routes, the plan field and the member cap were removed. Every SDK,
  tracking and flag-evaluation route authenticates with `deps.get_api_key`,
  which looks up the platform `APIKey` table only.

This test forbids the phrasings that were removed (and close variants) and
requires the pages to say what is true. It is a sweep, not a proof: a new
wording of the same claim is not caught; review is. When the code changes --
workspace keys or plans brought back, or experiments scoped to a workspace --
change the docs and this test together.

The dashboard's copy is swept too: the docs index card
(`frontend/src/pages/docs/index.tsx`) always, and the workspace pages'
module-page descriptions (`modules/frontend/src/pages/workspaces/`) and the
model's docstrings whenever `modules/` is present -- a core tree has no such
files to sweep. The OpenAPI tag description in
`modules/backend/app/register.py` is swept through the full OpenAPI
snapshot, which carries it in both trees.

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
    REPO_ROOT / "frontend" / "src" / "pages" / "docs" / "index.tsx",
)

#: The workspace dashboard pages and the model's docstrings. Swept whenever
#: `modules/` exists, and then required to exist, so a full tree cannot skip them.
MODULE_PAGES = REPO_ROOT / "modules" / "frontend" / "src" / "pages" / "workspaces"
if (REPO_ROOT / "modules").is_dir():
    SWEPT += (
        MODULE_PAGES / "index.tsx",
        MODULE_PAGES / "new.tsx",
        MODULE_PAGES / "[id]" / "index.tsx",
        REPO_ROOT / "modules" / "backend" / "app" / "models" / "workspace.py",
    )

#: The model keeps the plan and limit columns and the key table on purpose
#: (retained, unused), so its source is not swept for REMOVED_FEATURES.
RETAINS_REMOVED_COLUMNS = (
    REPO_ROOT / "modules" / "backend" / "app" / "models" / "workspace.py"
)
FULL_SNAPSHOT = REPO_ROOT / "docs" / "api" / "openapi-v1.full.json"

#: (pattern, why it is false). Matched case-insensitively against the text
#: with markup dropped and whitespace collapsed, so a wrapped line still matches.
FALSE_CLAIMS: Tuple[Tuple[str, str], ...] = (
    (r"isolation boundary", "workspaces do not limit access to experiments or flags"),
    (r"invisible to (users|anyone|members)", "platform roles decide visibility"),
    (r"isolated (project )?namespace", "experiments and flags are not in a workspace"),
    (r"isolate experiments", "workspaces do not separate experiments or flags"),
    # "a workspace-scoped API key" (a key that belongs to a workspace) is true;
    # "generate a scoped API key" as the SDK credential is not.
    (
        r"(?<!workspace-)scoped api key",
        "workspace keys are not accepted by the SDK routes",
    ),
    (r"independent namespace", "experiments and flags are not in a workspace"),
    (r"provides workspace isolation", "workspaces do not limit access"),
    (
        r"change the role of any member",
        "the docs do not state who may grant OWNER",
    ),
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

#: Workspaces have no plan, no limits and no API keys (#263, #264). Matched
#: like FALSE_CLAIMS, against the flattened text (underscores dropped, so
#: ``max_members`` reads ``maxmembers`` and ``{workspace_id}`` reads
#: ``{workspaceid}``).
REMOVED_FEATURES: Tuple[Tuple[str, str], ...] = (
    (r"workspace api keys?", "workspaces issue no API keys"),
    (r"workspaces/\S*/api-keys", "the workspace API-key routes are removed"),
    (r"plan limits?", "workspaces have no plan and no limits"),
    (
        r"max ?(experiments|feature ?flags|members|api ?keys)",
        "workspaces have no limits",
    ),
    (r"planlimitexceeded", "adding members is never capped"),
    (r"member and api-key limits", "workspaces have no limits"),
    (r"usage & limits", "workspaces have no limits"),
)

#: A request or response body carrying ``plan``. Only in the workspace pages:
#: targeting examples elsewhere legitimately use ``{"plan": "pro"}``.
PLAN_FIELD = r'"plan" ?:'

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


def test_no_page_offers_workspace_keys_plans_or_limits() -> None:
    hits: List[str] = []
    checks = [
        (path, REMOVED_FEATURES) for path in SWEPT if path != RETAINS_REMOVED_COLUMNS
    ]
    checks += [
        (path, ((PLAN_FIELD, "workspaces have no plan"),))
        for path in (OVERVIEW, QUICKSTART)
    ]
    for path, patterns in checks:
        flat = _flatten(path.read_text(encoding="utf-8"))
        for pattern, why in patterns:
            for match in re.finditer(pattern, flat):
                start = max(0, match.start() - 60)
                hits.append(
                    f"{path.relative_to(REPO_ROOT)}: '...{flat[start : match.end() + 40]}...'"
                    f" -- removed: {why}"
                )
    assert not hits, "workspace docs describe removed features:\n" + "\n".join(hits)


def test_the_workspaces_tag_says_there_are_no_keys_or_plans() -> None:
    """``register.py``'s tag description, as the full snapshot publishes it."""
    import json

    tags = json.loads(FULL_SNAPSHOT.read_text(encoding="utf-8")).get("tags", [])
    found = [t["description"] for t in tags if t.get("name") == "Workspaces"]
    assert len(found) == 1, tags
    flat = _flatten(found[0])
    assert "no plan and no limits" in flat, flat
    assert "issue no api keys" in flat, flat


#: Paths, schemas and fields removed with workspace API keys and plans
#: (#263, #264), which the committed full snapshot must not publish. The live
#: application is checked the same way by the module smoke test
#: ``test_workspace_routes_contract.py``; this half reads the JSON alone, so
#: it also runs in a core tree, and catches a snapshot not regenerated.
_WS_POSITIVE_CONTROL = "/api/v1/workspaces/{workspace_id}/members"
_REMOVED_SCHEMAS = (
    "CreateAPIKeyRequest",
    "CreateAPIKeyResponse",
    "WorkspaceAPIKeyResponse",
)
_REMOVED_FIELDS = (
    "plan",
    "max_experiments",
    "max_feature_flags",
    "max_members",
    "max_api_keys",
    "api_key_count",
    "experiment_count",
    "flag_count",
)
_WORKSPACE_SCHEMAS = (
    "CreateWorkspaceRequest",
    "UpdateWorkspaceRequest",
    "WorkspaceResponse",
    "WorkspaceWithStatsResponse",
)


def _workspace_key_paths(document: dict) -> List[str]:
    """Every workspace path that names API keys, in any letter case."""
    return sorted(
        path
        for path in document.get("paths", {})
        if path.lower().startswith("/api/v1/workspaces") and "api-key" in path.lower()
    )


def test_the_full_snapshot_publishes_no_workspace_keys_or_plans() -> None:
    import json

    doc = json.loads(FULL_SNAPSHOT.read_text(encoding="utf-8"))
    assert _WS_POSITIVE_CONTROL in doc["paths"], (
        "the full snapshot has no workspaces routes; the absence checks prove nothing"
    )
    found = _workspace_key_paths(doc)
    assert not found, f"workspace API-key routes are still published: {found}"
    schemas = doc["components"]["schemas"]
    assert set(_WORKSPACE_SCHEMAS) <= set(schemas), "workspace schemas are missing"
    still = [name for name in _REMOVED_SCHEMAS if name in schemas]
    assert not still, f"removed schemas are still published: {still}"
    fields = [
        f"{name}.{field}"
        for name in _WORKSPACE_SCHEMAS
        for field in _REMOVED_FIELDS
        if field in schemas[name].get("properties", {})
    ]
    assert not fields, f"removed fields are still published: {fields}"
    for name in ("CreateWorkspaceRequest", "UpdateWorkspaceRequest"):
        assert schemas[name].get("additionalProperties") is False, name


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/workspaces/{workspace_id}/api-keys",
        "/api/v1/workspaces/{workspace_id}/api-keys/{key_id}/rotate",
        "/api/v1/Workspaces/{workspace_id}/API-Keys",
    ],
)
def test_the_snapshot_selector_catches_a_planted_route(path: str) -> None:
    doc = {"paths": {_WS_POSITIVE_CONTROL: {}, path: {}}}
    assert _workspace_key_paths(doc) == [path]


def test_overview_says_there_are_no_plans_or_limits() -> None:
    body = _section(OVERVIEW, "Plans and Limits")
    assert "workspaces have no plan and no limits" in body, body
    assert "any number of members" in body, body


def test_overview_says_workspaces_issue_no_api_keys() -> None:
    body = _section(OVERVIEW, "API Keys")
    assert "workspaces do not issue api keys" in body, body
    assert "platform api key" in body, body


def test_quickstart_connects_an_sdk_with_a_platform_key() -> None:
    sdk = _section(QUICKSTART, "3. Connect an SDK with a Platform API Key")
    assert "workspaces do not issue api keys" in sdk, sdk
    assert "platform api key" in sdk, sdk
    # Workspace keys started `ep_live_`, which flattens to `eplive`.
    assert "eplive" not in sdk, sdk
