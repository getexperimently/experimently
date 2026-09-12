"""
Tests for the updated NotificationService that orchestrates
Slack, Email, and Webhook channels with delivery logging.
"""

from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_service(db=None):
    """Build a NotificationService with optional mocked DB session."""
    from backend.app.services.notification_service import NotificationService

    svc = NotificationService()
    if db is not None:
        svc._db = db
    return svc


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_loads_webhook_url(self):
        svc = make_service()
        assert isinstance(svc._webhook_url, str)

    def test_init_creates_slack_notifier(self):
        svc = make_service()
        assert hasattr(svc, "_slack")

    def test_init_creates_email_notifier(self):
        svc = make_service()
        assert hasattr(svc, "_email")


# ---------------------------------------------------------------------------
# _log_delivery
# ---------------------------------------------------------------------------


class TestLogDelivery:
    def test_log_delivery_creates_record(self):
        from backend.app.models.notification import (
            NotificationChannel,
            NotificationStatus,
        )

        mock_db = MagicMock()
        svc = make_service(db=mock_db)
        svc._log_delivery(
            db=mock_db,
            event_type="test_event",
            channel=NotificationChannel.SLACK,
            recipient="#alerts",
            status=NotificationStatus.SENT,
        )
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_log_delivery_records_failure(self):
        from backend.app.models.notification import (
            NotificationChannel,
            NotificationStatus,
        )

        mock_db = MagicMock()
        svc = make_service(db=mock_db)
        svc._log_delivery(
            db=mock_db,
            event_type="safety_rollback",
            channel=NotificationChannel.EMAIL,
            recipient="admin@example.com",
            status=NotificationStatus.FAILED,
            error_message="Connection refused",
        )
        added = mock_db.add.call_args[0][0]
        assert added.status.value == "failed"
        assert added.error_message == "Connection refused"

    def test_log_delivery_swallows_db_errors(self):
        from backend.app.models.notification import (
            NotificationChannel,
            NotificationStatus,
        )

        mock_db = MagicMock()
        mock_db.add.side_effect = Exception("DB error")
        svc = make_service(db=mock_db)
        # Should not raise
        svc._log_delivery(
            db=mock_db,
            event_type="test",
            channel=NotificationChannel.WEBHOOK,
            recipient="http://example.com",
            status=NotificationStatus.SKIPPED,
        )

    def test_log_delivery_no_db_skips_silently(self):
        svc = make_service(db=None)
        from backend.app.models.notification import (
            NotificationChannel,
            NotificationStatus,
        )

        # Should not raise even without a DB session
        svc._log_delivery(
            db=None,
            event_type="test",
            channel=NotificationChannel.SLACK,
            recipient="#alerts",
            status=NotificationStatus.SENT,
        )


# ---------------------------------------------------------------------------
# notify_experiment_started
# ---------------------------------------------------------------------------


class TestNotifyExperimentStarted:
    def test_calls_webhook_send(self):
        svc = make_service()
        with patch.object(svc, "_send", return_value=True) as mock_wh:
            svc.notify_experiment_started("exp-id-1", "My Experiment")
            mock_wh.assert_called_once()

    def test_calls_slack_send(self):
        svc = make_service()
        with patch.object(
            svc._slack, "send_experiment_started", return_value=True
        ) as mock_sl:
            with patch.object(svc, "send_webhook", return_value=True):
                svc.notify_experiment_started("exp-id-1", "My Experiment")
                mock_sl.assert_called_once()

    def test_calls_email_send(self):
        svc = make_service()
        with patch.object(
            svc._email, "send_experiment_started_email", return_value=True
        ) as mock_em:
            with patch.object(svc, "send_webhook", return_value=True):
                with patch.object(
                    svc._slack, "send_experiment_started", return_value=True
                ):
                    svc.notify_experiment_started(
                        "exp-id-1", "My Experiment", owner_email="o@example.com"
                    )
                    mock_em.assert_called_once()

    def test_returns_bool(self):
        svc = make_service()
        with patch.object(svc, "send_webhook", return_value=False):
            with patch.object(
                svc._slack, "send_experiment_started", return_value=False
            ):
                with patch.object(
                    svc._email, "send_experiment_started_email", return_value=False
                ):
                    result = svc.notify_experiment_started("id", "name")
                    assert isinstance(result, bool)

    def test_never_raises(self):
        svc = make_service()
        with patch.object(svc, "send_webhook", side_effect=Exception("boom")):
            # Should not propagate
            svc.notify_experiment_started("id", "name")


