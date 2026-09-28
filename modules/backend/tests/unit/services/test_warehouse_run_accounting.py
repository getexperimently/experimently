"""The per-connection daily run count and its reset (#312)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from modules.backend.app.models.warehouse_analysis_run import WarehouseAnalysisRun
from modules.backend.app.models.warehouse_connection import WarehouseConnection
from modules.backend.app.services import warehouse_run_accounting as accounting

#: A fixed clock: 21:00 UTC on 2026-09-27.
NOW = datetime(2026, 9, 27, 21, 0, 0, tzinfo=timezone.utc)
TODAY = datetime(2026, 9, 27, 0, 0, 0)  # naive UTC, as created_at is stored


def _connection(db_session) -> WarehouseConnection:
    conn = WarehouseConnection(
        name=f"acct-{uuid.uuid4().hex[:8]}", warehouse_type="snowflake"
    )
    db_session.add(conn)
    db_session.commit()
    return conn


def _run(conn, created_at, kind="preview", status="succeeded", error_code=None):
    return WarehouseAnalysisRun(
        kind=kind,
        status=status,
        error_code=error_code,
        connection_id=conn.id,
        connection_name=conn.name,
        warehouse_type=conn.warehouse_type,
        request={},
        created_at=created_at,
        updated_at=created_at,
    )


@pytest.mark.regression
def test_runs_counted_today(db_session):
    """Previews and analyses, any status, since 00:00 UTC; nothing else."""
    conn = _connection(db_session)
    other = _connection(db_session)
    db_session.add_all(
        [
            # Counted: today, a preview, a failure, the first instant of the day.
            _run(conn, TODAY),
            _run(
                conn,
                TODAY + timedelta(hours=9),
                status="failed",
                error_code="bytes_limit",
            ),
            _run(conn, TODAY + timedelta(hours=20), status="queued"),
            # Not counted: yesterday's last instant, another connection.
            _run(conn, TODAY - timedelta(microseconds=1)),
            _run(other, TODAY + timedelta(hours=1)),
        ]
    )
    db_session.commit()

    assert accounting.runs_counted_today(db_session, conn.id, NOW) == 3
    assert accounting.runs_counted_today(db_session, other.id, NOW) == 1
    # A minute into tomorrow, today's runs no longer count.
    tomorrow = accounting.resets_at(NOW) + timedelta(minutes=1)
    assert accounting.runs_counted_today(db_session, conn.id, tomorrow) == 0


def test_analyses_count_too(db_session, normal_user):
    from backend.app.models.experiment import Experiment, ExperimentStatus

    conn = _connection(db_session)
    experiment = Experiment(
        name=f"acct-{uuid.uuid4().hex[:8]}",
        description="d",
        hypothesis="h",
        owner_id=normal_user.id,
        status=ExperimentStatus.DRAFT,
    )
    db_session.add(experiment)
    db_session.commit()
    run = _run(conn, TODAY + timedelta(hours=1), kind="analysis")
    run.experiment_id = experiment.id
    db_session.add(run)
    db_session.commit()

    assert accounting.runs_counted_today(db_session, conn.id, NOW) == 1


@pytest.mark.regression
@pytest.mark.parametrize(
    ("used", "limit", "reached"),
    [
        (0, 20, False),
        (19, 20, False),
        (20, 20, True),
        (21, 20, True),
        (0, 1, False),
        (1, 1, True),
    ],
)
def test_the_run_after_the_limit_is_refused(used, limit, reached):
    """With a limit of 20 the 20th run is admitted and the 21st is not."""
    assert accounting.daily_limit_reached(used, limit) is reached


def test_the_count_resets_at_midnight_utc():
    assert accounting.day_start(NOW) == datetime(2026, 9, 27, tzinfo=timezone.utc)
    assert accounting.resets_at(NOW) == datetime(2026, 9, 28, tzinfo=timezone.utc)
    assert accounting.seconds_until_reset(NOW) == 3 * 3600
    # Partial seconds round up; the last instant still waits a second.
    assert accounting.seconds_until_reset(NOW + timedelta(microseconds=1)) == 3 * 3600
    last = datetime(2026, 9, 27, 23, 59, 59, 999999, tzinfo=timezone.utc)
    assert accounting.seconds_until_reset(last) == 1


def test_the_day_is_the_utc_day_whatever_the_offset():
    """20:00 in UTC-07:00 is 03:00 UTC the next day."""
    pacific = timezone(timedelta(hours=-7))
    evening = datetime(2026, 9, 27, 20, 0, tzinfo=pacific)
    assert accounting.day_start(evening) == datetime(2026, 9, 28, tzinfo=timezone.utc)
    assert accounting.resets_at(evening) == datetime(2026, 9, 29, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "call",
    [accounting.day_start, accounting.resets_at, accounting.seconds_until_reset],
)
def test_a_naive_now_is_refused(call):
    with pytest.raises(ValueError, match="timezone-aware"):
        call(datetime(2026, 9, 27, 21, 0))
