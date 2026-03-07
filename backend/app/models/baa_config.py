"""
Business Associate Agreement (BAA) configuration model for EP-050: HIPAA Compliance.

A BAA is a legally required contract between a HIPAA covered entity and
a business associate (like this platform) that specifies how PHI may be used.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declared_attr

from backend.app.models.base import Base, BaseModel
from backend.app.core.database_config import get_schema_name


class BAAConfig(Base, BaseModel):
    """
    Business Associate Agreement (BAA) configuration.

    Tracks signed BAAs between the platform (as business associate)
    and covered entities, including which PHI categories are covered
    and the geographic data residency region.
    """

    __tablename__ = "baa_configs"

    # Covered entity information
    organization_name = Column(String(255), nullable=False)
    signatory_name = Column(String(255), nullable=False)
    signatory_email = Column(String(255), nullable=False, index=True)

    # Agreement period
    effective_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=True)

    # Data residency: where PHI is stored/processed
    data_residency_region = Column(
        String(50),
        nullable=False,
        comment="AWS region where PHI data resides, e.g. us-east-1",
    )

    # Which PHI categories are covered by this BAA
    phi_categories = Column(
        JSONB,
        nullable=False,
        default=list,
        comment="List of PHI categories: demographics, diagnosis, treatment, billing",
    )

    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Integrity: SHA-256 hash of the signed BAA document
    signed_document_hash = Column(
        String(64),
        nullable=False,
        comment="SHA-256 hex digest of the signed BAA document for integrity verification",
    )

    # Audit trail: who created this entry
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
        nullable=True,
    )

    @declared_attr
    def __table_args__(cls):
        return ({"schema": get_schema_name()},)

    @property
    def is_expired(self) -> bool:
        """Return True if the BAA has passed its expiry date."""
        if self.expiry_date is None:
            return False
        return self.expiry_date < date.today()

    def __repr__(self) -> str:
        return (
            f"<BAAConfig id={self.id} "
            f"org={self.organization_name!r} "
            f"active={self.is_active}>"
        )
