"""
Pydantic schemas for Warehouse-Native Analytics (Issue #26).

IMPORTANT: The ``WarehouseConnectionResponse`` schema deliberately omits all
credential fields (password, private_key, encrypted_credentials).  Credentials
are stored encrypted and must never be returned in API responses.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WarehouseType(str, Enum):
    """Supported customer data warehouse platforms."""

    SNOWFLAKE = "snowflake"
    BIGQUERY = "bigquery"
    REDSHIFT = "redshift"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class WarehouseConnectionCreate(BaseModel):
    """
    Payload for creating a new warehouse connection.

    Credential fields (``password``) are accepted on input but are never
    returned in any response — they are stored encrypted server-side.
    """

    name: str = Field(
        ..., min_length=1, max_length=200, description="Human-readable connection name"
    )
    warehouse_type: WarehouseType = Field(..., description="Target warehouse platform")
    host: Optional[str] = Field(
        None, description="Warehouse hostname (Snowflake / Redshift)"
    )
    database: Optional[str] = Field(None, description="Default database / catalog name")
    schema_name: Optional[str] = Field(
        None, description="Default schema inside the database"
    )
    username: Optional[str] = Field(None, description="Service-account or IAM username")
    password: Optional[str] = Field(
        None, description="Password (write-only; never returned)"
    )
    project_id: Optional[str] = Field(
        None, description="GCP project ID (BigQuery only)"
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class WarehouseConnectionResponse(BaseModel):
    """
    Public representation of a warehouse connection.

    Credential fields are intentionally excluded to prevent leakage.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    warehouse_type: str
    is_active: bool

    # Note: password, private_key, encrypted_credentials intentionally absent


class SyncRequest(BaseModel):
    """
    Request body for triggering a warehouse sync for a specific experiment.

    The service will use the provided table names to generate dialect-aware SQL
    and execute it against the registered warehouse connection.
    """

    assignments_table: str = Field(
        ...,
        description="Warehouse table containing user→variant assignments",
    )
    events_table: str = Field(
        ...,
        description="Warehouse table containing conversion / metric events",
    )
    metric_event: str = Field(
        ...,
        description="Event type string that counts as a conversion (e.g. 'purchase')",
    )
    start_date: Optional[str] = Field(
        None,
        description="ISO-8601 start date filter for events (UTC)",
    )
    end_date: Optional[str] = Field(
        None,
        description="ISO-8601 end date filter for events (UTC)",
    )
    connection_id: Optional[str] = Field(
        None,
        description="UUID of the warehouse connection to use (uses first active if omitted)",
    )


class SyncStatusResponse(BaseModel):
    """Response from a warehouse sync operation."""

    model_config = ConfigDict(from_attributes=True)

    experiment_id: str
    status: str = Field(
        ...,
        description="One of: pending | running | success | failed",
    )
    rows_processed: int = 0
    variants_updated: int = 0
    error: Optional[str] = None
    generated_sql: Optional[str] = Field(
        None,
        description="The SQL that was (or would be) executed against the warehouse",
    )


class ConnectionTestResponse(BaseModel):
    """Result of testing whether a warehouse connection is reachable."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    latency_ms: float
    error: Optional[str] = None
