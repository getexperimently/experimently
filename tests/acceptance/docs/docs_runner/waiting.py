"""``poll``: the one way a step waits for something the stack does on its own.

A background job of the stack (the safety monitor, say) acts on a timer, not
when a step asks it to. An ``api`` step that expects what such a job does
says how long the job may take::

    poll: {up_to_seconds: 420, every_seconds: 15}

The runner sends the step's request, checks its expectation, and while the
expectation does not hold, sends it again every ``every_seconds`` until it
holds or ``up_to_seconds`` have passed since the first ask (the last ask is
made at the bound). The step's result is the last answer's: a step whose
expectation never held FAILs at the bound, showing what the last answer was.
It never passes and is never skipped. A request that cannot be sent at all
fails the step at once; it is not asked again.

A poll waits for what the step expects, so it is not a sleep (``loader``
still refuses ``sleep``, ``wait``, ``delay`` and the rest). Only a ``GET`` may
poll: sending a change again would repeat it.

Nothing here imports Playwright or the product, and the clock and the sleep
are given, so the unit job tests it without waiting.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Polled(Generic[T]):
    """The last answer, whether the expectation held, and what it took."""

    answer: T
    held: bool
    asks: int
    #: Seconds from the first ask to the last answer.
    seconds: float


def poll(
    ask: Callable[[], T],
    holds: Callable[[T], bool],
    *,
    up_to_seconds: float,
    every_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Polled[T]:
    """Ask until ``holds(answer)``, or until *up_to_seconds* have passed.

    The first ask is made at once. After an answer that does not hold, the
    next ask is ``every_seconds`` later, or at the bound if that is sooner; an
    answer that does not hold at or after the bound is the last one.
    """
    if every_seconds <= 0 or up_to_seconds < every_seconds:
        raise ValueError("a poll asks every_seconds > 0, up to at least that long")
    started = clock()
    asks = 0
    while True:
        answer = ask()
        asks += 1
        elapsed = clock() - started
        if holds(answer):
            return Polled(answer, True, asks, elapsed)
        remaining = up_to_seconds - elapsed
        if remaining <= 0:
            return Polled(answer, False, asks, elapsed)
        sleep(min(every_seconds, remaining))


def describe(polled: Polled, up_to_seconds: float) -> str:
    """One line on how the poll ended, for the step's ``observed``."""
    asks = "ask" if polled.asks == 1 else "asks"
    if polled.held:
        return f"held after {polled.seconds:.0f} s ({polled.asks} {asks})"
    return (
        f"did not hold within {up_to_seconds:g} s ({polled.asks} {asks} over"
        f" {polled.seconds:.0f} s)"
    )
