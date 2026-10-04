"""The audit log export is in the committed OpenAPI snapshots (#221).

A route missing from a snapshot is only a warning in
``test_openapi_snapshot.py``, so this pins ``GET /api/v1/audit-logs/export``
by name: present in the core and full snapshots and in the dashboard's URL
fixture, marked beta, with its ``format`` choices, both media types and the
``X-Total-Count`` header.
"""

from __future__ import annotations

import json

import pytest

from backend.tests.smoke.modules_manifest import REPO_ROOT

pytestmark = [pytest.mark.smoke]

EXPORT = "/api/v1/audit-logs/export"
SNAPSHOTS = (
    REPO_ROOT / "docs" / "api" / "openapi-v1.stable.json",
    REPO_ROOT / "docs" / "api" / "openapi-v1.full.json",
)
URL_FIXTURE = REPO_ROOT / "frontend" / "src" / "tests" / "fixtures" / "openapi.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", SNAPSHOTS, ids=lambda p: p.name)
def test_the_export_is_pinned_in_the_snapshot(path):
    paths = _load(path)["paths"]
    assert EXPORT in paths, f"{EXPORT} is not in {path.name}: run `make openapi`"
    assert set(paths[EXPORT]) == {"get"}
    operation = paths[EXPORT]["get"]
    assert operation["x-stability"] == "beta"
    params = {p["name"]: p for p in operation["parameters"]}
    assert set(params) == {
        "format",
        "user_id",
        "entity_type",
        "entity_id",
        "action_type",
        "from_date",
        "to_date",
    }
    assert params["format"]["schema"]["enum"] == ["json", "csv"]
    assert params["format"]["schema"]["default"] == "json"
    ok = operation["responses"]["200"]
    assert set(ok["content"]) == {"application/json", "text/csv"}
    assert "X-Total-Count" in ok["headers"]
    assert "422" in operation["responses"]


def test_the_export_is_in_the_dashboard_url_fixture():
    assert "get" in _load(URL_FIXTURE)["paths"][EXPORT]
