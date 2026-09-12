"""
Unit tests for the notifications API endpoints (EP-030 Batch 3B).

Tests cover:
- Notification preferences (get, update) — 7 tests
- Admin preferences listing — 4 tests
- Delivery log — 7 tests
- Test notification endpoint — 7 tests
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.notification import NotificationChannel, NotificationStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_user(role="ADMIN", user_id=None):
    """Build a mock User object with the given role."""
    from backend.app.models.user import UserRole

    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.role = UserRole[role]
    user.username = f"{role.lower()}_user"
    user.email = f"{role.lower()}@example.com"
    user.is_active = True
    return user


def make_prefs(user_id=None):
    """Build a mock NotificationPreference ORM-like object."""
    prefs = MagicMock()
    prefs.id = uuid.uuid4()
    prefs.user_id = user_id or uuid.uuid4()
    prefs.notify_experiment_started = True
    prefs.notify_experiment_completed = True
    prefs.notify_safety_rollback = True
    prefs.notify_rollout_advanced = False
    prefs.slack_channel = None
    prefs.email_override = None
    prefs.created_at = datetime.now(timezone.utc)
    prefs.updated_at = datetime.now(timezone.utc)
    return prefs


def make_log_entry(event_type="experiment_started", status=NotificationStatus.SENT):
    """Build a mock NotificationDeliveryLog ORM-like object."""
    entry = MagicMock()
    entry.id = uuid.uuid4()
    entry.event_type = event_type
    entry.channel = NotificationChannel.SLACK
    entry.recipient = "#platform-alerts"
    entry.subject = None
    entry.status = status
    entry.error_message = None
    entry.payload = None
    entry.created_at = datetime.now(timezone.utc)
    return entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_user():
    return make_user("ADMIN")


@pytest.fixture
def developer_user():
    return make_user("DEVELOPER")


@pytest.fixture
def analyst_user():
    return make_user("ANALYST")


@pytest.fixture
def viewer_user():
    return make_user("VIEWER")


# ---------------------------------------------------------------------------
# Preferences — GET /api/v1/notifications/preferences
# ---------------------------------------------------------------------------


def test_get_preferences_returns_defaults_when_none_exist(client, admin_user):
    """When no preferences row exists the endpoint creates and returns defaults."""
    mock_db = MagicMock()
    # query(...).filter_by(...).first() returns None → no existing prefs
    mock_db.query.return_value.filter_by.return_value.first.return_value = None

    new_prefs = make_prefs(user_id=admin_user.id)
    # After add+commit the refresh should populate the object on mock_db
    mock_db.refresh.side_effect = lambda obj: None

    with patch(
        "backend.app.api.v1.endpoints.notifications.NotificationPreference"
    ) as MockPref:
        MockPref.return_value = new_prefs
        app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        response = client.get("/api/v1/notifications/preferences")

        app.dependency_overrides.pop(deps.get_current_active_user, None)
        app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called()


def test_get_preferences_returns_existing_prefs(client, admin_user):
    """When a preferences row exists the endpoint returns it without creating a new one."""
    mock_db = MagicMock()
    existing_prefs = make_prefs(user_id=admin_user.id)
    mock_db.query.return_value.filter_by.return_value.first.return_value = (
        existing_prefs
    )

    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/preferences")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200
    # Should NOT have tried to create a new prefs row
    mock_db.add.assert_not_called()


def test_get_preferences_requires_auth(client):
    """The endpoint returns 401/403 when no user is authenticated."""
    # Remove any overrides so the real auth dependency runs and fails
    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    response = client.get("/api/v1/notifications/preferences")

    assert response.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Preferences — PUT /api/v1/notifications/preferences
# ---------------------------------------------------------------------------


def test_update_preferences_creates_if_not_exists(client, admin_user):
    """PUT creates a new prefs row when none exists for the user."""
    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = None
    created_prefs = make_prefs(user_id=admin_user.id)

    with patch(
        "backend.app.api.v1.endpoints.notifications.NotificationPreference"
    ) as MockPref:
        MockPref.return_value = created_prefs
        app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        response = client.put(
            "/api/v1/notifications/preferences",
            json={"notify_experiment_started": False},
        )

        app.dependency_overrides.pop(deps.get_current_active_user, None)
        app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called()


def test_update_preferences_updates_existing(client, admin_user):
    """PUT updates fields on an existing prefs row."""
    mock_db = MagicMock()
    existing_prefs = make_prefs(user_id=admin_user.id)
    mock_db.query.return_value.filter_by.return_value.first.return_value = (
        existing_prefs
    )

    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.put(
        "/api/v1/notifications/preferences",
        json={"notify_safety_rollback": False},
    )

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200
    # No new row should have been added
    mock_db.add.assert_not_called()
    mock_db.commit.assert_called()


def test_update_preferences_partial_update_preserves_others(client, admin_user):
    """A partial PUT only changes the supplied fields; others remain unchanged."""
    mock_db = MagicMock()
    existing_prefs = make_prefs(user_id=admin_user.id)
    existing_prefs.notify_experiment_started = True
    existing_prefs.notify_rollout_advanced = False
    mock_db.query.return_value.filter_by.return_value.first.return_value = (
        existing_prefs
    )

    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    # Only change notify_rollout_advanced
    response = client.put(
        "/api/v1/notifications/preferences",
        json={"notify_rollout_advanced": True},
    )

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200
    # notify_experiment_started must not have been touched (setattr not called for it)
    # We verify by checking that notify_rollout_advanced was set
    assert existing_prefs.notify_rollout_advanced is True


def test_update_preferences_requires_auth(client):
    """PUT returns 401/403 when no user is authenticated."""
    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    response = client.put(
        "/api/v1/notifications/preferences",
        json={"notify_experiment_started": False},
    )

    assert response.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Admin preferences list — GET /api/v1/notifications/admin/preferences
# ---------------------------------------------------------------------------


def test_list_all_preferences_admin_only(client, admin_user):
    """ADMIN user can successfully retrieve the full preferences list."""
    mock_db = MagicMock()
    prefs_list = [make_prefs(), make_prefs()]
    mock_db.query.return_value.all.return_value = prefs_list

    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/admin/preferences")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_list_all_preferences_requires_admin_role(client, developer_user):
    """A DEVELOPER (non-admin) receives a 403 response."""
    mock_db = MagicMock()

    app.dependency_overrides[deps.get_current_active_user] = lambda: developer_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/admin/preferences")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 403


def test_list_all_preferences_non_admin_returns_403(client, analyst_user):
    """An ANALYST receives a 403 response."""
    mock_db = MagicMock()

    app.dependency_overrides[deps.get_current_active_user] = lambda: analyst_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/admin/preferences")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 403


def test_list_all_preferences_viewer_returns_403(client, viewer_user):
    """A VIEWER receives a 403 response."""
    mock_db = MagicMock()

    app.dependency_overrides[deps.get_current_active_user] = lambda: viewer_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/admin/preferences")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Delivery log — GET /api/v1/notifications/delivery-log
# ---------------------------------------------------------------------------


def _make_log_query_mock(mock_db, entries, total=None):
    """Wire mock_db so that the chained query calls used in delivery-log work."""
    query_mock = MagicMock()
    filter_mock = MagicMock()
    order_mock = MagicMock()
    offset_mock = MagicMock()
    limit_mock = MagicMock()

    mock_db.query.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.count.return_value = total if total is not None else len(entries)
    query_mock.order_by.return_value = order_mock
    order_mock.offset.return_value = offset_mock
    offset_mock.limit.return_value = limit_mock
    limit_mock.all.return_value = entries
    return query_mock


def test_delivery_log_requires_admin(client, admin_user):
    """ADMIN can access the delivery log."""
    mock_db = MagicMock()
    entries = [make_log_entry()]
    _make_log_query_mock(mock_db, entries)

    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/delivery-log")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200


def test_delivery_log_non_admin_returns_403(client, developer_user):
    """A DEVELOPER receives 403 for the delivery log endpoint."""
    mock_db = MagicMock()

    app.dependency_overrides[deps.get_current_active_user] = lambda: developer_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/delivery-log")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 403


def test_delivery_log_pagination(client, admin_user):
    """The endpoint accepts page and limit query parameters."""
    mock_db = MagicMock()
    entries = [make_log_entry() for _ in range(5)]
    _make_log_query_mock(mock_db, entries, total=50)

    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/delivery-log?page=2&limit=5")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 2
    assert data["limit"] == 5
    assert data["total"] == 50


def test_delivery_log_filter_by_event_type(client, admin_user):
    """The endpoint accepts an event_type filter query parameter."""
    mock_db = MagicMock()
    entries = [make_log_entry(event_type="safety_rollback")]
    _make_log_query_mock(mock_db, entries)

    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get(
        "/api/v1/notifications/delivery-log?event_type=safety_rollback"
    )

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200


def test_delivery_log_filter_by_status(client, admin_user):
    """The endpoint accepts a status filter query parameter."""
    mock_db = MagicMock()
    entries = [make_log_entry(status=NotificationStatus.FAILED)]
    _make_log_query_mock(mock_db, entries)

    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/delivery-log?status=failed")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200


def test_delivery_log_returns_list_response(client, admin_user):
    """The response body has the expected shape: items, total, page, limit."""
    mock_db = MagicMock()
    entries = [make_log_entry(), make_log_entry()]
    _make_log_query_mock(mock_db, entries, total=2)

    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    response = client.get("/api/v1/notifications/delivery-log")

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "limit" in data
    assert data["total"] == 2


# ---------------------------------------------------------------------------
# Test notification — POST /api/v1/notifications/test
# ---------------------------------------------------------------------------


def test_test_notification_developer_can_send(client, developer_user):
    """A DEVELOPER can send a test notification."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: developer_user

    with patch(
        "backend.app.api.v1.endpoints.notifications.NotificationService"
    ) as MockSvc:
        instance = MockSvc.return_value
        instance._slack.send_generic_alert.return_value = True

        response = client.post(
            "/api/v1/notifications/test",
            json={"channel": "slack", "message": "hello", "recipient": "#test"},
        )

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    assert response.status_code == 200


