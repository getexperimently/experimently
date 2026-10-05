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

# The strict policy every API response carries, except the two below.
API_CSP = "default-src 'none'; frame-ancestors 'none'"

# The two API reference pages (main.py's get_swagger_docs and get_redoc_docs).
# Matched exactly: "/api/v1/docs/", "/api/v1/docsx" and "/api/v1/redoc/x" keep
# API_CSP.
DOCS_PATHS = frozenset({"/api/v1/docs", "/api/v1/redoc"})

# The sha256 of the one inline <script> FastAPI's get_swagger_ui_html writes
# (it is the same for any title). A FastAPI upgrade that changes that template
# changes the hash; backend/tests/unit/api/test_docs_page_csp.py recomputes it
# from the served page and fails until this constant is updated.
SWAGGER_INIT_SCRIPT_SHA256 = "sha256-Udn0n0xqWFJphI3snuYNtGBFJIs1xE50HEzK4gkIzho="

# What the two pages load: Swagger UI's and ReDoc's script and stylesheet from
# cdn.jsdelivr.net, ReDoc's Google Fonts stylesheet and font files, FastAPI's
# favicon, ReDoc's footer logo (an image its script requests from
# cdn.redoc.ly), the OpenAPI document from this origin, and ReDoc's blob:
# worker. No inline script other than the hashed one, and no eval.
DOCS_CSP = (
    "default-src 'none'; "
    f"script-src https://cdn.jsdelivr.net '{SWAGGER_INIT_SCRIPT_SHA256}'; "
    "style-src https://cdn.jsdelivr.net https://fonts.googleapis.com 'unsafe-inline'; "
    "font-src https://fonts.gstatic.com data:; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "connect-src 'self'; "
    "worker-src blob:; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


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

        # Content-Security-Policy: strict for an API-only service, no
        # scripts, no styles, no frames. The two API reference pages, matched
        # by exact path, get DOCS_CSP so that their assets load.
        if request.url.path in DOCS_PATHS:
            response.headers["Content-Security-Policy"] = DOCS_CSP
        else:
            response.headers["Content-Security-Policy"] = API_CSP

        return response
