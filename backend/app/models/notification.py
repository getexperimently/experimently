"""
Database models for notification preferences and delivery logs.

Tracks per-user notification preferences and every delivery attempt
so operators can audit what notifications were sent and why.
"""

import uuid
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Enum as SQLAEnum,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.models.base import Base
from backend.app.core.database_config import get_schema_name


class NotificationChannel(str, Enum):
    """Delivery channel for a notification."""
    SLACK = "slack"
    EMAIL = "email"
    WEBHOOK = "webhook"


class NotificationStatus(str, Enum):
    """Delivery status recorded in the log."""
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class NotificationPreference(Base):
    """Per-user notification preferences."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        Index("ix_notif_pref_user_id", "user_id"),
        {"schema": get_schema_name()},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Event toggles
    notify_experiment_started = Column(Boolean, default=True, nullable=False)
    notify_experiment_completed = Column(Boolean, default=True, nullable=False)
    notify_safety_rollback = Column(Boolean, default=True, nullable=False)
    notify_rollout_advanced = Column(Boolean, default=False, nullable=False)

    # Channel overrides (optional — falls back to global defaults)
    slack_channel = Column(String(255), nullable=True)
    email_override = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class NotificationDeliveryLog(Base):
    """Audit log of every notification delivery attempt."""

    __tablename__ = "notification_delivery_log"
    __table_args__ = (
        Index("ix_notif_log_event_type", "event_type"),
        Index("ix_notif_log_created_at", "created_at"),
        Index("ix_notif_log_status", "status"),
        {"schema": get_schema_name()},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(100), nullable=False)
    channel = Column(
        SQLAEnum(NotificationChannel, name="notification_channel"),
        nullable=False,
    )
    recipient = Column(String(512), nullable=False)
    subject = Column(String(512), nullable=True)
    status = Column(
        SQLAEnum(NotificationStatus, name="notification_status"),
        nullable=False,
        default=NotificationStatus.SENT,
    )
    error_message = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
