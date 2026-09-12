"""
Scheduler health service for tracking and exposing scheduler run history and health.

Persists run history to the database and provides queryable health information
for each background scheduler including consecutive failure counts and average
run durations.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.app.models.scheduler_run import SchedulerRun
from backend.app.schemas.scheduler import (
    SchedulerHealthResponse,
    SchedulerName,
    SchedulerRunRecord,
    SchedulerRunStatus,
)

logger = logging.getLogger(__name__)

# A scheduler is considered "running" if it completed a run within the last N minutes.
_RUNNING_THRESHOLD_MINUTES = 30

# Number of recent runs to inspect for health calculations.
_HEALTH_LOOKBACK = 20


class SchedulerHealthService:
    """Tracks and exposes scheduler health and run history."""

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def record_run(
        self,
        db: Session,
        scheduler_name: str,
        started_at: datetime,
        completed_at: Optional[datetime],
        status: str,
        items_processed: int = 0,
        items_failed: int = 0,
        error_msg: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> SchedulerRun:
        """
        Persist a scheduler run record to the database.

        Args:
            db: Active SQLAlchemy session.
            scheduler_name: One of the SchedulerName values ("experiment", etc.).
            started_at: UTC datetime when the run began.
            completed_at: UTC datetime when the run finished (None if still running).
            status: One of the SchedulerRunStatus values.
            items_processed: Number of items successfully processed.
            items_failed: Number of items that failed.
            error_msg: Human-readable error message for failed runs.
            metadata: Optional dict of additional run metadata.

        Returns:
            The persisted SchedulerRun instance.
        """
        run = SchedulerRun(
            scheduler_name=scheduler_name,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            items_processed=items_processed,
            items_failed=items_failed,
            error_message=error_msg,
            metadata_=metadata or {},
        )
        db.add(run)
        db.commit()
        logger.debug(
            "Recorded scheduler run: scheduler=%s status=%s items_processed=%d",
            scheduler_name,
            status,
            items_processed,
        )
        return run

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def _fetch_recent_runs(
        self, db: Session, scheduler_name: str, limit: int = _HEALTH_LOOKBACK
    ) -> list:
        """Fetch the most recent runs for a scheduler, newest first."""
        return (
            db.query(SchedulerRun)
            .filter(SchedulerRun.scheduler_name == scheduler_name)
            .order_by(desc(SchedulerRun.started_at))
            .limit(limit)
            .all()
        )

    def get_consecutive_failures(
        self, db: Session, scheduler_name: str, limit: int = 10
    ) -> int:
        """
        Count consecutive failures from the most recent run backwards until
        a successful run is encountered.

        A run is considered successful only when its status is "success".
        Runs with status "skipped" or "partial" do not break the failure streak.

        Args:
            db: Active SQLAlchemy session.
            scheduler_name: Scheduler name to query.
            limit: Maximum number of recent runs to inspect.

        Returns:
            Number of consecutive non-successful runs from the most recent run.
        """
        runs = (
            db.query(SchedulerRun)
            .filter(SchedulerRun.scheduler_name == scheduler_name)
            .order_by(desc(SchedulerRun.started_at))
            .limit(limit)
            .all()
        )

        consecutive = 0
        for run in runs:
            if run.status == SchedulerRunStatus.SUCCESS or run.status == "success":
                break
            consecutive += 1
        return consecutive

    def get_health(
        self, db: Session, scheduler_name: SchedulerName
    ) -> SchedulerHealthResponse:
        """
        Compute the current health state for a single scheduler.

        Args:
            db: Active SQLAlchemy session.
            scheduler_name: Which scheduler to query.

        Returns:
            SchedulerHealthResponse with is_running, consecutive_failures,
            last_run_at, last_run_status, and average_duration_seconds.
        """
        name_str = (
            scheduler_name.value if hasattr(scheduler_name, "value") else scheduler_name
        )
        runs = self._fetch_recent_runs(db, name_str)

        if not runs:
            return SchedulerHealthResponse(
                scheduler_name=scheduler_name,
                is_running=False,
            )

        latest = runs[0]

        # Determine if the scheduler is running based on recent activity.
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(minutes=_RUNNING_THRESHOLD_MINUTES)

        latest_completed = latest.completed_at
        if latest_completed and latest_completed.tzinfo is None:
            latest_completed = latest_completed.replace(tzinfo=timezone.utc)

        latest_started = latest.started_at
        if latest_started and latest_started.tzinfo is None:
            latest_started = latest_started.replace(tzinfo=timezone.utc)

        is_running = bool(latest_completed and latest_completed >= threshold) or bool(
            latest_started and latest_started >= threshold
        )

        # Map raw status string to enum
        def _to_status(s: str) -> Optional[SchedulerRunStatus]:
            try:
                return SchedulerRunStatus(s)
            except ValueError:
                return None

        last_run_status = _to_status(latest.status)

        # Last run timestamp as ISO string
        last_run_at = None
        if latest_started:
            last_run_at = (
                latest_started.isoformat()
                if latest_started.tzinfo
                else (latest_started.replace(tzinfo=timezone.utc).isoformat())
            )

        # Consecutive failures
        consecutive_failures = 0
        for run in runs:
            if run.status == SchedulerRunStatus.SUCCESS or run.status == "success":
                break
            consecutive_failures += 1

        # Average duration (only for runs that have both started_at and completed_at)
        durations = []
        for run in runs:
            if run.started_at and run.completed_at:
                st = run.started_at
                ct = run.completed_at
                if st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)
                if ct.tzinfo is None:
                    ct = ct.replace(tzinfo=timezone.utc)
                duration = (ct - st).total_seconds()
                if duration >= 0:
                    durations.append(duration)

        average_duration_seconds = (
            sum(durations) / len(durations) if durations else None
        )

        return SchedulerHealthResponse(
            scheduler_name=scheduler_name,
            is_running=is_running,
            last_run_at=last_run_at,
            last_run_status=last_run_status,
            consecutive_failures=consecutive_failures,
            average_duration_seconds=average_duration_seconds,
        )

    def get_all_health(self, db: Session) -> list[SchedulerHealthResponse]:
        """
        Return health status for all four background schedulers.

        Returns:
            List of four SchedulerHealthResponse objects, one per scheduler.
        """
        return [self.get_health(db, name) for name in SchedulerName]

    def get_run_history(
        self,
        db: Session,
        scheduler_name: str,
        limit: int = 20,
    ) -> list[SchedulerRunRecord]:
        """
        Return paginated run history for a scheduler.

        Args:
            db: Active SQLAlchemy session.
            scheduler_name: Name of the scheduler to query.
            limit: Maximum number of records to return (default 20).

        Returns:
            List of SchedulerRunRecord objects ordered newest-first.
        """
        runs = (
            db.query(SchedulerRun)
            .filter(SchedulerRun.scheduler_name == scheduler_name)
            .order_by(desc(SchedulerRun.started_at))
            .limit(limit)
            .all()
        )

        records = []
        for run in runs:
            started_iso = None
            if run.started_at:
                st = run.started_at
                if st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)
                started_iso = st.isoformat()

            completed_iso = None
            if run.completed_at:
                ct = run.completed_at
                if ct.tzinfo is None:
                    ct = ct.replace(tzinfo=timezone.utc)
                completed_iso = ct.isoformat()

            try:
                sched_name = SchedulerName(run.scheduler_name)
            except ValueError:
                sched_name = run.scheduler_name

            try:
                status = SchedulerRunStatus(run.status)
            except ValueError:
                status = run.status

            records.append(
                SchedulerRunRecord(
                    id=str(run.id),
                    scheduler_name=sched_name,
                    started_at=started_iso or "",
                    completed_at=completed_iso,
                    status=status,
                    items_processed=run.items_processed or 0,
                    items_failed=run.items_failed or 0,
                    error_message=run.error_message,
                    metadata=run.metadata_ or {},
                )
            )
        return records
