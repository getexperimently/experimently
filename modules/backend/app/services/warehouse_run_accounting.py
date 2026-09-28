"""The per-connection daily limit on warehouse queries (#312).

Every connection has ``max_runs_per_day``.  What counts against it is every
row of ``warehouse_analysis_runs`` on that connection -- analyses *and*
previews, whatever their status, a failed one included -- created since
00:00 UTC today.  The count resets at 00:00 UTC.

This module answers the two questions the admission of a run asks, and
nothing else: how many have been used today, and is the limit reached.  The
caller asks them inside the transaction that inserts the run, under the lock
that serialises admissions, so two requests cannot both see the last slot.

``created_at`` is stored naive, in UTC (``BaseModel``), so the day boundary is
compared naive too.  A naive *now* is refused rather than guessed at.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.backend.app.models.warehouse_analysis_run import (
    RUN_KINDS,
    WarehouseAnalysisRun,
)

#: The kinds of run the daily limit counts: all of them.  A preview queries
#: the warehouse too.
COUNTED_KINDS: tuple[str, ...] = RUN_KINDS


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone.utc)


def day_start(now: datetime) -> datetime:
    """00:00 UTC of *now*'s UTC day, as an aware datetime."""
    utc = _utc(now)
    return utc.replace(hour=0, minute=0, second=0, microsecond=0)


def resets_at(now: datetime) -> datetime:
    """When today's count resets: the next 00:00 UTC."""
    return day_start(now) + timedelta(days=1)


def seconds_until_reset(now: datetime) -> int:
    """Whole seconds from *now* to the reset, rounded up; at least 1."""
    remaining = resets_at(now) - _utc(now)
    seconds = int(remaining.total_seconds())
    if remaining.total_seconds() > seconds:
        seconds += 1
    return max(seconds, 1)


def runs_counted_today(db: Session, connection_id: UUID, now: datetime) -> int:
    """How many runs on *connection_id* count against today's limit."""
    since = day_start(now).replace(tzinfo=None)
    statement = select(func.count()).where(
        WarehouseAnalysisRun.connection_id == connection_id,
        WarehouseAnalysisRun.kind.in_(COUNTED_KINDS),
        WarehouseAnalysisRun.created_at >= since,
    )
    return int(db.execute(statement).scalar_one())


def daily_limit_reached(used: int, max_runs_per_day: int) -> bool:
    """Whether one more run would go over the limit.

    With a limit of 20, the 20th run of the day is admitted and the 21st is
    not.
    """
    return used >= max_runs_per_day


__all__ = [
    "COUNTED_KINDS",
    "daily_limit_reached",
    "day_start",
    "resets_at",
    "runs_counted_today",
    "seconds_until_reset",
]
