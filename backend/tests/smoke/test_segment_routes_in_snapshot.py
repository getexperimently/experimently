"""The segment routes changed by #440 are in the stable snapshot, as changed.

A route missing from ``docs/api/openapi-v1.stable.json`` is only a warning in
``test_openapi_snapshot.py``, so this pins the segment operations by name:
the nine stable ones and the two beta member routes are present, every
``{segment_id}`` is typed as a UUID, evaluate documents its 409 for stored
rules that are not valid, the request schemas describe the targeting rule
format, and a segment carries its ``kind``. ``docs/api/stability.md`` lists the
changed stable operations in its table of changed stable operations.
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

#: The id-list member routes (#440 PR B), beta.
MEMBER_OPERATIONS = {
    ("/api/v1/segments/{segment_id}/members", "post"),
    ("/api/v1/segments/{segment_id}/members/remove", "post"),
}


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_nine_segment_operations_are_stable_and_the_member_routes_beta(snapshot):
    found = {
        (path, method)
        for path, item in snapshot["paths"].items()
        if path.startswith("/api/v1/segments")
        for method in item
    }
    assert found == SEGMENT_OPERATIONS | MEMBER_OPERATIONS
    for path, method in SEGMENT_OPERATIONS:
        assert "x-stability" not in snapshot["paths"][path][method]
    for path, method in MEMBER_OPERATIONS:
        assert snapshot["paths"][path][method]["x-stability"] == "beta"


def test_the_member_routes_document_their_answers(snapshot):
    for path, method in MEMBER_OPERATIONS:
        assert set(snapshot["paths"][path][method]["responses"]) == {
            "200",
            "404",
            "409",
            "422",
        }
    schemas = snapshot["components"]["schemas"]
    assert set(schemas["SegmentMembersAddResponse"]["properties"]) == {
        "added",
        "already_members",
        "member_count",
    }
    assert set(schemas["SegmentMembersRemoveResponse"]["properties"]) == {
        "removed",
        "not_members",
        "member_count",
    }
    for name, field in (
        ("SegmentMembersAdd", "add"),
        ("SegmentMembersRemove", "remove"),
    ):
        assert schemas[name]["additionalProperties"] is False
        ids = schemas[name]["properties"][field]
        assert (ids["minItems"], ids["maxItems"]) == (1, 10_000)
        assert (ids["items"]["minLength"], ids["items"]["maxLength"]) == (1, 255)


def test_a_segment_carries_its_kind(snapshot):
    schemas = snapshot["components"]["schemas"]
    assert schemas["SegmentKind"]["enum"] == ["rules", "id_list"]
    for name in ("SegmentCreate", "SegmentResponse"):
        assert schemas[name]["properties"]["kind"]["$ref"].endswith("/SegmentKind")
    assert "kind" not in schemas["SegmentUpdate"]["properties"]


def test_every_segment_id_is_a_uuid(snapshot):
    typed = []
    for path, method in sorted(SEGMENT_OPERATIONS | MEMBER_OPERATIONS):
        for parameter in snapshot["paths"][path][method].get("parameters", []):
            if parameter["name"] == "segment_id":
                assert parameter["in"] == "path"
                assert parameter["schema"].get("format") == "uuid", (path, method)
                typed.append((path, method))
    assert len(typed) == 8


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


def test_stability_md_lists_the_kind_change():
    """PR B's row: every stable operation that now carries or takes ``kind``."""
    text = STABILITY.read_text(encoding="utf-8")
    row = next(
        (line for line in text.splitlines() if "| #440 (id lists) |" in line), None
    )
    assert row is not None, "docs/api/stability.md has no #440 kind row"
    assert "`kind`" in row
    for path in (
        "/api/v1/segments",
        "/api/v1/segments/{segment_id}",
        "/api/v1/segments/{segment_id}/evaluate",
        "/api/v1/segments/bulk-evaluate",
        "/api/v1/segments/{segment_id}/preview",
    ):
        assert f"{path}`" in row, path


@pytest.mark.parametrize(
    "path, method",
    [
        ("/api/v1/segments/{segment_id}", "delete"),
        ("/api/v1/segments/{segment_id}", "put"),
    ],
)
def test_archive_and_update_document_the_in_use_409(snapshot, path, method):
    """#440 PR C: a segment that targeting uses cannot be archived or deactivated."""
    responses = snapshot["paths"][path][method]["responses"]
    assert "409" in responses
    assert "segment_in_use" in responses["409"]["description"]


def test_stability_md_lists_segment_targeting():
    """PR C's row: the stable operations whose answers segment targeting changed."""
    text = STABILITY.read_text(encoding="utf-8")
    row = next(
        (line for line in text.splitlines() if "| #440 (segment targeting) |" in line),
        None,
    )
    assert row is not None, "docs/api/stability.md has no #440 segment targeting row"
    for fact in ("`in_segment`", "`not_in_segment`", "segment_in_use", "409", "422"):
        assert fact in row, fact
    for operation in (
        "`DELETE /api/v1/segments/{segment_id}`",
        "`PUT /api/v1/segments/{segment_id}`",
        "`POST /api/v1/feature-flags/`",
        "`PUT /api/v1/feature-flags/{flag_id}`",
        "`POST /api/v1/experiments/`",
        "`PUT /api/v1/experiments/{experiment_id}`",
        "`POST /api/v1/experiments/{experiment_id}/clone`",
    ):
        assert operation in row, operation
