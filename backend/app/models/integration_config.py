"""IntegrationConfig model — stores encrypted third-party integration credentials."""

import enum
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.app.core.database_config import get_schema_name
from backend.app.models.base import Base


class IntegrationType(str, enum.Enum):
    SALESFORCE = "salesforce"
    JIRA = "jira"
    GITHUB = "github"


class IntegrationConfig(Base):
    __tablename__ = "integration_configs"
    __table_args__ = (
        Index("ix_integration_configs_type", "integration_type"),
        UniqueConstraint("integration_type", name="uq_integration_configs_type"),
        {"schema": get_schema_name()},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_type = Column(SQLAEnum(IntegrationType), nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    encrypted_config = Column(JSONB, nullable=True)  # In production, encrypted at rest
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(1024), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
