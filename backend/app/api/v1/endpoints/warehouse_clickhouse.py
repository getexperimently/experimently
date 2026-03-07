"""
ClickHouse Warehouse Analytics API (EP-048).

Exposes REST endpoints for running read-only SQL queries and fetching
experiment / feature-flag metrics directly from a ClickHouse database.

Routes:
    POST   /api/v1/warehouse/clickhouse/test-connection
    POST   /api/v1/warehouse/clickhouse/query
    GET    /api/v1/warehouse/clickhouse/metrics/experiments/{experiment_id}
    GET    /api/v1/warehouse/clickhouse/metrics/flags/{flag_id}

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
from backend.app.services.clickhouse_connector import (
    ClickHouseConnector,
    ClickHouseConnectionError,
    ClickHouseQueryError,
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
        detail="DEVELOPER or ADMIN role required for ClickHouse operations",
    )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ClickHouseConnectionParams(BaseModel):
    """ClickHouse connection credentials supplied per-request."""

    model_config = ConfigDict(extra="allow")

    host: str = Field(..., description="ClickHouse server hostname")
    port: int = Field(8123, description="ClickHouse HTTP port (8123 for HTTP, 8443 for HTTPS)")
    database: str = Field("default", description="ClickHouse database name")
    user: str = Field("default", description="ClickHouse username")
    password: str = Field("", description="ClickHouse password")
    secure: bool = Field(False, description="Use HTTPS (TLS)")
    timeout: int = Field(30, description="Query timeout in seconds")


class TestConnectionRequest(ClickHouseConnectionParams):
    """Request body for POST /test-connection."""


class TestConnectionResponse(BaseModel):
    """Response from a ClickHouse connectivity test."""

    status: str  # "connected" | "failed"
    message: Optional[str] = None


class QueryRequest(ClickHouseConnectionParams):
    """Request body for POST /query."""

    sql: str = Field(..., description="Read-only SQL statement to execute")


class QueryResponse(BaseModel):
    """Response from a ClickHouse query execution."""

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
    summary="Test ClickHouse connection",
    description=(
        "Verify that the supplied ClickHouse credentials can reach the server. "
        "Credentials are NOT persisted. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def test_connection(
    body: TestConnectionRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> TestConnectionResponse:
    """Test whether the ClickHouse server is reachable."""
    _require_developer(current_user)

    connector = ClickHouseConnector(
        host=body.host,
        port=body.port,
        database=body.database,
        user=body.user,
        password=body.password,
        secure=body.secure,
        timeout=body.timeout,
    )

    try:
        ok = connector.test_connection()
    except ClickHouseConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ClickHouse connection failed: {exc}",
        )

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ClickHouse connection failed: server unreachable",
        )

    return TestConnectionResponse(status="connected")


# ---------------------------------------------------------------------------
# POST /query
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Execute a read-only ClickHouse query",
    description=(
        "Execute a read-only SQL query against the specified ClickHouse server. "
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

    connector = ClickHouseConnector(
        host=body.host,
        port=body.port,
        database=body.database,
        user=body.user,
        password=body.password,
        secure=body.secure,
        timeout=body.timeout,
    )

    try:
        with connector:
            rows = connector.execute_query(body.sql)
    except ClickHouseQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except ClickHouseConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ClickHouse connection failed: {exc}",
        )

    return QueryResponse(rows=rows, row_count=len(rows))


# ---------------------------------------------------------------------------
# GET /metrics/experiments/{experiment_id}
# ---------------------------------------------------------------------------


@router.get(
    "/metrics/experiments/{experiment_id}",
    response_model=MetricsResponse,
    summary="Get experiment metrics from ClickHouse",
    description=(
        "Fetch per-variant conversion metrics for an experiment directly from "
        "the ClickHouse server. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def get_experiment_metrics(
    experiment_id: str,
    host: str = Query(..., description="ClickHouse server hostname"),
    port: int = Query(8123, description="ClickHouse HTTP port"),
    database: str = Query("default", description="Database name"),
    user: str = Query("default", description="ClickHouse username"),
    password: str = Query("", description="ClickHouse password"),
    secure: bool = Query(False, description="Use HTTPS"),
    timeout: int = Query(30, description="Query timeout in seconds"),
    current_user: User = Depends(deps.get_current_active_user),
) -> MetricsResponse:
    """Fetch per-variant metrics for the given experiment from ClickHouse."""
    _require_developer(current_user)

    connector = ClickHouseConnector(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        secure=secure,
        timeout=timeout,
    )

    try:
        with connector:
            metrics = connector.get_experiment_metrics(experiment_id)
    except ClickHouseConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ClickHouse connection failed: {exc}",
        )
    except ClickHouseQueryError as exc:
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
    summary="Get feature flag metrics from ClickHouse",
    description=(
        "Fetch per-group error-rate metrics for a feature flag directly from "
        "the ClickHouse server. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def get_feature_flag_metrics(
    flag_id: str,
    host: str = Query(..., description="ClickHouse server hostname"),
    port: int = Query(8123, description="ClickHouse HTTP port"),
    database: str = Query("default", description="Database name"),
    user: str = Query("default", description="ClickHouse username"),
    password: str = Query("", description="ClickHouse password"),
    secure: bool = Query(False, description="Use HTTPS"),
    timeout: int = Query(30, description="Query timeout in seconds"),
    current_user: User = Depends(deps.get_current_active_user),
) -> MetricsResponse:
    """Fetch per-group metrics for the given feature flag from ClickHouse."""
    _require_developer(current_user)

    connector = ClickHouseConnector(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        secure=secure,
        timeout=timeout,
    )

    try:
        with connector:
            metrics = connector.get_feature_flag_metrics(flag_id)
    except ClickHouseConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ClickHouse connection failed: {exc}",
        )
    except ClickHouseQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return MetricsResponse(metrics=metrics)
