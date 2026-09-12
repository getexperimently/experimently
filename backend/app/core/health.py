"""
Health probes and the Prometheus scrape endpoint.

Routes (all unauthenticated, none in the OpenAPI schema):

``GET /health/live``
    Liveness: the process is up and the event loop answers. Never touches the
    database or Redis, so a dependency outage does not make orchestrators
    restart healthy processes. Used by the container ``HEALTHCHECK``.

``GET /health/ready``
    Readiness: PostgreSQL must answer ``SELECT 1``. Redis is checked and
    reported but only fails readiness when ``REDIS_REQUIRED=true`` (the
    application degrades gracefully without Redis: rate limiting falls back to
    memory, caching is skipped). Disk space below 1 GB is reported as ``low``.
    Returns 200 when ready, 503 otherwise.

``GET /health``
    Alias of ``/health/ready`` kept for the existing ALB/ECS/CDK wiring.

``GET /metrics``
    Prometheus text exposition. When ``METRICS_TOKEN`` is set the request must
    carry it (``Authorization: Bearer <token>`` or ``?token=<token>``);
    when it is not set the endpoint is open in development/test only and
    returns 403 elsewhere. ``METRICS_ENABLED=false`` disables it (404).

All switches (``METRICS_TOKEN``, ``METRICS_ENABLED``, ``REDIS_REQUIRED``,
``ENVIRONMENT``) are read from ``settings`` (``backend/app/core/config.py``),
which is the single source of truth for the environment.
"""

from __future__ import annotations

import hmac
import logging
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()



# ---------------------------------------------------------------------------
# Settings helpers (tolerant of the pre-/post-canonicalisation config)
# ---------------------------------------------------------------------------


def _safe_error(exc: BaseException) -> str:
    """First line of the error without credentials (never echo a password)."""
    text = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    if "password" in text.lower():
        return f"{exc.__class__.__name__}: authentication failed"
    return text[:200]


# Environment and feature switches come from ``settings`` only: pydantic-
# settings already reads the process environment, and ``config.py`` is the
# single place that canonicalises ENVIRONMENT.


def environment_name() -> str:
    """Canonical environment name (``development``, ``test``, ``staging``, ``production``)."""
    return str(settings.ENVIRONMENT)


def is_production() -> bool:
    return bool(settings.is_production)


def is_development_or_test() -> bool:
    return bool(settings.is_development or settings.is_test)


def metrics_token() -> Optional[str]:
    token = settings.METRICS_TOKEN
    return str(token) if token else None


def metrics_enabled() -> bool:
    return bool(settings.METRICS_ENABLED)


def redis_required() -> bool:
    return bool(settings.REDIS_REQUIRED)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_database() -> Dict[str, Any]:
    """``SELECT 1`` on a session from the application pool."""
    try:
        from sqlalchemy import text

        from backend.app.db.session import SessionLocal

        t0 = time.perf_counter()
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return {"status": "healthy", "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
    except Exception as exc:
        return {"status": "unhealthy", "error": _safe_error(exc)}


def check_redis() -> Dict[str, Any]:
    """``PING`` Redis using the connection settings."""
    try:
        import redis as redis_lib

        t0 = time.perf_counter()
        client = redis_lib.Redis(
            host=str(settings.REDIS_HOST),
            port=int(settings.REDIS_PORT),
            password=settings.REDIS_PASSWORD or None,
            db=int(settings.REDIS_DB or 0),
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        try:
            client.ping()
        finally:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort
                pass
        return {"status": "healthy", "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
    except Exception as exc:
        return {"status": "unhealthy", "error": _safe_error(exc)}


def check_disk(path: str = "/") -> Dict[str, Any]:
    """Free space on *path*; ``low`` below 1 GB."""
    try:
        usage = shutil.disk_usage(path)
        free_gb = round(usage.free / (1024**3), 2)
        return {"status": "healthy" if free_gb > 1.0 else "low", "free_gb": free_gb}
    except Exception as exc:
        return {"status": "unhealthy", "error": _safe_error(exc)}


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def liveness_payload() -> Dict[str, Any]:
    return {
        "status": "alive",
        "timestamp": _timestamp(),
        "version": str(getattr(settings, "VERSION", "")),
    }


def readiness_payload() -> tuple[Dict[str, Any], int]:
    """Run the readiness checks. Returns ``(body, http_status)``."""
    checks: Dict[str, Dict[str, Any]] = {
        "database": check_database(),
        "redis": check_redis(),
        "disk": check_disk(),
    }

    ready = checks["database"]["status"] == "healthy"
    if checks["redis"]["status"] != "healthy" and redis_required():
        ready = False
    if checks["disk"]["status"] == "unhealthy":
        ready = False

    body: Dict[str, Any] = {
        "status": "healthy" if ready else "unhealthy",
        "timestamp": _timestamp(),
    }

    if not is_production():
        # Details (errors, latencies, environment) only outside production.
        body["version"] = str(settings.VERSION)
        body["environment"] = environment_name()
        body["checks"] = checks
    else:
        body["checks"] = {
            name: {"status": data.get("status", "unknown")} for name, data in checks.items()
        }

    return body, (200 if ready else 503)


# ---------------------------------------------------------------------------
# /metrics access control
# ---------------------------------------------------------------------------


def _presented_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.query_params.get("token") or None


def metrics_access(request: Request) -> Optional[JSONResponse]:
    """Return an error response when the scrape is not allowed, else ``None``."""
    if not metrics_enabled():
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    expected = metrics_token()
    if expected:
        presented = _presented_token(request)
        if not presented or not hmac.compare_digest(presented, expected):
            return JSONResponse(
                {"detail": "Invalid or missing metrics token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None

    if is_development_or_test():
        return None

    return JSONResponse(
        {"detail": "The /metrics endpoint requires METRICS_TOKEN outside development"},
        status_code=403,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health/live", include_in_schema=False)
async def health_live() -> JSONResponse:
    """Liveness probe: process up. Never touches external dependencies."""
    return JSONResponse(content=liveness_payload(), status_code=200)


@router.get("/health/ready", include_in_schema=False)
async def health_ready() -> JSONResponse:
    """Readiness probe: database (and Redis when required) reachable."""
    body, status_code = readiness_payload()
    return JSONResponse(content=body, status_code=status_code)


@router.get("/health", include_in_schema=False)
async def health_check() -> JSONResponse:
    """Compatibility alias of ``/health/ready``."""
    body, status_code = readiness_payload()
    return JSONResponse(content=body, status_code=status_code)


@router.get("/metrics", include_in_schema=False, response_model=None)
async def prometheus_metrics(request: Request) -> Response:
    """Prometheus text exposition, guarded by ``METRICS_TOKEN`` (see module docstring)."""
    denied = metrics_access(request)
    if denied is not None:
        return denied
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return PlainTextResponse(
            content=generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to generate Prometheus metrics: %s", exc)
        return PlainTextResponse(content="# metrics unavailable\n", status_code=503)


__all__ = [
    "router",
    "liveness_payload",
    "readiness_payload",
    "metrics_access",
    "check_database",
    "check_redis",
    "check_disk",
    "is_production",
    "is_development_or_test",
    "environment_name",
]
