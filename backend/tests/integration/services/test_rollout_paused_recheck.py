"""A paused rollout schedule is never advanced by work already in flight (#629).

The rollout scheduler read the ACTIVE schedules at the start of a tick,
without a lock, and later took the flag ``FOR UPDATE`` to write the new
percentage. A pause committed in between -- by an operator, or by a writer
that pauses the schedule while it holds that flag lock -- was not seen: the
tick waited for the lock, then advanced the paused schedule anyway. The
manual stage advance had the same unlocked check before its flag lock, and
the scheduler's last-stage branch overwrote PAUSED with COMPLETED.

Now each of them takes the flag lock, then reads the schedule again from the
database (``populate_existing``, ``FOR UPDATE``) and stops if it is no longer
ACTIVE. The tick counts that schedule as skipped, not failed, so the run is
recorded as a success.

Each test is a two-session interleave on PostgreSQL: session B takes the flag
lock; A (the tick, or the manual advance) starts in a thread and is seen
waiting on B in ``pg_stat_activity``; B pauses the schedule and commits; A
finishes. The thread's join timeout is the failure detector, not a duration.

The database is shared with other tests, so the tick is narrowed to this
test's schedule, and each test reads back the rows it created.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Tuple
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.rollout_schedule import (
    RolloutSchedule,
    RolloutScheduleStatus,
    RolloutStage,
    RolloutStageStatus,
    TriggerType,
)
from backend.app.services.rollout_service import RolloutService

pytestmark = [pytest.mark.integration, pytest.mark.regression]

JOIN_TIMEOUT_S = 30
WAIT_FOR_BLOCK_S = 15
PAUSED_REFUSAL = "Cannot advance stage for schedule in paused status"


def _factory(db_session):
    # autoflush=False, as backend.app.db.session.SessionLocal is configured.
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)

    def session():
        s = factory()
        s.execute(text("SET search_path TO test_experimentation"))
        return s

    return session


def _hours_ago(hours: float) -> datetime:
    """A naive UTC timestamp, as ``rollout_stages`` stores them."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(tzinfo=None)


def _schedule(db_session, *, stages: List[dict], flag_percentage: int = 10):
    """Create a flag, an ACTIVE schedule for it and its stages.

    Returns ``(flag_id, schedule_id, [stage_id, ...])``.
    """
    suffix = uuid.uuid4().hex[:10]
    session = _factory(db_session)()
    try:
        flag = FeatureFlag(
            key=f"recheck629-{suffix}",
            name=f"recheck629 {suffix}",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=flag_percentage,
        )
        session.add(flag)
        session.flush()
        schedule = RolloutSchedule(
            name=f"recheck629 {suffix}",
            feature_flag_id=flag.id,
            status=RolloutScheduleStatus.ACTIVE,
        )
        session.add(schedule)
        session.flush()
        stage_rows = []
        for order, spec in zip(range(1, len(stages) + 1), stages):
            stage = RolloutStage(
                rollout_schedule_id=schedule.id,
                name=f"stage {order}",
                stage_order=order,
                target_percentage=spec["percentage"],
                status=spec["status"],
                trigger_type=spec.get("trigger", TriggerType.TIME_BASED),
                trigger_configuration={"duration": 24},
                updated_at=spec.get("updated_at", _hours_ago(0)),
            )
            session.add(stage)
            stage_rows.append(stage)
        session.commit()
        return flag.id, schedule.id, [s.id for s in stage_rows]
    finally:
        session.close()


def _state(db_session, flag_id, schedule_id, stage_ids):
    session = _factory(db_session)()
    try:
        flag = session.get(FeatureFlag, flag_id)
        schedule = session.get(RolloutSchedule, schedule_id)
        stages = [session.get(RolloutStage, stage_id).status for stage_id in stage_ids]
        return flag.rollout_percentage, schedule.status, stages
    finally:
        session.close()