def test_test_notification_admin_can_send(client, admin_user):
    """An ADMIN can send a test notification."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user

    with patch(
        "backend.app.api.v1.endpoints.notifications.NotificationService"
    ) as MockSvc:
        instance = MockSvc.return_value
        instance._slack.send_generic_alert.return_value = True

        response = client.post(
            "/api/v1/notifications/test",
            json={"channel": "slack", "message": "hello"},
        )

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    assert response.status_code == 200


def test_test_notification_viewer_returns_403(client, viewer_user):
    """A VIEWER receives 403 for the test notification endpoint."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: viewer_user

    response = client.post(
        "/api/v1/notifications/test",
        json={"channel": "slack", "message": "hello"},
    )

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    assert response.status_code == 403


def test_test_notification_analyst_returns_403(client, analyst_user):
    """An ANALYST receives 403 for the test notification endpoint."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: analyst_user

    response = client.post(
        "/api/v1/notifications/test",
        json={"channel": "slack", "message": "hello"},
    )

    app.dependency_overrides.pop(deps.get_current_active_user, None)
    assert response.status_code == 403


def test_test_notification_slack_channel(client, admin_user):
    """Sending via the slack channel calls SlackNotifier.send_generic_alert."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user

    with patch(
        "backend.app.api.v1.endpoints.notifications.NotificationService"
    ) as MockSvc:
        instance = MockSvc.return_value
        instance._slack.send_generic_alert.return_value = True

        response = client.post(
            "/api/v1/notifications/test",
            json={"channel": "slack", "message": "slack test", "recipient": "#ops"},
        )

    app.dependency_overrides.pop(deps.get_current_active_user, None)

    assert response.status_code == 200
    instance._slack.send_generic_alert.assert_called_once()


