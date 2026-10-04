# Segmentation models
import enum

from sqlalchemy import CheckConstraint, Column, ForeignKey, String, Text, text
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


class SegmentKind(str, enum.Enum):
    """What decides a segment's members, fixed when it is created (#440)."""

    #: Users whose attributes match ``rules``.
    RULES = "rules"
    #: Users whose ``user_id`` is stored in ``segment_members``.
    ID_LIST = "id_list"


#: The check on ``segments.kind``: the same name and SQL as migration
#: ``37dcb2969766``.
SEGMENT_KIND_CHECK = "ck_segments_kind"
SEGMENT_KIND_CHECK_SQL = "kind IN ('rules', 'id_list')"


class Segment(Base, BaseModel):
    """User segment model for targeting rules."""

    __tablename__ = "segments"

    name = Column(String(128), nullable=False)
    # The server default is what the migration gives existing rows, and what
    # lets an older image that does not know the column keep inserting.
    kind = Column(
        String(16),
        nullable=False,
        default=SegmentKind.RULES.value,
        server_default=text("'rules'"),
    )
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
        return (
            CheckConstraint(SEGMENT_KIND_CHECK_SQL, name=SEGMENT_KIND_CHECK),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<Segment {self.id}: {self.name}>"


class SegmentMember(Base):
    """One user id in an id-list segment (#440).

    Plain ``Base``: no per-row id and no timestamps. The primary key
    ``(segment_id, member_id)`` serves the membership lookup and the count.
    """

    __tablename__ = "segment_members"

    segment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.segments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    member_id = Column(String(255), primary_key=True)

    @declared_attr
    def __table_args__(cls):
        return ({"schema": get_schema_name()},)

    def __repr__(self):
        return f"<SegmentMember segment={self.segment_id}>"
