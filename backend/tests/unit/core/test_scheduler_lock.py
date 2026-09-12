"""
Tests for the PostgreSQL advisory scheduler lock and the shared tick runner.

These tests are database-backed: they use the per-process test database
(``test_db`` engine, NullPool, so every ``engine.connect()`` is a distinct
PostgreSQL session — exactly the multi-replica situation the lock exists for).

Covered:
- a second connection cannot acquire the lock while the first holds it
- the lock is released when the ``with`` block exits (normally or by exception)
- ``run_locked_tick`` skips the tick when the lock is held elsewhere
- ``run_locked_tick`` runs the tick, records the run through
  ``SchedulerHealthService.record_run`` and stamps
  ``scheduler_last_success_timestamp{name}``
- a failing tick is recorded as ``failed`` and the exception is re-raised
"""

from __future__ import annotations

import re
import uuid

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.orm import sessionmaker

from backend.app.core import scheduler_lock as lock_module
from backend.app.core.scheduler_lock import (
    async_scheduler_lock,
    release,
    scheduler_lock,
    try_acquire,
)
from backend.app.core.scheduler_tick import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    TickResult,
    run_locked_tick,
)
from backend.app.models.scheduler_run import SchedulerRun


def _name() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


def _gauge(name: str):
    return REGISTRY.get_sample_value("scheduler_last_success_timestamp", {"name": name})


# ---------------------------------------------------------------------------
# scheduler_lock
# ---------------------------------------------------------------------------


class TestSchedulerLock:
    def test_second_connection_cannot_acquire_while_first_holds(self, test_db):
        name = _name()
        with scheduler_lock(name, engine=test_db) as acquired:
            assert acquired is True

            other = test_db.connect()
            try:
                assert try_acquire(other, name) is False
            finally:
                other.close()

    def test_lock_released_after_exit(self, test_db):
        name = _name()
        with scheduler_lock(name, engine=test_db) as acquired:
            assert acquired is True

        other = test_db.connect()
        try:
            assert try_acquire(other, name) is True
            assert release(other, name) is True
        finally:
            other.close()

    def test_lock_released_when_block_raises(self, test_db):
        name = _name()
        with pytest.raises(RuntimeError):
            with scheduler_lock(name, engine=test_db) as acquired:
                assert acquired is True
                raise RuntimeError("boom")

        other = test_db.connect()
        try:
            assert try_acquire(other, name) is True
            release(other, name)
        finally:
            other.close()

    def test_nested_context_on_other_connection_yields_false(self, test_db):
        name = _name()
        with scheduler_lock(name, engine=test_db) as first:
            assert first is True
            # A second replica (new connection from the NullPool engine).
            with scheduler_lock(name, engine=test_db) as second:
                assert second is False
            # The inner block must not have released the outer holder's lock.
            other = test_db.connect()
            try:
                assert try_acquire(other, name) is False
            finally:
                other.close()

    def test_different_names_do_not_conflict(self, test_db):
        with scheduler_lock(_name(), engine=test_db) as a:
            with scheduler_lock(_name(), engine=test_db) as b:
                assert a is True and b is True

    def test_unreachable_database_yields_false(self):
        from sqlalchemy import create_engine

        bad = create_engine(
            "postgresql://nobody:nothing@127.0.0.1:1/nope",
            connect_args={"connect_timeout": 1},
        )
        try:
            with scheduler_lock(_name(), engine=bad) as acquired:
                assert acquired is False
        finally:
            bad.dispose()

    def test_lock_name_is_namespaced(self):
        assert (
            lock_module.lock_name("experiment") == "experimently.scheduler.experiment"
        )

    def test_lock_connection_is_not_idle_in_transaction(self, test_db):
        """A session-level advisory lock needs no transaction; the holder must stay idle."""
        from sqlalchemy import text

        name = _name()
        with scheduler_lock(name, engine=test_db) as acquired:
            assert acquired is True
            with test_db.connect() as probe:
                states = (
                    probe.execute(
                        text(
                            "SELECT state FROM pg_stat_activity "
                            "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                            "AND query LIKE '%pg_try_advisory_lock%'"
                        )
                    )
                    .scalars()
                    .all()
                )
            assert states, "lock holder session not visible"
            assert all(state == "idle" for state in states), states


class TestAsyncSchedulerLock:
    @pytest.mark.asyncio
    async def test_acquires_and_releases(self, test_db):
        name = _name()
        async with async_scheduler_lock(name, engine=test_db) as acquired:
            assert acquired is True
            with scheduler_lock(name, engine=test_db) as other:
                assert other is False
        with scheduler_lock(name, engine=test_db) as again:
            assert again is True

    @pytest.mark.asyncio
    async def test_released_when_block_raises(self, test_db):
        name = _name()
        with pytest.raises(RuntimeError):
            async with async_scheduler_lock(name, engine=test_db) as acquired:
                assert acquired
                raise RuntimeError("boom")
        with scheduler_lock(name, engine=test_db) as again:
            assert again is True

    @pytest.mark.asyncio
    async def test_unreachable_database_does_not_block_the_event_loop(self):
        """Connecting to a dead database must run off-loop: the loop keeps ticking meanwhile."""
        import asyncio

        from sqlalchemy import create_engine

        bad = create_engine(
            "postgresql://nobody:nothing@10.255.255.1:5432/nope",  # non-routable: hangs until connect_timeout
            connect_args={"connect_timeout": 2},
        )
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        hb = asyncio.create_task(heartbeat())
        try:
            async with async_scheduler_lock(_name(), engine=bad) as acquired:
                assert acquired is False
        finally:
            hb.cancel()
            bad.dispose()
        # If the connect had blocked the loop, the heartbeat could not have advanced.
        assert ticks >= 5, ticks


