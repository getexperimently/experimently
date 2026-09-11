"""
Tests for the rate limiting middleware.

Covers:
- SlidingWindowRateLimiter (in-memory fallback)
- RedisRateLimiter (Redis-backed + fallback behaviour)
- RateLimitMiddleware (end-to-end HTTP layer)
- Client IP extraction from X-Forwarded-For
- Route-specific rate limit configuration
"""

import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.middleware.rate_limiter import (
    SlidingWindowRateLimiter,
    RedisRateLimiter,
    RateLimitMiddleware,
    RATE_LIMIT_CONFIG,
    DEFAULT_RATE_LIMIT,
    resolve_rate_limit,
    _get_client_ip,
)


# ---------------------------------------------------------------------------
# SlidingWindowRateLimiter tests
# ---------------------------------------------------------------------------


class TestSlidingWindowRateLimiter:
    """Tests for the in-memory sliding-window rate limiter."""

    def test_allows_within_limit(self):
        limiter = SlidingWindowRateLimiter()
        for i in range(5):
            allowed, remaining = limiter.is_allowed("key1", limit=5, window_seconds=60)
            assert allowed is True
            assert remaining == 5 - i - 1

    def test_blocks_over_limit(self):
        limiter = SlidingWindowRateLimiter()
        for _ in range(5):
            limiter.is_allowed("key1", limit=5, window_seconds=60)
        allowed, remaining = limiter.is_allowed("key1", limit=5, window_seconds=60)
        assert allowed is False
        assert remaining == 0

    def test_independent_keys(self):
        limiter = SlidingWindowRateLimiter()
        for _ in range(3):
            limiter.is_allowed("key_a", limit=3, window_seconds=60)
        # key_a is exhausted
        allowed_a, _ = limiter.is_allowed("key_a", limit=3, window_seconds=60)
        assert allowed_a is False
        # key_b should still be fine
        allowed_b, remaining_b = limiter.is_allowed("key_b", limit=3, window_seconds=60)
        assert allowed_b is True
        assert remaining_b == 2

    def test_window_expiry(self):
        limiter = SlidingWindowRateLimiter()
        # Fill the limit
        for _ in range(3):
            limiter.is_allowed("key1", limit=3, window_seconds=1)
        allowed, _ = limiter.is_allowed("key1", limit=3, window_seconds=1)
        assert allowed is False

        # Wait for window to expire
        time.sleep(1.1)
        allowed, remaining = limiter.is_allowed("key1", limit=3, window_seconds=1)
        assert allowed is True
        assert remaining == 2


# ---------------------------------------------------------------------------
# RedisRateLimiter tests
# ---------------------------------------------------------------------------


class TestRedisRateLimiter:
    """Tests for the Redis-backed rate limiter."""

    def test_uses_redis_when_available(self):
        """When Redis is reachable, INCR/EXPIRE are used."""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [1, -1]  # first request, no TTL yet
        mock_redis.pipeline.return_value = mock_pipe

        limiter = RedisRateLimiter()
        limiter._redis_client = mock_redis
        limiter._redis_available = True

        allowed, remaining = limiter.is_allowed("key1", limit=10, window_seconds=60)

        assert allowed is True
        assert remaining == 9
        mock_pipe.incr.assert_called_once_with("ratelimit:key1")
        mock_pipe.ttl.assert_called_once_with("ratelimit:key1")
        mock_redis.expire.assert_called_once_with("ratelimit:key1", 60)

    def test_redis_blocks_over_limit(self):
        """When Redis count exceeds limit, request is denied."""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [11, 45]  # 11th request, TTL exists
        mock_redis.pipeline.return_value = mock_pipe

        limiter = RedisRateLimiter()
        limiter._redis_client = mock_redis
        limiter._redis_available = True

        allowed, remaining = limiter.is_allowed("key1", limit=10, window_seconds=60)

        assert allowed is False
        assert remaining == 0

    def test_falls_back_on_redis_error(self):
        """On Redis pipeline error, falls back to in-memory limiter."""
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_pipe.execute.side_effect = Exception("Connection refused")
        mock_redis.pipeline.return_value = mock_pipe

        limiter = RedisRateLimiter()
        limiter._redis_client = mock_redis
        limiter._redis_available = True

        allowed, remaining = limiter.is_allowed("key1", limit=10, window_seconds=60)

        assert allowed is True
        assert remaining == 9
        assert limiter._redis_available is False

    def test_falls_back_when_redis_unavailable(self):
        """When Redis was previously detected as unavailable, uses fallback."""
        limiter = RedisRateLimiter()
        limiter._redis_available = False
        limiter._redis_client = None

        allowed, remaining = limiter.is_allowed("key1", limit=5, window_seconds=60)

        assert allowed is True
        assert remaining == 4

    def test_lazy_connect_failure(self):
        """If initial Redis connection fails, falls back gracefully."""
        with patch("backend.app.middleware.rate_limiter.RedisRateLimiter._get_redis", return_value=None):
            limiter = RedisRateLimiter(redis_host="nonexistent")
            limiter._redis_available = False

            allowed, remaining = limiter.is_allowed("key1", limit=5, window_seconds=60)
            assert allowed is True
            assert remaining == 4


