"""
Databricks Warehouse Analytics API (EP-041).

Exposes REST endpoints for running read-only SQL queries and fetching
experiment / feature-flag metrics directly from a Databricks SQL warehouse.

Routes:
    POST   /api/v1/warehouse/databricks/test-connection
    POST   /api/v1/warehouse/databricks/query
    GET    /api/v1/warehouse/databricks/metrics/experiments/{experiment_id}
    GET    /api/v1/warehouse/databricks/metrics/flags/{flag_id}

All endpoints require DEVELOPER or ADMIN role.
Credentials (host, http_path, access_token) are supplied per-request and
are never persisted.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api import deps
from backend.app.models.user import User, UserRole
from backend.app.services.databricks_connector import (
    DatabricksConnector,
    DatabricksConnectionError,
    DatabricksQueryError,
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
        detail="DEVELOPER or ADMIN role required for Databricks operations",
    )


# ---------------------------------------------------------------------------
# Shared connection-parameter fields (inline in each request body)
# ---------------------------------------------------------------------------


class DatabricksConnectionParams(BaseModel):
    """Databricks connection credentials supplied per-request."""

    model_config = ConfigDict(extra="allow")

    host: str = Field(..., description="Databricks workspace hostname")
    http_path: str = Field(..., description="SQL warehouse HTTP path")
    access_token: str = Field(..., description="Personal access token")
    catalog: str = Field("main", description="Unity Catalog catalog name")
    schema_name: str = Field("default", alias="schema", description="Schema name")
    timeout_seconds: int = Field(30, description="Query timeout in seconds")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TestConnectionRequest(DatabricksConnectionParams):
    """Request body for POST /test-connection."""


class TestConnectionResponse(BaseModel):
    """Response from a Databricks connectivity test."""

    status: str  # "connected" | "failed"
    message: Optional[str] = None


class QueryRequest(DatabricksConnectionParams):
    """Request body for POST /query."""

    sql: str = Field(..., description="Read-only SQL statement to execute")


class QueryResponse(BaseModel):
    """Response from a Databricks query execution."""

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
    summary="Test Databricks connection",
    description=(
        "Verify that the supplied Databricks credentials can reach the SQL warehouse. "
        "Credentials are NOT persisted. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def test_connection(
    body: TestConnectionRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> TestConnectionResponse:
    """Test whether the Databricks SQL warehouse is reachable."""
    _require_developer(current_user)

    connector = DatabricksConnector(
        host=body.host,
        http_path=body.http_path,
        access_token=body.access_token,
        catalog=body.catalog,
        schema=body.schema_name,
        timeout_seconds=body.timeout_seconds,
    )

    try:
        ok = connector.test_connection()
    except DatabricksConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Databricks connection failed: {exc}",
        )

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Databricks connection failed: warehouse unreachable",
        )

    return TestConnectionResponse(status="connected")


# ---------------------------------------------------------------------------
# POST /query
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Execute a read-only Databricks query",
    description=(
        "Execute a read-only SQL query against the specified Databricks SQL warehouse. "
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

    connector = DatabricksConnector(
        host=body.host,
        http_path=body.http_path,
        access_token=body.access_token,
        catalog=body.catalog,
        schema=body.schema_name,
        timeout_seconds=body.timeout_seconds,
    )

    try:
        with connector:
            rows = connector.execute_query(body.sql)
    except DatabricksQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except DatabricksConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Databricks connection failed: {exc}",
        )

    return QueryResponse(rows=rows, row_count=len(rows))


# ---------------------------------------------------------------------------
# GET /metrics/experiments/{experiment_id}
# ---------------------------------------------------------------------------


@router.get(
    "/metrics/experiments/{experiment_id}",
    response_model=MetricsResponse,
    summary="Get experiment metrics from Databricks",
    description=(
        "Fetch per-variant conversion metrics for an experiment directly from "
        "the Databricks SQL warehouse. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def get_experiment_metrics(
    experiment_id: str,
    host: str = Query(..., description="Databricks workspace hostname"),
    http_path: str = Query(..., description="SQL warehouse HTTP path"),
    access_token: str = Query(..., description="Personal access token"),
    catalog: str = Query("main", description="Unity Catalog catalog name"),
    schema: str = Query("default", description="Schema name"),
    timeout_seconds: int = Query(30, description="Query timeout in seconds"),
    current_user: User = Depends(deps.get_current_active_user),
) -> MetricsResponse:
    """Fetch per-variant metrics for the given experiment from Databricks."""
    _require_developer(current_user)

    connector = DatabricksConnector(
        host=host,
        http_path=http_path,
        access_token=access_token,
        catalog=catalog,
        schema=schema,
        timeout_seconds=timeout_seconds,
    )

    try:
        with connector:
            metrics = connector.get_experiment_metrics(experiment_id)
    except DatabricksConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Databricks connection failed: {exc}",
        )
    except DatabricksQueryError as exc:
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
    summary="Get feature flag metrics from Databricks",
    description=(
        "Fetch per-group error-rate metrics for a feature flag directly from "
        "the Databricks SQL warehouse. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def get_feature_flag_metrics(
    flag_id: str,
    host: str = Query(..., description="Databricks workspace hostname"),
    http_path: str = Query(..., description="SQL warehouse HTTP path"),
    access_token: str = Query(..., description="Personal access token"),
    catalog: str = Query("main", description="Unity Catalog catalog name"),
    schema: str = Query("default", description="Schema name"),
    timeout_seconds: int = Query(30, description="Query timeout in seconds"),
    current_user: User = Depends(deps.get_current_active_user),
) -> MetricsResponse:
    """Fetch per-group metrics for the given feature flag from Databricks."""
    _require_developer(current_user)

    connector = DatabricksConnector(
        host=host,
        http_path=http_path,
        access_token=access_token,
        catalog=catalog,
        schema=schema,
        timeout_seconds=timeout_seconds,
    )

    try:
        with connector:
            metrics = connector.get_feature_flag_metrics(flag_id)
    except DatabricksConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Databricks connection failed: {exc}",
        )
    except DatabricksQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return MetricsResponse(metrics=metrics)
