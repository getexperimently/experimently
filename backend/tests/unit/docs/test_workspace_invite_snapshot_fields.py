"""The invitation page and the invite modal read only fields the API returns.

The dashboard's ``WorkspaceInvite`` type once named ``workspace_name`` and
``inviter_username`` while the API's ``WorkspaceInviteResponse`` had neither,
so the invitation page rendered blanks. This pins the two sides together
through the committed full-profile OpenAPI snapshot
(``docs/api/openapi-v1.full.json``), which the snapshot test in turn keeps
equal to what the API serves.

Reads only files: no git, no ``modules`` import. The snapshot is present in
``scripts/core_build.sh``'s copy, so the first test runs there too; the
second reads the dashboard type under ``modules/`` and is skipped, with the
reason, when that directory is absent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
FULL_SNAPSHOT = REPO_ROOT / "docs" / "api" / "openapi-v1.full.json"
WORKSPACES_TS = (
    REPO_ROOT / "modules" / "frontend" / "src" / "services" / "workspaces.ts"
)

#: What `/workspaces/invites/[token]` and the members page's invite modal read.
FIELDS_THE_DASHBOARD_READS = (
    "email",
    "role",
    "token",
    "expires_at",
    "accepted_at",
    "workspace_name",
    "inviter_username",
)


def _invite_schema() -> Dict:
    doc = json.loads(FULL_SNAPSHOT.read_text(encoding="utf-8"))
    return doc["components"]["schemas"]["WorkspaceInviteResponse"]


def _ts_interface_fields(source: str, name: str) -> List[str]:
    match = re.search(
        rf"export interface {re.escape(name)} \{{(.*?)^\}}", source, re.S | re.M
    )
    assert match, f"no `export interface {name}` in {WORKSPACES_TS}"
    return re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\??\s*:", match.group(1), re.M)


def test_the_invite_response_has_every_field_the_dashboard_reads() -> None:
    schema = _invite_schema()
    properties = set(schema["properties"])
    required = set(schema.get("required", ()))

    missing = [f for f in FIELDS_THE_DASHBOARD_READS if f not in properties]
    assert not missing, (
        f"WorkspaceInviteResponse in {FULL_SNAPSHOT.relative_to(REPO_ROOT)} "
        f"has no {missing}; the invitation page would render blanks"
    )
    # Always present in the body (null where the field allows it), so the page
    # never sees `undefined`.
    not_required = [f for f in FIELDS_THE_DASHBOARD_READS if f not in required]
    assert not not_required, f"not in `required`: {not_required}"


def test_the_dashboard_invite_type_names_only_api_fields() -> None:
    if not WORKSPACES_TS.is_file():
        pytest.skip(
            "modules/ is absent (core build): there is no dashboard invite type to compare"
        )
    declared = _ts_interface_fields(
        WORKSPACES_TS.read_text(encoding="utf-8"), "WorkspaceInvite"
    )
    assert set(FIELDS_THE_DASHBOARD_READS) <= set(declared), declared

    properties = set(_invite_schema()["properties"])
    unknown = [f for f in declared if f not in properties]
    assert not unknown, (
        f"WorkspaceInvite in {WORKSPACES_TS.relative_to(REPO_ROOT)} declares "
        f"{unknown}, which WorkspaceInviteResponse does not return"
    )
