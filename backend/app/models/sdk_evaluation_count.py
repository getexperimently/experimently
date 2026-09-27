"""
Per-minute counters behind ``POST /api/v1/tracking/evaluations``.

A server-side SDK that evaluates flags locally reports how many evaluations it
made, per flag, and the route turns each report into a ``flag_evaluation``
``RawMetric`` row -- the denominator safety monitoring divides reported errors
by.  The accepted count is capped, so that a runaway or misconfigured reporter
cannot inflate the denominator without limit:

* :class:`SdkEvaluationKeyCount` -- per API key, flag and minute;
* :class:`SdkEvaluationFlagCount` -- per flag and minute, across every key.

Both are updated by an atomic ``INSERT ... ON CONFLICT DO UPDATE ...
RETURNING`` (see ``backend/app/services/sdk_evaluation_service.py``), so the
caps hold across API tasks without a read-then-write race.  A row is only
useful during its own minute; the route prunes rows a few minutes old.
"""

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from backend.app.core.database_config import get_schema_name
from backend.app.models.base import Base


class SdkEvaluationKeyCount(Base):
    """Evaluations reported by one API key for one flag in one minute."""

    __tablename__ = "sdk_evaluation_key_counts"

    api_key_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.api_keys.id", ondelete="CASCADE"),
        primary_key=True,
    )
    flag_key = Column(String(100), primary_key=True)
    #: The minute the reports were received in (server clock, naive UTC).
    minute = Column(DateTime, primary_key=True, index=True)
    #: Every count this key reported for the flag in the minute, before the cap.
    requested = Column(BigInteger, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<SdkEvaluationKeyCount {self.api_key_id} {self.flag_key} "
            f"{self.minute} requested={self.requested}>"
        )


class SdkEvaluationFlagCount(Base):
    """Evaluations accepted for one flag in one minute, summed over every key."""

    __tablename__ = "sdk_evaluation_flag_counts"

    flag_key = Column(String(100), primary_key=True)
    #: The minute the reports were received in (server clock, naive UTC).
    minute = Column(DateTime, primary_key=True, index=True)
    #: What the per-key caps let through for the flag in the minute, before the
    #: per-flag cap.
    offered = Column(BigInteger, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<SdkEvaluationFlagCount {self.flag_key} {self.minute} "
            f"offered={self.offered}>"
        )
