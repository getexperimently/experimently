"""
Pydantic v2 schemas for compliance audit events.

These schemas support SOC 2 Type 2 and ISO 27001 compliance audit
event creation, retrieval, and listing.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# Re-export enums from the model so that schemas and models share the same definitions.
from backend.app.models.compliance_audit_event import AuditAction, AuditOutcome

__all__ = [
    "AuditAction",
    "AuditOutcome",
    "ComplianceAuditEventCreate",
    "ComplianceAuditEventResponse",
    "ComplianceAuditEventListResponse",
]


class ComplianceAuditEventCreate(BaseModel):
    """Schema for creating a new compliance audit event."""

    # Required fields
    action: AuditAction = Field(..., description="The action that was performed")
    resource_type: str = Field(..., description="Type of resource that was acted upon")
    outcome: AuditOutcome = Field(..., description="Outcome of the action")

    # Actor context (optional — system events may lack actor)
    actor_id: Optional[uuid.UUID] = Field(None, description="UUID of the actor who performed the action")
    actor_ip: Optional[str] = Field(None, max_length=45, description="IP address of the actor")
    actor_user_agent: Optional[str] = Field(None, max_length=512, description="User agent of the actor")

    # Request context
    session_id: Optional[str] = Field(None, max_length=128, description="Session identifier")
    request_id: Optional[str] = Field(None, max_length=128, description="Request identifier for tracing")

    # Resource details
    resource_id: Optional[str] = Field(None, max_length=128, description="ID of the affected resource")

    # Change data
    old_value: Optional[Dict[str, Any]] = Field(None, description="Previous state of the resource (JSON)")
    new_value: Optional[Dict[str, Any]] = Field(None, description="New state of the resource (JSON)")


class ComplianceAuditEventResponse(BaseModel):
    """Schema for a compliance audit event response (read from DB)."""

    model_config = ConfigDict(from_attributes=True)

    # Core identifiers
    id: uuid.UUID = Field(..., description="Unique event identifier")
    timestamp: Optional[datetime] = Field(None, description="When the event occurred")

    # Actor
    actor_id: Optional[uuid.UUID] = Field(None)
    actor_ip: Optional[str] = Field(None)
    actor_user_agent: Optional[str] = Field(None)

    # Request context
    session_id: Optional[str] = Field(None)
    request_id: Optional[str] = Field(None)

    # Action details
    action: AuditAction = Field(..., description="The action that was performed")
    resource_type: str = Field(..., description="Type of resource")
    resource_id: Optional[str] = Field(None)

    # Change data
    old_value: Optional[Dict[str, Any]] = Field(None)
    new_value: Optional[Dict[str, Any]] = Field(None)

    # Outcome and integrity
    outcome: AuditOutcome = Field(..., description="Outcome of the action")
    hmac_signature: Optional[str] = Field(None, description="HMAC-SHA256 signature for tamper detection")

    # Retention
    archived_at: Optional[datetime] = Field(None)
    retention_expires_at: Optional[datetime] = Field(None)


class ComplianceAuditEventListResponse(BaseModel):
    """Paginated list of compliance audit events."""

    items: List[ComplianceAuditEventResponse] = Field(..., description="Audit event records")
    total: int = Field(..., description="Total number of matching records")
    page: int = Field(..., description="Current page number (1-indexed)")
    limit: int = Field(..., description="Maximum number of records per page")
