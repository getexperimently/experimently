"""One use of a warehouse connection: an analysis run or a source preview (#312).

Every query the platform sends to a customer's warehouse on someone's behalf
is recorded here before it is sent, which is what the per-connection daily
limit counts (``modules.backend.app.services.warehouse_run_accounting``):

* ``kind = 'analysis'`` -- the runs of an experiment's analysis;
* ``kind = 'preview'`` -- a source preview, which queries the warehouse too.

A run moves ``queued -> running -> succeeded | failed``; a failed run always
carries one of the fixed error codes.  At most one run per connection is
queued or running at a time (``uq_warehouse_runs_one_in_flight``).

A run is a record of what happened, so it outlives what it used: deleting
the connection leaves ``connection_id`` NULL and the run keeps its own copy
of the connection's name and type.  Deleting the experiment deletes its runs.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declared_attr

from backend.app.core.database_config import get_schema_name
from backend.app.models.base import Base, BaseModel

RUN_KINDS: tuple[str, ...] = ("analysis", "preview")
RUN_STATUSES: tuple[str, ...] = ("queued", "running", "succeeded", "failed")
#: The statuses of a run that has not finished.
IN_FLIGHT_STATUSES: tuple[str, ...] = ("queued", "running")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class WarehouseAnalysisRun(Base, BaseModel):
    """A warehouse query job: an experiment analysis, or a source preview."""

    __tablename__ = "warehouse_analysis_runs"

    kind = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{get_schema_name()}.warehouse_connections.id", ondelete="SET NULL"
        ),
        nullable=True,
    )
    #: The connection as it was when the run was requested.
    connection_name = Column(String(200), nullable=False)
    warehouse_type = Column(String(20), nullable=False)
    experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.experiments.id", ondelete="CASCADE"),
        nullable=True,
    )
    requested_by = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: What was asked for: the source ids, the variant map.  Never SQL text.
    request = Column(JSONB, nullable=False, default=dict)
    #: The resolved analysis window, in UTC.
    window_start = Column(DateTime(timezone=True), nullable=True)
    window_end = Column(DateTime(timezone=True), nullable=True)
    #: The statements sent, each with its sha256.
    statements = Column(JSONB, nullable=True)
    #: The aggregates the warehouse returned, exactly as returned.
    sufficient_statistics = Column(JSONB, nullable=True)
    results = Column(JSONB, nullable=True)
    #: Query or job ids, bytes billed or scanned, elapsed time.
    job_metadata = Column(JSONB, nullable=True)
    error_code = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def __table_args__(cls):
        return (
            Index(
                "ix_warehouse_runs_connection_created",
                "connection_id",
                "created_at",
            ),
            Index(
                "ix_warehouse_runs_experiment_created",
                "experiment_id",
                "created_at",
            ),
            # One run in flight per connection: a second concurrent request
            # fails on this index instead of racing past the daily limit.
            Index(
                "uq_warehouse_runs_one_in_flight",
                "connection_id",
                unique=True,
                postgresql_where=text(_in("status", IN_FLIGHT_STATUSES)),
            ),
            CheckConstraint(_in("kind", RUN_KINDS), name="ck_warehouse_runs_kind"),
            CheckConstraint(
                _in("status", RUN_STATUSES), name="ck_warehouse_runs_status"
            ),
            # JSONB would otherwise store Python None as the JSON value null.
            CheckConstraint(
                "jsonb_typeof(request) = 'object'",
                name="ck_warehouse_runs_request_object",
            ),
            CheckConstraint(
                "kind <> 'analysis' OR experiment_id IS NOT NULL",
                name="ck_warehouse_runs_analysis_has_experiment",
            ),
            # A failed run says why; any other run has no error.
            CheckConstraint(
                "(status = 'failed') = (error_code IS NOT NULL)",
                name="ck_warehouse_runs_error_code",
            ),
            CheckConstraint(
                "window_start IS NULL OR window_end IS NULL "
                "OR window_start < window_end",
                name="ck_warehouse_runs_window",
            ),
            {"schema": get_schema_name()},
        )

    def __repr__(self) -> str:
        return (
            f"<WarehouseAnalysisRun id={self.id} kind={self.kind!r} "
            f"status={self.status!r}>"
        )