def _interleave(
    db_session, flag_id, schedule_id, action: Callable[[], Any]
) -> Dict[str, Any]:
    """Run ``action`` in a thread while session B holds the flag lock.

    B takes the flag ``FOR UPDATE``; ``action`` starts and is seen waiting on
    B; B pauses the schedule and commits; ``action`` finishes. Returns
    ``{"blocked": bool, "result": ..., "error": ...}``.
    """
    make_session = _factory(db_session)
    holder = make_session()
    observer = make_session()
    outcome: Dict[str, Any] = {"blocked": False, "result": None, "error": None}

    def run():
        try:
            outcome["result"] = action()
        except BaseException as exc:  # reported to the test thread
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    try:
        holder.query(FeatureFlag).filter(
            FeatureFlag.id == flag_id
        ).with_for_update().one()
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar()

        worker.start()
        deadline = time.monotonic() + WAIT_FOR_BLOCK_S
        while time.monotonic() < deadline and worker.is_alive():
            waiting = observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE :pid = ANY(pg_blocking_pids(pid))"
                ),
                {"pid": holder_pid},
            ).scalar()
            observer.rollback()
            if waiting:
                outcome["blocked"] = True
                break
            time.sleep(0.02)

        if outcome["blocked"]:
            # The pause, committed while the action waits on the flag lock.
            RolloutService.pause_rollout_schedule(holder, schedule_id)
        else:
            holder.rollback()
    finally:
        if holder.in_transaction():
            holder.rollback()
        holder.close()
        observer.close()
        worker.join(JOIN_TIMEOUT_S)

    assert not worker.is_alive(), "the action did not finish once the lock was free"
    return outcome


def _tick_only(db_session, schedule_id) -> Tuple[Any, MagicMock]:
    """A tick action, narrowed to one schedule, run under ``run_locked_tick``.

    Returns ``(action, notification mock)``; the action returns the
    ``TickOutcome``.
    """
    from backend.app.core.rollout_scheduler import SCHEDULER_NAME, RolloutScheduler
    from backend.app.core.scheduler_tick import run_locked_tick

    original = RolloutScheduler._process_schedule

    async def only_ours(self, db, schedule, current_time):
        if schedule.id != schedule_id:
            return False, 0, []
        return await original(self, db, schedule, current_time)

    scheduler = RolloutScheduler(interval_minutes=1)
    scheduler._notification_service = MagicMock()
    engine = db_session.get_bind()

    def action():
        with (
            patch.object(RolloutScheduler, "_process_schedule", only_ours),
            patch(
                "backend.app.core.rollout_scheduler.SessionLocal",
                _factory(db_session),
            ),
        ):
            return asyncio.run(
                run_locked_tick(
                    SCHEDULER_NAME,
                    scheduler.process_rollout_schedules,
                    engine=engine,
                    record=False,
                )
            )

    return action, scheduler._notification_service


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.records: list = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def scheduler_log(monkeypatch):
    """The scheduler logger's records, captured on the logger itself.

    The module's ``logger`` is pinned to the real named logger, as in
    ``test_rollout_scheduler_row_isolation.py``: a unit test can leave a
    MagicMock there for the rest of the session.
    """
    import backend.app.core.rollout_scheduler as rollout_scheduler

    logger = logging.getLogger("backend.app.core.rollout_scheduler")
    monkeypatch.setattr(rollout_scheduler, "logger", logger)
    handler = _Records()
    disabled, level = logger.disabled, logger.level
    logger.disabled = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled = disabled
        logger.setLevel(level)


def _assert_skipped_run(outcome, notifications, flag_id, records, schedule_id):
    from backend.app.core.scheduler_tick import STATUS_SUCCESS

    assert outcome["blocked"], "the tick never waited on the flag lock"
    assert outcome["error"] is None, repr(outcome["error"])
    tick = outcome["result"]
    assert tick.status == STATUS_SUCCESS, tick
    assert tick.result.items_failed == 0
    assert tick.result.metadata.get("schedules_skipped") == 1
    notified = {
        c.kwargs["feature_flag_id"]
        for c in notifications.notify_rollout_advanced.call_args_list
    }
    assert str(flag_id) not in notified
    skips = [
        r
        for r in records
        if r.levelno == logging.INFO
        and r.getMessage()
        == f"Rollout schedule {schedule_id} is no longer active (paused); skipped"
    ]
    assert skips, [r.getMessage() for r in records]
    assert not [r for r in records if r.levelno >= logging.ERROR]


def test_a_tick_waiting_on_the_flag_lock_does_not_start_a_stage_of_a_paused_schedule(
    db_session, scheduler_log
):
    """Stage 1 (10%) is due to complete and stage 2 (50%) may start. The
    schedule is paused while the tick waits for the flag lock: stage 2 stays
    PENDING, stage 1 is not COMPLETED, the flag stays at 10%, and the run is
    a success."""
    flag_id, schedule_id, stage_ids = _schedule(
        db_session,
        stages=[
            {
                "percentage": 10,
                "status": RolloutStageStatus.IN_PROGRESS,
                "updated_at": _hours_ago(30),
            },
            {"percentage": 50, "status": RolloutStageStatus.PENDING},
        ],
    )
    action, notifications = _tick_only(db_session, schedule_id)

    outcome = _interleave(db_session, flag_id, schedule_id, action)

    assert outcome["blocked"], "the tick never waited on the flag lock"
    assert _state(db_session, flag_id, schedule_id, stage_ids) == (
        10,
        RolloutScheduleStatus.PAUSED,
        [RolloutStageStatus.IN_PROGRESS, RolloutStageStatus.PENDING],
    )
    _assert_skipped_run(outcome, notifications, flag_id, scheduler_log, schedule_id)


