"""
Scheduler for feature flag safety monitoring.

This module provides scheduling functionality for automatically
monitoring feature flags for safety issues and triggering rollbacks.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Dict, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_

from backend.app.core.config import settings as app_settings
from backend.app.db.session import SessionLocal
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.safety import RollbackTriggerType
from backend.app.services.safety_service import SafetyService
from backend.app.services.notification_service import NotificationService
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


def _rollback_target_percentage(config: Any) -> int:
    """
    The percentage an automatic rollback should set the flag to.

    Reads ``rollback_percentage`` from the flag's safety config and clamps it to
    0-100; anything missing or non-numeric rolls back to 0 (fully off).
    """
    value = getattr(config, "rollback_percentage", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, min(100, int(value)))


class SafetyScheduler:
    """Handles scheduled tasks for feature flag safety monitoring."""

    def __init__(self, interval_minutes: Optional[int] = None):
        """
        Initialize the safety scheduler.

        Args:
            interval_minutes: How often to check feature flags for safety issues
                (in minutes). Defaults to ``settings.SAFETY_CHECK_INTERVAL_MINUTES``.
        """
        if interval_minutes is None:
            interval_minutes = app_settings.SAFETY_CHECK_INTERVAL_MINUTES
        self.interval_minutes = interval_minutes
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self._notification_service = NotificationService()

    async def start(self):
        """Start the scheduler."""
        if self.is_running:
            logger.warning("Safety scheduler is already running")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._run_scheduler())
        logger.info(
            f"Safety scheduler started with {self.interval_minutes} minute interval"
        )

    async def stop(self):
        """Stop the scheduler."""
        if not self.is_running:
            return

        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("Safety scheduler stopped")

    async def _run_scheduler(self):
        """Run the scheduler loop."""
        while self.is_running:
            try:
                # Process feature flags that need safety checks
                await self.check_feature_flags_safety()

                # Wait for the next interval
                await asyncio.sleep(self.interval_minutes * 60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in safety scheduler: {str(e)}")
                # Wait a bit before trying again
                await asyncio.sleep(60)

    async def check_feature_flags_safety(self):
        """
        Check all active feature flags for safety issues.

        This checks:
        1. All active feature flags with rollout percentage > 0
        2. For each flag, check if safety monitoring is enabled
        3. If enabled, check safety metrics
        4. If auto-rollback is enabled and safety check fails, trigger rollback
        """
        logger.info("Checking feature flags safety")

        # Use a new database session for this task
        db = SessionLocal()
        try:
            # Get all active feature flags with rollout percentage > 0
            active_flags = (
                db.query(FeatureFlag)
                .filter(
                    and_(
                        FeatureFlag.status == FeatureFlagStatus.ACTIVE,
                        FeatureFlag.rollout_percentage > 0,
                    )
                )
                .all()
            )

            if not active_flags:
                logger.info("No active feature flags with rollout percentage > 0 found")
                return

            safety_service = SafetyService(db)

            # Check each feature flag for safety issues
            for feature_flag in active_flags:
                try:
                    # Get safety configuration for the feature flag
                    config = await safety_service.async_get_feature_flag_safety_config(
                        feature_flag.id
                    )

                    # Skip if safety monitoring is not enabled for this flag
                    if not config.enabled:
                        continue

                    # Check safety status
                    safety_check = await safety_service.check_feature_flag_safety(
                        feature_flag.id
                    )

                    # Log the safety check result
                    if safety_check.is_healthy:
                        logger.info(
                            f"Feature flag {feature_flag.key} ({feature_flag.id}) is healthy"
                        )
                    else:
                        logger.warning(
                            f"Feature flag {feature_flag.key} ({feature_flag.id}) has safety issues: {safety_check.details}"
                        )

                    # If auto-rollback is enabled and safety check fails, trigger rollback
                    settings = await safety_service.async_get_safety_settings()

                    if (
                        settings.enable_automatic_rollbacks
                        and not safety_check.is_healthy
                    ):
                        logger.warning(
                            f"Triggering automatic rollback for feature flag {feature_flag.key} ({feature_flag.id})"
                        )

                        # Find what metric triggered the rollback
                        trigger_reason = "Automatic rollback due to safety issues"
                        for metric in safety_check.metrics:
                            if not metric.is_healthy:
                                trigger_reason = f"Automatic rollback due to {metric.name} exceeding threshold ({metric.current_value} > {metric.threshold})"
                                break

                        # Roll back to the percentage configured for this flag
                        # (e.g. back to the internal 5% stage), not always to 0.
                        target_percentage = _rollback_target_percentage(config)

                        if feature_flag.rollout_percentage <= target_percentage:
                            # Already rolled back; the error window is still hot
                            # from before the rollback. Do not write another
                            # record or send another notification every cycle.
                            logger.info(
                                f"Feature flag {feature_flag.key} is unhealthy but already at "
                                f"{feature_flag.rollout_percentage}% (rollback target {target_percentage}%); "
                                "waiting for the error window to clear"
                            )
                            continue

                        # Execute rollback
                        rollback_result = (
                            await safety_service.async_rollback_feature_flag(
                                feature_flag_id=feature_flag.id,
                                percentage=target_percentage,
                                reason=trigger_reason,
                                trigger_type=RollbackTriggerType.AUTOMATIC,
                            )
                        )

                        if rollback_result.success:
                            logger.info(
                                f"Successfully rolled back feature flag {feature_flag.key}: {rollback_result.message}"
                            )
                            try:
                                self._notification_service.notify_safety_rollback(
                                    feature_flag_id=str(feature_flag.id),
                                    feature_flag_name=feature_flag.key,
                                    reason=trigger_reason,
                                )
                            except Exception as exc:
                                logger.warning(
                                    "Notification failed (non-critical): %s", exc
                                )
                        else:
                            logger.error(
                                f"Failed to roll back feature flag {feature_flag.key}: {rollback_result.message}"
                            )

                except Exception as e:
                    logger.error(
                        f"Error checking safety for feature flag {feature_flag.id}: {str(e)}"
                    )

        except Exception as e:
            logger.error(f"Error checking feature flags safety: {str(e)}")
        finally:
            db.close()


# Create a global instance of the safety scheduler
safety_scheduler = SafetyScheduler()
