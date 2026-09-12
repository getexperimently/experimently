"""
Rate limiting middleware for the Experimentation Platform.

Provides a Redis-backed rate limiter (fixed-window via INCR + EXPIRE) with
automatic fallback to an in-memory sliding-window limiter when Redis is
unavailable.  The middleware attaches standard rate-limit headers to every
response and records Prometheus counters for hits and rejections.
"""

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Callable, Dict, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory fallback limiter
# ---------------------------------------------------------------------------


class SlidingWindowRateLimiter:
    """
    Thread-safe sliding-window rate limiter backed by in-memory deques.

    Each (key, route) pair gets an independent deque of timestamps for
    requests in the current window.  Requests older than ``window_seconds``
    are evicted on each check.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: Dict[str, deque] = defaultdict(deque)

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Check whether a new request from *key* is within the allowed rate.

        Returns:
            ``(allowed, remaining)`` — whether the request is allowed and how
            many requests remain in the current window.
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            window = self._windows[key]

            # Evict timestamps outside the current window
            while window and window[0] <= cutoff:
                window.popleft()

            count = len(window)
            if count >= limit:
                return False, 0

            window.append(now)
            return True, limit - count - 1


# ---------------------------------------------------------------------------
# Redis-backed rate limiter
# ---------------------------------------------------------------------------


class RedisRateLimiter:
    """
    Fixed-window rate limiter backed by Redis ``INCR`` + ``EXPIRE``.

    On any Redis error the limiter transparently falls back to the
    in-memory :class:`SlidingWindowRateLimiter` so that the application
    keeps serving traffic even when Redis is temporarily unreachable.
    """

    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_password: Optional[str] = None,
        redis_db: int = 0,
    ) -> None:
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._redis_password = redis_password
        self._redis_db = redis_db
        self._redis_client: Optional[object] = None
        self._redis_available: bool = True
        self._fallback = SlidingWindowRateLimiter()

    def _get_redis(self):
        """Lazy-connect to Redis on first call."""
        if self._redis_client is None and self._redis_available:
            try:
                import redis as redis_lib

                self._redis_client = redis_lib.Redis(
                    host=self._redis_host,
                    port=self._redis_port,
                    password=self._redis_password or None,
                    db=self._redis_db,
                    socket_connect_timeout=2,
                    socket_timeout=1,
                    decode_responses=True,
                )
                # Test connectivity
                self._redis_client.ping()
                self._redis_available = True
                logger.info(
                    "Rate limiter connected to Redis at %s:%s",
                    self._redis_host,
                    self._redis_port,
                )
            except Exception as exc:
                logger.warning(
                    "Rate limiter Redis unavailable, using in-memory fallback: %s", exc
                )
                self._redis_client = None
                self._redis_available = False
        return self._redis_client

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Check whether a request identified by *key* is within the rate limit.

        Uses Redis ``INCR`` with a fixed-window TTL.  Falls back to the
        in-memory limiter on any Redis error.
        """
        client = self._get_redis()
        if client is None or not self._redis_available:
            return self._fallback.is_allowed(key, limit, window_seconds)

        redis_key = f"ratelimit:{key}"
        try:
            pipe = client.pipeline(transaction=True)
            pipe.incr(redis_key)
            pipe.ttl(redis_key)
            results = pipe.execute()

            current_count = results[0]
            ttl = results[1]

            # First request in this window — set expiry
            if ttl == -1:
                client.expire(redis_key, window_seconds)

            if current_count > limit:
                return False, 0

            remaining = limit - current_count
            return True, remaining

        except Exception as exc:
            logger.warning("Redis rate-limit error, falling back to in-memory: %s", exc)
            self._redis_available = False
            return self._fallback.is_allowed(key, limit, window_seconds)


# ---------------------------------------------------------------------------
# Route-specific configuration
# ---------------------------------------------------------------------------

