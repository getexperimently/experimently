"""
Unit tests for the Lambda@Edge Split URL handler — EP-036 Batch 1.

Tests cover:
- Viewer-request event parsing
- Cookie detection → existing assignment reuse
- New assignment flow (no cookie → hash → pick URL → redirect + set cookie)
- Holdout check (users in holdout see the first / control URL)
- Response headers: Location, Set-Cookie, X-Split-URL-Variant, Cache-Control
- Pass-through when no config header is present
- Malformed config header handling
- Insufficient variants (< 2) → pass-through
"""
import json
import sys
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Add the split_url_router Lambda to sys.path so the handler can be imported.
# The module lives at backend/lambda/split_url_router/handler.py
# ---------------------------------------------------------------------------
_lambda_dir = Path(__file__).resolve().parents[3] / "lambda"
sys.path.insert(0, str(_lambda_dir / "split_url_router"))

# These imports will FAIL (red phase) until the implementation exists.
from handler import handler, _parse_cookies, _hash_user, _pick_variant  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _make_event(
    config: Optional[dict],
    cookie_header: str = "",
    uri: str = "/",
    client_ip: str = "1.2.3.4",
    user_agent: str = "TestAgent/1.0",
) -> dict:
    """Build a minimal Lambda@Edge viewer-request event."""
    headers: dict = {
        "x-forwarded-for": [{"key": "X-Forwarded-For", "value": client_ip}],
        "user-agent": [{"key": "User-Agent", "value": user_agent}],
    }
    if config is not None:
        headers["x-split-url-config"] = [
            {"key": "X-Split-URL-Config", "value": json.dumps(config)}
        ]
    if cookie_header:
        headers["cookie"] = [{"key": "Cookie", "value": cookie_header}]

    return {
        "Records": [
            {
                "cf": {
                    "request": {
                        "uri": uri,
                        "headers": headers,
                    }
                }
            }
        ]
    }


_TWO_VARIANT_CONFIG = {
    "experiment_key": "hp_test",
    "variants": [
        {"name": "control", "url": "https://example.com/a", "traffic_allocation": 50},
        {"name": "treatment", "url": "https://example.com/b", "traffic_allocation": 50},
    ],
    "cookie_ttl_days": 30,
}


# ──────────────────────────────────────────────────────────────────────────
# _parse_cookies
# ──────────────────────────────────────────────────────────────────────────

class TestParseCookies:
    def test_empty_string(self):
        assert _parse_cookies("") == {}

    def test_single_cookie(self):
        result = _parse_cookies("session=abc123")
        assert result == {"session": "abc123"}

    def test_multiple_cookies(self):
        result = _parse_cookies("a=1; b=2; c=3")
        assert result["a"] == "1"
        assert result["b"] == "2"
        assert result["c"] == "3"

    def test_cookie_value_with_url(self):
        result = _parse_cookies("split_url_exp=https://example.com/a")
        assert result["split_url_exp"] == "https://example.com/a"

    def test_cookie_with_spaces_around_separator(self):
        result = _parse_cookies("x=1 ; y=2")
        assert "x" in result
        assert "y" in result

    def test_no_value(self):
        # Cookie without '=' should not appear in result (or be ignored gracefully)
        result = _parse_cookies("novalue")
        assert "novalue" not in result


# ──────────────────────────────────────────────────────────────────────────
# _hash_user
# ──────────────────────────────────────────────────────────────────────────

class TestHashUserLambda:
    def test_returns_float_in_range(self):
        h = _hash_user("1.2.3.4", "Mozilla/5.0", "exp_key")
        assert isinstance(h, float)
        assert 0.0 <= h < 1.0

    def test_is_deterministic(self):
        h1 = _hash_user("10.0.0.1", "UA", "exp1")
        h2 = _hash_user("10.0.0.1", "UA", "exp1")
        assert h1 == h2

    def test_different_ip_different_hash(self):
        h1 = _hash_user("1.2.3.4", "UA", "exp1")
        h2 = _hash_user("5.6.7.8", "UA", "exp1")
        assert h1 != h2

    def test_different_experiment_different_hash(self):
        h1 = _hash_user("1.2.3.4", "UA", "exp1")
        h2 = _hash_user("1.2.3.4", "UA", "exp2")
        assert h1 != h2


