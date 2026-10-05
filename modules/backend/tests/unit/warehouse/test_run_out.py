"""``run_out`` withholds a run's statements when told to (D34, D50).

Since D50 only ADMIN, DEVELOPER and ANALYST reach a run, and each of them is
given its statements, so no route passes ``include_sql=False`` today.  The
serialiser still honours it, so a run's SQL stays withheld if a read route's
roles are ever widened again.  This pins that property without a database.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from modules.backend.app.api.v1.endpoints import warehouse_analysis as wa
from modules.backend.app.models.warehouse_analysis_run import WarehouseAnalysisRun
from modules.backend.app.schemas import responses_warehouse as out

pytestmark = [pytest.mark.unit, pytest.mark.modules]

SQL_TEXT = "SELECT run_out_sentinel_4b1e FROM events"
SHA = "9f2c" * 16


def _run(kind: str) -> WarehouseAnalysisRun:
    when = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    return WarehouseAnalysisRun(
        id=uuid.uuid4(),
        kind=kind,
        status="succeeded",
        connection_id=uuid.uuid4(),
        connection_name="Athena prod",
        warehouse_type="athena",
        experiment_id=uuid.uuid4() if kind == "analysis" else None,
        request={"metric_source_ids": ["m-1"], "total_seconds": 3},
        statements=[
            {"kind": "metric", "dialect": "athena", "sha256": SHA, "sql": SQL_TEXT}
        ],
        results={"metrics": []},
        job_metadata=[{"query_id": "q-1"}],
        created_at=when,
        started_at=when,
        finished_at=when,
    )


@pytest.mark.parametrize("kind", ["analysis", "preview"])
def test_statements_are_withheld_when_include_sql_is_false(kind):
    body = wa.run_out(_run(kind), include_sql=False)
    assert body["statements"] is None
    raw = json.dumps(body, default=str)
    api = out.RunOut.model_validate(body).model_dump_json()
    for text in (raw, api):
        assert SQL_TEXT not in text
        assert "run_out_sentinel_4b1e" not in text
        assert SHA not in text


@pytest.mark.parametrize("kind", ["analysis", "preview"])
def test_statements_are_returned_when_include_sql_is_true(kind):
    """Vacuity guard: the run under test does carry SQL and a SHA-256."""
    body = wa.run_out(_run(kind), include_sql=True)
    assert body["statements"] == _run(kind).statements
    api = out.RunOut.model_validate(body).model_dump_json()
    assert SQL_TEXT in api and SHA in api
