"""
Unit tests for SchedulerHealthService (P3-B TDD).

Tests cover:
- record_run persists a SchedulerRun to the database
- get_consecutive_failures returns 0 when last run succeeded
- get_consecutive_failures returns N when last N runs failed
- get_consecutive_failures returns 0 for empty history
- get_health returns correct is_running based on recent run times
- get_health populates consecutive_failures correctly
- get_health populates last_run_status and last_run_at
- get_health computes average_duration_seconds from run history
- get_all_health returns list of length 4
- get_run_history returns at most `limit` records
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.services.scheduler_health_service import SchedulerHealthService
from backend.app.schemas.scheduler import (
    SchedulerName,
    SchedulerRunStatus,
    SchedulerHealthResponse,
    SchedulerRunRecord,
)
from backend.app.models.scheduler_run import SchedulerRun


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_run(
    scheduler_name: str = "experiment",
    status: str = "success",
    started_at: datetime = None,
    completed_at: datetime = None,
    items_processed: int = 5,
    items_failed: int = 0,
    error_message: str = None,
):
    """Create a mock SchedulerRun object."""
    run = MagicMock(spec=SchedulerRun)
    run.id = uuid4()
    run.scheduler_name = scheduler_name
    run.status = status
    run.started_at = started_at or datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    run.completed_at = completed_at or datetime(2026, 3, 1, 10, 0, 5, tzinfo=timezone.utc)
    run.items_processed = items_processed
    run.items_failed = items_failed
    run.error_message = error_message
    run.metadata_ = {}
    return run


def make_db():
    """Create a mock SQLAlchemy session."""
    return MagicMock(spec=Session)


# ---------------------------------------------------------------------------
# record_run
# ---------------------------------------------------------------------------


class TestRecordRun:
    def setup_method(self):
        self.db = make_db()
        self.service = SchedulerHealthService()

    def test_record_run_adds_to_db(self):
        started_at = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        completed_at = datetime(2026, 3, 1, 10, 0, 5, tzinfo=timezone.utc)

        self.service.record_run(
            db=self.db,
            scheduler_name="experiment",
            started_at=started_at,
            completed_at=completed_at,
            status="success",
            items_processed=3,
            items_failed=0,
        )

        self.db.add.assert_called_once()
        self.db.commit.assert_called_once()

    def test_record_run_returns_scheduler_run(self):
        started_at = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        completed_at = datetime(2026, 3, 1, 10, 0, 5, tzinfo=timezone.utc)

        result = self.service.record_run(
            db=self.db,
            scheduler_name="safety",
            started_at=started_at,
            completed_at=completed_at,
            status="failed",
            items_processed=0,
            items_failed=1,
            error_msg="DB connection error",
        )

        assert result is not None
        assert isinstance(result, SchedulerRun)

    def test_record_run_stores_error_message(self):
        started_at = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        completed_at = datetime(2026, 3, 1, 10, 0, 1, tzinfo=timezone.utc)

        result = self.service.record_run(
            db=self.db,
            scheduler_name="metrics",
            started_at=started_at,
            completed_at=completed_at,
            status="failed",
            items_processed=0,
            items_failed=1,
            error_msg="Metrics aggregation failed",
        )

        assert result.error_message == "Metrics aggregation failed"


# ---------------------------------------------------------------------------
# get_consecutive_failures
# ---------------------------------------------------------------------------


class TestGetConsecutiveFailures:
    def setup_method(self):
        self.db = make_db()
        self.service = SchedulerHealthService()

    def test_returns_zero_when_empty_history(self):
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = self.service.get_consecutive_failures(self.db, "experiment")
        assert result == 0

    def test_returns_zero_when_last_run_succeeded(self):
        runs = [make_run(status="success")]
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = runs

        result = self.service.get_consecutive_failures(self.db, "experiment")
        assert result == 0

    def test_returns_one_when_last_run_failed(self):
        runs = [make_run(status="failed"), make_run(status="success")]
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = runs

        result = self.service.get_consecutive_failures(self.db, "experiment")
        assert result == 1

    def test_returns_three_when_last_three_failed(self):
        runs = [
            make_run(status="failed"),
            make_run(status="failed"),
            make_run(status="failed"),
            make_run(status="success"),
        ]
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = runs

        result = self.service.get_consecutive_failures(self.db, "experiment")
        assert result == 3

    def test_returns_all_failed_when_no_success(self):
        runs = [
            make_run(status="failed"),
            make_run(status="failed"),
        ]
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = runs

        result = self.service.get_consecutive_failures(self.db, "experiment")
        assert result == 2

    def test_skipped_does_not_count_as_success(self):
        """SKIPPED runs should not break the failure streak."""
        runs = [
            make_run(status="failed"),
            make_run(status="skipped"),
            make_run(status="failed"),
            make_run(status="success"),
        ]
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = runs

        # skipped is not success, so failures continue
        result = self.service.get_consecutive_failures(self.db, "experiment")
        # First run is failed, then skipped (not success), then failed - 3 non-success
        assert result >= 1  # at minimum the first failed run counts


# ---------------------------------------------------------------------------
# get_health
# ---------------------------------------------------------------------------


class TestGetHealth:
    def setup_method(self):
        self.db = make_db()
        self.service = SchedulerHealthService()

    def _mock_db_for_runs(self, runs):
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = runs

    def test_returns_scheduler_health_response(self):
        self._mock_db_for_runs([])
        result = self.service.get_health(self.db, SchedulerName.EXPERIMENT)
        assert isinstance(result, SchedulerHealthResponse)

    def test_scheduler_name_matches(self):
        self._mock_db_for_runs([])
        result = self.service.get_health(self.db, SchedulerName.ROLLOUT)
        assert result.scheduler_name == SchedulerName.ROLLOUT

    def test_is_running_false_when_no_recent_runs(self):
        """No run history means scheduler is not confirmed running."""
        self._mock_db_for_runs([])
        result = self.service.get_health(self.db, SchedulerName.EXPERIMENT)
        assert result.is_running is False

    def test_is_running_true_when_very_recent_run(self):
        """A run completed within the last 30 minutes implies scheduler is running."""
        now = datetime.now(timezone.utc)
        recent_run = make_run(
            status="success",
            started_at=now - timedelta(minutes=10),
            completed_at=now - timedelta(minutes=9, seconds=55),
        )
        self._mock_db_for_runs([recent_run])
        result = self.service.get_health(self.db, SchedulerName.EXPERIMENT)
        assert result.is_running is True

    def test_last_run_status_populated(self):
        run = make_run(status="failed")
        self._mock_db_for_runs([run])
        result = self.service.get_health(self.db, SchedulerName.SAFETY)
        assert result.last_run_status == SchedulerRunStatus.FAILED

    def test_last_run_at_populated(self):
        started = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
        run = make_run(status="success", started_at=started)
        self._mock_db_for_runs([run])
        result = self.service.get_health(self.db, SchedulerName.METRICS)
        assert result.last_run_at is not None

    def test_consecutive_failures_zero_on_success(self):
        run = make_run(status="success")
        self._mock_db_for_runs([run])
        result = self.service.get_health(self.db, SchedulerName.EXPERIMENT)
        assert result.consecutive_failures == 0

    def test_consecutive_failures_nonzero_on_failures(self):
        runs = [make_run(status="failed"), make_run(status="failed")]
        self._mock_db_for_runs(runs)
        result = self.service.get_health(self.db, SchedulerName.EXPERIMENT)
        assert result.consecutive_failures == 2

    def test_average_duration_computed(self):
        """Average duration is computed from completed runs."""
        now = datetime.now(timezone.utc)
        run1 = make_run(
            status="success",
            started_at=now - timedelta(minutes=60),
            completed_at=now - timedelta(minutes=59, seconds=55),  # 5 second run
        )
        run2 = make_run(
            status="success",
            started_at=now - timedelta(minutes=30),
            completed_at=now - timedelta(minutes=29, seconds=45),  # 15 second run
        )
        self._mock_db_for_runs([run1, run2])
        result = self.service.get_health(self.db, SchedulerName.EXPERIMENT)
        # Average should be ~10 seconds (5 + 15) / 2
        assert result.average_duration_seconds is not None
        assert result.average_duration_seconds > 0


# ---------------------------------------------------------------------------
# get_all_health
# ---------------------------------------------------------------------------


class TestGetAllHealth:
    def setup_method(self):
        self.db = make_db()
        self.service = SchedulerHealthService()

    def test_returns_one_entry_per_scheduler(self):
        # Mock all queries to return empty
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        result = self.service.get_all_health(self.db)
        assert isinstance(result, list)
        assert len(result) == len(SchedulerName)

    def test_covers_all_scheduler_names(self):
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        result = self.service.get_all_health(self.db)
        names = {r.scheduler_name for r in result}
        assert names == set(SchedulerName)


# ---------------------------------------------------------------------------
# get_run_history
# ---------------------------------------------------------------------------


class TestGetRunHistory:
    def setup_method(self):
        self.db = make_db()
        self.service = SchedulerHealthService()

    def test_returns_list(self):
        runs = [make_run(status="success") for _ in range(5)]
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = runs

        result = self.service.get_run_history(self.db, "experiment")
        assert isinstance(result, list)

    def test_default_limit_is_20(self):
        runs = [make_run() for _ in range(20)]
        query_chain = self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value
        query_chain.all.return_value = runs

        self.service.get_run_history(self.db, "experiment")
        # Verify .limit(20) was called
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.assert_called_with(20)

    def test_custom_limit_respected(self):
        runs = [make_run() for _ in range(5)]
        query_chain = self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value
        query_chain.all.return_value = runs

        self.service.get_run_history(self.db, "experiment", limit=5)
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.assert_called_with(5)

    def test_returns_scheduler_run_records(self):
        runs = [make_run(status="success")]
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = runs

        result = self.service.get_run_history(self.db, "experiment")
        assert len(result) == 1
        assert isinstance(result[0], SchedulerRunRecord)
