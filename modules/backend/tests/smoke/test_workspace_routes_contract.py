"""Workspaces serve no API-key routes and publish no plan or limits (#263, #264).

The four workspace API-key operations were removed. This checks the live
application's OpenAPI document (``app.openapi()``), which is what the router
actually mounts. The same absence in the committed full snapshot is checked by
the core docs test ``backend/tests/unit/docs/test_workspaces_docs.py``, which
reads the JSON alone and so runs in a core tree too.

The positive control (the members route) must be present, so a registration
that mounted nothing cannot pass the absence checks.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.smoke

WORKSPACES = "/api/v1/workspaces"
POSITIVE_CONTROL = "/api/v1/workspaces/{workspace_id}/members"

#: Request and response schemas removed with the key routes and the plan field.
REMOVED_SCHEMAS = (
    "CreateAPIKeyRequest",
    "CreateAPIKeyResponse",
    "WorkspaceAPIKeyResponse",
)
#: Fields no workspace schema may carry any more.
REMOVED_FIELDS = (
    "plan",
    "max_experiments",
    "max_feature_flags",
    "max_members",
    "max_api_keys",
    "api_key_count",
    "experiment_count",
    "flag_count",
)
WORKSPACE_SCHEMAS = (
    "CreateWorkspaceRequest",
    "UpdateWorkspaceRequest",
    "WorkspaceResponse",
    "WorkspaceWithStatsResponse",
)


def key_paths(document: dict) -> list[str]:
    """Every workspace path that names API keys, in any letter case."""
    return sorted(
        path
        for path in document.get("paths", {})
        if path.lower().startswith(WORKSPACES) and "api-key" in path.lower()
    )


@pytest.fixture(scope="module")
def live() -> dict:
    from backend.app.main import app

    return app.openapi()


def test_the_positive_control_is_present(live):
    assert POSITIVE_CONTROL in live["paths"], (
        "the workspaces routes are not mounted; the absence checks below prove "
        "nothing until they are"
    )


def test_no_workspace_api_key_route(live):
    assert POSITIVE_CONTROL in live["paths"], "positive control failed"
    found = key_paths(live)
    assert not found, f"workspace API-key routes are still served: {found}"


def test_no_key_schema_and_no_plan_field(live):
    schemas = live.get("components", {}).get("schemas", {})
    assert set(WORKSPACE_SCHEMAS) <= set(schemas), "workspace schemas are missing"
    still = [name for name in REMOVED_SCHEMAS if name in schemas]
    assert not still, f"removed schemas are still published: {still}"
    fields = [
        f"{name}.{field}"
        for name in WORKSPACE_SCHEMAS
        for field in REMOVED_FIELDS
        if field in schemas[name].get("properties", {})
    ]
    assert not fields, f"removed fields are still published: {fields}"


def test_requests_refuse_unknown_fields(live):
    schemas = live["components"]["schemas"]
    for name in ("CreateWorkspaceRequest", "UpdateWorkspaceRequest"):
        assert schemas[name].get("additionalProperties") is False, name


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/workspaces/{workspace_id}/api-keys",
        "/api/v1/workspaces/{workspace_id}/api-keys/{key_id}",
        "/api/v1/workspaces/{workspace_id}/api-keys/{key_id}/rotate",
        "/api/v1/Workspaces/{workspace_id}/API-Keys",
    ],
)
def test_the_selector_catches_a_planted_route(path):
    """The check's own tamper list: each planted path must be found."""
    assert key_paths({"paths": {POSITIVE_CONTROL: {}, path: {}}}) == [path]
