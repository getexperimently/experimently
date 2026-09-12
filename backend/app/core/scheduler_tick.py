"""
Shared runner for background scheduler ticks.

All five schedulers (experiment, rollout, metrics, safety, bandit) run their
periodic work through :func:`run_locked_tick`, which gives every tick the same
three guarantees:

1. **Single runner per tick** — the work runs under the PostgreSQL advisory
   lock from :mod:`backend.app.core.scheduler_lock`; a replica that does not
   get the lock skips the tick.
2. **Run history** — every executed tick is persisted through
   :meth:`SchedulerHealthService.record_run` (``scheduler_runs`` table), which
   feeds ``GET /api/v1/scheduler/health``.
3. **Prometheus signal** — ``scheduler_last_success_timestamp{name}``,
   ``scheduler_tick_duration_seconds{name}`` and
   ``scheduler_ticks_total{name,status}`` from :mod:`backend.app.core.metrics`.

A tick callable may return ``None``, a :class:`TickResult`, or a mapping with
``items_processed`` / ``items_failed`` / ``metadata`` keys; anything else is
treated as "ran, nothing to report". Exceptions raised by the tick are
recorded as a failed run and then **re-raised** so each scheduler loop keeps
its own error handling and back-off.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Optional

from sqlalchemy.engine import Engine

from backend.app.core import metrics as prom
from backend.app.core.scheduler_lock import async_scheduler_lock

logger = logging.getLogger(__name__)

STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class TickResult:
    """What a scheduler tick reports back."""

    items_processed: int = 0
    items_failed: int = 0
    metadata: dict = field(default_factory=dict)

    @classmethod
    def coerce(cls, value: Any) -> "TickResult":
        if isinstance(value, TickResult):
            return value
        if isinstance(value, Mapping):
            return cls(
                items_processed=int(value.get("items_processed", 0) or 0),
                items_failed=int(value.get("items_failed", 0) or 0),
                metadata=dict(value.get("metadata") or {}),
            )
        return cls()


@dataclass
class TickOutcome:
    """Summary of one call to :func:`run_locked_tick`."""

    name: str
    status: str
    acquired: bool
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    result: TickResult
    error: Optional[str] = None

    @property
    def ran(self) -> bool:
        return self.acquired


def _persist_run(
    name: str,
    started_at: datetime,
    completed_at: datetime,
    status: str,
    result: TickResult,
    error: Optional[str],
) -> None:
    """Best-effort write of the run record; never raises."""
    try:
        from backend.app.db.session import SessionLocal
        from backend.app.services.scheduler_health_service import SchedulerHealthService

        db = SessionLocal()
        try:
            SchedulerHealthService().record_run(
                db=db,
                scheduler_name=name,
                started_at=started_at,
                completed_at=completed_at,
                status=status,
                items_processed=result.items_processed,
                items_failed=result.items_failed,
                error_msg=error,
                metadata=result.metadata or None,
            )
        finally:
            db.close()
    except Exception as exc:  # pragma: no cover - depends on DB availability
        logger.warning("scheduler %s: could not record run (%s)", name, exc)


async def run_locked_tick(
    name: str,
    tick: Callable[[], Awaitable[Any]],
    *,
    engine: Optional[Engine] = None,
    record: bool = True,
) -> TickOutcome:
    """
    Run one scheduler tick under the advisory lock and record the outcome.

    Args:
        name: Scheduler name (``experiment``, ``rollout``, ``metrics``,
            ``safety``, ``bandit``). Used for the lock key, the run record and
            the metric labels.
        tick: Zero-argument coroutine function doing the work.
        engine: Engine for the lock connection (defaults to the app engine).
        record: Persist the run through ``SchedulerHealthService`` (default).

    Returns:
        A :class:`TickOutcome`. ``outcome.acquired`` is ``False`` when the tick
        was skipped because another replica holds the lock.

    Raises:
        Whatever *tick* raised, after the failed run has been recorded.
    """
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    async with async_scheduler_lock(name, engine=engine) as acquired:
        if not acquired:
            completed_at = datetime.now(timezone.utc)
            prom.record_scheduler_tick(name, STATUS_SKIPPED, time.perf_counter() - t0)
            logger.info("scheduler %s: lock held elsewhere, tick skipped", name)
            return TickOutcome(
                name=name,
                status=STATUS_SKIPPED,
                acquired=False,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=completed_at.timestamp() - started_at.timestamp(),
                result=TickResult(),
            )

        error: Optional[str] = None
        exc_to_raise: Optional[Exception] = None
        result = TickResult()
        try:
            raw = await tick()
            result = TickResult.coerce(raw)
            if result.items_failed and result.items_processed:
                status = STATUS_PARTIAL
            elif result.items_failed and not result.items_processed:
                status = STATUS_FAILED
                error = f"{result.items_failed} item(s) failed"
            else:
                status = STATUS_SUCCESS
        except asyncio.CancelledError:
            # Shutdown: release the lock (context manager) and propagate
            # without recording a bogus "failed" run.
            raise
        except Exception as exc:  # noqa: BLE001 - recorded then re-raised
            status = STATUS_FAILED
            error = str(exc) or exc.__class__.__name__
            exc_to_raise = exc

    completed_at = datetime.now(timezone.utc)
    duration = time.perf_counter() - t0

    prom.record_scheduler_tick(name, status, duration)
    if status == STATUS_SUCCESS:
        prom.record_scheduler_success(name)

    if record:
        _persist_run(name, started_at, completed_at, status, result, error)

    if exc_to_raise is not None:
        raise exc_to_raise

    return TickOutcome(
        name=name,
        status=status,
        acquired=True,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration,
        result=result,
        error=error,
    )


__all__ = [
    "TickResult",
    "TickOutcome",
    "run_locked_tick",
    "STATUS_SUCCESS",
    "STATUS_PARTIAL",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
]
