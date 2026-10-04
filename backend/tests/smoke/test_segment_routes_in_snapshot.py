"""The segment routes changed by #440 are in the stable snapshot, as changed.

A route missing from ``docs/api/openapi-v1.stable.json`` is only a warning in
``test_openapi_snapshot.py``, so this pins the segment operations by name:
all nine are present and stable, every ``{segment_id}`` is typed as a UUID,
evaluate documents its 409 for stored rules that are not valid, and the
request schemas describe the targeting rule format. ``docs/api/stability.md``
lists the same operations in its table of changed stable operations.
"""

from __future__ import annotations

import json

import pytest

from backend.tests.smoke.modules_manifest import REPO_ROOT

pytestmark = [pytest.mark.smoke, pytest.mark.regression]

SNAPSHOT = REPO_ROOT / "docs" / "api" / "openapi-v1.stable.json"
STABILITY = REPO_ROOT / "docs" / "api" / "stability.md"

SEGMENT_OPERATIONS = {
    ("/api/v1/segments", "get"),
    ("/api/v1/segments", "post"),
    ("/api/v1/segments/bulk-evaluate", "post"),
    ("/api/v1/segments/{segment_id}", "get"),
    ("/api/v1/segments/{segment_id}", "put"),
    ("/api/v1/segments/{segment_id}", "delete"),
    ("/api/v1/segments/{segment_id}/evaluate", "post"),
    ("/api/v1/segments/{segment_id}/experiments", "get"),
    ("/api/v1/segments/{segment_id}/preview", "post"),
}


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_exactly_the_nine_segment_operations_are_stable(snapshot):
    found = {
        (path, method)
        for path, item in snapshot["paths"].items()
        if path.startswith("/api/v1/segments")
        for method in item
    }
    assert found == SEGMENT_OPERATIONS
    for path, method in SEGMENT_OPERATIONS:
        assert "x-stability" not in snapshot["paths"][path][method]


def test_every_segment_id_is_a_uuid(snapshot):
    typed = []
    for path, method in sorted(SEGMENT_OPERATIONS):
        for parameter in snapshot["paths"][path][method].get("parameters", []):
            if parameter["name"] == "segment_id":
                assert parameter["in"] == "path"
                assert parameter["schema"].get("format") == "uuid", (path, method)
                typed.append((path, method))
    assert len(typed) == 6


def test_evaluate_documents_the_409(snapshot):
    responses = snapshot["paths"]["/api/v1/segments/{segment_id}/evaluate"]["post"][
        "responses"
    ]
    assert set(responses) == {"200", "409", "422"}


@pytest.mark.parametrize("schema", ["SegmentCreate", "SegmentUpdate"])
def test_the_rules_schema_names_the_targeting_rule_format(snapshot, schema):
    rules = snapshot["components"]["schemas"][schema]["properties"]["rules"]
    assert "the format flag and experiment targeting use" in rules["description"]
    assert '"groups"' in rules["description"]


def test_the_create_example_is_in_the_targeting_rule_format(snapshot):
    example = snapshot["components"]["schemas"]["SegmentCreate"]["example"]["rules"]
    assert set(example) == {"logical_operator", "groups"}
    operators = {c["operator"] for g in example["groups"] for c in g["conditions"]}
    assert operators == {"equals"}


def test_stability_md_lists_the_changed_segment_operations():
    text = STABILITY.read_text(encoding="utf-8")
    row = next((line for line in text.splitlines() if "| #440 |" in line), None)
    assert row is not None, "docs/api/stability.md has no #440 row"
    for path, method in SEGMENT_OPERATIONS - {("/api/v1/segments", "get")}:
        assert path in row, path
