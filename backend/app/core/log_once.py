"""
Remember which (owner, reason) pairs have already been logged.

Evaluating targeting rules runs on every flag evaluation and every assignment.
A problem with a rule's *definition* (a ``between`` with no upper bound, an
operator the engine does not implement, a dashboard rule that cannot be
converted) is the same problem on every evaluation, so it is worth one
WARNING, not one per request. Callers ask :meth:`OnceLog.first` before
logging::

    if EVALUATION_NOTES.first(owner, "between: no upper bound"):
        logger.warning("... %s ...", owner)

The key is supplied by the caller and is meant to be an identifier and a fixed
reason -- a flag key, an experiment id, an operator, a constant string -- never
a user's attribute value: the set lives for the life of the process. It is
capped; when it fills it is emptied and each problem is logged once more.
"""

from __future__ import annotations

import threading
from typing import Hashable, Set, Tuple

#: Default number of (owner, reason) pairs remembered before the set is emptied.
DEFAULT_LIMIT = 4096


class OnceLog:
    """A capped, thread-safe set of (owner, reason) keys already logged."""

    def __init__(self, limit: int = DEFAULT_LIMIT) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        # Never rebound: callers may hold a reference to it (pattern_match
        # exposes it as ``_reported`` and its tests clear it).
        self.seen: Set[Tuple[Hashable, Hashable]] = set()

    def first(self, owner: Hashable, reason: Hashable) -> bool:
        """True the first time ``(owner, reason)`` is seen (since the last clear)."""
        key = (owner, reason)
        with self._lock:
            if key in self.seen:
                return False
            if len(self.seen) >= self._limit:
                self.seen.clear()
            self.seen.add(key)
        return True

    def clear(self) -> None:
        """Forget every key, so each problem is logged once more."""
        with self._lock:
            self.seen.clear()


#: Shared by the rules engine, the rules evaluation service and the targeting
#: adapter for problems in a rule's definition.
EVALUATION_NOTES = OnceLog()