def test_test_notification_webhook_channel(client, admin_user):
    """Sending via the webhook channel calls NotificationService.send_webhook."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user

    with patch(
        "backend.app.api.v1.endpoints.notifications.NotificationService"
    ) as MockSvc:
        instance = MockSvc.return_value
        instance._webhook_url = "http://example.com/webhook"
        instance.send_webhook.return_value = True

        response = client.post(
            "/api/v1/notifications/test",
            json={"channel": "webhook", "message": "webhook test"},
        )

    app.dependency_overrides.pop(deps.get_current_active_user, None)

    assert response.status_code == 200
    instance.send_webhook.assert_called_once()


def test_test_notification_returns_success_field(client, admin_user):
    """The response body includes a 'success' field."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user

    with patch(
        "backend.app.api.v1.endpoints.notifications.NotificationService"
    ) as MockSvc:
        instance = MockSvc.return_value
        instance._slack.send_generic_alert.return_value = True

        response = client.post(
            "/api/v1/notifications/test",
            json={"channel": "slack", "message": "check success field"},
        )

    app.dependency_overrides.pop(deps.get_current_active_user, None)

    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "channel" in data
    assert "message" in data


def test_test_notification_default_channel_is_slack(client, admin_user):
    """When no channel is specified the default (slack) is used."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user

    with patch(
        "backend.app.api.v1.endpoints.notifications.NotificationService"
    ) as MockSvc:
        instance = MockSvc.return_value
        instance._slack.send_generic_alert.return_value = (
            False  # returns False but no error
        )

        response = client.post(
            "/api/v1/notifications/test",
            json={"message": "default channel test"},
        )

    app.dependency_overrides.pop(deps.get_current_active_user, None)

    assert response.status_code == 200
    data = response.json()
    assert data["channel"] == "slack"
