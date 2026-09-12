"""
SQLAlchemy model for persisting scheduler run history.

This module defines the SchedulerRun model which records each execution of a
background scheduler including status, item counts, and any error messages.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declared_attr

from backend.app.core.database_config import get_schema_name
from backend.app.models.base import Base, BaseModel


class SchedulerRun(Base, BaseModel):
    """
    Persists the result of each background scheduler execution.

    Attributes:
        scheduler_name: One of "experiment", "rollout", "metrics", "safety".
        started_at: UTC timestamp when the run began.
        completed_at: UTC timestamp when the run finished (None if still running).
        status: One of "success", "partial", "failed", "skipped".
        items_processed: Number of items successfully processed in this run.
        items_failed: Number of items that failed during this run.
        error_message: Human-readable error message when status is "failed".
        metadata_: Arbitrary JSON metadata about the run (stored as "metadata" column).
    """

    __tablename__ = "scheduler_runs"

    # Override id so we can set it explicitly (UUID primary key)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    scheduler_name = Column(String(64), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), nullable=False)
    items_processed = Column(Integer, default=0)
    items_failed = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    # "metadata" is a reserved word in SQLAlchemy's MetaData; use metadata_ as the
    # Python attribute name and map it to the "metadata" column in the database.
    metadata_ = Column("metadata", JSONB, default=dict)

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return ({"schema": schema_name},)

    def __repr__(self):
        return (
            f"<SchedulerRun scheduler={self.scheduler_name!r} "
            f"status={self.status!r} started_at={self.started_at!r}>"
        )
