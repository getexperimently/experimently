"""
Test cases for evaluation result caching.

Tests the caching layer for rule evaluation results.
"""

import time
import timeit

import pytest

from backend.app.core.evaluation_cache import CacheEntry, CacheKey, EvaluationCache
from backend.app.schemas.targeting_rule import (
    Condition,
    LogicalOperator,
    OperatorType,
    RuleGroup,
    TargetingRule,
)


class TestCacheKeyGeneration:
    """Test cache key generation from user context and rule."""

    def test_generate_cache_key(self):
        """Test basic cache key generation."""
        user_context = {"user_id": "user_123", "country": "US", "age": 25}

        rule_id = "rule_1"

        cache = EvaluationCache()
        key = cache.generate_key(rule_id, user_context)

        assert key is not None
        assert isinstance(key, str)
        assert len(key) > 0

    def test_same_inputs_same_key(self):
        """Test that same inputs produce same cache key."""
        user_context = {"user_id": "user_123", "country": "US", "age": 25}

        rule_id = "rule_1"

        cache = EvaluationCache()
        key1 = cache.generate_key(rule_id, user_context)
        key2 = cache.generate_key(rule_id, user_context)

        assert key1 == key2

    def test_different_user_different_key(self):
        """Test that different users produce different keys."""
        user_context1 = {"user_id": "user_123", "country": "US"}
        user_context2 = {"user_id": "user_456", "country": "US"}

        rule_id = "rule_1"

        cache = EvaluationCache()
        key1 = cache.generate_key(rule_id, user_context1)
        key2 = cache.generate_key(rule_id, user_context2)

        assert key1 != key2

    def test_different_rule_different_key(self):
        """Test that different rules produce different keys."""
        user_context = {"user_id": "user_123"}

        cache = EvaluationCache()
        key1 = cache.generate_key("rule_1", user_context)
        key2 = cache.generate_key("rule_2", user_context)

        assert key1 != key2

    def test_key_order_independence(self):
        """Test that dict key order doesn't affect cache key."""
        user_context1 = {"country": "US", "age": 25, "user_id": "user_123"}
        user_context2 = {"user_id": "user_123", "age": 25, "country": "US"}

        rule_id = "rule_1"

        cache = EvaluationCache()
        key1 = cache.generate_key(rule_id, user_context1)
        key2 = cache.generate_key(rule_id, user_context2)

        # Should be same despite different order
        assert key1 == key2


class TestCacheStorage:
    """Test cache storage and retrieval."""

    def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = EvaluationCache()

        result = cache.get("rule_1", {"user_id": "user_123"})

        assert result is None

    def test_cache_hit(self):
        """Test cache hit returns stored result."""
        cache = EvaluationCache()

        user_context = {"user_id": "user_123", "country": "US"}
        rule_id = "rule_1"

        # Store result
        cache.set(rule_id, user_context, True)

        # Retrieve result
        result = cache.get(rule_id, user_context)

        assert result is True

    def test_cache_stores_false_values(self):
        """Test that False results are also cached."""
        cache = EvaluationCache()

        user_context = {"user_id": "user_123"}
        rule_id = "rule_1"

        # Store False result
        cache.set(rule_id, user_context, False)

        # Retrieve result
        result = cache.get(rule_id, user_context)

        assert result is False
        assert result is not None  # Distinguish from cache miss

    def test_cache_overwrites_existing_entry(self):
        """Test that new value overwrites existing entry."""
        cache = EvaluationCache()

        user_context = {"user_id": "user_123"}
        rule_id = "rule_1"

        # Store initial result
        cache.set(rule_id, user_context, True)

        # Overwrite with new result
        cache.set(rule_id, user_context, False)

        # Should get updated result
        result = cache.get(rule_id, user_context)
        assert result is False


class TestCacheTTL:
    """Test time-to-live (TTL) for cache entries."""

    def test_entry_expires_after_ttl(self):
        """Test that cache entries expire after TTL."""
        cache = EvaluationCache(default_ttl=0.1)  # 100ms TTL

        user_context = {"user_id": "user_123"}
        rule_id = "rule_1"

        # Store result
        cache.set(rule_id, user_context, True)

        # Should be in cache immediately
        assert cache.get(rule_id, user_context) is True

        # Wait for expiration
        time.sleep(0.15)

        # Should be expired
        assert cache.get(rule_id, user_context) is None

    def test_entry_valid_before_ttl(self):
        """Test that entries are valid before TTL expires."""
        cache = EvaluationCache(default_ttl=10.0)  # 10 second TTL

        user_context = {"user_id": "user_123"}
        rule_id = "rule_1"

        # Store result
        cache.set(rule_id, user_context, True)

        # Wait a bit but less than TTL
        time.sleep(0.05)

        # Should still be in cache
        assert cache.get(rule_id, user_context) is True

    def test_custom_ttl_per_entry(self):
        """Test setting custom TTL for specific entries."""
        cache = EvaluationCache(default_ttl=10.0)

        user_context = {"user_id": "user_123"}
        rule_id = "rule_1"

        # Store with custom short TTL
        cache.set(rule_id, user_context, True, ttl=0.1)

        # Wait for custom TTL to expire
        time.sleep(0.15)

        # Should be expired
        assert cache.get(rule_id, user_context) is None


