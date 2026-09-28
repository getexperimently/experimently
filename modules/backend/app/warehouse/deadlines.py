"""Fixed time limits for warehouse calls, enforced where the work happens.

Two kinds of limit apply to every warehouse operation:

* **per call** -- connect within :data:`CONNECT_SECONDS`, and each read or
  write within :data:`READ_SECONDS`;
* **total** -- the whole operation (a connection test, a preview, a run)
  within a fixed budget computed by :func:`connection_test_total`,
  :func:`preview_total` or :func:`run_total`.  A caller cannot raise either.

A per-read limit alone does not bound a call: an upstream that sends one byte
just inside every read limit keeps the call alive indefinitely.  So the total
is enforced by a :class:`Deadline` that the worker thread consults itself --
the egress layer checks it before every socket read and write and caps each
one at ``min(per-call limit, remaining)``, and poll loops call
:meth:`Deadline.check` or :meth:`Deadline.sleep` between polls.  Awaiting the
worker's future with a limit on the request side would free the request but
leave the thread working; the in-thread check is what frees the thread.

The clock is :func:`time.monotonic` unless a test injects another.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode

#: Seconds to establish a TCP connection (and to wait for a pooled one).
CONNECT_SECONDS = 5.0
#: Seconds for each read or write on an established connection.
READ_SECONDS = 30.0
#: Total seconds for a connection test.
CONNECTION_TEST_TOTAL_SECONDS = 30.0
#: Added to the query limit for a preview's total.
PREVIEW_MARGIN_SECONDS = 30.0
#: Added to the per-query limits for a run's total.
RUN_MARGIN_SECONDS = 60.0

Clock = Callable[[], float]
Sleeper = Callable[[float], None]


def connection_test_total() -> float:
    """The total for a connection test: 30 s."""
    return CONNECTION_TEST_TOTAL_SECONDS


def preview_total(query_timeout_seconds: float) -> float:
    """The total for a preview: the connection's query limit plus 30 s."""
    return float(query_timeout_seconds) + PREVIEW_MARGIN_SECONDS


def run_total(query_timeout_seconds: float, metrics: int) -> float:
    """The total for a run: (1 + metrics) x the query limit, plus 60 s."""
    return (1 + int(metrics)) * float(query_timeout_seconds) + RUN_MARGIN_SECONDS


class Deadline:
    """A total time budget on a monotonic clock, checked in the working thread."""

    def __init__(self, total_seconds: float, *, clock: Optional[Clock] = None) -> None:
        if not total_seconds > 0:
            raise ValueError("a deadline needs a positive total")
        self._clock: Clock = clock or time.monotonic
        self.total_seconds = float(total_seconds)
        self._end = self._clock() + self.total_seconds

    def remaining(self) -> float:
        """Seconds left, never negative."""
        return max(0.0, self._end - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def check(self) -> float:
        """Raise ``time_limit`` if the budget is spent; otherwise the seconds left."""
        remaining = self.remaining()
        if remaining <= 0.0:
            raise WarehouseError(WarehouseErrorCode.TIME_LIMIT)
        return remaining

    def cap(self, per_call: Optional[float]) -> float:
        """``min(per_call, remaining)``; raises ``time_limit`` when none is left.

        ``None`` (no per-call limit given) is read as :data:`READ_SECONDS`, so
        nothing downstream ever waits without a bound.
        """
        remaining = self.check()
        limit = READ_SECONDS if per_call is None else float(per_call)
        return min(limit, remaining)

    def http_timeout(self) -> httpx.Timeout:
        """The limits for one HTTP call: the per-call limits capped by what is left."""
        return httpx.Timeout(
            connect=self.cap(CONNECT_SECONDS),
            read=self.cap(READ_SECONDS),
            write=self.cap(READ_SECONDS),
            pool=self.cap(CONNECT_SECONDS),
        )

    def sleep(self, seconds: float, *, sleeper: Optional[Sleeper] = None) -> None:
        """Wait between polls, never past the deadline; ``time_limit`` once it passes."""
        (sleeper or time.sleep)(self.cap(seconds))
        self.check()
