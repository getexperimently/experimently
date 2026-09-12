"""
Mutual Exclusion Group model for preventing conflicting experiment assignments (EP-022).

A mutual exclusion group ensures that a user can only be assigned to one
experiment within the group, preventing cross-contamination of results.
"""

import enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

from backend.app.core.database_config import get_schema_name

from .base import Base, BaseModel


class MutualExclusionGroupStatus(enum.Enum):
    """Status of a mutual exclusion group."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class MutualExclusionGroup(Base, BaseModel):
    """Mutual exclusion group ensuring users see at most one experiment in the group."""

    __tablename__ = "mutual_exclusion_groups"

    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    traffic_allocation = Column(Float, nullable=False, default=1.0)
    status = Column(
        SQLAEnum(MutualExclusionGroupStatus),
        default=MutualExclusionGroupStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    owner = relationship("User")
    experiments = relationship(
        "Experiment",
        back_populates="mutual_exclusion_group",
        foreign_keys="Experiment.mutual_exclusion_group_id",
    )

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(f"{schema_name}_meg_status", "status"),
            CheckConstraint(
                "traffic_allocation >= 0.0 AND traffic_allocation <= 1.0",
                name="check_meg_traffic_allocation",
            ),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<MutualExclusionGroup {self.name}>"
