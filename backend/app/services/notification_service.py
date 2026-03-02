"""
Notification service for scheduler webhook notifications.

Sends structured event payloads to configured webhook URLs (e.g. Slack, Teams)
when significant scheduler events occur such as experiments starting/ending,
safety rollbacks, or rollout stage advances.

All methods swallow exceptions so that notification failures never disrupt
the primary scheduler logic.
"""

import logging
from datetime import datetime, timezone

import httpx

from backend.app.core.config import settings
from backend.app.schemas.scheduler import NotificationEvent

logger = logging.getLogger(__name__)


class NotificationService:
    """Handles webhook-based notifications for scheduler events."""

    def __init__(self):
        self._webhook_url = getattr(settings, "NOTIFICATION_WEBHOOK_URL", "")

    # ------------------------------------------------------------------
    # Core send method
    # ------------------------------------------------------------------

    def send_webhook(self, url: str, event: NotificationEvent) -> bool:
        """
        POST a NotificationEvent as JSON to the given webhook URL.

        Args:
            url: Fully-qualified webhook URL.
            event: The event payload to send.

        Returns:
            True if the server responded with a 2xx status code, False otherwise.
            Exceptions (connection errors, timeouts) are swallowed and return False.
        """
        try:
            payload = event.model_dump()
            response = httpx.post(url, json=payload, timeout=5)
            if 200 <= response.status_code < 300:
                logger.debug(
                    "Webhook notification sent successfully to %s (status=%d)",
                    url,
                    response.status_code,
                )
                return True
            else:
                logger.warning(
                    "Webhook notification failed: url=%s status=%d",
                    url,
                    response.status_code,
                )
                return False
        except Exception as exc:
            logger.error("Webhook notification error for url=%s: %s", url, exc)
            return False

    # ------------------------------------------------------------------
    # Convenience notification helpers
    # ------------------------------------------------------------------

    def _send(self, event: NotificationEvent) -> bool:
        """Send an event to the configured webhook URL, if set."""
        url = self._webhook_url
        if not url:
            logger.debug(
                "Notification skipped (NOTIFICATION_WEBHOOK_URL not configured): event_type=%s",
                event.event_type,
            )
            return False
        return self.send_webhook(url, event)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def notify_experiment_started(
        self,
        experiment_id: str,
        experiment_name: str,
    ) -> bool:
        """
        Send a notification that an experiment has been automatically started
        by the scheduler.

        Args:
            experiment_id: The experiment's unique identifier.
            experiment_name: Human-readable name of the experiment.

        Returns:
            True if the webhook was sent and acknowledged, False otherwise.
        """
        event = NotificationEvent(
            event_type="experiment_started",
            experiment_id=experiment_id,
            new_status="active",
            message=f"Experiment '{experiment_name}' has been started automatically.",
            timestamp=self._now_iso(),
            metadata={"experiment_name": experiment_name},
        )
        return self._send(event)

    def notify_experiment_ended(
        self,
        experiment_id: str,
        experiment_name: str,
        winning_variant: str = None,
    ) -> bool:
        """
        Send a notification that an experiment has been automatically ended
        (completed) by the scheduler.

        Args:
            experiment_id: The experiment's unique identifier.
            experiment_name: Human-readable name of the experiment.
            winning_variant: Optional name of the winning variant.

        Returns:
            True if the webhook was sent and acknowledged, False otherwise.
        """
        msg = f"Experiment '{experiment_name}' has been completed automatically."
        metadata = {"experiment_name": experiment_name}
        if winning_variant:
            msg += f" Winning variant: {winning_variant}."
            metadata["winning_variant"] = winning_variant

        event = NotificationEvent(
            event_type="experiment_ended",
            experiment_id=experiment_id,
            old_status="active",
            new_status="completed",
            message=msg,
            timestamp=self._now_iso(),
            metadata=metadata,
        )
        return self._send(event)

    def notify_safety_rollback(
        self,
        feature_flag_id: str,
        feature_flag_name: str,
        reason: str,
    ) -> bool:
        """
        Send a notification that a feature flag has been automatically rolled
        back by the safety monitoring scheduler.

        Args:
            feature_flag_id: The feature flag's unique identifier.
            feature_flag_name: Human-readable name of the feature flag.
            reason: Human-readable description of why the rollback occurred.

        Returns:
            True if the webhook was sent and acknowledged, False otherwise.
        """
        event = NotificationEvent(
            event_type="safety_rollback",
            feature_flag_id=feature_flag_id,
            message=(
                f"Feature flag '{feature_flag_name}' was automatically rolled back. "
                f"Reason: {reason}"
            ),
            timestamp=self._now_iso(),
            metadata={
                "feature_flag_name": feature_flag_name,
                "reason": reason,
            },
        )
        return self._send(event)

    def notify_rollout_advanced(
        self,
        feature_flag_id: str,
        stage_name: str,
        new_percentage: int,
    ) -> bool:
        """
        Send a notification that a rollout schedule has advanced to a new stage.

        Args:
            feature_flag_id: The feature flag's unique identifier.
            stage_name: Name of the newly activated rollout stage.
            new_percentage: The rollout percentage now applied to the feature flag.

        Returns:
            True if the webhook was sent and acknowledged, False otherwise.
        """
        event = NotificationEvent(
            event_type="rollout_advanced",
            feature_flag_id=feature_flag_id,
            message=(
                f"Rollout advanced to stage '{stage_name}' — "
                f"feature flag is now at {new_percentage}% rollout."
            ),
            timestamp=self._now_iso(),
            metadata={
                "stage_name": stage_name,
                "new_percentage": new_percentage,
            },
        )
        return self._send(event)
