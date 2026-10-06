"""Pace the run's sign-ins to the stack's sign-in limit.

``POST /api/v1/auth/login`` answers at most 10 sign-ins a minute from one
address (``backend/app/middleware/rate_limiter.py``), and the stack keeps that
documented default. Every journey of a run reaches the stack from the one
machine the run is on, so their sign-ins add up: the journeys of a session make
more than 10 in a minute between them, and the next one would be refused ("Too
many attempts") although no reader following one guide would ever see that.

So the runner signs in no faster than the limit allows. Before each sign-in
(the runner's own, for an ``api`` step's caller, and a click on the dashboard's
**Sign in** button), ``SignInPacer.wait`` looks at the sign-ins of the last
``WINDOW_SECONDS``: when there are ``LIMIT`` of them, it waits until the oldest
is ``WINDOW_SECONDS`` and ``MARGIN_SECONDS`` old. Every sign-in the stack
receives is recorded (``record``), the refused ones too, since the limit counts
them. The step that waited says so in its log line ("waited N s for the
sign-in limit"). This and the crawl's one re-ask are the only waits in the
runner that are not Playwright's own; neither is a step's, and the loader still
refuses a step that asks for one.

Nothing here imports Playwright: the clock and the sleep are passed in, so the
unit job tests it with a fake clock and no real waiting.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable, Deque, Optional

#: The documented sign-in limit: this many a minute from one address.
LIMIT = 10
WINDOW_SECONDS = 60.0
#: Past the window, so the runner's clock and the stack's never disagree on it.
MARGIN_SECONDS = 1.0
#: The dashboard's button that sends a sign-in.
SIGN_IN_BUTTONS = frozenset({"Sign in"})
#: The route a sign-in is sent to, by the dashboard and by the runner alike.
SIGN_IN_PATH = "/api/v1/auth/login"


class SignInPacer:
    """The run's sign-ins, and the wait before the next one."""

    def __init__(
        self,
        limit: int = LIMIT,
        window: float = WINDOW_SECONDS,
        margin: float = MARGIN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limit = limit
        self.window = window
        self.margin = margin
        self.clock = clock
        self.sleep = sleep
        self.sent: Deque[float] = deque()

    def _forget_old(self, now: float) -> None:
        while self.sent and now - self.sent[0] > self.window + self.margin:
            self.sent.popleft()

    def wait(self) -> float:
        """Wait, if the next sign-in would be over the limit; the seconds waited."""
        now = self.clock()
        self._forget_old(now)
        if len(self.sent) < self.limit:
            return 0.0
        oldest = self.sent[len(self.sent) - self.limit]
        delay = oldest + self.window + self.margin - now
        if delay <= 0:
            return 0.0
        self.sleep(delay)
        self._forget_old(self.clock())
        return delay

    def record(self, at: Optional[float] = None) -> None:
        """A sign-in the stack received (or is about to), at *at* or now."""
        self.sent.append(self.clock() if at is None else at)
