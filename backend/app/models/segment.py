# Segmentation models
import enum

from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy import Enum as SQLAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

from backend.app.core.database_config import get_schema_name

from .base import Base, BaseModel


class SegmentStatus(enum.Enum):
    """Segment lifecycle status."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class Segment(Base, BaseModel):
    """User segment model for targeting rules."""

    __tablename__ = "segments"

    name = Column(String(128), nullable=False)
    description = Column(Text)
    status = Column(
        SQLAEnum(SegmentStatus),
        default=SegmentStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
    )
    rules = Column(JSONB)  # Rules for segment membership

    # Relationships
    owner = relationship("User", back_populates="segments")
    raw_metrics = relationship(
        "RawMetric",
        back_populates="segment",
        cascade="all, delete-orphan",
    )
    aggregated_metrics = relationship(
        "AggregatedMetric",
        back_populates="segment",
        cascade="all, delete-orphan",
    )

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return ({"schema": schema_name},)

    def __repr__(self):
        return f"<Segment {self.id}: {self.name}>"
