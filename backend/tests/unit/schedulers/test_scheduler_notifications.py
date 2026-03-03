"""
Tests for EP-030 Batch 3A: Scheduler -> NotificationService wiring.

Verifies that each scheduler calls the appropriate NotificationService method
on key events, and that notification failures never disrupt primary scheduler logic.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock, call
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Safety Scheduler Tests
# ---------------------------------------------------------------------------


class TestSafetySchedulerNotifications:
    """Tests that SafetyScheduler calls NotificationService on safety rollback events."""

    @pytest.mark.asyncio
    async def test_safety_rollback_calls_notify_safety_rollback(self):
        """notify_safety_rollback is called when a rollback succeeds."""
        mock_notification_service = MagicMock()
        mock_notification_service.notify_safety_rollback = MagicMock(return_value=True)

        # Build lightweight mocks for all DB/service collaborators
        mock_flag = MagicMock()
        mock_flag.id = "flag-uuid-1"
        mock_flag.key = "my-feature-flag"
        mock_flag.rollout_percentage = 50

        mock_metric = MagicMock()
        mock_metric.is_healthy = False
        mock_metric.name = "error_rate"
        mock_metric.current_value = 0.15
        mock_metric.threshold = 0.05

        mock_safety_check = MagicMock()
        mock_safety_check.is_healthy = False
        mock_safety_check.details = "error_rate too high"
        mock_safety_check.metrics = [mock_metric]

        mock_config = MagicMock()
        mock_config.enabled = True

        mock_settings = MagicMock()
        mock_settings.enable_automatic_rollbacks = True

        mock_rollback_result = MagicMock()
        mock_rollback_result.success = True
        mock_rollback_result.message = "Rolled back to 0%"

        mock_safety_service = MagicMock()
        mock_safety_service.async_get_feature_flag_safety_config = AsyncMock(return_value=mock_config)
        mock_safety_service.check_feature_flag_safety = AsyncMock(return_value=mock_safety_check)
        mock_safety_service.async_get_safety_settings = AsyncMock(return_value=mock_settings)
        mock_safety_service.async_rollback_feature_flag = AsyncMock(return_value=mock_rollback_result)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_flag]

        with patch("backend.app.core.safety_scheduler.SessionLocal", return_value=mock_db), \
             patch("backend.app.core.safety_scheduler.SafetyService", return_value=mock_safety_service):

            from backend.app.core.safety_scheduler import SafetyScheduler
            scheduler = SafetyScheduler()
            scheduler._notification_service = mock_notification_service

            await scheduler.check_feature_flags_safety()

        mock_notification_service.notify_safety_rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_safety_rollback_notification_swallows_errors(self):
        """A notification failure does not propagate and scheduler continues."""
        mock_notification_service = MagicMock()
        mock_notification_service.notify_safety_rollback.side_effect = RuntimeError("webhook down")

        mock_flag = MagicMock()
        mock_flag.id = "flag-uuid-2"
        mock_flag.key = "another-flag"
        mock_flag.rollout_percentage = 30

        mock_metric = MagicMock()
        mock_metric.is_healthy = False
        mock_metric.name = "latency"
        mock_metric.current_value = 500
        mock_metric.threshold = 200

        mock_safety_check = MagicMock()
        mock_safety_check.is_healthy = False
        mock_safety_check.metrics = [mock_metric]

        mock_config = MagicMock()
        mock_config.enabled = True

        mock_settings = MagicMock()
        mock_settings.enable_automatic_rollbacks = True

        mock_rollback_result = MagicMock()
        mock_rollback_result.success = True
        mock_rollback_result.message = "Rolled back"

        mock_safety_service = MagicMock()
        mock_safety_service.async_get_feature_flag_safety_config = AsyncMock(return_value=mock_config)
        mock_safety_service.check_feature_flag_safety = AsyncMock(return_value=mock_safety_check)
        mock_safety_service.async_get_safety_settings = AsyncMock(return_value=mock_settings)
        mock_safety_service.async_rollback_feature_flag = AsyncMock(return_value=mock_rollback_result)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_flag]

        with patch("backend.app.core.safety_scheduler.SessionLocal", return_value=mock_db), \
             patch("backend.app.core.safety_scheduler.SafetyService", return_value=mock_safety_service):

            from backend.app.core.safety_scheduler import SafetyScheduler
            scheduler = SafetyScheduler()
            scheduler._notification_service = mock_notification_service

            # Should not raise even though notification raises
            await scheduler.check_feature_flags_safety()

        # Notification was attempted
        mock_notification_service.notify_safety_rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_safety_no_rollback_when_healthy_no_notification(self):
        """No notification is sent when the feature flag is healthy."""
        mock_notification_service = MagicMock()

        mock_flag = MagicMock()
        mock_flag.id = "flag-uuid-3"
        mock_flag.key = "healthy-flag"
        mock_flag.rollout_percentage = 20

        mock_safety_check = MagicMock()
        mock_safety_check.is_healthy = True
        mock_safety_check.metrics = []

        mock_config = MagicMock()
        mock_config.enabled = True

        mock_settings = MagicMock()
        mock_settings.enable_automatic_rollbacks = True

        mock_safety_service = MagicMock()
        mock_safety_service.async_get_feature_flag_safety_config = AsyncMock(return_value=mock_config)
        mock_safety_service.check_feature_flag_safety = AsyncMock(return_value=mock_safety_check)
        mock_safety_service.async_get_safety_settings = AsyncMock(return_value=mock_settings)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_flag]

        with patch("backend.app.core.safety_scheduler.SessionLocal", return_value=mock_db), \
             patch("backend.app.core.safety_scheduler.SafetyService", return_value=mock_safety_service):

            from backend.app.core.safety_scheduler import SafetyScheduler
            scheduler = SafetyScheduler()
            scheduler._notification_service = mock_notification_service

            await scheduler.check_feature_flags_safety()

        mock_notification_service.notify_safety_rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_safety_rollback_passes_flag_name(self):
        """notify_safety_rollback receives the correct feature_flag_name argument."""
        mock_notification_service = MagicMock()
        mock_notification_service.notify_safety_rollback = MagicMock(return_value=True)

        mock_flag = MagicMock()
        mock_flag.id = "flag-uuid-4"
        mock_flag.key = "checkout-v2"
        mock_flag.rollout_percentage = 10

        mock_metric = MagicMock()
        mock_metric.is_healthy = False
        mock_metric.name = "error_rate"
        mock_metric.current_value = 0.2
        mock_metric.threshold = 0.05

        mock_safety_check = MagicMock()
        mock_safety_check.is_healthy = False
        mock_safety_check.metrics = [mock_metric]

        mock_config = MagicMock()
        mock_config.enabled = True

        mock_settings = MagicMock()
        mock_settings.enable_automatic_rollbacks = True

        mock_rollback_result = MagicMock()
        mock_rollback_result.success = True
        mock_rollback_result.message = "ok"

        mock_safety_service = MagicMock()
        mock_safety_service.async_get_feature_flag_safety_config = AsyncMock(return_value=mock_config)
        mock_safety_service.check_feature_flag_safety = AsyncMock(return_value=mock_safety_check)
        mock_safety_service.async_get_safety_settings = AsyncMock(return_value=mock_settings)
        mock_safety_service.async_rollback_feature_flag = AsyncMock(return_value=mock_rollback_result)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_flag]

        with patch("backend.app.core.safety_scheduler.SessionLocal", return_value=mock_db), \
             patch("backend.app.core.safety_scheduler.SafetyService", return_value=mock_safety_service):

            from backend.app.core.safety_scheduler import SafetyScheduler
            scheduler = SafetyScheduler()
            scheduler._notification_service = mock_notification_service

            await scheduler.check_feature_flags_safety()

        kwargs = mock_notification_service.notify_safety_rollback.call_args
        assert kwargs[1].get("feature_flag_name") == "checkout-v2" or \
               (kwargs[0] and "checkout-v2" in str(kwargs))

    @pytest.mark.asyncio
    async def test_safety_rollback_passes_reason(self):
        """notify_safety_rollback receives a non-empty reason string."""
        mock_notification_service = MagicMock()
        mock_notification_service.notify_safety_rollback = MagicMock(return_value=True)

        mock_flag = MagicMock()
        mock_flag.id = "flag-uuid-5"
        mock_flag.key = "payments-flag"
        mock_flag.rollout_percentage = 40

        mock_metric = MagicMock()
        mock_metric.is_healthy = False
        mock_metric.name = "error_rate"
        mock_metric.current_value = 0.3
        mock_metric.threshold = 0.1

        mock_safety_check = MagicMock()
        mock_safety_check.is_healthy = False
        mock_safety_check.metrics = [mock_metric]

        mock_config = MagicMock()
        mock_config.enabled = True

        mock_settings = MagicMock()
        mock_settings.enable_automatic_rollbacks = True

        mock_rollback_result = MagicMock()
        mock_rollback_result.success = True
        mock_rollback_result.message = "ok"

        mock_safety_service = MagicMock()
        mock_safety_service.async_get_feature_flag_safety_config = AsyncMock(return_value=mock_config)
        mock_safety_service.check_feature_flag_safety = AsyncMock(return_value=mock_safety_check)
        mock_safety_service.async_get_safety_settings = AsyncMock(return_value=mock_settings)
        mock_safety_service.async_rollback_feature_flag = AsyncMock(return_value=mock_rollback_result)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_flag]

        with patch("backend.app.core.safety_scheduler.SessionLocal", return_value=mock_db), \
             patch("backend.app.core.safety_scheduler.SafetyService", return_value=mock_safety_service):

            from backend.app.core.safety_scheduler import SafetyScheduler
            scheduler = SafetyScheduler()
            scheduler._notification_service = mock_notification_service

            await scheduler.check_feature_flags_safety()

        kwargs = mock_notification_service.notify_safety_rollback.call_args
        # reason is passed as keyword argument
        reason_value = kwargs[1].get("reason", "")
        assert reason_value, "reason should be a non-empty string"
        assert "rollback" in reason_value.lower() or "error_rate" in reason_value.lower()


# ---------------------------------------------------------------------------
# Rollout Scheduler Tests
# ---------------------------------------------------------------------------


class TestRolloutSchedulerNotifications:
    """Tests that RolloutScheduler calls NotificationService when a stage advances."""

    def _make_rollout_mocks(self, flag_id="flag-rollout-1", stage_name="Stage 1", target_pct=25):
        """Build mock objects for RolloutScheduler._activate_stage tests."""
        from backend.app.models.rollout_schedule import RolloutStageStatus

        mock_stage = MagicMock()
        mock_stage.id = "stage-uuid-1"
        mock_stage.name = stage_name
        mock_stage.target_percentage = target_pct
        mock_stage.status = RolloutStageStatus.PENDING
        mock_stage.updated_at = datetime.now(timezone.utc)

        mock_schedule = MagicMock()
        mock_schedule.id = "schedule-uuid-1"
        mock_schedule.feature_flag_id = flag_id

        mock_flag = MagicMock()
        mock_flag.id = flag_id
        mock_flag.key = "my-rollout-flag"
        mock_flag.rollout_percentage = 0

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = mock_flag

        return mock_db, mock_schedule, mock_stage, mock_flag

    @pytest.mark.asyncio
    async def test_rollout_advance_calls_notify_rollout_advanced(self):
        """notify_rollout_advanced is called after _activate_stage succeeds."""
        mock_notification_service = MagicMock()
        mock_notification_service.notify_rollout_advanced = MagicMock(return_value=True)

        mock_db, mock_schedule, mock_stage, mock_flag = self._make_rollout_mocks()

        from backend.app.core.rollout_scheduler import RolloutScheduler
        scheduler = RolloutScheduler()
        scheduler._notification_service = mock_notification_service

        result = await scheduler._activate_stage(
            mock_db, mock_schedule, mock_stage, datetime.now(timezone.utc)
        )

        assert result is True
        mock_notification_service.notify_rollout_advanced.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollout_advance_notification_swallows_errors(self):
        """A notification failure does not prevent _activate_stage from returning True."""
        mock_notification_service = MagicMock()
        mock_notification_service.notify_rollout_advanced.side_effect = RuntimeError("network error")

        mock_db, mock_schedule, mock_stage, mock_flag = self._make_rollout_mocks()

        from backend.app.core.rollout_scheduler import RolloutScheduler
        scheduler = RolloutScheduler()
        scheduler._notification_service = mock_notification_service

        result = await scheduler._activate_stage(
            mock_db, mock_schedule, mock_stage, datetime.now(timezone.utc)
        )

        # Stage was activated successfully despite notification error
        assert result is True
        mock_notification_service.notify_rollout_advanced.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollout_advance_passes_stage_name(self):
        """notify_rollout_advanced receives the correct stage_name."""
        mock_notification_service = MagicMock()

        mock_db, mock_schedule, mock_stage, mock_flag = self._make_rollout_mocks(
            stage_name="Beta Rollout"
        )

        from backend.app.core.rollout_scheduler import RolloutScheduler
        scheduler = RolloutScheduler()
        scheduler._notification_service = mock_notification_service

        await scheduler._activate_stage(
            mock_db, mock_schedule, mock_stage, datetime.now(timezone.utc)
        )

        kwargs = mock_notification_service.notify_rollout_advanced.call_args
        assert kwargs[1].get("stage_name") == "Beta Rollout" or \
               (kwargs[0] and "Beta Rollout" in str(kwargs))

    @pytest.mark.asyncio
    async def test_rollout_advance_passes_percentage(self):
        """notify_rollout_advanced receives the correct new_percentage."""
        mock_notification_service = MagicMock()

        mock_db, mock_schedule, mock_stage, mock_flag = self._make_rollout_mocks(
            target_pct=75
        )

        from backend.app.core.rollout_scheduler import RolloutScheduler
        scheduler = RolloutScheduler()
        scheduler._notification_service = mock_notification_service

        await scheduler._activate_stage(
            mock_db, mock_schedule, mock_stage, datetime.now(timezone.utc)
        )

        kwargs = mock_notification_service.notify_rollout_advanced.call_args
        assert kwargs[1].get("new_percentage") == 75 or \
               (kwargs[0] and 75 in kwargs[0])


# ---------------------------------------------------------------------------
# Experiment Scheduler Tests
# ---------------------------------------------------------------------------


class TestExperimentSchedulerNotifications:
    """Tests that ExperimentScheduler calls NotificationService on experiment events."""

    def _make_experiment_mock(self, exp_id="exp-uuid-1", name="My Experiment",
                               start_date=None, end_date=None):
        """Build a mock Experiment for scheduler tests."""
        from backend.app.models.experiment import ExperimentStatus
        now = datetime.now(timezone.utc)
        mock_exp = MagicMock()
        mock_exp.id = exp_id
        mock_exp.name = name
        mock_exp.start_date = start_date or now
        mock_exp.end_date = end_date or now
        mock_exp.status = ExperimentStatus.DRAFT
        return mock_exp

    @pytest.mark.asyncio
    async def test_experiment_started_calls_notify(self):
        """notify_experiment_started is called for each activated experiment."""
        mock_notification_service = MagicMock()
        mock_notification_service.notify_experiment_started = MagicMock(return_value=True)

        mock_exp = self._make_experiment_mock()

        mock_db = MagicMock()
        # First query returns experiments_to_activate, second returns empty (nothing to complete)
        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [mock_exp],  # experiments_to_activate
            [],          # experiments_to_complete
        ]

        with patch("backend.app.core.scheduler.SessionLocal", return_value=mock_db):
            from backend.app.core.scheduler import ExperimentScheduler
            scheduler = ExperimentScheduler()
            scheduler._notification_service = mock_notification_service

            await scheduler.process_scheduled_experiments()

        mock_notification_service.notify_experiment_started.assert_called_once()

    @pytest.mark.asyncio
    async def test_experiment_completed_calls_notify(self):
        """notify_experiment_ended is called for each completed experiment."""
        mock_notification_service = MagicMock()
        mock_notification_service.notify_experiment_ended = MagicMock(return_value=True)

        mock_exp = self._make_experiment_mock(name="Checkout Experiment")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [],          # nothing to activate
            [mock_exp],  # experiments_to_complete
        ]

        with patch("backend.app.core.scheduler.SessionLocal", return_value=mock_db):
            from backend.app.core.scheduler import ExperimentScheduler
            scheduler = ExperimentScheduler()
            scheduler._notification_service = mock_notification_service

            await scheduler.process_scheduled_experiments()

        mock_notification_service.notify_experiment_ended.assert_called_once()

    @pytest.mark.asyncio
    async def test_experiment_notification_swallows_errors(self):
        """A notification failure does not stop scheduling from completing."""
        mock_notification_service = MagicMock()
        mock_notification_service.notify_experiment_started.side_effect = RuntimeError("slack down")

        mock_exp = self._make_experiment_mock()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [mock_exp],
            [],
        ]

        with patch("backend.app.core.scheduler.SessionLocal", return_value=mock_db):
            from backend.app.core.scheduler import ExperimentScheduler
            scheduler = ExperimentScheduler()
            scheduler._notification_service = mock_notification_service

            # Must not raise
            await scheduler.process_scheduled_experiments()

        mock_notification_service.notify_experiment_started.assert_called_once()

    @pytest.mark.asyncio
    async def test_experiment_started_passes_name(self):
        """notify_experiment_started receives the correct experiment_name."""
        mock_notification_service = MagicMock()

        mock_exp = self._make_experiment_mock(name="Homepage Banner Test")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [mock_exp],
            [],
        ]

        with patch("backend.app.core.scheduler.SessionLocal", return_value=mock_db):
            from backend.app.core.scheduler import ExperimentScheduler
            scheduler = ExperimentScheduler()
            scheduler._notification_service = mock_notification_service

            await scheduler.process_scheduled_experiments()

        kwargs = mock_notification_service.notify_experiment_started.call_args
        assert kwargs[1].get("experiment_name") == "Homepage Banner Test" or \
               (kwargs[0] and "Homepage Banner Test" in str(kwargs))

    @pytest.mark.asyncio
    async def test_experiment_completed_passes_name(self):
        """notify_experiment_ended receives the correct experiment_name."""
        mock_notification_service = MagicMock()

        mock_exp = self._make_experiment_mock(name="Search Ranking V2")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [],
            [mock_exp],
        ]

        with patch("backend.app.core.scheduler.SessionLocal", return_value=mock_db):
            from backend.app.core.scheduler import ExperimentScheduler
            scheduler = ExperimentScheduler()
            scheduler._notification_service = mock_notification_service

            await scheduler.process_scheduled_experiments()

        kwargs = mock_notification_service.notify_experiment_ended.call_args
        assert kwargs[1].get("experiment_name") == "Search Ranking V2" or \
               (kwargs[0] and "Search Ranking V2" in str(kwargs))


# ---------------------------------------------------------------------------
# Integration-style wiring tests (verify attribute/import presence)
# ---------------------------------------------------------------------------


class TestSchedulerWiring:
    """Verify each scheduler is actually wired to the NotificationService."""

    def test_safety_scheduler_wired_to_notification_service(self):
        """SafetyScheduler instance exposes _notification_service after our wiring."""
        from backend.app.core.safety_scheduler import SafetyScheduler
        scheduler = SafetyScheduler()
        assert hasattr(scheduler, "_notification_service") or hasattr(scheduler, "notification_service"), \
            "SafetyScheduler must expose a notification_service attribute"

    def test_rollout_scheduler_wired_to_notification_service(self):
        """RolloutScheduler instance exposes _notification_service after our wiring."""
        from backend.app.core.rollout_scheduler import RolloutScheduler
        scheduler = RolloutScheduler()
        assert hasattr(scheduler, "_notification_service") or hasattr(scheduler, "notification_service"), \
            "RolloutScheduler must expose a notification_service attribute"

    def test_experiment_scheduler_wired_to_notification_service(self):
        """ExperimentScheduler instance exposes _notification_service after our wiring."""
        from backend.app.core.scheduler import ExperimentScheduler
        scheduler = ExperimentScheduler()
        assert hasattr(scheduler, "_notification_service") or hasattr(scheduler, "notification_service"), \
            "ExperimentScheduler must expose a notification_service attribute"

    def test_notification_service_imported_in_safety_scheduler(self):
        """The safety_scheduler module imports NotificationService."""
        import importlib
        import backend.app.core.safety_scheduler as mod

        # Re-import to get fresh module state
        importlib.reload(mod)

        scheduler = mod.SafetyScheduler()
        # After wiring, the scheduler should hold a NotificationService instance
        ns = getattr(scheduler, "_notification_service", None) or \
             getattr(scheduler, "notification_service", None)
        assert ns is not None, "SafetyScheduler must have a NotificationService instance"
        # Verify it has the expected method
        assert callable(getattr(ns, "notify_safety_rollback", None)), \
            "notification_service must expose notify_safety_rollback"

    def test_notification_service_imported_in_rollout_scheduler(self):
        """The rollout_scheduler module imports NotificationService."""
        import importlib
        import backend.app.core.rollout_scheduler as mod

        importlib.reload(mod)

        scheduler = mod.RolloutScheduler()
        ns = getattr(scheduler, "_notification_service", None) or \
             getattr(scheduler, "notification_service", None)
        assert ns is not None, "RolloutScheduler must have a NotificationService instance"
        assert callable(getattr(ns, "notify_rollout_advanced", None)), \
            "notification_service must expose notify_rollout_advanced"

    def test_notification_service_imported_in_experiment_scheduler(self):
        """The scheduler module imports NotificationService."""
        import importlib
        import backend.app.core.scheduler as mod

        importlib.reload(mod)

        scheduler = mod.ExperimentScheduler()
        ns = getattr(scheduler, "_notification_service", None) or \
             getattr(scheduler, "notification_service", None)
        assert ns is not None, "ExperimentScheduler must have a NotificationService instance"
        assert callable(getattr(ns, "notify_experiment_started", None)), \
            "notification_service must expose notify_experiment_started"
