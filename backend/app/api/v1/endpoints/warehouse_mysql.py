"""
MySQL Warehouse Analytics API (EP-048).

Exposes REST endpoints for running read-only SQL queries and fetching
experiment / feature-flag metrics directly from a MySQL or MariaDB database.

Routes:
    POST   /api/v1/warehouse/mysql/test-connection
    POST   /api/v1/warehouse/mysql/query
    GET    /api/v1/warehouse/mysql/metrics/experiments/{experiment_id}
    GET    /api/v1/warehouse/mysql/metrics/flags/{flag_id}

All endpoints require DEVELOPER or ADMIN role.
Credentials (host, port, database, user, password) are supplied per-request
and are never persisted.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api import deps
from backend.app.models.user import User, UserRole
from backend.app.services.mysql_connector import (
    MySQLConnectionError,
    MySQLConnector,
    MySQLQueryError,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Permission helper
# ---------------------------------------------------------------------------


def _require_developer(user: User) -> None:
    """Raise HTTP 403 if the user does not have DEVELOPER or ADMIN role."""
    if user.is_superuser or user.role in (UserRole.ADMIN, UserRole.DEVELOPER):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="DEVELOPER or ADMIN role required for MySQL operations",
    )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class MySQLConnectionParams(BaseModel):
    """MySQL connection credentials supplied per-request."""

    model_config = ConfigDict(extra="allow")

    host: str = Field(..., description="MySQL server hostname")
    port: int = Field(3306, description="MySQL server port")
    database: str = Field(..., description="MySQL database name")
    user: str = Field(..., description="MySQL username")
    password: str = Field("", description="MySQL password")
    charset: str = Field("utf8mb4", description="Connection charset (default utf8mb4)")
    timeout: int = Field(30, description="Connection / query timeout in seconds")


class TestConnectionRequest(MySQLConnectionParams):
    """Request body for POST /test-connection."""


class TestConnectionResponse(BaseModel):
    """Response from a MySQL connectivity test."""

    status: str  # "connected" | "failed"
    message: Optional[str] = None


class QueryRequest(MySQLConnectionParams):
    """Request body for POST /query."""

    sql: str = Field(..., description="Read-only SQL statement to execute")


class QueryResponse(BaseModel):
    """Response from a MySQL query execution."""

    rows: List[Dict[str, Any]] = []
    row_count: int = 0


class MetricsResponse(BaseModel):
    """Generic metrics response."""

    metrics: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# POST /test-connection
# ---------------------------------------------------------------------------


@router.post(
    "/test-connection",
    response_model=TestConnectionResponse,
    summary="Test MySQL connection",
    description=(
        "Verify that the supplied MySQL credentials can reach the server. "
        "Credentials are NOT persisted. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def test_connection(
    body: TestConnectionRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> TestConnectionResponse:
    """Test whether the MySQL server is reachable."""
    _require_developer(current_user)

    connector = MySQLConnector(
        host=body.host,
        port=body.port,
        database=body.database,
        user=body.user,
        password=body.password,
        charset=body.charset,
        timeout=body.timeout,
    )

    try:
        ok = connector.test_connection()
    except MySQLConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MySQL connection failed: {exc}",
        )

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MySQL connection failed: server unreachable",
        )

    return TestConnectionResponse(status="connected")


# ---------------------------------------------------------------------------
# POST /query
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Execute a read-only MySQL query",
    description=(
        "Execute a read-only SQL query against the specified MySQL database. "
        "DML / DDL statements are rejected with HTTP 400. "
        "Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def execute_query(
    body: QueryRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> QueryResponse:
    """Execute a read-only SQL query and return rows as a list of dicts."""
    _require_developer(current_user)

    connector = MySQLConnector(
        host=body.host,
        port=body.port,
        database=body.database,
        user=body.user,
        password=body.password,
        charset=body.charset,
        timeout=body.timeout,
    )

    try:
        with connector:
            rows = connector.execute_query(body.sql)
    except MySQLQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except MySQLConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MySQL connection failed: {exc}",
        )

    return QueryResponse(rows=rows, row_count=len(rows))


# ---------------------------------------------------------------------------
# GET /metrics/experiments/{experiment_id}
# ---------------------------------------------------------------------------


@router.get(
    "/metrics/experiments/{experiment_id}",
    response_model=MetricsResponse,
    summary="Get experiment metrics from MySQL",
    description=(
        "Fetch per-variant conversion metrics for an experiment directly from "
        "the MySQL database. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def get_experiment_metrics(
    experiment_id: str,
    host: str = Query(..., description="MySQL server hostname"),
    port: int = Query(3306, description="MySQL server port"),
    database: str = Query(..., description="MySQL database name"),
    user: str = Query(..., description="MySQL username"),
    password: str = Query("", description="MySQL password"),
    charset: str = Query("utf8mb4", description="Connection charset"),
    timeout: int = Query(30, description="Query timeout in seconds"),
    current_user: User = Depends(deps.get_current_active_user),
) -> MetricsResponse:
    """Fetch per-variant metrics for the given experiment from MySQL."""
    _require_developer(current_user)

    connector = MySQLConnector(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        charset=charset,
        timeout=timeout,
    )

    try:
        with connector:
            metrics = connector.get_experiment_metrics(experiment_id)
    except MySQLConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MySQL connection failed: {exc}",
        )
    except MySQLQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return MetricsResponse(metrics=metrics)


# ---------------------------------------------------------------------------
# GET /metrics/flags/{flag_id}
# ---------------------------------------------------------------------------


@router.get(
    "/metrics/flags/{flag_id}",
    response_model=MetricsResponse,
    summary="Get feature flag metrics from MySQL",
    description=(
        "Fetch per-group error-rate metrics for a feature flag directly from "
        "the MySQL database. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def get_feature_flag_metrics(
    flag_id: str,
    host: str = Query(..., description="MySQL server hostname"),
    port: int = Query(3306, description="MySQL server port"),
    database: str = Query(..., description="MySQL database name"),
    user: str = Query(..., description="MySQL username"),
    password: str = Query("", description="MySQL password"),
    charset: str = Query("utf8mb4", description="Connection charset"),
    timeout: int = Query(30, description="Query timeout in seconds"),
    current_user: User = Depends(deps.get_current_active_user),
) -> MetricsResponse:
    """Fetch per-group metrics for the given feature flag from MySQL."""
    _require_developer(current_user)

    connector = MySQLConnector(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        charset=charset,
        timeout=timeout,
    )

    try:
        with connector:
            metrics = connector.get_feature_flag_metrics(flag_id)
    except MySQLConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MySQL connection failed: {exc}",
        )
    except MySQLQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return MetricsResponse(metrics=metrics)
