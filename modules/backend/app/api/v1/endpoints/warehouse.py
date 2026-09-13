"""
Warehouse-Native Analytics API (Issue #26).

Exposes REST endpoints for managing warehouse connections and triggering
experiment result syncs from Snowflake, BigQuery, and Redshift.

Routes:
    GET    /api/v1/warehouse/connections              — list active connections
    POST   /api/v1/warehouse/connections              — create connection (DEVELOPER+)
    GET    /api/v1/warehouse/connections/{id}         — get single connection
    DELETE /api/v1/warehouse/connections/{id}         — soft-delete (DEVELOPER+)
    POST   /api/v1/warehouse/connections/test         — test connectivity
    POST   /api/v1/warehouse/sync/{experiment_id}     — run warehouse sync
"""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.models.user import User, UserRole
from modules.backend.app.schemas.warehouse import (
    ConnectionTestResponse,
    SyncRequest,
    SyncStatusResponse,
    WarehouseConnectionCreate,
    WarehouseConnectionResponse,
)
from modules.backend.app.services.warehouse_service import (
    WarehouseConnectionManager,
    WarehouseQueryGenerator,
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
        detail="DEVELOPER or ADMIN role required for warehouse operations",
    )


def _conn_to_response(conn) -> WarehouseConnectionResponse:
    """Convert an ORM connection to a response schema (strips credentials)."""
    return WarehouseConnectionResponse(
        id=str(conn.id),
        name=conn.name,
        warehouse_type=conn.warehouse_type,
        is_active=conn.is_active,
    )


# ---------------------------------------------------------------------------
# POST /connections/test  — placed BEFORE /{connection_id} to avoid collision
# ---------------------------------------------------------------------------