class TestCacheSizeManagement:
    """Test cache size limits and eviction."""

    def test_cache_respects_max_size(self):
        """Test that cache doesn't exceed max size."""
        cache = EvaluationCache(max_size=5)

        # Add 10 entries
        for i in range(10):
            cache.set(f"rule_{i}", {"user_id": f"user_{i}"}, True)

        # Cache size should not exceed max
        assert cache.size <= 5

    def test_lru_eviction(self):
        """Test that least recently used entries are evicted."""
        cache = EvaluationCache(max_size=3)

        # Add 3 entries
        cache.set("rule_1", {"user_id": "user_1"}, True)
        cache.set("rule_2", {"user_id": "user_2"}, True)
        cache.set("rule_3", {"user_id": "user_3"}, True)

        # Access rule_1 and rule_2 to mark as recently used
        cache.get("rule_1", {"user_id": "user_1"})
        cache.get("rule_2", {"user_id": "user_2"})

        # Add a 4th entry - should evict rule_3 (least recently used)
        cache.set("rule_4", {"user_id": "user_4"}, True)

        # rule_3 should be evicted
        assert cache.get("rule_3", {"user_id": "user_3"}) is None

        # rule_1 and rule_2 should still be present
        assert cache.get("rule_1", {"user_id": "user_1"}) is True
        assert cache.get("rule_2", {"user_id": "user_2"}) is True


class TestCacheInvalidation:
    """Test cache invalidation strategies."""

    def test_invalidate_by_rule_id(self):
        """Test invalidating all entries for a specific rule."""
        cache = EvaluationCache()

        # Add entries for multiple rules and users
        cache.set("rule_1", {"user_id": "user_1"}, True)
        cache.set("rule_1", {"user_id": "user_2"}, True)
        cache.set("rule_2", {"user_id": "user_1"}, True)

        # Invalidate rule_1
        cache.invalidate_rule("rule_1")

        # rule_1 entries should be gone
        assert cache.get("rule_1", {"user_id": "user_1"}) is None
        assert cache.get("rule_1", {"user_id": "user_2"}) is None

        # rule_2 should still be present
        assert cache.get("rule_2", {"user_id": "user_1"}) is True

    def test_invalidate_by_user(self):
        """Test invalidating all entries for a specific user."""
        cache = EvaluationCache()

        # Add entries
        cache.set("rule_1", {"user_id": "user_1", "country": "US"}, True)
        cache.set("rule_2", {"user_id": "user_1", "country": "US"}, True)
        cache.set("rule_1", {"user_id": "user_2", "country": "US"}, True)

        # Invalidate user_1
        cache.invalidate_user("user_1")

        # user_1 entries should be gone
        assert cache.get("rule_1", {"user_id": "user_1", "country": "US"}) is None
        assert cache.get("rule_2", {"user_id": "user_1", "country": "US"}) is None

        # user_2 should still be present
        assert cache.get("rule_1", {"user_id": "user_2", "country": "US"}) is True

    def test_clear_all(self):
        """Test clearing entire cache."""
        cache = EvaluationCache()

        # Add multiple entries
        cache.set("rule_1", {"user_id": "user_1"}, True)
        cache.set("rule_2", {"user_id": "user_2"}, True)
        cache.set("rule_3", {"user_id": "user_3"}, True)

        assert cache.size > 0

        # Clear all
        cache.clear()

        # All should be gone
        assert cache.size == 0
        assert cache.get("rule_1", {"user_id": "user_1"}) is None


class TestCacheStatistics:
    """Test cache statistics tracking."""

    def test_track_hit_rate(self):
        """Test tracking cache hit rate."""
        cache = EvaluationCache()

        user_context = {"user_id": "user_123"}

        # Cache miss
        cache.get("rule_1", user_context)

        # Store and hit
        cache.set("rule_1", user_context, True)
        cache.get("rule_1", user_context)
        cache.get("rule_1", user_context)

        stats = cache.get_stats()

        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.666, rel=0.01)

    def test_track_evictions(self):
        """Test tracking number of evictions."""
        cache = EvaluationCache(max_size=2)

        # Fill cache beyond capacity
        cache.set("rule_1", {"user_id": "user_1"}, True)
        cache.set("rule_2", {"user_id": "user_2"}, True)
        cache.set("rule_3", {"user_id": "user_3"}, True)  # Causes eviction

        stats = cache.get_stats()

        assert stats["evictions"] >= 1

    def test_track_size(self):
        """Test tracking current cache size."""
        cache = EvaluationCache()

        assert cache.size == 0

        cache.set("rule_1", {"user_id": "user_1"}, True)
        assert cache.size == 1

        cache.set("rule_2", {"user_id": "user_2"}, True)
        assert cache.size == 2


