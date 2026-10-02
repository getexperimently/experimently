"""One rollout schedule no longer breaks the rest of the tick (#593).

``RolloutScheduler.process_rollout_schedules`` committed each schedule's
changes with ``db.commit()`` inside a per-schedule ``try``, but its ``except``
never rolled the session back. After one commit the database refused, the
session stayed failed, and every later schedule in that tick failed too.

And a schedule that had to wait for ``min_stage_duration`` hit a ``continue``
after marking its active stage COMPLETED and before its own commit, so the
change stayed pending in the session and was committed by whichever schedule
committed next. The wait was also measured from the timestamp the scheduler
had just overwritten, so it was never met.

Now each schedule runs in its own savepoint, is committed on its own, and a
failure rolls the session back; the minimum duration is checked, from the
start of the active stage, before anything is changed.

The refusal below is a real constraint error from PostgreSQL: a
``before_update`` listener, scoped to the test, puts an out-of-range
``target_percentage`` on a stage of the first of this test's schedules the
tick reaches (``check_target_percentage``). It picks the first one at run
time because the scheduler's query has no ORDER BY.

The database is shared with other tests, so the tick's own counts are not
asserted; each test reads back the rows it created.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.rollout_schedule import (
    RolloutSchedule,
    RolloutScheduleStatus,
    RolloutStage,
    RolloutStageStatus,
    TriggerType,
)

pytestmark = [pytest.mark.integration, pytest.mark.regression]

CONSTRAINT = "check_target_percentage"


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


def _schedule(
    db_session,
    *,
    stages: List[dict],
    min_stage_duration: Optional[int] = None,
    flag_percentage: int = 10,
):
    """Create a flag, an ACTIVE schedule for it and its stages.

    Returns ``(flag_id, schedule_id, [stage_id, ...])``.
    """
    suffix = uuid.uuid4().hex[:10]
    session = _factory(db_session)()
    try:
        flag = FeatureFlag(
            key=f"rows593-{suffix}",
            name=f"rows593 {suffix}",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=flag_percentage,
        )
        session.add(flag)
        session.flush()
        schedule = RolloutSchedule(
            name=f"rows593 {suffix}",
            feature_flag_id=flag.id,
            status=RolloutScheduleStatus.ACTIVE,
            min_stage_duration=min_stage_duration,
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
                trigger_type=TriggerType.TIME_BASED,
                trigger_configuration={"duration": 24},
                updated_at=spec.get("updated_at", _hours_ago(0)),
            )
            session.add(stage)
            stage_rows.append(stage)
        session.commit()
        return flag.id, schedule.id, [s.id for s in stage_rows]
    finally:
        session.close()


def _completing(db_session):
    """A schedule whose only stage is due to complete, which completes the
    schedule. Its changes are committed by the per-schedule commit."""
    return _schedule(
        db_session,
        stages=[
            {
                "percentage": 100,
                "status": RolloutStageStatus.IN_PROGRESS,
                "updated_at": _hours_ago(30),
            }
        ],
    )


def _two_stage(db_session, *, min_stage_duration):
    """Stage 1 (10%) started 30 hours ago and is due to complete; stage 2
    (50%) is pending with no start date, so it may start at once."""
    return _schedule(
        db_session,
        min_stage_duration=min_stage_duration,
        stages=[
            {
                "percentage": 10,
                "status": RolloutStageStatus.IN_PROGRESS,
                "updated_at": _hours_ago(30),
            },
            {"percentage": 50, "status": RolloutStageStatus.PENDING},
        ],
    )


def _state(db_session, flag_id, schedule_id, stage_ids):
    session = _factory(db_session)()
    try:
        flag = session.get(FeatureFlag, flag_id)
        schedule = session.get(RolloutSchedule, schedule_id)
        stages = [session.get(RolloutStage, stage_id).status for stage_id in stage_ids]
        return flag.rollout_percentage, schedule.status, stages
    finally:
        session.close()


@contextmanager
def _refuse_first(schedule_ids):
    """Make the database refuse the stage UPDATE of the first of these
    schedules the tick reaches. Yields a list that receives its id."""
    ours = set(schedule_ids)
    refused: list = []

    def before_update(mapper, connection, target):
        if target.rollout_schedule_id not in ours:
            return
        if not refused:
            refused.append(target.rollout_schedule_id)
        if target.rollout_schedule_id == refused[0]:
            target.target_percentage = 150

    event.listen(RolloutStage, "before_update", before_update)
    try:
        yield refused
    finally:
        event.remove(RolloutStage, "before_update", before_update)


def _tick(db_session):
    """One scheduler tick against the test database. Returns the tick's
    result and the notification mock."""
    from backend.app.core.rollout_scheduler import RolloutScheduler

    scheduler = RolloutScheduler(interval_minutes=1)
    scheduler._notification_service = MagicMock()
    with patch("backend.app.core.rollout_scheduler.SessionLocal", _factory(db_session)):
        result = asyncio.run(scheduler.process_rollout_schedules())
    return result, scheduler._notification_service


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records: list = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def scheduler_log(monkeypatch):
    """The scheduler logger's ERROR records, captured on the logger itself.

    The module's ``logger`` is pinned to the real named logger for the test:
    a unit test reloads the module while ``backend/tests/unit/conftest.py``
    patches ``logging.getLogger``, which leaves a MagicMock there for the rest
    of the session. Pytest's own log capture is not used for the same kind of
    reason: it relies on propagation to the root logger.
    """
    import backend.app.core.rollout_scheduler as rollout_scheduler

    logger = logging.getLogger("backend.app.core.rollout_scheduler")
    monkeypatch.setattr(rollout_scheduler, "logger", logger)
    handler = _Records()
    disabled = logger.disabled
    logger.disabled = False
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled = disabled


def _logged(records, schedule_id):
    return [
        r
        for r in records
        if r.getMessage() == f"Error processing rollout schedule {schedule_id}"
        and r.exc_info
        and CONSTRAINT in str(r.exc_info[1])
    ]


def test_one_refused_schedule_leaves_the_others_processed(db_session, scheduler_log):
    """Three schedules due to complete in one tick; the first one the tick
    reaches is refused. The other two still complete."""
    rows = [_completing(db_session) for _ in range(3)]
    by_schedule = {schedule_id: (f, schedule_id, s) for f, schedule_id, s in rows}

    with _refuse_first(by_schedule) as refused:
        result, _ = _tick(db_session)

    assert len(refused) == 1, "the tick never reached this test's schedules"
    refused_id = refused[0]
    for schedule_id, row in by_schedule.items():
        if schedule_id == refused_id:
            assert _state(db_session, *row) == (
                10,
                RolloutScheduleStatus.ACTIVE,
                [RolloutStageStatus.IN_PROGRESS],
            )
        else:
            assert _state(db_session, *row) == (
                10,
                RolloutScheduleStatus.COMPLETED,
                [RolloutStageStatus.COMPLETED],
            ), f"schedule {schedule_id} was not processed after the refused one"
    assert result["items_failed"] >= 1
    assert _logged(scheduler_log, refused_id), [r.getMessage() for r in scheduler_log]


def test_one_refused_stage_start_rolls_back_only_that_schedule(
    db_session, scheduler_log
):
    """Three schedules due to move from stage 1 to stage 2; the first one the
    tick reaches is refused while its stages are written. That schedule is
    left exactly as it was, flag included; the other two advance."""
    rows = [_two_stage(db_session, min_stage_duration=None) for _ in range(3)]
    by_schedule = {schedule_id: (f, schedule_id, s) for f, schedule_id, s in rows}

    with _refuse_first(by_schedule) as refused:
        _, notifications = _tick(db_session)

    assert len(refused) == 1, "the tick never reached this test's schedules"
    refused_id = refused[0]
    advanced_flags = set()
    for schedule_id, row in by_schedule.items():
        if schedule_id == refused_id:
            assert _state(db_session, *row) == (
                10,
                RolloutScheduleStatus.ACTIVE,
                [RolloutStageStatus.IN_PROGRESS, RolloutStageStatus.PENDING],
            )
        else:
            assert _state(db_session, *row) == (
                50,
                RolloutScheduleStatus.ACTIVE,
                [RolloutStageStatus.COMPLETED, RolloutStageStatus.IN_PROGRESS],
            )
            advanced_flags.add(str(row[0]))
    notified = {
        c.kwargs["feature_flag_id"]
        for c in notifications.notify_rollout_advanced.call_args_list
    }
    assert advanced_flags <= notified
    assert str(by_schedule[refused_id][0]) not in notified
    assert _logged(scheduler_log, refused_id)


def test_a_schedule_waiting_for_min_stage_duration_changes_nothing(db_session):
    """Two schedules that must wait (stage 1 started 30 hours ago, 48 hours
    required), then one that completes and commits. The waiting schedules'
    stage 1 is not marked COMPLETED by that later commit."""
    waiting = [_two_stage(db_session, min_stage_duration=48) for _ in range(2)]
    committer = _completing(db_session)

    _tick(db_session)

    for row in waiting:
        assert _state(db_session, *row) == (
            10,
            RolloutScheduleStatus.ACTIVE,
            [RolloutStageStatus.IN_PROGRESS, RolloutStageStatus.PENDING],
        )
    assert _state(db_session, *committer) == (
        10,
        RolloutScheduleStatus.COMPLETED,
        [RolloutStageStatus.COMPLETED],
    )


def test_a_met_min_stage_duration_advances_in_one_tick(db_session):
    """Stage 1 started 30 hours ago and 12 hours are required: the next stage
    starts in this tick, measured from when stage 1 started."""
    flag_id, schedule_id, stage_ids = _two_stage(db_session, min_stage_duration=12)

    _, notifications = _tick(db_session)

    assert _state(db_session, flag_id, schedule_id, stage_ids) == (
        50,
        RolloutScheduleStatus.ACTIVE,
        [RolloutStageStatus.COMPLETED, RolloutStageStatus.IN_PROGRESS],
    )
    notifications.notify_rollout_advanced.assert_any_call(
        feature_flag_id=str(flag_id), stage_name="stage 2", new_percentage=50
    )


def test_a_schedule_whose_commit_fails_leaves_nothing_for_the_next_commit(
    db_session,
):
    """The database accepts a schedule's writes but its commit fails. Its
    changes are rolled back, not committed by the next schedule's commit."""
    from backend.app.core.rollout_scheduler import RolloutScheduler

    rows = [_completing(db_session) for _ in range(3)]
    by_schedule = {schedule_id: (f, schedule_id, s) for f, schedule_id, s in rows}
    state = {"target": None, "raised": False}

    def before_update(mapper, connection, target):
        if target.rollout_schedule_id in by_schedule and state["target"] is None:
            state["target"] = target.rollout_schedule_id

    make_session = _factory(db_session)

    def session_with_failing_commit():
        session = make_session()
        commit = session.commit

        def failing_commit():
            if state["target"] is not None and not state["raised"]:
                state["raised"] = True
                raise RuntimeError("commit failed (test)")
            return commit()

        session.commit = failing_commit
        return session

    scheduler = RolloutScheduler(interval_minutes=1)
    scheduler._notification_service = MagicMock()
    event.listen(RolloutStage, "before_update", before_update)
    try:
        with patch(
            "backend.app.core.rollout_scheduler.SessionLocal",
            session_with_failing_commit,
        ):
            asyncio.run(scheduler.process_rollout_schedules())
    finally:
        event.remove(RolloutStage, "before_update", before_update)

    assert state["raised"], "the tick never reached this test's schedules"
    target = state["target"]
    for schedule_id, row in by_schedule.items():
        if schedule_id == target:
            assert _state(db_session, *row) == (
                10,
                RolloutScheduleStatus.ACTIVE,
                [RolloutStageStatus.IN_PROGRESS],
            ), "the failed schedule's changes were committed by a later schedule"
        else:
            assert _state(db_session, *row) == (
                10,
                RolloutScheduleStatus.COMPLETED,
                [RolloutStageStatus.COMPLETED],
            )
