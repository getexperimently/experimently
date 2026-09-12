"""
Spec / Pydantic schemas for advanced toggle operations (P1-B).
Defines the API contract for bulk operations and enhanced audit logging.
"""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BulkToggleAction(str, Enum):
    ENABLE = "enable"
    DISABLE = "disable"
    ARCHIVE = "archive"


class BulkToggleRequest(BaseModel):
    """Request body for bulk feature flag toggle operations."""

    flag_ids: List[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of feature flag IDs to toggle (max 100)",
    )
    action: BulkToggleAction
    reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Reason for bulk operation (stored in audit log)",
    )


class BulkToggleResult(BaseModel):
    """Result for a single flag in a bulk operation."""

    flag_id: str
    flag_key: str
    success: bool
    error: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None


class BulkToggleResponse(BaseModel):
    """Response for bulk toggle operation."""

    total: int
    succeeded: int
    failed: int
    results: List[BulkToggleResult]
    audit_log_ids: List[str]  # IDs of created audit log entries


class AuditDiff(BaseModel):
    """Structured diff between old and new state of an entity."""

    field: str
    old_value: Any
    new_value: Any
    changed: bool


class DetailedAuditLogResponse(BaseModel):
    """Extended audit log entry with structured diff and metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime
    user_id: Optional[str]
    user_email: str
    action_type: str
    entity_type: str
    entity_id: str
    entity_name: str
    old_value: Optional[str]
    new_value: Optional[str]
    diff: Optional[List[AuditDiff]] = None  # Parsed structured diff
    reason: Optional[str]
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditLogStreamEvent(BaseModel):
    """Single event in the audit log SSE stream."""

    event_type: str = "audit_log"
    data: DetailedAuditLogResponse
    sequence: int


class FlagChangeHistoryResponse(BaseModel):
    """Complete change history for a single feature flag."""

    flag_id: str
    flag_key: str
    flag_name: str
    total_changes: int
    history: List[DetailedAuditLogResponse]
