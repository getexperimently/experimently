"""
PostgreSQL advisory lock for background scheduler ticks.

Every API replica (and every uvicorn worker) starts the same five background
schedulers in the FastAPI lifespan. Without coordination, ``N`` copies of the
rollout advancement, safety rollback, bandit weight refresh, metrics
aggregation and experiment scheduling logic race against one database. This
module provides a session-level advisory lock so that only one copy of a given
scheduler runs a tick at a time::

    from backend.app.core.scheduler_lock import scheduler_lock, async_scheduler_lock

    with scheduler_lock("experiment") as acquired:
        if not acquired:
            return  # another replica holds the lock for this tick
        ...do the work...

    async with async_scheduler_lock("experiment") as acquired:   # from a coroutine
        ...

Implementation notes
--------------------
* ``pg_try_advisory_lock(hashtext(name))`` is non-blocking: a replica that does
  not get the lock skips the tick instead of queueing behind the holder.
* The lock is session-scoped, so it is taken on a **dedicated connection**
  checked out from the engine for the duration of the ``with`` block and
  released with ``pg_advisory_unlock`` on exit (also on exceptions). Closing the
  connection would release it too, but an explicit unlock keeps pooled
  connections clean.
* The connection runs in AUTOCOMMIT mode: a session-level advisory lock does
  not need a transaction, and without autocommit the ``SELECT`` would leave the
  connection "idle in transaction" for the whole tick, which managed Postgres
  services kill after ``idle_in_transaction_session_timeout`` (silently
  releasing the lock mid-tick).
* ``async_scheduler_lock`` does the (blocking) acquire and release in a worker
  thread so a slow or unreachable database never stalls the event loop.
* ``hashtext`` is PostgreSQL's built-in text hash (``int4``), so every replica
  derives the same lock key from the same name without a shared registry.
* When the database is unreachable the context manager yields ``False`` and
  logs a warning — a scheduler must never crash the API because it could not
  coordinate; it simply skips the tick.
* Under the test settings profile the same code runs against the test
  database, so the behaviour is covered by
  ``backend/tests/unit/core/test_scheduler_lock.py``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

# Namespace prefix so scheduler locks cannot collide with other advisory-lock
# users of the same database (e.g. alembic, application code).
LOCK_NAMESPACE = "experimently.scheduler."


def lock_name(name: str) -> str:
    """Fully-qualified advisory lock name for a scheduler."""
    return f"{LOCK_NAMESPACE}{name}"


def _default_engine() -> Engine:
    from backend.app.db.session import engine

    return engine


def try_acquire(conn: Connection, name: str) -> bool:
    """Attempt to take the advisory lock for *name* on *conn* (non-blocking)."""
    row = conn.execute(
        text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": lock_name(name)}
    ).scalar()
    return bool(row)


def release(conn: Connection, name: str) -> bool:
    """Release the advisory lock for *name* held by *conn*."""
    row = conn.execute(
        text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": lock_name(name)}
    ).scalar()
    return bool(row)


def _acquire(engine: Engine, name: str) -> Tuple[Optional[Connection], bool]:
    """Check out a dedicated autocommit connection and try to take the lock."""
    try:
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    except Exception as exc:
        logger.warning("scheduler_lock(%s): could not connect (database unavailable): %s", name, exc)
        return None, False
    try:
        acquired = try_acquire(conn, name)
    except Exception as exc:
        logger.warning("scheduler_lock(%s): could not acquire (database unavailable): %s", name, exc)
        conn.close()
        return None, False
    if acquired:
        logger.debug("scheduler_lock(%s): acquired", name)
    else:
        logger.debug("scheduler_lock(%s): not acquired; skipping tick", name)
    return conn, acquired


def _release(conn: Optional[Connection], name: str, acquired: bool) -> None:
    if conn is None:
        return
    try:
        if acquired:
            release(conn, name)
            logger.debug("scheduler_lock(%s): released", name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("scheduler_lock(%s): release failed: %s", name, exc)
    finally:
        conn.close()


@contextmanager
def scheduler_lock(name: str, engine: Optional[Engine] = None) -> Iterator[bool]:
    """
    Hold the scheduler advisory lock for *name* while the block runs.

    Yields ``True`` when this process acquired the lock (the caller should do
    the tick), ``False`` when another session holds it or the database could
    not be reached (the caller should skip the tick).

    Args:
        name: Scheduler identifier (``"experiment"``, ``"rollout"``, ...).
        engine: SQLAlchemy engine to take the dedicated connection from.
            Defaults to the application engine.
    """
    engine = engine or _default_engine()
    conn, acquired = _acquire(engine, name)
    try:
        yield acquired
    finally:
        _release(conn, name, acquired)


@asynccontextmanager
async def async_scheduler_lock(name: str, engine: Optional[Engine] = None) -> AsyncIterator[bool]:
    """
    Coroutine-friendly :func:`scheduler_lock`.

    Acquire and release run in a worker thread (``asyncio.to_thread``), so an
    unreachable database or a slow connection pool blocks only that thread,
    never the event loop serving HTTP requests.
    """
    engine = engine or _default_engine()
    conn, acquired = await asyncio.to_thread(_acquire, engine, name)
    try:
        yield acquired
    finally:
        await asyncio.to_thread(_release, conn, name, acquired)


__all__ = [
    "scheduler_lock",
    "async_scheduler_lock",
    "try_acquire",
    "release",
    "lock_name",
    "LOCK_NAMESPACE",
]