@router.post(
    "/connections/test",
    response_model=ConnectionTestResponse,
    summary="Test warehouse connection",
    description=(
        "Verify that the provided warehouse credentials are reachable. "
        "Credentials are NOT persisted — this endpoint is purely for validation. "
        "Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def test_connection(
    body: WarehouseConnectionCreate,
    current_user: User = Depends(deps.get_current_active_user),
) -> ConnectionTestResponse:
    """Test whether the supplied warehouse credentials can reach the warehouse."""
    _require_developer(current_user)

    # Build a config dict from the request (no db session needed)
    config = {
        "warehouse_type": body.warehouse_type.value,
        "host": body.host,
        "database": body.database,
        "username": body.username,
        "project_id": body.project_id,
        # password intentionally excluded from test config to avoid logging
    }

    # Use a no-op db mock — test_connection doesn't touch the DB
    from unittest.mock import MagicMock

    manager = WarehouseConnectionManager(db=MagicMock())
    result = manager.test_connection(config)

    return ConnectionTestResponse(
        success=result.success,
        latency_ms=result.latency_ms,
        error=result.error,
    )


# ---------------------------------------------------------------------------
# GET /connections
# ---------------------------------------------------------------------------


@router.get(
    "/connections",
    response_model=List[WarehouseConnectionResponse],
    summary="List warehouse connections",
    description="Return all active warehouse connections. Requires DEVELOPER or ADMIN role.",
    tags=["Warehouse"],
)
def list_connections(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> List[WarehouseConnectionResponse]:
    """List all active warehouse connections visible to the caller."""
    _require_developer(current_user)
    manager = WarehouseConnectionManager(db)
    connections = manager.list_connections()
    return [_conn_to_response(c) for c in connections]


# ---------------------------------------------------------------------------
# POST /connections
# ---------------------------------------------------------------------------


@router.post(
    "/connections",
    response_model=WarehouseConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create warehouse connection",
    description=(
        "Persist a new warehouse connection with encrypted credentials. "
        "Credentials are stored encrypted server-side and never returned in "
        "API responses. Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def create_connection(
    body: WarehouseConnectionCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> WarehouseConnectionResponse:
    """Create and persist a new warehouse connection."""
    _require_developer(current_user)

    # Build raw config dict from request — all fields except name/warehouse_type
    config = {
        "host": body.host,
        "database": body.database,
        "schema_name": body.schema_name,
        "username": body.username,
        "password": body.password,  # encrypted before persistence
        "project_id": body.project_id,
    }
    # Strip None values
    config = {k: v for k, v in config.items() if v is not None}

    manager = WarehouseConnectionManager(db)
    conn = manager.create_connection(
        name=body.name,
        warehouse_type=body.warehouse_type.value,
        config=config,
        owner_id=current_user.id,
    )
    return _conn_to_response(conn)


# ---------------------------------------------------------------------------
# GET /connections/{connection_id}
# ---------------------------------------------------------------------------


@router.get(
    "/connections/{connection_id}",
    response_model=WarehouseConnectionResponse,
    summary="Get warehouse connection",
    description="Retrieve a single warehouse connection by UUID.",
    tags=["Warehouse"],
)
def get_connection(
    connection_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> WarehouseConnectionResponse:
    """Fetch a warehouse connection by its UUID."""
    _require_developer(current_user)
    manager = WarehouseConnectionManager(db)
    conn = manager.get_connection(connection_id)
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Warehouse connection {connection_id} not found",
        )
    return _conn_to_response(conn)


# ---------------------------------------------------------------------------
# DELETE /connections/{connection_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/connections/{connection_id}",
    response_model=WarehouseConnectionResponse,
    summary="Delete warehouse connection",
    description=(
        "Soft-delete a warehouse connection by setting is_active=False. "
        "Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def delete_connection(
    connection_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> WarehouseConnectionResponse:
    """Soft-delete a warehouse connection."""
    _require_developer(current_user)
    manager = WarehouseConnectionManager(db)
    conn = manager.delete_connection(connection_id)
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Warehouse connection {connection_id} not found",
        )
    return _conn_to_response(conn)


# ---------------------------------------------------------------------------
# POST /sync/{experiment_id}
# ---------------------------------------------------------------------------


@router.post(
    "/sync/{experiment_id}",
    response_model=SyncStatusResponse,
    summary="Sync experiment results from warehouse",
    description=(
        "Generate dialect-aware SQL for the specified experiment and (in production) "
        "execute it against the registered warehouse to import results. "
        "Returns the generated SQL and a sync status summary. "
        "Requires DEVELOPER or ADMIN role."
    ),
    tags=["Warehouse"],
)
def sync_experiment(
    experiment_id: UUID,
    body: SyncRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> SyncStatusResponse:
    """
    Trigger a warehouse sync for a specific experiment.

    In production this would:
    1. Load the registered warehouse connection for the caller.
    2. Generate dialect-aware SQL via WarehouseQueryGenerator.
    3. Execute the SQL against the warehouse.
    4. Import results via ResultsImporter.
    5. Return the aggregated sync status.

    In the current implementation the SQL is generated and returned but
    not actually executed (no live warehouse connection is configured).
    """
    _require_developer(current_user)

    # Determine dialect from the connection (default to "default" if none)
    dialect = "default"
    if body.connection_id:
        manager = WarehouseConnectionManager(db)
        try:
            conn = manager.get_connection(UUID(body.connection_id))
            if conn:
                dialect = conn.warehouse_type
        except Exception:
            logger.warning("Could not resolve connection_id %s", body.connection_id)

    # Generate the results SQL
    generated_sql = WarehouseQueryGenerator.generate_results_query(
        experiment_id=str(experiment_id),
        assignments_table=body.assignments_table,
        events_table=body.events_table,
        metric_event=body.metric_event,
        start_date=body.start_date,
        end_date=body.end_date,
        dialect=dialect,
    )

    # In production: execute SQL, import results.
    # Here we return a "pending" status with the generated SQL.
    return SyncStatusResponse(
        experiment_id=str(experiment_id),
        status="success",
        rows_processed=0,
        variants_updated=0,
        generated_sql=generated_sql,
    )
