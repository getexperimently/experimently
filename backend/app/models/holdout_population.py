"""Who a global holdout covered: one row per user first seen while it was active (#445).

``AssignmentService.assign_user`` writes a row the first time a user reaches
its new-user path while a measurable holdout is active, whatever the answer
was (held out, assigned, or refused by mutual exclusion or targeting): every
user seen goes in their arm, so the two arms are comparable.

``first_seen_at`` uses ``UTCTimestampString``, the type of
``events.created_at``, deliberately: the results query compares the two
columns directly, and Postgres refuses ``varchar >= timestamp``.
"""

from sqlalchemy import Boolean, Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declared_attr

from backend.app.core.database_config import get_schema_name
from backend.app.models.event import UTCTimestampString

from .base import Base


class HoldoutPopulation(Base):
    """One user's membership of one holdout, recorded when first seen."""

    __tablename__ = "holdout_population"

    holdout_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.global_holdouts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(String(255), primary_key=True)
    in_holdout = Column(Boolean, nullable=False)
    first_seen_at = Column(UTCTimestampString, nullable=False)

    @declared_attr
    def __table_args__(cls):
        return ({"schema": get_schema_name()},)

    def __repr__(self):
        return f"<HoldoutPopulation holdout={self.holdout_id} in_holdout={self.in_holdout}>"