# ---------------------------------------------------------------------------
# notify_experiment_ended
# ---------------------------------------------------------------------------


class TestNotifyExperimentEnded:
    def test_calls_slack(self):
        svc = make_service()
        with patch.object(
            svc._slack, "send_experiment_completed", return_value=True
        ) as mock_sl:
            with patch.object(svc, "send_webhook", return_value=True):
                svc.notify_experiment_ended(
                    "exp-id-1", "My Experiment", winning_variant="Variant B"
                )
                mock_sl.assert_called_once()

    def test_passes_winner_to_email(self):
        svc = make_service()
        with patch.object(
            svc._email, "send_experiment_completed_email", return_value=True
        ) as mock_em:
            with patch.object(svc, "send_webhook", return_value=True):
                with patch.object(
                    svc._slack, "send_experiment_completed", return_value=True
                ):
                    svc.notify_experiment_ended(
                        "id", "Name", winning_variant="B", owner_email="x@y.com"
                    )
                    mock_em.assert_called_once()

    def test_never_raises(self):
        svc = make_service()
        with patch.object(svc, "send_webhook", side_effect=RuntimeError("oops")):
            svc.notify_experiment_ended("id", "name")


# ---------------------------------------------------------------------------
# notify_safety_rollback
# ---------------------------------------------------------------------------


class TestNotifySafetyRollback:
    def test_calls_slack_alert(self):
        svc = make_service()
        with patch.object(
            svc._slack, "send_safety_rollback_alert", return_value=True
        ) as mock_sl:
            with patch.object(svc, "send_webhook", return_value=True):
                svc.notify_safety_rollback("flag-id", "my-flag", "high error rate")
                mock_sl.assert_called_once()

    def test_calls_webhook(self):
        svc = make_service()
        with patch.object(svc, "_send", return_value=True) as mock_wh:
            with patch.object(
                svc._slack, "send_safety_rollback_alert", return_value=False
            ):
                svc.notify_safety_rollback("flag-id", "my-flag", "latency exceeded")
                mock_wh.assert_called_once()

    def test_never_raises(self):
        svc = make_service()
        with patch.object(
            svc._slack,
            "send_safety_rollback_alert",
            side_effect=Exception("slack down"),
        ):
            svc.notify_safety_rollback("id", "flag", "reason")


# ---------------------------------------------------------------------------
# notify_rollout_advanced
# ---------------------------------------------------------------------------


class TestNotifyRolloutAdvanced:
    def test_calls_slack(self):
        svc = make_service()
        with patch.object(
            svc._slack, "send_rollout_advanced", return_value=True
        ) as mock_sl:
            with patch.object(svc, "send_webhook", return_value=True):
                svc.notify_rollout_advanced("flag-id", "Stage 2", 50)
                mock_sl.assert_called_once()

    def test_never_raises(self):
        svc = make_service()
        with patch.object(
            svc._slack, "send_rollout_advanced", side_effect=Exception("network")
        ):
            svc.notify_rollout_advanced("id", "stage", 25)


# ---------------------------------------------------------------------------
# send_webhook (existing functionality preserved)
# ---------------------------------------------------------------------------


class TestSendWebhook:
    def test_send_webhook_success(self):
        import httpx

        from backend.app.schemas.scheduler import NotificationEvent

        svc = make_service()
        event = NotificationEvent(
            event_type="test",
            message="hello",
            timestamp=datetime.utcnow().isoformat(),
        )
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            result = svc.send_webhook("http://example.com/hook", event)
            assert result is True

    def test_send_webhook_non_2xx_returns_false(self):
        from backend.app.schemas.scheduler import NotificationEvent

        svc = make_service()
        event = NotificationEvent(
            event_type="test",
            message="hello",
            timestamp=datetime.utcnow().isoformat(),
        )
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_post.return_value = mock_resp
            result = svc.send_webhook("http://example.com/hook", event)
            assert result is False

    def test_send_webhook_connection_error_returns_false(self):
        from backend.app.schemas.scheduler import NotificationEvent

        svc = make_service()
        event = NotificationEvent(
            event_type="test",
            message="hello",
            timestamp=datetime.utcnow().isoformat(),
        )
        with patch("httpx.post", side_effect=Exception("connection refused")):
            result = svc.send_webhook("http://example.com/hook", event)
            assert result is False
