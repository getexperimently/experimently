"""
Middleware that attaches a unique request ID to every HTTP request.

The request ID is:

* Taken from the incoming ``X-Request-ID`` header when present (useful for
  distributed tracing where an upstream service or load balancer already set
  an ID).
* Otherwise generated fresh as a UUID4.

The ID is:

* Added to the response ``X-Request-ID`` header so callers can correlate
  logs and traces.
* Bound to the structured-logging context so every log line emitted during
  the request automatically carries ``request_id``, ``path``, and ``method``.
"""

import uuid
from typing import Callable, Awaitable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.app.core.logger import bind_log_context


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that ensures every request has a unique ID."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id: str = request.headers.get(
            "X-Request-ID", str(uuid.uuid4())
        )

        # Bind to the current async context so all log lines in this request
        # automatically include request_id, path, and method.
        bind_log_context(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
