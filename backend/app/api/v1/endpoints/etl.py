"""
ETL & Glue Job REST endpoints (P3-A).

Provides endpoints for managing AWS Glue ETL jobs, Athena queries,
S3 partition registration, and Glue crawler management.

Endpoints:
    POST /api/v1/etl/jobs/run              — trigger ETL job (ADMIN/DEVELOPER)
    GET  /api/v1/etl/jobs/{run_id}/status  — get job run status (any authenticated user)
    POST /api/v1/etl/query                 — run Athena SQL query (ANALYST+)
    POST /api/v1/etl/partitions/add        — add S3 partitions to Glue catalog (ADMIN)
    GET  /api/v1/etl/crawler/status        — get crawler state (any authenticated user)
    POST /api/v1/etl/crawler/run           — trigger crawler (ADMIN)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api import deps
from backend.app.models.user import User, UserRole
from backend.app.schemas.etl import (
    AthenaQueryRequest,
    AthenaQueryResult,
    ETLJobRequest,
    ETLJobResponse,
    ETLJobType,
    GlueCrawlerStatus,
    PartitionInfo,
)
from backend.app.services.etl_service import ETLService

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Dependency — shared ETLService instance (override-able in tests)
# ---------------------------------------------------------------------------

_etl_service: Optional[ETLService] = None


def get_etl_service() -> ETLService:
    """
    Dependency that returns a singleton ETLService.

    Can be overridden in tests via app.dependency_overrides.
    """
    global _etl_service
    if _etl_service is None:
        _etl_service = ETLService()
    return _etl_service


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


def _require_admin_or_developer(current_user: User) -> None:
    """Raise 403 if the user is not ADMIN or DEVELOPER."""
    allowed = {UserRole.ADMIN, UserRole.DEVELOPER}
    if current_user.role not in allowed and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only ADMIN or DEVELOPER users can perform this action.",
        )


def _require_analyst_or_above(current_user: User) -> None:
    """Raise 403 if the user is a VIEWER (below ANALYST)."""
    if current_user.role == UserRole.VIEWER and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only ANALYST, DEVELOPER, or ADMIN users can perform this action.",
        )


def _require_admin(current_user: User) -> None:
    """Raise 403 if the user is not ADMIN."""
    if current_user.role != UserRole.ADMIN and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only ADMIN users can perform this action.",
        )


# ---------------------------------------------------------------------------
# POST /jobs/run — trigger ETL job
# ---------------------------------------------------------------------------


@router.post(
    "/jobs/run",
    response_model=ETLJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger an ETL job run",
    description=(
        "Start a Glue ETL job for transforming raw S3 events to Parquet, "
        "aggregating metrics, or generating daily summaries. "
        "Requires ADMIN or DEVELOPER role."
    ),
    responses={
        202: {"description": "Job started successfully"},
        403: {"description": "Insufficient permissions"},
        422: {"description": "Invalid request parameters"},
        500: {"description": "Failed to start Glue job"},
    },
)
def run_etl_job(
    request: ETLJobRequest,
    current_user: User = Depends(deps.get_current_active_user),
    svc: ETLService = Depends(get_etl_service),
) -> ETLJobResponse:
    """Trigger an AWS Glue ETL job run."""
    _require_admin_or_developer(current_user)

    logger.info(
        f"User {current_user.username} triggering ETL job "
        f"type={request.job_type} date={request.date}"
    )
    return svc.run_etl_job(request)


# ---------------------------------------------------------------------------
# GET /jobs/{run_id}/status — get job status
# ---------------------------------------------------------------------------


@router.get(
    "/jobs/{run_id}/status",
    response_model=ETLJobResponse,
    summary="Get ETL job run status",
    description="Retrieve the current status of a Glue job run. Any authenticated user can read.",
    responses={
        200: {"description": "Job status returned"},
        404: {"description": "Job run not found"},
    },
)
def get_job_status(
    run_id: str,
    job_name: str = Query(..., description="Glue job name"),
    job_type: Optional[ETLJobType] = Query(None, description="ETL job type (optional)"),
    current_user: User = Depends(deps.get_current_active_user),
    svc: ETLService = Depends(get_etl_service),
) -> ETLJobResponse:
    """Return the current status of a Glue job run."""
    return svc.get_job_status(
        job_run_id=run_id,
        job_name=job_name,
        job_type=job_type,
    )


# ---------------------------------------------------------------------------
# POST /query — run Athena SQL query
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    response_model=AthenaQueryResult,
    summary="Run an Athena SQL query",
    description=(
        "Execute a SQL query against the Glue/Athena data catalog. "
        "Requires ANALYST, DEVELOPER, or ADMIN role."
    ),
    responses={
        200: {"description": "Query results returned"},
        400: {"description": "Query failed or was cancelled"},
        403: {"description": "Insufficient permissions"},
        422: {"description": "Invalid SQL"},
        500: {"description": "Failed to execute query"},
    },
)
def run_athena_query(
    request: AthenaQueryRequest,
    current_user: User = Depends(deps.get_current_active_user),
    svc: ETLService = Depends(get_etl_service),
) -> AthenaQueryResult:
    """Execute an Athena SQL query and return results."""
    _require_analyst_or_above(current_user)

    logger.info(
        f"User {current_user.username} running Athena query on db={request.database}"
    )
    return svc.run_athena_query(request)


# ---------------------------------------------------------------------------
# POST /partitions/add — add Glue catalog partitions
# ---------------------------------------------------------------------------


@router.post(
    "/partitions/add",
    response_model=list[PartitionInfo],
    status_code=status.HTTP_201_CREATED,
    summary="Add S3 partitions to the Glue catalog",
    description=(
        "Register 24 hourly Hive-style partitions for a given date. "
        "Requires ADMIN role."
    ),
    responses={
        201: {"description": "Partitions registered"},
        403: {"description": "Insufficient permissions"},
        500: {"description": "Failed to create partitions"},
    },
)
def add_partitions(
    database: str = Query(..., description="Glue database name"),
    table: str = Query(..., description="Glue table name"),
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    current_user: User = Depends(deps.get_current_active_user),
    svc: ETLService = Depends(get_etl_service),
) -> list[PartitionInfo]:
    """Register hourly S3 partitions in the Glue catalog for a given date."""
    _require_admin(current_user)

    logger.info(
        f"User {current_user.username} adding partitions for "
        f"{database}.{table} date={date}"
    )
    return svc.add_partitions(database=database, table=table, date=date)


# ---------------------------------------------------------------------------
# GET /crawler/status — get crawler state
# ---------------------------------------------------------------------------


@router.get(
    "/crawler/status",
    response_model=GlueCrawlerStatus,
    summary="Get Glue crawler status",
    description="Return the current state of the Glue crawler. Any authenticated user can read.",
    responses={
        200: {"description": "Crawler status returned"},
        404: {"description": "Crawler not found"},
    },
)
def get_crawler_status(
    crawler_name: str = Query(
        None,
        description="Glue crawler name (defaults to settings.GLUE_CRAWLER_NAME)",
    ),
    current_user: User = Depends(deps.get_current_active_user),
    svc: ETLService = Depends(get_etl_service),
) -> GlueCrawlerStatus:
    """Return the current state of the Glue crawler."""
    from backend.app.core.config import settings as cfg

    name = crawler_name or cfg.GLUE_CRAWLER_NAME
    return svc.get_crawler_status(crawler_name=name)


# ---------------------------------------------------------------------------
# POST /crawler/run — trigger crawler
# ---------------------------------------------------------------------------


@router.post(
    "/crawler/run",
    response_model=GlueCrawlerStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger the Glue crawler",
    description=(
        "Start the Glue crawler to discover new partitions and update the catalog. "
        "Requires ADMIN role."
    ),
    responses={
        202: {"description": "Crawler started"},
        403: {"description": "Insufficient permissions"},
        409: {"description": "Crawler already running"},
        500: {"description": "Failed to start crawler"},
    },
)
def run_crawler(
    crawler_name: str = Query(
        None,
        description="Glue crawler name (defaults to settings.GLUE_CRAWLER_NAME)",
    ),
    current_user: User = Depends(deps.get_current_active_user),
    svc: ETLService = Depends(get_etl_service),
) -> GlueCrawlerStatus:
    """Start the Glue crawler and return its status."""
    _require_admin(current_user)

    from backend.app.core.config import settings as cfg

    name = crawler_name or cfg.GLUE_CRAWLER_NAME

    logger.info(f"User {current_user.username} triggering Glue crawler '{name}'")
    return svc.run_crawler(crawler_name=name)
