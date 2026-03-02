"""
Global Holdout model for excluding a percentage of users from all experiments (EP-022).

A global holdout reserves a fixed percentage of users who will never be
assigned to any experiment, providing a clean baseline for measuring the
cumulative effect of running experiments.
"""

import uuid

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    Text,
    ForeignKey,
    Index,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declared_attr

from .base import Base, BaseModel
from backend.app.core.database_config import get_schema_name


class GlobalHoldout(Base, BaseModel):
    """Global holdout configuration reserving users from all experiments."""

    __tablename__ = "global_holdouts"

    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    holdout_percentage = Column(Integer, nullable=False, default=10)
    is_active = Column(Boolean, nullable=False, default=False)
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    owner = relationship("User")

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(f"{schema_name}_holdout_active", "is_active"),
            CheckConstraint(
                "holdout_percentage >= 1 AND holdout_percentage <= 20",
                name="check_holdout_percentage_range",
            ),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<GlobalHoldout {self.name} ({self.holdout_percentage}%)>"
