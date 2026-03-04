"""
Thread-safe in-memory cache for feature flag definitions with TTL support.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from .types import FeatureFlagDefinition


class FlagCache:
    """
    Thread-safe cache for feature flag definitions fetched from the platform API.

    The cache is valid for `ttl` seconds after the last successful refresh.
    Concurrent reads are fully safe; writes use a lock to prevent races.
    """

    def __init__(self, ttl: int = 300) -> None:
        self._ttl = ttl
        self._flags: Dict[str, FeatureFlagDefinition] = {}
        self._fetched_at: Optional[float] = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_valid(self) -> bool:
        """Return True if the cache has data that has not expired."""
        with self._lock:
            if self._fetched_at is None:
                return False
            return (time.monotonic() - self._fetched_at) < self._ttl

    def get(self, flag_key: str) -> Optional[FeatureFlagDefinition]:
        """Return the flag definition for `flag_key`, or None if not cached."""
        with self._lock:
            return self._flags.get(flag_key)

    def get_all(self) -> Dict[str, FeatureFlagDefinition]:
        """Return a snapshot of all cached flags."""
        with self._lock:
            return dict(self._flags)

    def update(self, flags: list[FeatureFlagDefinition]) -> None:
        """Replace the entire cache with the given flag definitions."""
        with self._lock:
            self._flags = {f.key: f for f in flags}
            self._fetched_at = time.monotonic()

    def clear(self) -> None:
        """Clear all cached entries and reset the TTL timer."""
        with self._lock:
            self._flags.clear()
            self._fetched_at = None

    def __len__(self) -> int:
        with self._lock:
            return len(self._flags)
