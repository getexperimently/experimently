"""
SOC 2 Type 2 / ISO 27001 compliance audit event model.
Separate from the existing AuditLog — this table is append-only,
HMAC-signed, and has configurable retention.
"""

import enum
import uuid

from sqlalchemy import Column, DateTime, Index, String
from sqlalchemy import Enum as SQLAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.app.core.database_config import get_schema_name
from backend.app.models.base import Base


class AuditAction(str, enum.Enum):
    """Actions that can be recorded in the compliance audit log."""

    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILED = "LOGIN_FAILED"
    ROLE_GRANT = "ROLE_GRANT"
    ROLE_REVOKE = "ROLE_REVOKE"
    KEY_CREATE = "KEY_CREATE"
    KEY_REVOKE = "KEY_REVOKE"
    EXPORT = "EXPORT"
    REPORT_GENERATED = "REPORT_GENERATED"


class AuditOutcome(str, enum.Enum):
    """Outcome of the audited action."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"


class ComplianceAuditEvent(Base):
    """
    Compliance-grade audit event record.

    This table is append-only, HMAC-signed for tamper-evidence, and supports
    configurable retention schedules for SOC 2 Type 2 and ISO 27001 compliance.
    """

    __tablename__ = "audit_events_v2"
    __table_args__ = (
        Index("ix_audit_events_v2_timestamp", "timestamp"),
        Index("ix_audit_events_v2_actor_id", "actor_id"),
        Index("ix_audit_events_v2_resource", "resource_type", "resource_id"),
        {"schema": get_schema_name()},
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Actor (who performed the action)
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    actor_ip = Column(String(45), nullable=True)
    actor_user_agent = Column(String(512), nullable=True)

    # Request context
    session_id = Column(String(128), nullable=True)
    request_id = Column(String(128), nullable=True)

    # Action details
    action = Column(SQLAEnum(AuditAction, name="audit_action_type"), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=True)

    # Change data
    old_value = Column(JSONB, nullable=True)
    new_value = Column(JSONB, nullable=True)

    # Outcome
    outcome = Column(SQLAEnum(AuditOutcome, name="audit_outcome_type"), nullable=False)

    # Integrity
    hmac_signature = Column(String(64), nullable=True)

    # Retention and archival
    archived_at = Column(DateTime(timezone=True), nullable=True)
    retention_expires_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ComplianceAuditEvent(id={self.id}, "
            f"action={self.action}, "
            f"resource_type={self.resource_type}, "
            f"outcome={self.outcome}, "
            f"timestamp={self.timestamp})>"
        )