def test_a_tick_waiting_on_the_flag_lock_does_not_start_the_first_stage(
    db_session, scheduler_log
):
    """No stage started yet; stage 1 (25%) may start. Paused while the tick
    waits: stage 1 stays PENDING and the flag stays at 10%."""
    flag_id, schedule_id, stage_ids = _schedule(
        db_session,
        stages=[{"percentage": 25, "status": RolloutStageStatus.PENDING}],
    )
    action, notifications = _tick_only(db_session, schedule_id)

    outcome = _interleave(db_session, flag_id, schedule_id, action)

    assert outcome["blocked"], "the tick never waited on the flag lock"
    assert _state(db_session, flag_id, schedule_id, stage_ids) == (
        10,
        RolloutScheduleStatus.PAUSED,
        [RolloutStageStatus.PENDING],
    )
    _assert_skipped_run(outcome, notifications, flag_id, scheduler_log, schedule_id)


def test_a_tick_completing_the_last_stage_leaves_a_paused_schedule_paused(
    db_session, scheduler_log
):
    """The only stage is due to complete, which would complete the schedule.
    That branch now takes the flag lock and re-reads the schedule too: a
    pause committed while it waited is not overwritten with COMPLETED, and
    the stage is not marked COMPLETED."""
    flag_id, schedule_id, stage_ids = _schedule(
        db_session,
        stages=[
            {
                "percentage": 100,
                "status": RolloutStageStatus.IN_PROGRESS,
                "updated_at": _hours_ago(30),
            }
        ],
    )
    action, notifications = _tick_only(db_session, schedule_id)

    outcome = _interleave(db_session, flag_id, schedule_id, action)

    assert outcome["blocked"], "the tick never waited on the flag lock"
    assert _state(db_session, flag_id, schedule_id, stage_ids) == (
        10,
        RolloutScheduleStatus.PAUSED,
        [RolloutStageStatus.IN_PROGRESS],
    )
    _assert_skipped_run(outcome, notifications, flag_id, scheduler_log, schedule_id)


def test_a_manual_advance_waiting_on_the_flag_lock_is_refused_once_paused(
    db_session,
):
    """A manual stage (25%) is advanced while another session holds the flag
    lock and pauses the schedule. The advance answers main's refusal (the
    route maps it to 400) and changes nothing."""
    flag_id, schedule_id, stage_ids = _schedule(
        db_session,
        stages=[
            {
                "percentage": 25,
                "status": RolloutStageStatus.PENDING,
                "trigger": TriggerType.MANUAL,
            }
        ],
    )
    make_session = _factory(db_session)

    def action():
        session = make_session()
        try:
            return RolloutService.manually_advance_stage(session, stage_ids[0])
        finally:
            session.close()

    outcome = _interleave(db_session, flag_id, schedule_id, action)

    assert outcome["blocked"], "the advance never waited on the flag lock"
    assert isinstance(outcome["error"], ValueError), repr(outcome)
    assert str(outcome["error"]) == PAUSED_REFUSAL
    assert _state(db_session, flag_id, schedule_id, stage_ids) == (
        10,
        RolloutScheduleStatus.PAUSED,
        [RolloutStageStatus.PENDING],
    )


def test_a_manual_advance_completing_the_last_stage_is_refused_once_paused(
    db_session,
):
    """The manual stage is IN_PROGRESS and the last one, so advancing it
    would complete the schedule. That path took no flag lock before; now it
    does, and a pause committed while it waits is not overwritten."""
    flag_id, schedule_id, stage_ids = _schedule(
        db_session,
        stages=[
            {
                "percentage": 25,
                "status": RolloutStageStatus.IN_PROGRESS,
                "trigger": TriggerType.MANUAL,
            }
        ],
    )
    make_session = _factory(db_session)

    def action():
        session = make_session()
        try:
            return RolloutService.manually_advance_stage(session, stage_ids[0])
        finally:
            session.close()

    outcome = _interleave(db_session, flag_id, schedule_id, action)

    assert outcome["blocked"], "the advance never waited on the flag lock"
    assert isinstance(outcome["error"], ValueError), repr(outcome)
    assert str(outcome["error"]) == PAUSED_REFUSAL
    assert _state(db_session, flag_id, schedule_id, stage_ids) == (
        10,
        RolloutScheduleStatus.PAUSED,
        [RolloutStageStatus.IN_PROGRESS],
    )