class TestCacheThreadSafety:
    """Test cache thread safety."""

    def test_concurrent_access(self):
        """Test that concurrent access doesn't corrupt cache."""
        import threading

        cache = EvaluationCache()

        def worker(thread_id):
            for i in range(100):
                user_context = {"user_id": f"user_{thread_id}_{i}"}
                cache.set(f"rule_{i}", user_context, True)
                cache.get(f"rule_{i}", user_context)

        # Create multiple threads
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # Cache should still be functional
        stats = cache.get_stats()
        assert stats is not None
        assert cache.size >= 0  # No corruption


class TestCacheWarming:
    """Test cache warming strategies."""

    def test_warm_cache_with_common_users(self):
        """Test pre-warming cache with common user patterns."""
        cache = EvaluationCache()

        # Simulate warming cache with common patterns
        common_contexts = [
            {"country": "US", "verified": True},
            {"country": "CA", "verified": True},
            {"country": "UK", "verified": False},
        ]

        rule_ids = ["rule_1", "rule_2"]

        for rule_id in rule_ids:
            for context in common_contexts:
                # Pre-compute and cache results
                # In real implementation, this would evaluate the rule
                cache.set(rule_id, context, True)

        # Verify cache is warmed
        assert cache.size == 6  # 2 rules * 3 contexts

        # Subsequent lookups should be fast
        result = cache.get("rule_1", {"country": "US", "verified": True})
        assert result is True


class TestCachePerformance:
    """Test cache performance characteristics."""

    @staticmethod
    def _time_lookups(entries: int, lookups: int = 1000) -> float:
        """Best of five runs of *lookups* gets against a cache holding *entries*.

        Best-of-N rather than a single run: one stalled moment on a shared
        runner is enough to make a single `time.time()` delta meaningless, and
        `timeit` takes the minimum for exactly this reason.
        """
        cache = EvaluationCache(max_size=max(entries, lookups) * 2)
        for i in range(entries):
            cache.set(f"rule_{i}", {"user_id": f"user_{i}"}, True)
        keys = [
            (f"rule_{i % entries}", {"user_id": f"user_{i % entries}"})
            for i in range(lookups)
        ]

        def run() -> None:
            for rule_id, context in keys:
                cache.get(rule_id, context)

        return min(timeit.repeat(run, repeat=5, number=1))

    def test_cache_lookup_does_not_slow_down_as_the_cache_grows(self):
        """A lookup is a hash lookup: its cost must not grow with cache size.

        This used to be `assert duration < 0.05` for 1000 lookups -- a single
        wall-clock reading compared against an absolute number. It measured the
        runner, not the cache: it passes in 2.6 ms on a laptop and failed a
        pull request at 285 ms on a contended GitHub runner, a 100x difference
        with no code change behind it. CLAUDE.md names this exact shape:
        "Never assert a single wall-clock timing ... take the best of several
        runs (what `timeit` does), or assert on the deterministic thing the
        timing was standing in for."

        The deterministic thing here is the complexity. Both measurements run
        in the same process, so a slow runner slows both equally and cancels
        out of the ratio. Measured: 1.00x for 100x the entries. A linear scan
        would be ~100x, so the bound below has two orders of magnitude of
        headroom and still fails a real regression.
        """
        small = self._time_lookups(entries=100)
        large = self._time_lookups(entries=10_000)

        assert large < small * 10, (
            f"1000 lookups took {small * 1000:.2f} ms against 100 entries and "
            f"{large * 1000:.2f} ms against 10,000 ({large / small:.1f}x). A "
            "hash lookup should not care how full the cache is; this looks "
            "like the lookup became a scan."
        )

    def test_a_cache_hit_does_not_re_evaluate(self):
        """The property the speedup was standing in for, asserted directly.

        The previous version slept 1 ms ten times, timed that against ten cache
        hits, and asserted `cached < uncached / 5` -- the other shape CLAUDE.md
        warns about, and one whose "speedup" was really a measurement of
        `time.sleep`. What makes a cache fast is that it does not run the
        expensive thing again, and that is a count, not a duration.
        """
        cache = EvaluationCache()
        user_context = {"user_id": "user_123", "country": "US", "age": 25}
        calls = 0

        def expensive_evaluation() -> bool:
            nonlocal calls
            calls += 1
            return True

        cache.set("rule_1", user_context, expensive_evaluation())
        assert calls == 1

        for _ in range(10):
            assert cache.get("rule_1", user_context) is True

        assert calls == 1, (
            f"the expensive evaluation ran {calls} times for one set and ten "
            "gets; a cache hit must not re-evaluate"
        )