# (max_requests, window_seconds)
RATE_LIMIT_CONFIG: Dict[str, Tuple[int, int]] = {
    # Authentication endpoints — strict limits to slow brute-force attempts
    "/api/v1/auth/token": (10, 60),
    "/api/v1/auth/login": (10, 60),
    "/api/v1/auth/signup": (5, 60),
    "/api/v1/auth/forgot-password": (5, 60),
    "/api/v1/auth/reset-password": (5, 60),
}

# Default rate limit for all other endpoints
DEFAULT_RATE_LIMIT: Tuple[int, int] = (300, 60)  # 300 req/min

# SDK-facing endpoints: assignment, event tracking and flag evaluation.  One
# server-side SDK or one office NAT can legitimately send thousands of requests
# a minute from a single IP, so these get a much higher per-IP ceiling
# (``settings.SDK_RATE_LIMIT_PER_MINUTE``, default 6000).  Prefix matching is
# needed because flag evaluation carries the flag key in the path.
SDK_PATH_PREFIXES: Tuple[str, ...] = (
    "/api/v1/tracking/",
    "/api/v1/feature-flags/evaluate/",
    "/api/v1/feature-flags/user/",
)
DEFAULT_SDK_RATE_LIMIT_PER_MINUTE = 6000


def resolve_rate_limit(
    path: str, sdk_limit_per_minute: int = DEFAULT_SDK_RATE_LIMIT_PER_MINUTE
) -> Tuple[int, int]:
    """
    Return ``(max_requests, window_seconds)`` for a request path.

    Exact entries in ``RATE_LIMIT_CONFIG`` win, then SDK path prefixes, then
    ``DEFAULT_RATE_LIMIT``.
    """
    exact = RATE_LIMIT_CONFIG.get(path)
    if exact is not None:
        return exact
    if any(path.startswith(prefix) for prefix in SDK_PATH_PREFIXES):
        return (int(sdk_limit_per_minute), 60)
    return DEFAULT_RATE_LIMIT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP, respecting ``X-Forwarded-For`` if present."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces per-IP, per-route rate limits.

    Rate limits are defined in ``RATE_LIMIT_CONFIG`` for sensitive routes
    and fall back to ``DEFAULT_RATE_LIMIT`` for everything else.
    Responses include standard ``X-RateLimit-*`` headers so clients can
    implement back-off without guessing.
    """

    def __init__(self, app: ASGIApp, enabled: bool = True) -> None:
        super().__init__(app)
        self._enabled = enabled
        self._sdk_limit = DEFAULT_SDK_RATE_LIMIT_PER_MINUTE

        if enabled:
            from backend.app.core.config import settings

            self._sdk_limit = int(
                getattr(
                    settings,
                    "SDK_RATE_LIMIT_PER_MINUTE",
                    DEFAULT_SDK_RATE_LIMIT_PER_MINUTE,
                )
            )
            self._limiter: object = RedisRateLimiter(
                redis_host=settings.REDIS_HOST,
                redis_port=int(settings.REDIS_PORT),
                redis_password=settings.REDIS_PASSWORD,
                redis_db=settings.REDIS_DB,
            )
        else:
            self._limiter = SlidingWindowRateLimiter()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        client_ip = _get_client_ip(request)

        # Determine the applicable limit for this path
        limit, window = resolve_rate_limit(path, self._sdk_limit)

        rate_key = f"{client_ip}:{path}"
        allowed, remaining = self._limiter.is_allowed(rate_key, limit, window)

        # Record Prometheus metrics
        try:
            from backend.app.core.metrics import (
                record_rate_limit_hit,
                record_rate_limit_rejection,
            )

            record_rate_limit_hit(path)
            if not allowed:
                record_rate_limit_rejection(path)
        except Exception:
            pass  # Metrics are best-effort

        if not allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={"client_ip": client_ip, "path": path, "limit": limit},
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too Many Requests. Please slow down and retry after a moment.",
                },
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Window": str(window),
                },
            )

        response = await call_next(request)

        # Attach informational rate-limit headers to successful responses
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(window)

        return response
