"""
PHI Audit Log model for EP-050: HIPAA Compliance.

Records every access to Protected Health Information (PHI)
to satisfy HIPAA's minimum necessary and audit requirements.
HIPAA mandates a 6-year retention period for audit records.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declared_attr

from backend.app.core.database_config import get_schema_name
from backend.app.models.base import Base, BaseModel


class PHIAuditLog(Base, BaseModel):
    """
    PHI (Protected Health Information) access audit log.

    Every read, write, delete, or export of PHI must be recorded here.
    Retention is 6 years per HIPAA §164.530(j).
    """

    __tablename__ = "phi_audit_logs"

    # Who accessed PHI
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # What was accessed
    resource_type = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Type of resource accessed: experiment, feature_flag, user_data",
    )
    resource_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="UUID of the specific resource accessed",
    )

    # What action was performed
    action = Column(
        String(20),
        nullable=False,
        index=True,
        comment="Action performed: READ, WRITE, DELETE, EXPORT",
    )

    # Which PHI fields were touched (HIPAA minimum-necessary principle)
    phi_fields_accessed = Column(
        JSONB,
        nullable=False,
        default=list,
        comment="List of PHI field names that were accessed",
    )

    # HIPAA minimum-necessary: why was this access needed?
    purpose = Column(
        String(50),
        nullable=False,
        comment="Purpose of PHI access: treatment, operations, research",
    )

    # Network context for breach investigation
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # Timestamp of the access event (separate from created_at for clarity)
    timestamp = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    # HIPAA requires 6-year retention
    retention_years = Column(Integer, default=6, nullable=False)

    @declared_attr
    def __table_args__(cls):
        return ({"schema": get_schema_name()},)

    def __repr__(self) -> str:
        return (
            f"<PHIAuditLog id={self.id} "
            f"action={self.action} "
            f"resource={self.resource_type}/{self.resource_id}>"
        )
