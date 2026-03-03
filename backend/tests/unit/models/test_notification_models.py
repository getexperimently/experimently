"""
Unit tests for notification preference and delivery log models.
Tests structure, column definitions, and enum values.
"""

import pytest
from sqlalchemy import inspect

from backend.app.models.notification import (
    NotificationPreference,
    NotificationDeliveryLog,
    NotificationChannel,
    NotificationStatus,
)
from backend.app.models.base import Base
from backend.app.core.database_config import get_schema_name


# ── Enum tests ──────────────────────────────────────────────────────────────

def test_notification_channel_values():
    assert NotificationChannel.SLACK == "slack"
    assert NotificationChannel.EMAIL == "email"
    assert NotificationChannel.WEBHOOK == "webhook"


def test_notification_status_values():
    assert NotificationStatus.SENT == "sent"
    assert NotificationStatus.FAILED == "failed"
    assert NotificationStatus.SKIPPED == "skipped"


# ── NotificationPreference model ────────────────────────────────────────────

def test_notification_preference_inherits_base():
    assert issubclass(NotificationPreference, Base)


def test_notification_preference_tablename():
    assert NotificationPreference.__tablename__ == "notification_preferences"


def test_notification_preference_schema():
    schema = get_schema_name()
    table_args = NotificationPreference.__table_args__
    schema_found = any(
        isinstance(a, dict) and a.get("schema") == schema
        for a in (table_args if isinstance(table_args, tuple) else [table_args])
    )
    assert schema_found, f"Expected schema '{schema}' in __table_args__"


def test_notification_preference_required_columns():
    inspector = inspect(NotificationPreference)
    columns = [c.name for c in inspector.columns]
    required = [
        "id",
        "user_id",
        "notify_experiment_started",
        "notify_experiment_completed",
        "notify_safety_rollback",
        "notify_rollout_advanced",
        "created_at",
        "updated_at",
    ]
    for col in required:
        assert col in columns, f"Missing column: {col}"


def test_notification_preference_optional_columns():
    inspector = inspect(NotificationPreference)
    columns = [c.name for c in inspector.columns]
    assert "slack_channel" in columns
    assert "email_override" in columns


def test_notification_preference_user_id_nullable_false():
    col = NotificationPreference.__table__.columns["user_id"]
    assert not col.nullable


def test_notification_preference_boolean_defaults():
    inspector = inspect(NotificationPreference)
    col_map = {c.name: c for c in inspector.columns}

    assert col_map["notify_experiment_started"].default.arg is True
    assert col_map["notify_experiment_completed"].default.arg is True
    assert col_map["notify_safety_rollback"].default.arg is True
    assert col_map["notify_rollout_advanced"].default.arg is False


# ── NotificationDeliveryLog model ───────────────────────────────────────────

def test_notification_delivery_log_inherits_base():
    assert issubclass(NotificationDeliveryLog, Base)


def test_notification_delivery_log_tablename():
    assert NotificationDeliveryLog.__tablename__ == "notification_delivery_log"


def test_notification_delivery_log_schema():
    schema = get_schema_name()
    table_args = NotificationDeliveryLog.__table_args__
    schema_found = any(
        isinstance(a, dict) and a.get("schema") == schema
        for a in (table_args if isinstance(table_args, tuple) else [table_args])
    )
    assert schema_found, f"Expected schema '{schema}' in __table_args__"


def test_notification_delivery_log_required_columns():
    inspector = inspect(NotificationDeliveryLog)
    columns = [c.name for c in inspector.columns]
    required = [
        "id",
        "event_type",
        "channel",
        "recipient",
        "status",
        "created_at",
    ]
    for col in required:
        assert col in columns, f"Missing column: {col}"


def test_notification_delivery_log_optional_columns():
    inspector = inspect(NotificationDeliveryLog)
    columns = [c.name for c in inspector.columns]
    assert "subject" in columns
    assert "error_message" in columns
    assert "payload" in columns


def test_notification_delivery_log_event_type_nullable_false():
    col = NotificationDeliveryLog.__table__.columns["event_type"]
    assert not col.nullable


def test_notification_delivery_log_channel_nullable_false():
    col = NotificationDeliveryLog.__table__.columns["channel"]
    assert not col.nullable


def test_notification_delivery_log_recipient_nullable_false():
    col = NotificationDeliveryLog.__table__.columns["recipient"]
    assert not col.nullable


# ── Schema tests ─────────────────────────────────────────────────────────────

def test_notification_preference_schema_defaults():
    from backend.app.schemas.notification import NotificationPreferenceCreate
    prefs = NotificationPreferenceCreate()
    assert prefs.notify_experiment_started is True
    assert prefs.notify_experiment_completed is True
    assert prefs.notify_safety_rollback is True
    assert prefs.notify_rollout_advanced is False
    assert prefs.slack_channel is None
    assert prefs.email_override is None


def test_notification_preference_schema_update_partial():
    from backend.app.schemas.notification import NotificationPreferenceUpdate
    update = NotificationPreferenceUpdate(notify_safety_rollback=False)
    assert update.notify_safety_rollback is False
    assert update.notify_experiment_started is None  # unset = None for partial update


def test_notification_delivery_log_response_schema():
    import uuid
    from datetime import datetime
    from backend.app.schemas.notification import NotificationDeliveryLogResponse
    data = NotificationDeliveryLogResponse(
        id=uuid.uuid4(),
        event_type="safety_rollback",
        channel=NotificationChannel.SLACK,
        recipient="#platform-alerts",
        status=NotificationStatus.SENT,
        created_at=datetime.utcnow(),
    )
    assert data.event_type == "safety_rollback"
    assert data.channel == NotificationChannel.SLACK


def test_test_notification_request_schema():
    from backend.app.schemas.notification import TestNotificationRequest
    req = TestNotificationRequest()
    assert req.channel == NotificationChannel.SLACK
    assert "Test notification" in req.message
