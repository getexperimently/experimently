"""The bounded pool warehouse calls run on, and its admission step.

Warehouse calls are slow and their time is set by someone else's system, so
none of them runs on the request thread pool (anyio's, shared by every sync
route) or on the event loop.  They run here: a module-owned
:class:`~concurrent.futures.ThreadPoolExecutor` of
``WAREHOUSE_MAX_CONCURRENT_JOBS`` threads (default 4) per process.

**Admission never waits.**  :meth:`WarehouseExecutor.try_submit` either takes a
slot at once or refuses at once:

* ``run_in_progress`` (409) when a job with the same ``key`` -- typically the
  connection id -- is already admitted;
* ``warehouse_busy`` (429, Retry-After 30) when every thread is taken, or when
  the organisation already has ``WAREHOUSE_MAX_CONCURRENT_RUNS`` (default 2)
  analyses or previews admitted.  Connection tests are bounded by the thread
  count and their own 30 s total, not by that cap.

A job admitted here always has a thread: slots equal threads, so nothing
queues behind a slow warehouse.

**Every job runs under a** :class:`~.deadlines.Deadline` created when its thread
picks it up, and receives it as its only argument; the egress layer and poll
loops check it inside the thread, so the thread is released when the total is
spent even if the upstream is still sending.

**Every failure leaves as a** :class:`~.errors.WarehouseError`, rebuilt clean:
an unexpected exception becomes ``internal`` and is logged by type name only,
so neither its text nor a chained upstream exception reaches a log or a
response.

One deployment is one organisation today, so callers pass the default
:data:`DEPLOYMENT`; the cap is keyed so that a future organisation id slots in.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import threading
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional, Set, TypeVar

from modules.backend.app.warehouse.deadlines import Clock, Deadline
from modules.backend.app.warehouse.errors import (
    WarehouseError,
    WarehouseErrorCode,
    log_warehouse_error,
    sanitised,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: The organisation key for this deployment.
DEPLOYMENT = "deployment"

#: Seconds the request side waits beyond a job's own total before giving up
#: on the answer.  The thread itself stops at the total (in-thread deadline).
REQUEST_SIDE_GRACE_SECONDS = 5.0


class JobKind(str, enum.Enum):
    CONNECTION_TEST = "connection_test"
    PREVIEW = "preview"
    ANALYSIS = "analysis"


#: The kinds the per-organisation cap counts (the rows SPEC 7 counts as runs).
_CAPPED_KINDS = frozenset({JobKind.PREVIEW, JobKind.ANALYSIS})


class WarehouseExecutor:
    """A fixed-size thread pool with a non-blocking, capped admission step."""

    def __init__(
        self,
        max_workers: int,
        *,
        per_organisation: int,
        clock: Optional[Clock] = None,
    ) -> None:
        if max_workers < 1 or per_organisation < 1:
            raise ValueError("the warehouse executor needs at least one slot")
        self.max_workers = max_workers
        self.per_organisation = per_organisation
        self._clock = clock
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="warehouse"
        )
        self._lock = threading.Lock()
        self._admitted = 0
        self._by_organisation: Counter[str] = Counter()
        self._keys: Set[str] = set()

    @property
    def admitted(self) -> int:
        """Jobs admitted and not yet finished."""
        with self._lock:
            return self._admitted

    def try_submit(
        self,
        job: Callable[[Deadline], T],
        *,
        total_seconds: float,
        kind: JobKind,
        organisation: str = DEPLOYMENT,
        key: Optional[str] = None,
    ) -> "Future[T]":
        """Admit ``job`` now or refuse now; never wait for a slot.

        Raises ``run_in_progress`` or ``warehouse_busy``.  On success the
        returned future resolves to the job's result, or raises a clean
        :class:`WarehouseError`.
        """
        kind = JobKind(kind)
        capped = kind in _CAPPED_KINDS
        with self._lock:
            if key is not None and key in self._keys:
                raise WarehouseError(WarehouseErrorCode.RUN_IN_PROGRESS)
            if self._admitted >= self.max_workers:
                raise WarehouseError(WarehouseErrorCode.WAREHOUSE_BUSY)
            if capped and self._by_organisation[organisation] >= self.per_organisation:
                raise WarehouseError(WarehouseErrorCode.WAREHOUSE_BUSY)
            self._admitted += 1
            if capped:
                self._by_organisation[organisation] += 1
            if key is not None:
                self._keys.add(key)

        def release() -> None:
            with self._lock:
                self._admitted -= 1
                if capped:
                    self._by_organisation[organisation] -= 1
                    if self._by_organisation[organisation] <= 0:
                        del self._by_organisation[organisation]
                if key is not None:
                    self._keys.discard(key)

        try:
            return self._pool.submit(self._run, job, total_seconds, kind, release)
        except BaseException:
            release()
            raise

    def _run(
        self,
        job: Callable[[Deadline], T],
        total_seconds: float,
        kind: JobKind,
        release: Callable[[], None],
    ) -> T:
        failure: Optional[WarehouseError] = None
        try:
            deadline = Deadline(total_seconds, clock=self._clock)
            return job(deadline)
        except WarehouseError as exc:
            failure = exc
        except BaseException as exc:
            logger.error(
                "warehouse job failed: %s",
                type(exc).__name__,
                extra={"warehouse_error": "internal", "job_kind": kind.value},
            )
            failure = WarehouseError(WarehouseErrorCode.INTERNAL)
        finally:
            release()
        # Outside the handlers: the copy carries no chained exception.
        assert failure is not None
        clean = sanitised(failure)
        log_warehouse_error(clean, event=f"warehouse {kind.value} failed")
        raise clean

    async def run(
        self,
        job: Callable[[Deadline], T],
        *,
        total_seconds: float,
        kind: JobKind,
        organisation: str = DEPLOYMENT,
        key: Optional[str] = None,
    ) -> T:
        """Admit ``job`` (or refuse at once) and await its result.

        For ``async def`` handlers: the event loop is never blocked -- neither
        by admission, which does not wait, nor by the job, which runs on this
        executor's thread.  The request side stops waiting a few seconds after
        the job's own total; the job's thread stops at the total by itself.
        """
        future = self.try_submit(
            job,
            total_seconds=total_seconds,
            kind=kind,
            organisation=organisation,
            key=key,
        )
        try:
            return await asyncio.wait_for(
                asyncio.wrap_future(future),
                timeout=total_seconds + REQUEST_SIDE_GRACE_SECONDS,
            )
        except asyncio.TimeoutError:
            pass
        raise WarehouseError(WarehouseErrorCode.TIME_LIMIT)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)


_executor: Optional[WarehouseExecutor] = None
_executor_lock = threading.Lock()


def get_executor() -> WarehouseExecutor:
    """The process-wide executor, sized from the modules' settings."""
    global _executor
    with _executor_lock:
        if _executor is None:
            from modules.backend.app.settings import settings

            _executor = WarehouseExecutor(
                settings.WAREHOUSE_MAX_CONCURRENT_JOBS,
                per_organisation=settings.WAREHOUSE_MAX_CONCURRENT_RUNS,
            )
        return _executor


__all__ = [
    "DEPLOYMENT",
    "JobKind",
    "WarehouseExecutor",
    "get_executor",
]
