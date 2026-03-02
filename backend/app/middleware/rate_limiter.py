"""
Rate limiting middleware for the Experimentation Platform.

This module provides in-memory rate limiting using a sliding-window
token-bucket algorithm without external dependencies. It is suitable
for single-process deployments (development / single-instance staging).
For multi-instance production use, replace with a Redis-backed limiter
such as slowapi with redis storage.
"""

import time
import threading
import logging
from collections import defaultdict, deque
from typing import Callable, Dict, Tuple
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """
    Thread-safe sliding-window rate limiter backed by in-memory deques.

    Each (key, route) pair gets an independent deque of timestamps for
    requests in the current window.  Requests older than `window_seconds`
    are evicted on each check.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> deque of (timestamp, route) hit times
        self._windows: Dict[str, deque] = defaultdict(deque)

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Check whether a new request from `key` is within the allowed rate.

        Args:
            key: Unique identifier for the client (e.g. IP + route).
            limit: Maximum number of requests permitted in `window_seconds`.
            window_seconds: The duration of the sliding window.

        Returns:
            Tuple of (allowed: bool, remaining: int) — how many requests
            are still available in the current window.
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


# Singleton limiter used by the middleware
_limiter = SlidingWindowRateLimiter()


# Route-specific rate limit configuration: (limit, window_seconds)
RATE_LIMIT_CONFIG: Dict[str, Tuple[int, int]] = {
    # Authentication endpoints — strict limits to slow brute-force attempts
    "/api/v1/auth/token": (10, 60),        # 10 req/min
    "/api/v1/auth/signup": (5, 60),        # 5 req/min
    "/api/v1/auth/forgot-password": (5, 60),  # 5 req/min
    "/api/v1/auth/reset-password": (5, 60),   # 5 req/min
    # Tracking endpoints — higher limits for legitimate SDK traffic
    "/api/v1/tracking/assign": (1000, 60),  # 1000 req/min
    "/api/v1/tracking/track": (5000, 60),   # 5000 req/min
}

# Default rate limit for all other endpoints
DEFAULT_RATE_LIMIT: Tuple[int, int] = (300, 60)  # 300 req/min


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For if present."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the leftmost (client) IP from the chain
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces per-IP, per-route rate limits.

    Rate limits are defined in RATE_LIMIT_CONFIG for sensitive routes
    and fall back to DEFAULT_RATE_LIMIT for everything else.
    Responses include standard RateLimit-* headers so clients can
    implement back-off without guessing.
    """

    def __init__(self, app: ASGIApp, enabled: bool = True) -> None:
        super().__init__(app)
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        client_ip = _get_client_ip(request)

        # Determine the applicable limit for this path
        limit, window = RATE_LIMIT_CONFIG.get(path, DEFAULT_RATE_LIMIT)

        rate_key = f"{client_ip}:{path}"
        allowed, remaining = _limiter.is_allowed(rate_key, limit, window)

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
