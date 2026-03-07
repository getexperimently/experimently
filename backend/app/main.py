"""
Main FastAPI application module.

This module initializes the FastAPI application with all necessary middleware,
routers, and configuration.
"""

import logging
import os
import shutil
import time
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Import routers and settings
from backend.app.api.api import api_router
from backend.app.core.config import settings
from backend.app.middleware.security_middleware import SecurityHeadersMiddleware
from backend.app.middleware.rate_limiter import RateLimitMiddleware
from backend.app.middleware.logging_middleware import LoggingMiddleware, RequestLoggingMiddleware
from backend.app.middleware.error_middleware import ErrorMiddleware
from backend.app.middleware.metrics_middleware import MetricsMiddleware
from backend.app.core.scheduler import experiment_scheduler
from backend.app.core.rollout_scheduler import rollout_scheduler
from backend.app.core.metrics_scheduler import metrics_scheduler
from backend.app.core.safety_scheduler import safety_scheduler

# --- EP-013 additions ---
try:
    from backend.app.core.logger import configure_logging, get_logger as _get_struct_logger
    from backend.app.middleware.request_id_middleware import RequestIDMiddleware
    from backend.app.middleware.prometheus_metrics_middleware import PrometheusMetricsMiddleware
    _monitoring_imports_ok = True
except Exception:  # pragma: no cover
    _monitoring_imports_ok = False

# ---------------------------------------------------------------------------
# Structured logging — initialise before anything else so that startup
# log messages are captured in the correct format.
# ---------------------------------------------------------------------------
_json_logs: bool = os.environ.get("APP_ENV", "dev") not in ("dev", "test")
if _monitoring_imports_ok:
    configure_logging(
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        json_logs=_json_logs,
        service_name="experimentation-platform",
    )

# Standard-library logger (used by the existing schedulers etc.)
logger = logging.getLogger(__name__)

# Maximum request body size (1 MB) — prevents DoS via oversized payloads
MAX_REQUEST_BODY_SIZE: int = 1_048_576  # 1 MB

# Create FastAPI application
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version=settings.VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# ---------------------------------------------------------------------------
# Middleware stack
# Starlette applies middleware in *reverse* registration order so the first
# add_middleware call wraps the outermost layer.
# ---------------------------------------------------------------------------

# Add CORS middleware — restrict methods and headers to what the API actually needs
cors_origins = [str(origin) for origin in settings.BACKEND_CORS_ORIGINS]
if not cors_origins:
    # Fall back to dev defaults
    cors_origins = ["http://localhost:3000", "http://localhost:3001"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# NOTE: All custom BaseHTTPMiddleware layers are disabled in local dev
# to avoid stacking deadlock. SecurityHeadersMiddleware is kept as
# it is lightweight and stateless.
app.add_middleware(SecurityHeadersMiddleware)

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)


# ---------------------------------------------------------------------------
# Prometheus /metrics endpoint
# ---------------------------------------------------------------------------

@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> PlainTextResponse:
    """Expose Prometheus metrics in text exposition format.

    This endpoint is intended for scraping by a Prometheus server or a
    local ``curl`` during development.  It should **not** be exposed
    publicly — protect it with a network policy or API gateway rule.
    """
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

        return PlainTextResponse(
            content=generate_latest().decode("utf-8"),
            media_type=CONTENT_TYPE_LATEST,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to generate Prometheus metrics: %s", exc)
        return PlainTextResponse(content="# metrics unavailable\n", status_code=503)


# ---------------------------------------------------------------------------
# Enhanced health-check endpoint
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
async def health_check() -> JSONResponse:
    """Detailed health check including database, Redis, and disk sub-checks.

    Returns HTTP 200 when all checks pass, HTTP 503 otherwise.
    """
    checks: dict = {}
    overall_healthy: bool = True

    # --- Database check ---
    try:
        from backend.app.db.session import SessionLocal

        t0 = time.perf_counter()
        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(text("SELECT 1"))
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            checks["database"] = {"status": "healthy", "latency_ms": latency_ms}
        finally:
            db.close()
    except Exception as exc:
        checks["database"] = {"status": "unhealthy", "error": str(exc)}
        overall_healthy = False

    # --- Redis check ---
    try:
        import redis as redis_lib

        t0 = time.perf_counter()
        r = redis_lib.Redis(
            host=settings.REDIS_HOST,
            port=int(settings.REDIS_PORT),
            password=settings.REDIS_PASSWORD or None,
            socket_connect_timeout=1,
        )
        r.ping()
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        checks["redis"] = {"status": "healthy", "latency_ms": latency_ms}
    except Exception as exc:
        checks["redis"] = {"status": "unhealthy", "error": str(exc)}
        overall_healthy = False

    # --- Disk check ---
    try:
        disk = shutil.disk_usage("/")
        free_gb = round(disk.free / (1024 ** 3), 2)
        checks["disk"] = {
            "status": "healthy" if free_gb > 1.0 else "low",
            "free_gb": free_gb,
        }
        if free_gb <= 1.0:
            overall_healthy = False
    except Exception as exc:
        checks["disk"] = {"status": "unhealthy", "error": str(exc)}
        overall_healthy = False

    body: dict = {
        "status": "healthy" if overall_healthy else "unhealthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Only expose detailed check info and environment in non-production
    if settings.ENVIRONMENT != "prod":
        body["version"] = settings.VERSION
        body["environment"] = settings.ENVIRONMENT
        body["checks"] = checks
    else:
        # In production, only expose aggregate status — no internal details
        body["checks"] = {
            name: {"status": data.get("status", "unknown")}
            for name, data in checks.items()
        }

    return JSONResponse(content=body, status_code=200 if overall_healthy else 503)


# ---------------------------------------------------------------------------
# Startup / shutdown lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event() -> None:
    """Start background tasks on application startup."""
    logger.info("Starting experiment scheduler")
    await experiment_scheduler.start()

    logger.info("Starting rollout scheduler")
    await rollout_scheduler.start()

    logger.info("Starting metrics scheduler")
    await metrics_scheduler.start()

    logger.info("Starting safety monitoring scheduler")
    await safety_scheduler.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Stop background tasks on application shutdown."""
    logger.info("Stopping experiment scheduler")
    await experiment_scheduler.stop()

    logger.info("Stopping rollout scheduler")
    await rollout_scheduler.stop()

    logger.info("Stopping metrics scheduler")
    await metrics_scheduler.stop()

    logger.info("Stopping safety monitoring scheduler")
    await safety_scheduler.stop()


# ---------------------------------------------------------------------------
# OpenAPI documentation routes
# ---------------------------------------------------------------------------

@app.get("/api/v1/openapi.json", include_in_schema=False)
async def get_openapi_schema():
    return get_openapi(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.PROJECT_DESCRIPTION,
        routes=app.routes,
    )


@app.get("/api/v1/docs", include_in_schema=False)
async def get_swagger_docs():
    return get_swagger_ui_html(
        openapi_url="/api/v1/openapi.json",
        title=f"{settings.PROJECT_NAME} - Swagger UI",
    )


@app.get("/api/v1/redoc", include_in_schema=False)
async def get_redoc_docs():
    return get_redoc_html(
        openapi_url="/api/v1/openapi.json",
        title=f"{settings.PROJECT_NAME} - ReDoc",
    )


# This allows other modules to import the application instance
# without creating circular imports
__all__ = ["app"]
