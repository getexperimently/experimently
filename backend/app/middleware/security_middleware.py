# backend/app/middleware/security_middleware.py
"""
Security middleware for adding security headers to responses.

This middleware adds various security headers to HTTP responses to enhance
application security and prevent common web vulnerabilities.
"""

import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to responses."""

    def __init__(self, app: ASGIApp):
        """Initialize the middleware."""
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to the response."""
        # Process the request and get the response
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking — API-only service, so DENY is appropriate
        response.headers["X-Frame-Options"] = "DENY"

        # XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer policy — only send origin when cross-origin
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy — restrict browser features; API doesn't need any
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), "
            "payment=(), usb=(), magnetometer=()"
        )

        # Remove server identification headers to reduce fingerprinting surface
        # MutableHeaders does not support .pop(); use conditional delete instead.
        if "server" in response.headers:
            del response.headers["server"]
        if "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]

        # HSTS — only in non-dev environments to avoid local HTTPS issues.
        # "dev" is the legacy spelling of "development" (see core/config.py).
        if settings.ENVIRONMENT not in ("development", "dev"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # Content Security Policy — strict for an API-only service
        # No scripts, no styles, no frames; only direct API responses
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )

        return response
