"""
Unit tests for split_url_service.py — EP-036 Batch 1.

Tests cover:
- Cookie name generation from experiment key
- User hashing (determinism, range)
- URL variant selection (2, 3, 4 variants)
- Consistent routing (same user → same URL)
- Edge cases (boundary hashes, single-character keys)
"""

import pytest

from backend.app.schemas.split_url_config import SplitUrlConfig, SplitUrlVariant

# ---------------------------------------------------------------------------
# These imports will FAIL (red phase) until the implementation exists.
# ---------------------------------------------------------------------------
from modules.backend.app.services.split_url_service import (
    get_cookie_name,
    get_url_variant,
    hash_user,
)

# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _make_variant(name: str, url: str, allocation: float) -> SplitUrlVariant:
    return SplitUrlVariant(name=name, url=url, traffic_allocation=allocation)


def _two_variant_config() -> SplitUrlConfig:
    return SplitUrlConfig(
        variants=[
            _make_variant("control", "https://example.com/a", 50.0),
            _make_variant("treatment", "https://example.com/b", 50.0),
        ]
    )


def _three_variant_config() -> SplitUrlConfig:
    return SplitUrlConfig(
        variants=[
            _make_variant("v1", "https://example.com/1", 33.34),
            _make_variant("v2", "https://example.com/2", 33.33),
            _make_variant("v3", "https://example.com/3", 33.33),
        ]
    )


def _four_variant_config() -> SplitUrlConfig:
    return SplitUrlConfig(
        variants=[
            _make_variant("v1", "https://example.com/1", 25.0),
            _make_variant("v2", "https://example.com/2", 25.0),
            _make_variant("v3", "https://example.com/3", 25.0),
            _make_variant("v4", "https://example.com/4", 25.0),
        ]
    )


# ──────────────────────────────────────────────────────────────────────────
# Cookie name generation
# ──────────────────────────────────────────────────────────────────────────


class TestGetCookieName:
    def test_basic_cookie_name(self):
        assert get_cookie_name("my_experiment") == "split_url_my_experiment"

    def test_cookie_name_with_dashes(self):
        assert get_cookie_name("exp-2024-homepage") == "split_url_exp-2024-homepage"

    def test_cookie_name_short_key(self):
        assert get_cookie_name("x") == "split_url_x"

    def test_cookie_name_numeric_key(self):
        assert get_cookie_name("exp_001") == "split_url_exp_001"

    def test_cookie_name_prefix(self):
        name = get_cookie_name("anything")
        assert name.startswith("split_url_")

    def test_cookie_name_is_deterministic(self):
        key = "stable_experiment"
        assert get_cookie_name(key) == get_cookie_name(key)


# ──────────────────────────────────────────────────────────────────────────
# User hashing
# ──────────────────────────────────────────────────────────────────────────


class TestHashUser:
    def test_hash_returns_float(self):
        result = hash_user("user123", "exp_key")
        assert isinstance(result, float)

    def test_hash_in_range(self):
        result = hash_user("user123", "exp_key")
        assert 0.0 <= result < 1.0

    def test_hash_is_deterministic(self):
        h1 = hash_user("user42", "my_exp")
        h2 = hash_user("user42", "my_exp")
        assert h1 == h2

    def test_different_users_different_hashes(self):
        h1 = hash_user("user_a", "exp1")
        h2 = hash_user("user_b", "exp1")
        assert h1 != h2

    def test_same_user_different_experiment_different_hash(self):
        h1 = hash_user("user_a", "exp1")
        h2 = hash_user("user_a", "exp2")
        assert h1 != h2

    def test_hash_distribution_rough(self):
        """Hash of many users should spread across [0, 1)."""
        hashes = [hash_user(f"user_{i}", "exp_dist") for i in range(200)]
        below_half = sum(1 for h in hashes if h < 0.5)
        # Expect roughly 50% below 0.5 — allow wide tolerance for 200 samples.
        assert 70 <= below_half <= 130

    def test_hash_empty_user_id(self):
        result = hash_user("", "exp_key")
        assert 0.0 <= result < 1.0

    def test_hash_long_user_id(self):
        result = hash_user("u" * 1000, "exp_key")
        assert 0.0 <= result < 1.0


# ──────────────────────────────────────────────────────────────────────────
# URL variant selection — 2 variants
# ──────────────────────────────────────────────────────────────────────────


