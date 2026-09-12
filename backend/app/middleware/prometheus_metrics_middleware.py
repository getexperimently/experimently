"""
FastAPI/Starlette middleware that automatically records Prometheus metrics
for every HTTP request.

Endpoint paths are normalised — UUIDs and numeric IDs are replaced with
``{id}`` — so that high-cardinality path segments do not explode the label
space of the Prometheus counter and histogram.
"""

import re
import time
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.app.core.metrics import record_request

# Matches UUID v4 segments in URL paths
_UUID_PATTERN: re.Pattern = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

# Matches purely-numeric path segments (e.g. /users/42)
_NUMERIC_PATTERN: re.Pattern = re.compile(r"/\d+")


def normalize_path(path: str) -> str:
    """Replace dynamic path segments with ``{id}`` for stable metric labels.

    Two categories of dynamic segments are replaced:

    * UUID v4 (e.g. ``550e8400-e29b-41d4-a716-446655440000``)
    * Pure numeric IDs (e.g. ``42``)
    """
    path = _UUID_PATTERN.sub("/{id}", path)
    path = _NUMERIC_PATTERN.sub("/{id}", path)
    return path


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that records Prometheus HTTP metrics for all requests.

    Uses :func:`backend.app.core.metrics.record_request` to increment the
    ``http_requests_total`` counter and observe the
    ``http_request_duration_seconds`` histogram.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start_time: float = time.time()
        response: Response = await call_next(request)
        duration: float = time.time() - start_time

        endpoint: str = normalize_path(request.url.path)
        record_request(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
            duration=duration,
        )
        return response