# ──────────────────────────────────────────────────────────────────────────
# _pick_variant
# ──────────────────────────────────────────────────────────────────────────

class TestPickVariant:
    _VARIANTS = [
        {"name": "control", "url": "https://example.com/a", "traffic_allocation": 50},
        {"name": "treatment", "url": "https://example.com/b", "traffic_allocation": 50},
    ]

    def test_low_hash_picks_first(self):
        variant = _pick_variant(0.0, self._VARIANTS)
        assert variant["name"] == "control"

    def test_high_hash_picks_second(self):
        variant = _pick_variant(0.99, self._VARIANTS)
        assert variant["name"] == "treatment"

    def test_boundary_hash_picks_second(self):
        # 0.5 is the boundary — should pick treatment (cumulative just reached 0.5)
        variant = _pick_variant(0.5, self._VARIANTS)
        assert variant["name"] == "treatment"

    def test_fallback_to_last_variant(self):
        # hash beyond all cumulative sums (e.g., due to float rounding) → last variant
        variant = _pick_variant(0.9999, self._VARIANTS)
        assert variant["name"] == "treatment"

    def test_three_variants(self):
        variants = [
            {"name": "v1", "url": "https://a.com", "traffic_allocation": 33},
            {"name": "v2", "url": "https://b.com", "traffic_allocation": 33},
            {"name": "v3", "url": "https://c.com", "traffic_allocation": 34},
        ]
        assert _pick_variant(0.1, variants)["name"] == "v1"
        assert _pick_variant(0.5, variants)["name"] == "v2"
        assert _pick_variant(0.9, variants)["name"] == "v3"


# ──────────────────────────────────────────────────────────────────────────
# handler — pass-through cases
# ──────────────────────────────────────────────────────────────────────────

class TestHandlerPassThrough:
    def test_no_config_header_passes_through(self):
        event = _make_event(config=None)
        result = handler(event, None)
        # Should return the original request dict
        assert "status" not in result
        assert "headers" in result

    def test_malformed_config_passes_through(self):
        event = _make_event(config=None)
        # Inject malformed JSON manually
        event["Records"][0]["cf"]["request"]["headers"]["x-split-url-config"] = [
            {"key": "X-Split-URL-Config", "value": "{not valid json"}
        ]
        result = handler(event, None)
        assert "status" not in result

    def test_empty_variants_passes_through(self):
        config = {"experiment_key": "emp", "variants": []}
        event = _make_event(config=config)
        result = handler(event, None)
        assert "status" not in result

    def test_single_variant_passes_through(self):
        config = {
            "experiment_key": "single",
            "variants": [
                {"name": "only", "url": "https://example.com", "traffic_allocation": 100}
            ],
        }
        event = _make_event(config=config)
        result = handler(event, None)
        assert "status" not in result


# ──────────────────────────────────────────────────────────────────────────
# handler — new assignment (no cookie)
# ──────────────────────────────────────────────────────────────────────────