class TestGetUrlVariantTwoVariants:
    def test_returns_variant_object(self):
        config = _two_variant_config()
        variant = get_url_variant("user1", "exp1", config)
        assert isinstance(variant, SplitUrlVariant)

    def test_returned_url_is_one_of_variants(self):
        config = _two_variant_config()
        valid_urls = {v.url for v in config.variants}
        variant = get_url_variant("user1", "exp1", config)
        assert variant.url in valid_urls

    def test_consistent_routing_two_variants(self):
        config = _two_variant_config()
        v1 = get_url_variant("stable_user", "exp1", config)
        v2 = get_url_variant("stable_user", "exp1", config)
        assert v1.url == v2.url

    def test_both_variants_reachable(self):
        """With enough users, both variants should be assigned."""
        config = _two_variant_config()
        assigned_urls = {
            get_url_variant(f"user_{i}", "exp_two", config).url for i in range(100)
        }
        assert len(assigned_urls) == 2

    def test_traffic_split_approx_50_50(self):
        config = _two_variant_config()
        counts = {"https://example.com/a": 0, "https://example.com/b": 0}
        for i in range(1000):
            url = get_url_variant(f"u{i}", "split_exp", config).url
            counts[url] += 1
        assert 400 <= counts["https://example.com/a"] <= 600
        assert 400 <= counts["https://example.com/b"] <= 600


# ──────────────────────────────────────────────────────────────────────────
# URL variant selection — 3 variants
# ──────────────────────────────────────────────────────────────────────────


class TestGetUrlVariantThreeVariants:
    def test_returns_valid_variant(self):
        config = _three_variant_config()
        valid_urls = {v.url for v in config.variants}
        variant = get_url_variant("user99", "exp3", config)
        assert variant.url in valid_urls

    def test_consistent_routing_three_variants(self):
        config = _three_variant_config()
        v1 = get_url_variant("user_abc", "exp3v", config)
        v2 = get_url_variant("user_abc", "exp3v", config)
        assert v1.url == v2.url

    def test_all_three_variants_reachable(self):
        config = _three_variant_config()
        assigned = {
            get_url_variant(f"user_{i}", "exp_three", config).url for i in range(300)
        }
        assert len(assigned) == 3

    def test_traffic_split_approx_equal_three(self):
        config = _three_variant_config()
        from collections import Counter

        counts = Counter()
        for i in range(1500):
            url = get_url_variant(f"u{i}", "exp_3w", config).url
            counts[url] += 1
        for url, count in counts.items():
            assert 350 <= count <= 650, f"{url} got {count} assignments"


# ──────────────────────────────────────────────────────────────────────────
# URL variant selection — 4 variants
# ──────────────────────────────────────────────────────────────────────────


class TestGetUrlVariantFourVariants:
    def test_returns_valid_variant(self):
        config = _four_variant_config()
        valid_urls = {v.url for v in config.variants}
        variant = get_url_variant("user_four", "exp4", config)
        assert variant.url in valid_urls

    def test_consistent_routing_four_variants(self):
        config = _four_variant_config()
        v1 = get_url_variant("user_xyz", "exp4v", config)
        v2 = get_url_variant("user_xyz", "exp4v", config)
        assert v1.url == v2.url

    def test_all_four_variants_reachable(self):
        config = _four_variant_config()
        assigned = {
            get_url_variant(f"user_{i}", "exp_four", config).url for i in range(400)
        }
        assert len(assigned) == 4

    def test_traffic_split_approx_equal_four(self):
        config = _four_variant_config()
        from collections import Counter

        counts = Counter()
        for i in range(2000):
            url = get_url_variant(f"u{i}", "exp_4w", config).url
            counts[url] += 1
        for url, count in counts.items():
            assert 350 <= count <= 650, f"{url} got {count} assignments"


# ──────────────────────────────────────────────────────────────────────────
# Skewed traffic allocation
# ──────────────────────────────────────────────────────────────────────────


class TestSkewedTrafficAllocation:
    def test_90_10_split(self):
        config = SplitUrlConfig(
            variants=[
                _make_variant("heavy", "https://example.com/heavy", 90.0),
                _make_variant("light", "https://example.com/light", 10.0),
            ]
        )
        from collections import Counter

        counts = Counter()
        for i in range(1000):
            url = get_url_variant(f"u{i}", "exp_skew", config).url
            counts[url] += 1
        # Heavy variant should get ~90%
        assert counts["https://example.com/heavy"] >= 800
        assert counts["https://example.com/light"] <= 200

    def test_fallback_to_last_variant(self):
        """get_url_variant always returns a variant, even with floating-point edge cases."""
        config = _two_variant_config()
        # This should not raise and should return the last variant as fallback
        result = get_url_variant("edge_user", "edge_exp", config)
        assert result is not None
        assert result.url in {"https://example.com/a", "https://example.com/b"}
