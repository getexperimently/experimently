"""
Main FastAPI application module.

This module initializes the FastAPI application with all necessary middleware,
routers, and configuration.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

# Import routers and settings
from backend.app.api.api import api_router, tags_metadata
from backend.app.core.bandit_scheduler import bandit_scheduler_runner
from backend.app.core.config import settings
from backend.app.core.health import is_development_or_test
from backend.app.core.health import router as health_router
from backend.app.core.metrics_scheduler import metrics_scheduler
from backend.app.core.rollout_scheduler import rollout_scheduler
from backend.app.core.safety_scheduler import safety_scheduler
from backend.app.core.scheduler import experiment_scheduler
from backend.app.middleware.rate_limiter import RateLimitMiddleware
from backend.app.middleware.security_middleware import SecurityHeadersMiddleware
from backend.app.modules_loader import abort_if_modules_broken, load_modules

# --- EP-013 additions ---
try:
    from backend.app.core.logger import configure_logging, log_format_from_env
    from backend.app.middleware.prometheus_metrics_middleware import (
        PrometheusMetricsMiddleware,
    )
    from backend.app.middleware.request_id_middleware import RequestIDMiddleware

    _monitoring_imports_ok = True
except Exception:  # pragma: no cover
    _monitoring_imports_ok = False

# ---------------------------------------------------------------------------
# Structured logging — initialise before anything else so that startup
# log messages are captured in the correct format.
#
# LOG_FORMAT=json  -> every line (structlog, stdlib, uvicorn) is one JSON object
# LOG_FORMAT=console -> coloured console output
# unset            -> console in development/test, JSON everywhere else
# ---------------------------------------------------------------------------
_log_format: str = "console"
if _monitoring_imports_ok:
    _log_format = str(
        getattr(settings, "LOG_FORMAT", "") or ""
    ).lower() or log_format_from_env(
        default="console" if is_development_or_test() else "json"
    )
_json_logs: bool = _log_format == "json"
if _monitoring_imports_ok:
    configure_logging(
        log_level=str(settings.LOG_LEVEL or "INFO").upper(),
        json_logs=_json_logs,
        service_name="experimentation-platform",
    )

# Standard-library logger (used by the existing schedulers etc.)
logger = logging.getLogger(__name__)

# The seam: install the modules' hooks (routers, models, tags, audit signer).
# Importing backend.app.api.api above already triggered this while it built
# the v1 router; the call is repeated here (it is idempotent) so that main.py
# — the process entry point — names the seam explicitly.  A core build has no
# `modules` package: nothing loads and every hook keeps its default.
if load_modules():
    logger.info("Modules hooks installed")
# Nothing to load is the core profile and starts cleanly.  A package that *was*
# found and did not install -- the registration raised, or its routers would
# not mount -- is a full-profile deployment that would serve less than it was
# deployed as (module routes 404, and on a failed registration compliance
# events unsigned), so outside development/test this raises and the process
# never starts.  Unconditional, because a routers-only failure leaves
# `load_modules()` True: it is `modules_failure()` that decides, not the
# return value.
abort_if_modules_broken()

if settings.dev_auth_bypass_active:
    logger.warning(
        "DEV_AUTH_BYPASS is active (ENVIRONMENT=%s): every request is served as the "
        "synthetic dev-admin superuser without credentials. Never expose this instance.",
        settings.ENVIRONMENT,
    )

# Maximum request body size (1 MB) — prevents DoS via oversized payloads
MAX_REQUEST_BODY_SIZE: int = 1_048_576  # 1 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage background scheduler lifecycle for the FastAPI app.

    Under the test profile the schedulers are not started: a ``TestClient``
    used as a context manager would otherwise run real ticks against the test
    database in the middle of unrelated tests (they patch the same service
    functions, and the ticks open and drop connections). Scheduler behaviour
    is covered directly in ``backend/tests/unit/core/test_scheduler_*``.
    """
    if settings.is_test:
        logger.info("Test environment: background schedulers are not started")
        yield
        return

    logger.info("Starting experiment scheduler")
    await experiment_scheduler.start()

    logger.info("Starting rollout scheduler")
    await rollout_scheduler.start()

    logger.info("Starting metrics scheduler")
    await metrics_scheduler.start()

    logger.info("Starting safety monitoring scheduler")
    await safety_scheduler.start()

    logger.info("Starting bandit scheduler")
    await bandit_scheduler_runner.start()

    yield

    logger.info("Stopping experiment scheduler")
    await experiment_scheduler.stop()

    logger.info("Stopping rollout scheduler")
    await rollout_scheduler.stop()

    logger.info("Stopping metrics scheduler")
    await metrics_scheduler.stop()

    logger.info("Stopping safety monitoring scheduler")
    await safety_scheduler.stop()

    logger.info("Stopping bandit scheduler")
    await bandit_scheduler_runner.stop()


# Create FastAPI application
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version=settings.VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    # Core tag descriptions plus whatever the modules' registration
    # contributed through hooks.register_tags(); computed at router build, so
    # it is read here after `api_router` has been imported above.
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware stack
# Starlette applies middleware in *reverse* registration order so the first
# add_middleware call wraps the outermost layer.
# ---------------------------------------------------------------------------

# Add CORS middleware — restrict methods and headers to what the API actually needs
cors_origins = [str(origin) for origin in settings.BACKEND_CORS_ORIGINS]
if not cors_origins:
    # Plain comma-separated form (CORS_ORIGINS=http://a,http://b), see .env.example
    cors_origins = [origin for origin in settings.CORS_ORIGINS if origin]
if not cors_origins:
    # Fall back to dev defaults
    cors_origins = [
        "http://localhost:3100",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3200",  # ShopLab demo storefront
        "http://localhost:3300",  # StreamPulse demo app
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# Security headers — lightweight and stateless
app.add_middleware(SecurityHeadersMiddleware)

# Rate limiter — disabled during tests to avoid interfering with test assertions
_rate_limit_enabled = not settings.is_test
app.add_middleware(RateLimitMiddleware, enabled=_rate_limit_enabled)

# Prometheus latency / request-count middleware (EP-013)
if _monitoring_imports_ok:
    app.add_middleware(PrometheusMetricsMiddleware)
    # X-Request-ID on every response + request_id/path/method bound into the
    # log context. Registered last so it is the outermost layer and every
    # log line from the middlewares above already carries the id.
    app.add_middleware(RequestIDMiddleware)

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Health probes (/health/live, /health/ready, /health) and Prometheus /metrics
app.include_router(health_router)


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