class TestHandlerNewAssignment:
    def test_returns_302_redirect(self):
        event = _make_event(config=_TWO_VARIANT_CONFIG, client_ip="10.0.0.1")
        result = handler(event, None)
        assert result["status"] == "302"

    def test_location_header_is_valid_url(self):
        event = _make_event(config=_TWO_VARIANT_CONFIG, client_ip="10.0.0.2")
        result = handler(event, None)
        location = result["headers"]["location"][0]["value"]
        assert location in {"https://example.com/a", "https://example.com/b"}

    def test_set_cookie_header_present(self):
        event = _make_event(config=_TWO_VARIANT_CONFIG, client_ip="10.0.0.3")
        result = handler(event, None)
        assert "set-cookie" in result["headers"]

    def test_set_cookie_contains_cookie_name(self):
        event = _make_event(config=_TWO_VARIANT_CONFIG, client_ip="10.0.0.4")
        result = handler(event, None)
        cookie = result["headers"]["set-cookie"][0]["value"]
        # Default cookie name is f"split_url_{experiment_key}"
        assert "split_url_hp_test" in cookie

    def test_x_split_url_variant_header(self):
        event = _make_event(config=_TWO_VARIANT_CONFIG, client_ip="10.0.0.5")
        result = handler(event, None)
        assert "x-split-url-variant" in result["headers"]
        variant_name = result["headers"]["x-split-url-variant"][0]["value"]
        assert variant_name in {"control", "treatment"}

    def test_cache_control_no_store(self):
        event = _make_event(config=_TWO_VARIANT_CONFIG, client_ip="10.0.0.6")
        result = handler(event, None)
        cache_ctrl = result["headers"]["cache-control"][0]["value"]
        assert "no-store" in cache_ctrl or "no-cache" in cache_ctrl

    def test_assignment_is_consistent_for_same_fingerprint(self):
        event = _make_event(
            config=_TWO_VARIANT_CONFIG,
            client_ip="192.168.1.100",
            user_agent="SameUA/1.0",
        )
        r1 = handler(event, None)
        r2 = handler(event, None)
        assert r1["headers"]["location"][0]["value"] == r2["headers"]["location"][0]["value"]

    def test_cookie_ttl_from_config(self):
        config = dict(_TWO_VARIANT_CONFIG)
        config["cookie_ttl_days"] = 7
        event = _make_event(config=config, client_ip="10.0.1.1")
        result = handler(event, None)
        cookie = result["headers"]["set-cookie"][0]["value"]
        # 7 days = 604800 seconds
        assert "604800" in cookie

    def test_custom_cookie_name_in_config(self):
        config = dict(_TWO_VARIANT_CONFIG)
        config["cookie_name"] = "my_custom_cookie"
        event = _make_event(config=config, client_ip="10.0.1.2")
        result = handler(event, None)
        cookie = result["headers"]["set-cookie"][0]["value"]
        assert "my_custom_cookie" in cookie


# ──────────────────────────────────────────────────────────────────────────
# handler — existing cookie (already assigned)
# ──────────────────────────────────────────────────────────────────────────

class TestHandlerExistingCookie:
    def test_existing_valid_cookie_passes_through(self):
        """If cookie holds a valid variant URL → pass through (no redirect)."""
        cookie_str = "split_url_hp_test=https://example.com/a"
        event = _make_event(
            config=_TWO_VARIANT_CONFIG,
            cookie_header=cookie_str,
            client_ip="172.16.0.1",
        )
        result = handler(event, None)
        # Should pass through the request — no status 302
        assert "status" not in result

    def test_existing_cookie_with_unknown_url_still_assigns(self):
        """Cookie with a URL not in the variant list → treat as new assignment."""
        cookie_str = "split_url_hp_test=https://unknown.com/z"
        event = _make_event(
            config=_TWO_VARIANT_CONFIG,
            cookie_header=cookie_str,
            client_ip="172.16.0.2",
        )
        result = handler(event, None)
        # Should redirect to a valid variant
        assert result.get("status") == "302"

    def test_wrong_cookie_name_triggers_new_assignment(self):
        """A cookie with a different name means no existing assignment."""
        cookie_str = "other_cookie=https://example.com/a"
        event = _make_event(
            config=_TWO_VARIANT_CONFIG,
            cookie_header=cookie_str,
            client_ip="172.16.0.3",
        )
        result = handler(event, None)
        assert result.get("status") == "302"


# ──────────────────────────────────────────────────────────────────────────
# handler — holdout check
# ──────────────────────────────────────────────────────────────────────────

class TestHandlerHoldout:
    def test_holdout_users_see_control_url(self):
        """
        When holdout_percentage is set and user is in holdout group,
        they should be redirected to the first (control) variant URL.
        """
        config = dict(_TWO_VARIANT_CONFIG)
        config["holdout_percentage"] = 100  # 100% holdout → all users in holdout

        event = _make_event(config=config, client_ip="99.1.2.3")
        result = handler(event, None)
        assert result.get("status") == "302"
        location = result["headers"]["location"][0]["value"]
        # Control URL is the first variant
        assert location == "https://example.com/a"

    def test_zero_holdout_proceeds_normally(self):
        """holdout_percentage=0 means no holdout — normal assignment."""
        config = dict(_TWO_VARIANT_CONFIG)
        config["holdout_percentage"] = 0

        event = _make_event(config=config, client_ip="88.1.2.3")
        result = handler(event, None)
        assert result.get("status") == "302"
        location = result["headers"]["location"][0]["value"]
        assert location in {"https://example.com/a", "https://example.com/b"}
