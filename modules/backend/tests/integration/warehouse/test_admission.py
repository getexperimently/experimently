"""Admission: the daily limit, the deployment limit, one job in flight per
connection, and how previews and connection tests take part."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from modules.backend.app.models.warehouse_analysis_run import WarehouseAnalysisRun
from modules.backend.app.services import warehouse_runner as runner
from modules.backend.app.warehouse.executor import WarehouseExecutor
from modules.backend.tests.integration.warehouse.conftest import WA, ts

pytestmark = [pytest.mark.integration, pytest.mark.modules]


def _data(wh, key):
    wh.exposures([("u1", key, "control", ts(2)), ("u2", key, "treatment", ts(2))])
    wh.events([("u1", ts(3), None)])


def _rows_on(wh, connection_id: str) -> list[WarehouseAnalysisRun]:
    wh.db.expire_all()
    return (
        wh.db.query(WarehouseAnalysisRun)
        .filter(WarehouseAnalysisRun.connection_id == uuid.UUID(connection_id))
        .all()
    )


def _plant(
    wh,
    connection_id: str,
    *,
    kind: str,
    created_at: datetime,
    status="succeeded",
    **values,
):
    row = WarehouseAnalysisRun(
        kind=kind,
        status=status,
        connection_id=uuid.UUID(connection_id),
        connection_name="Lake",
        warehouse_type="athena",
        experiment_id=values.pop("experiment_id", None),
        request=values.pop("request", {}),
        created_at=created_at.astimezone(timezone.utc).replace(tzinfo=None),
        **values,
    )
    wh.db.add(row)
    wh.db.commit()
    return row


def _hold(wh):
    wh.gate = threading.Event()
    return wh.gate


def _release_and_drain(wh, client, run_ids):
    wh.gate.set()
    for run_id in run_ids:
        wh.wait_for_run(client, run_id)
    wh.gate = None


def test_daily_run_limit_429(wh):
    """The 20th run of the UTC day is admitted, the 21st is not -- previews
    included -- and the count resets at 00:00 UTC."""
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _data(wh, experiment.key)
    ids = wh.ready(admin)
    earlier = wh.now - timedelta(hours=11)
    for index in range(19):
        _plant(
            wh,
            ids["connection_id"],
            kind="preview" if index == 0 else "analysis",
            status="failed" if index == 1 else "succeeded",
            error_code="time_limit" if index == 1 else None,
            experiment_id=None if index == 0 else experiment.id,
            created_at=earlier,
        )
    # Yesterday's rows do not count.
    _plant(
        wh,
        ids["connection_id"],
        kind="analysis",
        experiment_id=experiment.id,
        created_at=wh.now - timedelta(days=1),
    )

    twentieth = wh.start_run(admin, experiment, ids)
    assert twentieth.status_code == 202, twentieth.text
    wh.wait_for_run(admin, twentieth.json()["run_id"])

    refused = wh.start_run(admin, experiment, ids)
    assert refused.status_code == 429
    detail = refused.json()["detail"]
    assert detail["code"] == "daily_run_limit_reached"
    assert detail["limit"] == 20
    assert detail["resets_at"] == "2026-09-21T00:00:00Z"
    assert refused.headers["retry-after"] == str(12 * 3600)
    assert detail["message"] == (
        "Not run: Lake has reached its limit of 20 analyses per day (UTC, previews "
        "included). The count resets at 00:00 UTC, in 12 h 0 min. An admin can "
        "change the limit in Warehouse › Connections › Lake."
    )
    # A preview is refused by the same count.
    preview = admin.post(f"{WA}/sources/{ids['assignment_source_id']}/preview")
    assert preview.status_code == 429
    assert preview.json()["detail"]["code"] == "daily_run_limit_reached"
    assert len(_rows_on(wh, ids["connection_id"])) == 21

    wh.now = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
    again = wh.start_run(admin, experiment, ids)
    assert again.status_code == 202, again.text
    wh.wait_for_run(admin, again.json()["run_id"])


def test_two_concurrent_run_posts_one_202(wh):
    """Two sessions admit a run on one connection at once: the partial unique
    index lets one in and answers the other 409, whatever the process."""
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _data(wh, experiment.key)
    ids = wh.ready(admin)
    new = runner.NewRun(
        kind="analysis",
        connection_id=uuid.UUID(ids["connection_id"]),
        connection_name="Lake",
        warehouse_type="athena",
        max_runs_per_day=20,
        experiment_id=experiment.id,
        requested_by=None,
        request={"total_seconds": 360},
        window_start=ts(1),
        window_end=ts(10),
        statements=[],
    )
    barrier = threading.Barrier(2)
    outcomes: list = []

    def admit_once():
        session = wh.session_factory()
        try:
            barrier.wait(10)
            outcomes.append(
                runner.admit(session, new, now=wh.now, max_concurrent_runs=10)
            )
        except runner.AdmissionRefused as exc:
            outcomes.append((exc.status_code, exc.code))
        finally:
            session.close()

    threads = [threading.Thread(target=admit_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    admitted = [o for o in outcomes if isinstance(o, uuid.UUID)]
    refused = [o for o in outcomes if not isinstance(o, uuid.UUID)]
    assert len(admitted) == 1 and refused == [(409, "run_in_progress")], outcomes
    in_flight = [r for r in _rows_on(wh, ids["connection_id"]) if r.status == "queued"]
    assert len(in_flight) == 1
    in_flight[0].status = "failed"
    in_flight[0].error_code = "abandoned"
    wh.db.commit()


def test_a_second_run_on_a_busy_connection_409(wh):
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _data(wh, experiment.key)
    ids = wh.ready(admin)
    _hold(wh)
    first = wh.start_run(admin, experiment, ids)
    assert first.status_code == 202
    assert wh.entered.acquire(timeout=10)
    second = wh.start_run(admin, experiment, ids)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "run_in_progress"
    # A preview on the same connection waits its turn too (PE condition 9).
    preview = admin.post(f"{WA}/sources/{ids['metric_source_id']}/preview")
    assert preview.status_code == 409
    assert preview.json()["detail"]["code"] == "run_in_progress"
    _release_and_drain(wh, admin, [first.json()["run_id"]])
    # Neither refusal was recorded, so neither used a slot of the day.
    assert len(_rows_on(wh, ids["connection_id"])) == 1


def test_deployment_run_cap(wh, monkeypatch):
    """At WAREHOUSE_MAX_CONCURRENT_RUNS (2) runs in flight across the
    deployment, a third on another connection is 429 -- counted in the
    database, so it holds across API tasks, not only in this process."""
    wh.executor.shutdown(wait=True)
    wh.executor = WarehouseExecutor(8, per_organisation=8)
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _data(wh, experiment.key)
    connections = [wh.ready(admin) for _ in range(3)]
    _hold(wh)
    started = []
    for ids in connections[:2]:
        response = wh.start_run(admin, experiment, ids)
        assert response.status_code == 202, response.text
        started.append(response.json()["run_id"])
        assert wh.entered.acquire(timeout=10)
    third = wh.start_run(admin, experiment, connections[2])
    assert third.status_code == 429
    assert third.json()["detail"]["code"] == "warehouse_busy"
    assert third.headers["retry-after"] == "30"
    assert _rows_on(wh, connections[2]["connection_id"]) == []
    _release_and_drain(wh, admin, started)
    after = wh.start_run(admin, experiment, connections[2])
    assert after.status_code == 202
    wh.wait_for_run(admin, after.json()["run_id"])


def test_warehouse_busy_consumes_no_daily_slot(wh):
    """A full executor refuses before anything is written."""
    wh.executor.shutdown(wait=True)
    wh.executor = WarehouseExecutor(1, per_organisation=1)
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _data(wh, experiment.key)
    busy, other = wh.ready(admin), wh.ready(admin)
    _hold(wh)
    held = wh.start_run(admin, experiment, busy)
    assert held.status_code == 202
    assert wh.entered.acquire(timeout=10)
    for _ in range(3):
        refused = wh.start_run(admin, experiment, other)
        assert refused.status_code == 429
        assert refused.json()["detail"]["code"] == "warehouse_busy"
    assert _rows_on(wh, other["connection_id"]) == []
    _release_and_drain(wh, admin, [held.json()["run_id"]])


def test_connection_tests_and_validation_are_not_counted(wh):
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _data(wh, experiment.key)
    connection = wh.athena_connection(admin, max_runs_per_day=1)
    source = wh.assignment_source(admin, connection["id"])
    for _ in range(3):
        assert (
            admin.post(f"{WA}/connections/{connection['id']}/test").status_code == 200
        )
        wh.validate(admin, source["id"])
    assert _rows_on(wh, connection["id"]) == []
    preview = admin.post(f"{WA}/sources/{source['id']}/preview")
    assert preview.status_code == 200, preview.text
    # The preview used the only slot of the day.
    second = admin.post(f"{WA}/sources/{source['id']}/preview")
    assert second.status_code == 429


def test_stale_runs_are_marked_abandoned(wh):
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _data(wh, experiment.key)
    ids = wh.ready(admin)
    stale = _plant(
        wh,
        ids["connection_id"],
        kind="analysis",
        status="running",
        experiment_id=experiment.id,
        created_at=wh.now - timedelta(hours=2),
        heartbeat_at=wh.now - timedelta(seconds=361 + runner.STALE_MARGIN_SECONDS),
        request={"total_seconds": 360},
    )
    fresh = wh.start_run(admin, experiment, ids)
    assert fresh.status_code == 202, fresh.text
    wh.wait_for_run(admin, fresh.json()["run_id"])
    wh.db.refresh(stale)
    assert (stale.status, stale.error_code) == ("failed", "abandoned")


def test_a_run_with_a_recent_heartbeat_is_not_abandoned(wh):
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _data(wh, experiment.key)
    ids = wh.ready(admin)
    live = _plant(
        wh,
        ids["connection_id"],
        kind="analysis",
        status="running",
        experiment_id=experiment.id,
        created_at=wh.now - timedelta(hours=2),
        heartbeat_at=wh.now - timedelta(seconds=359 + runner.STALE_MARGIN_SECONDS),
        request={"total_seconds": 360},
    )
    refused = wh.start_run(admin, experiment, ids)
    assert refused.status_code == 409
    wh.db.refresh(live)
    assert live.status == "running"
    live.status, live.error_code = "failed", "abandoned"
    wh.db.commit()
