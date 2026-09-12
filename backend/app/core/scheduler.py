"""
Scheduler for background tasks.

This module provides scheduling functionality for recurring tasks
such as experiment status updates based on scheduled dates.
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.core.metrics import update_active_experiments
from backend.app.core.scheduler_tick import run_locked_tick
from backend.app.db.session import SessionLocal
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.services.notification_service import NotificationService

logger = get_logger(__name__)

SCHEDULER_NAME = "experiment"


class ExperimentScheduler:
    """Handles scheduled tasks for experiments."""

    def __init__(self, interval_minutes: int = 15):
        """
        Initialize the experiment scheduler.

        Args:
            interval_minutes: How often to check for experiments that need to be updated (in minutes)
        """
        self.interval_minutes = interval_minutes
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self._notification_service = NotificationService()

    async def start(self):
        """Start the scheduler."""
        if self.is_running:
            logger.warning("Scheduler is already running")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._run_scheduler())
        logger.info(
            f"Experiment scheduler started with {self.interval_minutes} minute interval"
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
        logger.info("Experiment scheduler stopped")

    async def _run_scheduler(self):
        """Run the scheduler loop."""
        while self.is_running:
            try:
                # One tick under the advisory lock; records the run and
                # skips when another replica holds the lock.
                await run_locked_tick(
                    SCHEDULER_NAME, self.process_scheduled_experiments
                )

                # Wait for the next interval
                await asyncio.sleep(self.interval_minutes * 60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in experiment scheduler: {e!s}")
                # Wait a bit before trying again
                await asyncio.sleep(60)

    async def process_scheduled_experiments(self) -> Dict[str, int]:
        """
        Process experiments that need status updates based on their scheduled dates.

        This checks for:
        1. Experiments in DRAFT or PAUSED status that should be activated
        2. Experiments in ACTIVE status that should be completed (time-based)
        3. Experiments in ACTIVE status that should be stopped due to
           bayesian_decision being STOP_WINNER or STOP_FUTILE (EP-035 Batch 2)

        Returns ``{"items_processed": n, "items_failed": m}`` for the run record.
        """
        logger.info("Processing scheduled experiments")

        activated_count = 0
        completed_count = 0
        bayesian_stopped_count = 0
        failed_count = 0

        # Use a new database session for this task
        db = SessionLocal()
        try:
            current_time = datetime.now(timezone.utc)

            # Find experiments to activate (start_date has passed)
            experiments_to_activate = (
                db.query(Experiment)
                .filter(
                    and_(
                        Experiment.status.in_(
                            [ExperimentStatus.DRAFT, ExperimentStatus.PAUSED]
                        ),
                        Experiment.start_date.isnot(None),
                        Experiment.start_date <= current_time,
                    )
                )
                .all()
            )

            # Activate experiments
            for experiment in experiments_to_activate:
                try:
                    experiment.status = ExperimentStatus.ACTIVE
                    experiment.updated_at = current_time
                    db.add(experiment)
                    activated_count += 1
                    logger.info(
                        f"Activating experiment: {experiment.id} - {experiment.name} "
                        f"(scheduled start: {experiment.start_date})"
                    )
                    try:
                        self._notification_service.notify_experiment_started(
                            experiment_id=str(experiment.id),
                            experiment_name=experiment.name,
                        )
                    except Exception as exc:
                        logger.warning("Notification failed (non-critical): %s", exc)
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error activating experiment {experiment.id}: {e!s}")

            # Commit all activation changes before checking for experiments to complete
            if activated_count > 0:
                db.commit()

            # Find experiments to complete (end_date has passed)
            experiments_to_complete = (
                db.query(Experiment)
                .filter(
                    and_(
                        Experiment.status == ExperimentStatus.ACTIVE,
                        Experiment.end_date.isnot(None),
                        Experiment.end_date <= current_time,
                    )
                )
                .all()
            )

            # Complete experiments
            for experiment in experiments_to_complete:
                try:
                    experiment.status = ExperimentStatus.COMPLETED
                    experiment.updated_at = current_time
                    db.add(experiment)
                    completed_count += 1
                    logger.info(
                        f"Completing experiment: {experiment.id} - {experiment.name} "
                        f"(scheduled end: {experiment.end_date})"
                    )
                    try:
                        self._notification_service.notify_experiment_ended(
                            experiment_id=str(experiment.id),
                            experiment_name=experiment.name,
                        )
                    except Exception as exc:
                        logger.warning("Notification failed (non-critical): %s", exc)
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error completing experiment {experiment.id}: {e!s}")

            # Commit completion changes
            if completed_count > 0:
                db.commit()

            # EP-035 Batch 2: Stop ACTIVE experiments where bayesian_decision
            # is STOP_WINNER or STOP_FUTILE (Bayesian stopping rules triggered).
            try:
                _bayesian_stop_decisions = ("STOP_WINNER", "STOP_FUTILE")
                experiments_to_bayesian_stop = (
                    db.query(Experiment)
                    .filter(
                        and_(
                            Experiment.status == ExperimentStatus.ACTIVE,
                            Experiment.bayesian_decision.in_(_bayesian_stop_decisions),
                        )
                    )
                    .all()
                )

                for experiment in experiments_to_bayesian_stop:
                    try:
                        experiment.status = ExperimentStatus.COMPLETED
                        experiment.updated_at = current_time
                        db.add(experiment)
                        bayesian_stopped_count += 1
                        logger.info(
                            f"Bayesian stopping experiment: {experiment.id} - "
                            f"{experiment.name} "
                            f"(bayesian_decision: {experiment.bayesian_decision})"
                        )
                        try:
                            self._notification_service.notify_experiment_ended(
                                experiment_id=str(experiment.id),
                                experiment_name=experiment.name,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Notification failed (non-critical): %s", exc
                            )
                    except Exception as e:
                        failed_count += 1
                        logger.error(
                            f"Error bayesian-stopping experiment {experiment.id}: {e!s}"
                        )

                if bayesian_stopped_count > 0:
                    db.commit()
            except Exception as e:
                logger.error(f"Error processing bayesian stopping rules: {e!s}")

            # Log the results
            total_completed = completed_count + bayesian_stopped_count
            if activated_count > 0 or total_completed > 0:
                logger.info(
                    f"Updated {activated_count} experiments to ACTIVE, "
                    f"{completed_count} to COMPLETED (time-based), "
                    f"{bayesian_stopped_count} to COMPLETED (bayesian stopping)"
                )
            else:
                logger.info("No experiments required scheduling updates")

            # Prometheus: active_experiments_gauge reflects the post-tick state.
            self._update_active_experiments_gauge(db)

        except Exception as e:
            failed_count += 1
            logger.error(f"Error processing scheduled experiments: {e!s}")
        finally:
            db.close()

        return {
            "items_processed": activated_count
            + completed_count
            + bayesian_stopped_count,
            "items_failed": failed_count,
            "metadata": {
                "activated": activated_count,
                "completed": completed_count,
                "bayesian_stopped": bayesian_stopped_count,
            },
        }

    @staticmethod
    def _update_active_experiments_gauge(db: Session) -> None:
        """Set ``active_experiments_gauge`` from the database (best-effort)."""
        try:
            count = (
                db.query(Experiment)
                .filter(Experiment.status == ExperimentStatus.ACTIVE)
                .count()
            )
            if isinstance(count, int):
                update_active_experiments(count)
        except Exception as exc:  # pragma: no cover - metrics must never break the tick
            logger.debug(f"Could not update active_experiments_gauge: {exc}")


# Create a singleton instance of the scheduler
experiment_scheduler = ExperimentScheduler()
