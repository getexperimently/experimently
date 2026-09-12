"""
Unit tests for scheduler Pydantic schemas (P3-B TDD).

Tests cover:
- SchedulerName enum values
- SchedulerRunStatus enum values
- SchedulerRunRecord fields and defaults
- SchedulerHealthResponse structure
- SchedulerNotificationConfig defaults
- NotificationEvent structure
- SchedulerConfigUpdate validation (interval_minutes bounds, max_retries bounds)
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.scheduler import (
    NotificationEvent,
    SchedulerConfigUpdate,
    SchedulerHealthResponse,
    SchedulerName,
    SchedulerNotificationConfig,
    SchedulerRunRecord,
    SchedulerRunStatus,
)

# ---------------------------------------------------------------------------
# SchedulerName enum
# ---------------------------------------------------------------------------


class TestSchedulerNameEnum:
    def test_experiment_value(self):
        assert SchedulerName.EXPERIMENT == "experiment"

    def test_rollout_value(self):
        assert SchedulerName.ROLLOUT == "rollout"

    def test_metrics_value(self):
        assert SchedulerName.METRICS == "metrics"

    def test_safety_value(self):
        assert SchedulerName.SAFETY == "safety"

    def test_bandit_value(self):
        assert SchedulerName.BANDIT == "bandit"

    def test_all_values(self):
        assert {m.value for m in SchedulerName} == {
            "experiment",
            "rollout",
            "metrics",
            "safety",
            "bandit",
        }


# ---------------------------------------------------------------------------
# SchedulerRunStatus enum
# ---------------------------------------------------------------------------


class TestSchedulerRunStatusEnum:
    def test_success_value(self):
        assert SchedulerRunStatus.SUCCESS == "success"

    def test_partial_value(self):
        assert SchedulerRunStatus.PARTIAL == "partial"

    def test_failed_value(self):
        assert SchedulerRunStatus.FAILED == "failed"

    def test_skipped_value(self):
        assert SchedulerRunStatus.SKIPPED == "skipped"

    def test_all_four_statuses(self):
        assert len(list(SchedulerRunStatus)) == 4


# ---------------------------------------------------------------------------
# SchedulerRunRecord
# ---------------------------------------------------------------------------


class TestSchedulerRunRecord:
    def test_minimal_valid_record(self):
        record = SchedulerRunRecord(
            scheduler_name=SchedulerName.EXPERIMENT,
            started_at="2026-03-01T00:00:00Z",
            status=SchedulerRunStatus.SUCCESS,
        )
        assert record.scheduler_name == SchedulerName.EXPERIMENT
        assert record.started_at == "2026-03-01T00:00:00Z"
        assert record.status == SchedulerRunStatus.SUCCESS

    def test_default_items_processed_is_zero(self):
        record = SchedulerRunRecord(
            scheduler_name=SchedulerName.METRICS,
            started_at="2026-03-01T00:00:00Z",
            status=SchedulerRunStatus.SKIPPED,
        )
        assert record.items_processed == 0

    def test_default_items_failed_is_zero(self):
        record = SchedulerRunRecord(
            scheduler_name=SchedulerName.SAFETY,
            started_at="2026-03-01T00:00:00Z",
            status=SchedulerRunStatus.SKIPPED,
        )
        assert record.items_failed == 0

    def test_default_metadata_is_empty_dict(self):
        record = SchedulerRunRecord(
            scheduler_name=SchedulerName.ROLLOUT,
            started_at="2026-03-01T00:00:00Z",
            status=SchedulerRunStatus.SUCCESS,
        )
        assert record.metadata == {}

    def test_default_id_is_none(self):
        record = SchedulerRunRecord(
            scheduler_name=SchedulerName.EXPERIMENT,
            started_at="2026-03-01T00:00:00Z",
            status=SchedulerRunStatus.SUCCESS,
        )
        assert record.id is None

    def test_default_completed_at_is_none(self):
        record = SchedulerRunRecord(
            scheduler_name=SchedulerName.EXPERIMENT,
            started_at="2026-03-01T00:00:00Z",
            status=SchedulerRunStatus.SUCCESS,
        )
        assert record.completed_at is None

    def test_default_error_message_is_none(self):
        record = SchedulerRunRecord(
            scheduler_name=SchedulerName.EXPERIMENT,
            started_at="2026-03-01T00:00:00Z",
            status=SchedulerRunStatus.SUCCESS,
        )
        assert record.error_message is None

    def test_full_record_with_all_fields(self):
        record = SchedulerRunRecord(
            id="abc-123",
            scheduler_name=SchedulerName.SAFETY,
            started_at="2026-03-01T10:00:00Z",
            completed_at="2026-03-01T10:00:05Z",
            status=SchedulerRunStatus.PARTIAL,
            items_processed=8,
            items_failed=2,
            error_message="2 flags failed safety check",
            metadata={"flags_checked": 10},
        )
        assert record.id == "abc-123"
        assert record.items_processed == 8
        assert record.items_failed == 2
        assert record.error_message == "2 flags failed safety check"
        assert record.metadata == {"flags_checked": 10}

    def test_invalid_scheduler_name_raises(self):
        with pytest.raises(ValidationError):
            SchedulerRunRecord(
                scheduler_name="invalid_name",
                started_at="2026-03-01T00:00:00Z",
                status=SchedulerRunStatus.SUCCESS,
            )

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            SchedulerRunRecord(
                scheduler_name=SchedulerName.EXPERIMENT,
                started_at="2026-03-01T00:00:00Z",
                status="invalid_status",
            )


# ---------------------------------------------------------------------------
# SchedulerHealthResponse
# ---------------------------------------------------------------------------


class TestSchedulerHealthResponse:
    def test_minimal_health_response(self):
        health = SchedulerHealthResponse(
            scheduler_name=SchedulerName.EXPERIMENT,
            is_running=True,
        )
        assert health.scheduler_name == SchedulerName.EXPERIMENT
        assert health.is_running is True

    def test_defaults_for_optional_fields(self):
        health = SchedulerHealthResponse(
            scheduler_name=SchedulerName.ROLLOUT,
            is_running=False,
        )
        assert health.last_run_at is None
        assert health.last_run_status is None
        assert health.consecutive_failures == 0
        assert health.next_run_at is None
        assert health.average_duration_seconds is None


# ---------------------------------------------------------------------------
# SchedulerNotificationConfig
# ---------------------------------------------------------------------------


class TestSchedulerNotificationConfig:
    def test_defaults(self):
        config = SchedulerNotificationConfig()
        assert config.webhook_url is None
        assert config.notify_on == [SchedulerRunStatus.FAILED]
        assert config.experiment_id is None

    def test_custom_notify_on(self):
        config = SchedulerNotificationConfig(
            notify_on=[SchedulerRunStatus.FAILED, SchedulerRunStatus.PARTIAL]
        )
        assert SchedulerRunStatus.PARTIAL in config.notify_on

    def test_with_webhook_url(self):
        config = SchedulerNotificationConfig(
            webhook_url="https://hooks.slack.com/services/T00/B00/xxx"
        )
        assert "slack.com" in config.webhook_url


# ---------------------------------------------------------------------------
# NotificationEvent
# ---------------------------------------------------------------------------


class TestNotificationEvent:
    def test_minimal_event(self):
        event = NotificationEvent(
            event_type="experiment_started",
            message="Experiment X has started",
            timestamp="2026-03-01T10:00:00Z",
        )
        assert event.event_type == "experiment_started"
        assert event.message == "Experiment X has started"
        assert event.timestamp == "2026-03-01T10:00:00Z"

    def test_default_metadata_is_empty(self):
        event = NotificationEvent(
            event_type="safety_rollback",
            message="Flag rolled back",
            timestamp="2026-03-01T10:00:00Z",
        )
        assert event.metadata == {}

    def test_optional_ids_default_to_none(self):
        event = NotificationEvent(
            event_type="rollout_advanced",
            message="Rollout advanced to 50%",
            timestamp="2026-03-01T10:00:00Z",
        )
        assert event.experiment_id is None
        assert event.feature_flag_id is None
        assert event.old_status is None
        assert event.new_status is None


# ---------------------------------------------------------------------------
# SchedulerConfigUpdate
# ---------------------------------------------------------------------------


class TestSchedulerConfigUpdate:
    def test_defaults(self):
        config = SchedulerConfigUpdate()
        assert config.enabled is True
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 60
        assert config.interval_minutes is None

    def test_valid_interval_minutes(self):
        config = SchedulerConfigUpdate(interval_minutes=15)
        assert config.interval_minutes == 15

    def test_interval_minutes_min_bound(self):
        config = SchedulerConfigUpdate(interval_minutes=1)
        assert config.interval_minutes == 1

    def test_interval_minutes_max_bound(self):
        config = SchedulerConfigUpdate(interval_minutes=1440)
        assert config.interval_minutes == 1440

    def test_interval_minutes_below_min_raises(self):
        with pytest.raises(ValidationError):
            SchedulerConfigUpdate(interval_minutes=0)

    def test_interval_minutes_above_max_raises(self):
        with pytest.raises(ValidationError):
            SchedulerConfigUpdate(interval_minutes=1441)

    def test_max_retries_min_bound(self):
        config = SchedulerConfigUpdate(max_retries=0)
        assert config.max_retries == 0

    def test_max_retries_max_bound(self):
        config = SchedulerConfigUpdate(max_retries=10)
        assert config.max_retries == 10

    def test_max_retries_above_max_raises(self):
        with pytest.raises(ValidationError):
            SchedulerConfigUpdate(max_retries=11)

    def test_retry_delay_seconds_min_bound(self):
        config = SchedulerConfigUpdate(retry_delay_seconds=10)
        assert config.retry_delay_seconds == 10

    def test_retry_delay_seconds_max_bound(self):
        config = SchedulerConfigUpdate(retry_delay_seconds=3600)
        assert config.retry_delay_seconds == 3600

    def test_retry_delay_below_min_raises(self):
        with pytest.raises(ValidationError):
            SchedulerConfigUpdate(retry_delay_seconds=9)

    def test_retry_delay_above_max_raises(self):
        with pytest.raises(ValidationError):
            SchedulerConfigUpdate(retry_delay_seconds=3601)