# ---------------------------------------------------------------------------
# Client IP extraction tests
# ---------------------------------------------------------------------------


class TestGetClientIp:
    """Tests for _get_client_ip helper."""

    def test_uses_x_forwarded_for(self):
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}
        assert _get_client_ip(request) == "1.2.3.4"

    def test_uses_client_host_when_no_forwarded_header(self):
        request = MagicMock()
        request.headers = {}
        request.client.host = "192.168.1.1"
        assert _get_client_ip(request) == "192.168.1.1"

    def test_returns_unknown_when_no_client(self):
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert _get_client_ip(request) == "unknown"


# ---------------------------------------------------------------------------
# RateLimitMiddleware integration tests
# ---------------------------------------------------------------------------


def _make_app(enabled: bool = True, limiter=None) -> FastAPI:
    """Create a minimal FastAPI app with rate limiting middleware."""
    test_app = FastAPI()

    @test_app.get("/api/v1/test")
    async def test_endpoint():
        return {"ok": True}

    @test_app.get("/api/v1/auth/token")
    async def auth_endpoint():
        return {"token": "abc"}

    middleware = RateLimitMiddleware(test_app, enabled=enabled)
    if limiter is not None:
        middleware._limiter = limiter
    # We need to build the app with the middleware manually
    # since TestClient wraps the ASGI app
    return middleware


class TestRateLimitMiddleware:
    """End-to-end tests for the rate limiting middleware."""

    def test_returns_rate_limit_headers(self):
        app = _make_app(enabled=True, limiter=SlidingWindowRateLimiter())
        client = TestClient(app)

        response = client.get("/api/v1/test")

        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Window" in response.headers

    def test_returns_429_when_limit_exceeded(self):
        limiter = SlidingWindowRateLimiter()
        app = _make_app(enabled=True, limiter=limiter)
        client = TestClient(app)

        limit, window = DEFAULT_RATE_LIMIT  # 300, 60

        # Exhaust the limit
        for _ in range(limit):
            resp = client.get("/api/v1/test")
            assert resp.status_code == 200

        # Next request should be rejected
        response = client.get("/api/v1/test")
        assert response.status_code == 429
        assert response.headers["Retry-After"] == str(window)
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert "Too Many Requests" in response.json()["detail"]

    def test_disabled_mode_passes_through(self):
        app = _make_app(enabled=False)
        client = TestClient(app)

        response = client.get("/api/v1/test")
        assert response.status_code == 200
        # No rate limit headers when disabled
        assert "X-RateLimit-Limit" not in response.headers

    def test_auth_endpoint_stricter_limit(self):
        limiter = SlidingWindowRateLimiter()
        app = _make_app(enabled=True, limiter=limiter)
        client = TestClient(app)

        auth_limit, _ = RATE_LIMIT_CONFIG["/api/v1/auth/token"]  # 10

        for _ in range(auth_limit):
            resp = client.get("/api/v1/auth/token")
            assert resp.status_code == 200

        response = client.get("/api/v1/auth/token")
        assert response.status_code == 429


# ---------------------------------------------------------------------------
# Rate limit config tests
# ---------------------------------------------------------------------------


class TestRateLimitConfig:
    """Verify the rate limit configuration constants."""

    def test_auth_endpoints_have_strict_limits(self):
        for path in ["/api/v1/auth/token", "/api/v1/auth/signup",
                     "/api/v1/auth/forgot-password", "/api/v1/auth/reset-password"]:
            limit, window = RATE_LIMIT_CONFIG[path]
            default_limit, _ = DEFAULT_RATE_LIMIT
            assert limit < default_limit, f"{path} should have stricter limit than default"

    def test_tracking_endpoints_have_higher_limits(self):
        default_limit, _ = DEFAULT_RATE_LIMIT
        for path in [
            "/api/v1/tracking/assign",
            "/api/v1/tracking/track",
            "/api/v1/tracking/batch",
            "/api/v1/tracking/assignments/user-1",
            "/api/v1/feature-flags/evaluate/my-flag",
            "/api/v1/feature-flags/user/user-1",
        ]:
            limit, window = resolve_rate_limit(path)
            assert limit >= default_limit, f"{path} should have higher limit for SDK traffic"
            assert window == 60

    def test_sdk_limit_is_configurable(self):
        assert resolve_rate_limit("/api/v1/tracking/batch", 42) == (42, 60)

    def test_exact_config_wins_over_prefix_and_default(self):
        assert resolve_rate_limit("/api/v1/auth/token") == RATE_LIMIT_CONFIG["/api/v1/auth/token"]
        assert resolve_rate_limit("/api/v1/experiments/") == DEFAULT_RATE_LIMIT
        # The dashboard's feature-flag CRUD routes are not SDK traffic
        assert resolve_rate_limit("/api/v1/feature-flags/") == DEFAULT_RATE_LIMIT

    def test_default_rate_limit(self):
        limit, window = DEFAULT_RATE_LIMIT
        assert limit == 300
        assert window == 60
