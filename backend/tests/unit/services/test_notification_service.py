"""
Unit tests for NotificationService (P3-B TDD).

Tests cover:
- send_webhook returns True on 2xx response
- send_webhook returns False on 4xx/5xx response
- send_webhook returns False on connection error (exception swallowed)
- send_webhook returns False on timeout (exception swallowed)
- notify_experiment_started builds correct event payload
- notify_experiment_ended builds correct event payload
- notify_safety_rollback builds correct event payload
- notify_rollout_advanced builds correct event payload
- Empty/missing webhook URL skips sending (logs debug, returns None/False)
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

from backend.app.services.notification_service import NotificationService
from backend.app.schemas.scheduler import NotificationEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_service(webhook_url: str = "https://hooks.example.com/test"):
    """Return a NotificationService with a configurable webhook URL."""
    with patch("backend.app.services.notification_service.settings") as mock_settings:
        mock_settings.NOTIFICATION_WEBHOOK_URL = webhook_url
        service = NotificationService()
        service._webhook_url = webhook_url  # set directly for test isolation
    return service


# ---------------------------------------------------------------------------
# send_webhook
# ---------------------------------------------------------------------------


class TestSendWebhook:
    def setup_method(self):
        self.service = NotificationService()
        self.service._webhook_url = "https://hooks.example.com/test"
        self.event = NotificationEvent(
            event_type="experiment_started",
            message="Experiment A started",
            timestamp="2026-03-01T10:00:00Z",
        )

    def test_returns_true_on_200_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("backend.app.services.notification_service.httpx.post", return_value=mock_response):
            result = self.service.send_webhook(
                url="https://hooks.example.com/test",
                event=self.event,
            )
        assert result is True

    def test_returns_true_on_201_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch("backend.app.services.notification_service.httpx.post", return_value=mock_response):
            result = self.service.send_webhook(
                url="https://hooks.example.com/test",
                event=self.event,
            )
        assert result is True

    def test_returns_false_on_400_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 400

        with patch("backend.app.services.notification_service.httpx.post", return_value=mock_response):
            result = self.service.send_webhook(
                url="https://hooks.example.com/test",
                event=self.event,
            )
        assert result is False

    def test_returns_false_on_500_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("backend.app.services.notification_service.httpx.post", return_value=mock_response):
            result = self.service.send_webhook(
                url="https://hooks.example.com/test",
                event=self.event,
            )
        assert result is False

    def test_returns_false_on_connection_error(self):
        """Connection errors must be swallowed and return False."""
        with patch(
            "backend.app.services.notification_service.httpx.post",
            side_effect=Exception("Connection refused"),
        ):
            result = self.service.send_webhook(
                url="https://hooks.example.com/test",
                event=self.event,
            )
        assert result is False

    def test_returns_false_on_timeout(self):
        """Timeout exceptions must be swallowed and return False."""
        import httpx as _httpx
        with patch(
            "backend.app.services.notification_service.httpx.post",
            side_effect=_httpx.TimeoutException("Request timed out"),
        ):
            result = self.service.send_webhook(
                url="https://hooks.example.com/test",
                event=self.event,
            )
        assert result is False

    def test_post_called_with_json_body(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("backend.app.services.notification_service.httpx.post", return_value=mock_response) as mock_post:
            self.service.send_webhook(
                url="https://hooks.example.com/test",
                event=self.event,
            )
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        # Verify URL is first positional arg
        assert call_kwargs[0][0] == "https://hooks.example.com/test"

    def test_post_uses_5_second_timeout(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("backend.app.services.notification_service.httpx.post", return_value=mock_response) as mock_post:
            self.service.send_webhook(
                url="https://hooks.example.com/test",
                event=self.event,
            )
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs.get("timeout") == 5


# ---------------------------------------------------------------------------
# Empty webhook URL
# ---------------------------------------------------------------------------


class TestEmptyWebhookUrl:
    def test_empty_url_does_not_call_httpx(self):
        service = NotificationService()
        service._webhook_url = ""

        with patch("backend.app.services.notification_service.httpx.post") as mock_post:
            result = service.notify_experiment_started(
                experiment_id="exp-1",
                experiment_name="Experiment Alpha",
            )
        mock_post.assert_not_called()

    def test_none_url_does_not_call_httpx(self):
        service = NotificationService()
        service._webhook_url = None

        with patch("backend.app.services.notification_service.httpx.post") as mock_post:
            service.notify_experiment_started(
                experiment_id="exp-1",
                experiment_name="Experiment Alpha",
            )
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# notify_experiment_started
# ---------------------------------------------------------------------------


class TestNotifyExperimentStarted:
    def setup_method(self):
        self.service = NotificationService()
        self.service._webhook_url = "https://hooks.example.com/test"

    def test_sends_correct_event_type(self):
        captured_events = []

        def fake_send_webhook(url, event):
            captured_events.append(event)
            return True

        self.service.send_webhook = fake_send_webhook
        self.service.notify_experiment_started(
            experiment_id="exp-1",
            experiment_name="Experiment Alpha",
        )
        assert len(captured_events) == 1
        assert captured_events[0].event_type == "experiment_started"

    def test_includes_experiment_id(self):
        captured_events = []

        def fake_send_webhook(url, event):
            captured_events.append(event)
            return True

        self.service.send_webhook = fake_send_webhook
        self.service.notify_experiment_started(
            experiment_id="exp-xyz",
            experiment_name="Test Exp",
        )
        assert captured_events[0].experiment_id == "exp-xyz"

    def test_message_contains_experiment_name(self):
        captured_events = []

        def fake_send_webhook(url, event):
            captured_events.append(event)
            return True

        self.service.send_webhook = fake_send_webhook
        self.service.notify_experiment_started(
            experiment_id="exp-1",
            experiment_name="My Great Experiment",
        )
        assert "My Great Experiment" in captured_events[0].message


# ---------------------------------------------------------------------------
# notify_experiment_ended
# ---------------------------------------------------------------------------


class TestNotifyExperimentEnded:
    def setup_method(self):
        self.service = NotificationService()
        self.service._webhook_url = "https://hooks.example.com/test"

    def test_sends_correct_event_type(self):
        captured_events = []

        def fake_send_webhook(url, event):
            captured_events.append(event)
            return True

        self.service.send_webhook = fake_send_webhook
        self.service.notify_experiment_ended(
            experiment_id="exp-1",
            experiment_name="Experiment Alpha",
            winning_variant="control",
        )
        assert captured_events[0].event_type == "experiment_ended"

    def test_includes_winning_variant_in_message(self):
        captured_events = []

        def fake_send_webhook(url, event):
            captured_events.append(event)
            return True

        self.service.send_webhook = fake_send_webhook
        self.service.notify_experiment_ended(
            experiment_id="exp-1",
            experiment_name="My Exp",
            winning_variant="variant_b",
        )
        assert "variant_b" in captured_events[0].message or "variant_b" in str(captured_events[0].metadata)


# ---------------------------------------------------------------------------
# notify_safety_rollback
# ---------------------------------------------------------------------------


class TestNotifySafetyRollback:
    def setup_method(self):
        self.service = NotificationService()
        self.service._webhook_url = "https://hooks.example.com/test"

    def test_sends_correct_event_type(self):
        captured_events = []

        def fake_send_webhook(url, event):
            captured_events.append(event)
            return True

        self.service.send_webhook = fake_send_webhook
        self.service.notify_safety_rollback(
            feature_flag_id="flag-1",
            feature_flag_name="dark_mode",
            reason="Error rate exceeded threshold",
        )
        assert captured_events[0].event_type == "safety_rollback"

    def test_includes_feature_flag_id(self):
        captured_events = []

        def fake_send_webhook(url, event):
            captured_events.append(event)
            return True

        self.service.send_webhook = fake_send_webhook
        self.service.notify_safety_rollback(
            feature_flag_id="flag-abc",
            feature_flag_name="beta_feature",
            reason="Latency spike",
        )
        assert captured_events[0].feature_flag_id == "flag-abc"


# ---------------------------------------------------------------------------
# notify_rollout_advanced
# ---------------------------------------------------------------------------


class TestNotifyRolloutAdvanced:
    def setup_method(self):
        self.service = NotificationService()
        self.service._webhook_url = "https://hooks.example.com/test"

    def test_sends_correct_event_type(self):
        captured_events = []

        def fake_send_webhook(url, event):
            captured_events.append(event)
            return True

        self.service.send_webhook = fake_send_webhook
        self.service.notify_rollout_advanced(
            feature_flag_id="flag-1",
            stage_name="Phase 2",
            new_percentage=50,
        )
        assert captured_events[0].event_type == "rollout_advanced"

    def test_includes_new_percentage_in_message(self):
        captured_events = []

        def fake_send_webhook(url, event):
            captured_events.append(event)
            return True

        self.service.send_webhook = fake_send_webhook
        self.service.notify_rollout_advanced(
            feature_flag_id="flag-1",
            stage_name="Phase 3",
            new_percentage=75,
        )
        assert "75" in captured_events[0].message or "75" in str(captured_events[0].metadata)