# ---------------------------------------------------------------------------
# run_locked_tick
# ---------------------------------------------------------------------------


@pytest.fixture
def record_sessions(test_db, monkeypatch):
    """Point the run-record writer at the test database."""
    import backend.app.db.session as session_module

    factory = sessionmaker(autocommit=False, autoflush=False, bind=test_db)
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    return factory


def _runs(factory, name):
    db = factory()
    try:
        return (
            db.query(SchedulerRun)
            .filter(SchedulerRun.scheduler_name == name)
            .order_by(SchedulerRun.started_at)
            .all()
        )
    finally:
        db.close()


class TestRunLockedTick:
    @pytest.mark.asyncio
    async def test_tick_skipped_when_lock_held_elsewhere(
        self, test_db, record_sessions
    ):
        name = _name()
        calls = []

        async def tick():
            calls.append(1)

        holder = test_db.connect()
        try:
            assert try_acquire(holder, name) is True
            outcome = await run_locked_tick(name, tick, engine=test_db)
        finally:
            release(holder, name)
            holder.close()

        assert calls == []
        assert outcome.acquired is False
        assert outcome.status == STATUS_SKIPPED
        # Skipped-for-lock ticks are not written to the run history.
        assert _runs(record_sessions, name) == []
        assert _gauge(name) is None

    @pytest.mark.asyncio
    async def test_tick_runs_records_run_and_sets_gauge(self, test_db, record_sessions):
        name = _name()

        async def tick():
            return {"items_processed": 3, "items_failed": 0, "metadata": {"k": "v"}}

        outcome = await run_locked_tick(name, tick, engine=test_db)

        assert outcome.acquired is True
        assert outcome.status == STATUS_SUCCESS
        assert outcome.result == TickResult(
            items_processed=3, items_failed=0, metadata={"k": "v"}
        )

        runs = _runs(record_sessions, name)
        assert len(runs) == 1
        run = runs[0]
        assert run.status == "success"
        assert run.items_processed == 3
        assert run.items_failed == 0
        assert run.completed_at is not None
        assert run.metadata_ == {"k": "v"}

        assert _gauge(name) is not None and _gauge(name) > 0

        # The lock is free again for the next tick.
        other = test_db.connect()
        try:
            assert try_acquire(other, name) is True
            release(other, name)
        finally:
            other.close()

    @pytest.mark.asyncio
    async def test_tick_returning_none_is_a_success(self, test_db, record_sessions):
        name = _name()

        async def tick():
            return None

        outcome = await run_locked_tick(name, tick, engine=test_db)
        assert outcome.status == STATUS_SUCCESS
        assert _runs(record_sessions, name)[0].items_processed == 0

    @pytest.mark.asyncio
    async def test_partial_when_some_items_fail(self, test_db, record_sessions):
        name = _name()

        async def tick():
            return {"items_processed": 2, "items_failed": 1}

        outcome = await run_locked_tick(name, tick, engine=test_db)
        assert outcome.status == "partial"
        assert _runs(record_sessions, name)[0].status == "partial"
        # Not a clean success: the success gauge must not be stamped.
        assert _gauge(name) is None

    @pytest.mark.asyncio
    async def test_failing_tick_is_recorded_and_reraised(
        self, test_db, record_sessions
    ):
        name = _name()

        async def tick():
            raise ValueError("tick exploded")

        with pytest.raises(ValueError, match="tick exploded"):
            await run_locked_tick(name, tick, engine=test_db)

        runs = _runs(record_sessions, name)
        assert len(runs) == 1
        assert runs[0].status == STATUS_FAILED
        assert "tick exploded" in (runs[0].error_message or "")
        assert _gauge(name) is None

        # Lock released despite the exception.
        other = test_db.connect()
        try:
            assert try_acquire(other, name) is True
            release(other, name)
        finally:
            other.close()

    @pytest.mark.asyncio
    async def test_record_false_skips_persistence(self, test_db, record_sessions):
        name = _name()

        async def tick():
            return {"items_processed": 1}

        outcome = await run_locked_tick(name, tick, engine=test_db, record=False)
        assert outcome.status == STATUS_SUCCESS
        assert _runs(record_sessions, name) == []


# ---------------------------------------------------------------------------
# Wiring: every scheduler loop goes through run_locked_tick
# ---------------------------------------------------------------------------


class TestSchedulerWiring:
    @pytest.mark.parametrize(
        "module_name",
        [
            "backend.app.core.scheduler",
            "backend.app.core.rollout_scheduler",
            "backend.app.core.metrics_scheduler",
            "backend.app.core.safety_scheduler",
            "backend.app.core.bandit_scheduler",
        ],
    )
    def test_scheduler_modules_use_run_locked_tick(self, module_name):
        import importlib
        import inspect

        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        # Formatter-insensitive: the call may wrap after the opening paren.
        assert re.search(r"run_locked_tick\(\s*SCHEDULER_NAME", source), module_name
        assert getattr(module, "SCHEDULER_NAME", None) in {
            "experiment",
            "rollout",
            "metrics",
            "safety",
            "bandit",
        }
