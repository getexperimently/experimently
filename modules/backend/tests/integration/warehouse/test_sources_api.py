"""Warehouse sources: the identifier gate, validation, previews and the audit log."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from modules.backend.app.models.warehouse_analysis_run import WarehouseAnalysisRun
from modules.backend.app.models.warehouse_source import WarehouseSource
from modules.backend.app.schemas.responses_warehouse import PreviewOut
from modules.backend.tests.integration.warehouse.conftest import WA, ts

pytestmark = [pytest.mark.integration, pytest.mark.modules]


def _tables(wh, key="checkout"):
    wh.exposures(
        [
            ("u1", key, "control", ts(12)),
            ("u2", key, "control", ts(13)),
            ("u3", key, "treatment", ts(14)),
            (None, key, "treatment", ts(14)),
            ("u4", key, None, ts(15)),
            ("old", key, "control", ts(1)),
        ]
    )
    wh.events([("u1", ts(13), 2.5), ("u2", ts(14), None), ("u3", ts(19), 1.0)])


@pytest.mark.parametrize(
    "table",
    [
        "main.exposures.extra",
        "MAIN.exposures",
        "main",
        "main.exposures\n",
        'main."x"',
        "main.ex posures",
    ],
)
def test_the_identifier_gate_refuses_at_create(wh, table):
    admin = wh.as_("ADMIN")
    connection = wh.athena_connection(admin)
    before = wh.db.query(WarehouseSource).count()
    response = admin.post(
        f"{WA}/sources",
        json={
            "kind": "assignment",
            "connection_id": connection["id"],
            "name": "Exposures",
            "table": table,
            "columns": {
                "unit_id": "user_id",
                "experiment_key": "experiment_key",
                "variant": "variant",
                "exposed_at": "exposed_at",
            },
        },
    )
    assert response.status_code == 422, response.text
    assert wh.db.query(WarehouseSource).count() == before
    assert wh.queries == [] and wh.specs == []


def test_a_filter_literal_outside_the_allowlist_is_refused(wh):
    admin = wh.as_("ADMIN")
    connection = wh.athena_connection(admin)
    for value in ("paid'", "a;b", "x/*", "tab\there", "back\\slash"):
        response = admin.post(
            f"{WA}/sources",
            json={
                "kind": "metric",
                "connection_id": connection["id"],
                "name": f"Orders {uuid.uuid4().hex[:4]}",
                "table": "main.events",
                "columns": {"unit_id": "user_id", "event_at": "event_at"},
                "metric_type": "proportion",
                "filters": [{"column": "status", "operator": "eq", "value": value}],
            },
        )
        assert response.status_code == 422, value


def test_validate_returns_columns_and_types(wh):
    _tables(wh)
    connection = wh.athena_connection(wh.as_("ADMIN"))
    analyst = wh.as_("ANALYST")
    metric = wh.metric_source(
        analyst,
        connection["id"],
        metric_type="mean",
        columns={"unit_id": "user_id", "event_at": "event_at", "value": "amount"},
    )
    assert metric["validated_at"] is None
    validated = wh.validate(analyst, metric["id"])
    assert set(validated) == {"source", "columns"}
    assert validated["columns"] == [
        {"name": "user_id", "type": "VARCHAR"},
        {"name": "event_at", "type": "TIMESTAMP WITH TIME ZONE"},
        {"name": "amount", "type": "DOUBLE"},
    ]
    assert validated["source"]["columns"] == {
        "unit_id": {"name": "user_id", "type": "VARCHAR"},
        "event_at": {"name": "event_at", "type": "TIMESTAMP WITH TIME ZONE"},
        "value": {"name": "amount", "type": "DOUBLE"},
    }
    assert validated["source"]["validated_at"] is not None
    # Validation read metadata only: no statement was sent.
    assert wh.queries == []
    # Editing clears it.  The analyst who created the source edits it; the
    # client is re-made here because the auth override is app-global.
    analyst = wh.as_("ANALYST")
    edited = analyst.put(
        f"{WA}/sources/{metric['id']}",
        json={
            "kind": "metric",
            "name": "Revenue",
            "table": "main.events",
            "columns": {
                "unit_id": "user_id",
                "event_at": "event_at",
                "value": "amount",
            },
            "metric_type": "mean",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["validated_at"] is None


@pytest.mark.parametrize(
    ("columns", "code", "field"),
    [
        (
            {"unit_id": "user_id", "event_at": "missing"},
            "identifier_not_found",
            "columns.event_at",
        ),
        (
            {"unit_id": "user_id", "event_at": "user_id"},
            "unsupported_column_type",
            "columns.event_at",
        ),
    ],
)
def test_validation_refusals_name_the_column(wh, columns, code, field):
    _tables(wh)
    admin = wh.as_("ADMIN")
    connection = wh.athena_connection(admin)
    source = wh.metric_source(admin, connection["id"], columns=columns)
    response = admin.post(f"{WA}/sources/{source['id']}/validate")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["field"] == field


def test_a_non_numeric_value_column_is_refused(wh):
    _tables(wh)
    admin = wh.as_("ADMIN")
    connection = wh.athena_connection(admin)
    source = wh.metric_source(
        admin,
        connection["id"],
        metric_type="mean",
        columns={"unit_id": "user_id", "event_at": "event_at", "value": "user_id"},
    )
    response = admin.post(f"{WA}/sources/{source['id']}/validate")
    assert response.json()["detail"]["code"] == "unsupported_column_type"


PREVIEW_FIELDS = {
    "kind",
    "window_start",
    "window_end",
    "total_rows",
    "null_unit_rows",
    "null_variant_rows",
    "variants",
    "null_value_rows",
    "earliest",
    "latest",
    "run_id",
}


def test_preview_returns_aggregates_only(wh):
    """The preview's response schema has counts, time bounds and labels; no
    field can carry a row."""
    assert set(PreviewOut.model_fields) == PREVIEW_FIELDS
    variant_fields = PreviewOut.model_json_schema()["$defs"]["PreviewVariantOut"][
        "properties"
    ]
    assert set(variant_fields) == {"label", "units"}

    _tables(wh, key="exp-a")
    wh.now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    admin = wh.as_("ADMIN")
    ids = wh.ready(admin)
    assignment = admin.post(
        f"{WA}/sources/{ids['assignment_source_id']}/preview",
        json={"experiment_key": "exp-a"},
    )
    assert assignment.status_code == 200, assignment.text
    body = assignment.json()
    assert set(body) == PREVIEW_FIELDS
    assert body["kind"] == "assignment"
    # The default window: the last 7 days before the clock (Sep 19).
    assert body["window_start"].startswith("2026-09-12T00:00:00")
    assert (body["total_rows"], body["null_unit_rows"], body["null_variant_rows"]) == (
        5,
        1,
        1,
    )
    assert body["variants"] == [
        {"label": "control", "units": 2},
        {"label": "treatment", "units": 1},
    ]
    assert body["earliest"].startswith("2026-09-12T00:00:00")
    assert body["latest"].startswith("2026-09-15T00:00:00")

    metric = admin.post(
        f"{WA}/sources/{ids['metric_source_id']}/preview",
        json={
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-19T00:00:00Z",
        },
    )
    assert metric.status_code == 200, metric.text
    body = metric.json()
    assert (body["total_rows"], body["null_unit_rows"], body["null_value_rows"]) == (
        2,
        0,
        None,
    )
    assert body["variants"] is None

    run = wh.db.get(WarehouseAnalysisRun, uuid.UUID(body["run_id"]))
    assert (run.kind, run.status) == ("preview", "succeeded")
    assert set(run.results) == {
        "total_rows",
        "null_unit_rows",
        "null_value_rows",
        "earliest",
        "latest",
    }
    for unit in ("u1", "u2", "u3", "u4", "old"):
        assert unit not in assignment.text and unit not in metric.text


def test_a_preview_needs_a_validated_source(wh):
    admin = wh.as_("ADMIN")
    connection = wh.athena_connection(admin)
    source = wh.metric_source(admin, connection["id"])
    response = admin.post(f"{WA}/sources/{source['id']}/preview")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "source_not_validated"


def test_a_failed_preview_is_recorded_with_its_code(wh):
    from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode

    _tables(wh)
    admin = wh.as_("ADMIN")
    ids = wh.ready(admin)
    wh.fail_with = WarehouseError(WarehouseErrorCode.BYTES_LIMIT)
    response = admin.post(f"{WA}/sources/{ids['metric_source_id']}/preview")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "bytes_limit"
    wh.db.expire_all()
    rows = (
        wh.db.query(WarehouseAnalysisRun)
        .filter(WarehouseAnalysisRun.connection_id == uuid.UUID(ids["connection_id"]))
        .all()
    )
    assert [(r.status, r.error_code, r.results) for r in rows] == [
        ("failed", "bytes_limit", None)
    ]


def _audit_rows(wh, source_id: str):
    return wh.db.execute(
        text(
            "SELECT action, old_value, new_value FROM test_experimentation.audit_events_v2 "
            "WHERE resource_type = 'warehouse_source' AND resource_id = :id "
            "ORDER BY timestamp"
        ),
        {"id": source_id},
    ).all()


def test_source_audit_has_full_definition(wh):
    _tables(wh)
    admin = wh.as_("ADMIN")
    connection = wh.athena_connection(admin)
    created = wh.metric_source(
        admin,
        connection["id"],
        name="Paid orders",
        filters=[{"column": "user_id", "operator": "ne", "value": "bot"}],
    )
    admin.put(
        f"{WA}/sources/{created['id']}",
        json={
            "kind": "metric",
            "name": "Paid orders",
            "table": "main.events",
            "columns": {"unit_id": "user_id", "event_at": "event_at"},
            "metric_type": "proportion",
            "conversion_window_hours": 24,
        },
    )
    admin.delete(f"{WA}/sources/{created['id']}")
    rows = _audit_rows(wh, created["id"])
    assert [str(r.action).split(".")[-1] for r in rows] == [
        "CREATE",
        "UPDATE",
        "DELETE",
    ]
    definition = rows[0].new_value
    assert definition == {
        "connection_id": connection["id"],
        "kind": "metric",
        "name": "Paid orders",
        "table_reference": {"parts": ["main", "events"]},
        "column_mapping": {
            "unit_id": {"name": "user_id", "type": None},
            "event_at": {"name": "event_at", "type": None},
        },
        "filters": [{"column": "user_id", "operator": "ne", "value": "bot"}],
        "metric_type": "proportion",
        "conversion_window_hours": 168,
        "cap_value": None,
        "validated_at": None,
    }
    assert rows[1].old_value == definition
    assert rows[1].new_value["conversion_window_hours"] == 24
    assert rows[1].new_value["filters"] == []
    assert rows[2].old_value["conversion_window_hours"] == 24
    assert rows[2].new_value is None


def test_a_source_name_is_unique_per_connection_and_kind(wh):
    admin = wh.as_("ADMIN")
    connection = wh.athena_connection(admin)
    wh.metric_source(admin, connection["id"], name="Orders")
    response = admin.post(
        f"{WA}/sources",
        json={
            "kind": "metric",
            "connection_id": connection["id"],
            "name": "Orders",
            "table": "main.events",
            "columns": {"unit_id": "user_id", "event_at": "event_at"},
            "metric_type": "proportion",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_name_taken"
