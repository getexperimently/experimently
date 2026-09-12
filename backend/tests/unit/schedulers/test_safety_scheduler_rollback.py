"""
Unit tests for SafetyScheduler automatic rollbacks.

The scheduler must roll an unhealthy flag back to the percentage configured
in the flag's safety config (``rollback_percentage``) rather than always to 0,
and must read its cadence from ``settings.SAFETY_CHECK_INTERVAL_MINUTES``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.safety_scheduler import (
    SafetyScheduler,
    _rollback_target_percentage,
)
from backend.app.models.safety import RollbackTriggerType


def _unhealthy_scheduler_env(
    rollback_percentage, enable_automatic_rollbacks=True, is_healthy=False
):
    """Build the mocked db + SafetyService for one unhealthy flag."""
    flag = MagicMock()
    flag.id = "flag-uuid-1"
    flag.key = "streampulse_player_v2"
    flag.rollout_percentage = 25

    metric = MagicMock()
    metric.is_healthy = is_healthy
    metric.name = "error_rate"
    metric.current_value = 0.12
    metric.threshold = 0.05

    safety_check = MagicMock()
    safety_check.is_healthy = is_healthy
    safety_check.details = "error_rate too high"
    safety_check.metrics = [metric]

    config = MagicMock()
    config.enabled = True
    config.rollback_percentage = rollback_percentage

    global_settings = MagicMock()
    global_settings.enable_automatic_rollbacks = enable_automatic_rollbacks

    rollback_result = MagicMock()
    rollback_result.success = True
    rollback_result.message = f"Rolled back to {rollback_percentage}%"

    service = MagicMock()
    service.async_get_feature_flag_safety_config = AsyncMock(return_value=config)
    service.check_feature_flag_safety = AsyncMock(return_value=safety_check)
    service.async_get_safety_settings = AsyncMock(return_value=global_settings)
    service.async_rollback_feature_flag = AsyncMock(return_value=rollback_result)

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [flag]
    return db, service, flag


@pytest.mark.asyncio
async def test_rollback_uses_config_rollback_percentage():
    db, service, flag = _unhealthy_scheduler_env(rollback_percentage=5)

    with (
        patch("backend.app.core.safety_scheduler.SessionLocal", return_value=db),
        patch("backend.app.core.safety_scheduler.SafetyService", return_value=service),
    ):
        scheduler = SafetyScheduler()
        scheduler._notification_service = MagicMock()
        await scheduler.check_feature_flags_safety()

    service.async_rollback_feature_flag.assert_awaited_once()
    kwargs = service.async_rollback_feature_flag.await_args.kwargs
    assert kwargs["feature_flag_id"] == flag.id
    assert kwargs["percentage"] == 5
    assert kwargs["trigger_type"] == RollbackTriggerType.AUTOMATIC
    assert "error_rate" in kwargs["reason"]

    scheduler._notification_service.notify_safety_rollback.assert_called_once()
    assert (
        scheduler._notification_service.notify_safety_rollback.call_args.kwargs[
            "feature_flag_name"
        ]
        == flag.key
    )


@pytest.mark.asyncio
async def test_rollback_defaults_to_zero_when_config_has_no_percentage():
    db, service, _ = _unhealthy_scheduler_env(rollback_percentage=None)

    with (
        patch("backend.app.core.safety_scheduler.SessionLocal", return_value=db),
        patch("backend.app.core.safety_scheduler.SafetyService", return_value=service),
    ):
        scheduler = SafetyScheduler()
        scheduler._notification_service = MagicMock()
        await scheduler.check_feature_flags_safety()

    assert service.async_rollback_feature_flag.await_args.kwargs["percentage"] == 0


@pytest.mark.asyncio
async def test_no_rollback_when_automatic_rollbacks_disabled():
    db, service, _ = _unhealthy_scheduler_env(
        rollback_percentage=5, enable_automatic_rollbacks=False
    )

    with (
        patch("backend.app.core.safety_scheduler.SessionLocal", return_value=db),
        patch("backend.app.core.safety_scheduler.SafetyService", return_value=service),
    ):
        scheduler = SafetyScheduler()
        scheduler._notification_service = MagicMock()
        await scheduler.check_feature_flags_safety()

    service.async_rollback_feature_flag.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_rollback_when_healthy():
    db, service, _ = _unhealthy_scheduler_env(rollback_percentage=5, is_healthy=True)

    with (
        patch("backend.app.core.safety_scheduler.SessionLocal", return_value=db),
        patch("backend.app.core.safety_scheduler.SafetyService", return_value=service),
    ):
        scheduler = SafetyScheduler()
        await scheduler.check_feature_flags_safety()

    service.async_rollback_feature_flag.assert_not_awaited()


@pytest.mark.parametrize(
    "value, expected",
    [
        (5, 5),
        (0, 0),
        (100, 100),
        (150, 100),
        (-3, 0),
        (7.9, 7),
        (None, 0),
        ("5", 0),
        (True, 0),
        (MagicMock(), 0),
    ],
)
def test_rollback_target_percentage_clamps_and_defaults(value, expected):
    config = MagicMock()
    config.rollback_percentage = value
    assert _rollback_target_percentage(config) == expected


def test_interval_defaults_come_from_settings(monkeypatch):
    from backend.app.core import rollout_scheduler as rollout_module
    from backend.app.core import safety_scheduler as safety_module

    monkeypatch.setattr(safety_module.app_settings, "SAFETY_CHECK_INTERVAL_MINUTES", 1)
    monkeypatch.setattr(
        rollout_module.app_settings, "ROLLOUT_CHECK_INTERVAL_MINUTES", 2
    )

    assert safety_module.SafetyScheduler().interval_minutes == 1
    assert rollout_module.RolloutScheduler().interval_minutes == 2
    # explicit argument still wins
    assert safety_module.SafetyScheduler(interval_minutes=9).interval_minutes == 9
    assert rollout_module.RolloutScheduler(interval_minutes=9).interval_minutes == 9


def test_settings_have_scheduler_interval_defaults():
    from backend.app.core.config import Settings

    settings = Settings(_env_file=None)
    assert settings.SAFETY_CHECK_INTERVAL_MINUTES == 5
    assert settings.ROLLOUT_CHECK_INTERVAL_MINUTES == 15


@pytest.mark.asyncio
async def test_no_repeat_rollback_when_flag_is_already_at_target():
    """An unhealthy flag that already sits at its rollback percentage is left
    alone: no new rollback call, record or notification each cycle."""
    db, service, flag = _unhealthy_scheduler_env(rollback_percentage=5)
    flag.rollout_percentage = 5

    with (
        patch("backend.app.core.safety_scheduler.SessionLocal", return_value=db),
        patch("backend.app.core.safety_scheduler.SafetyService", return_value=service),
    ):
        scheduler = SafetyScheduler()
        scheduler._notification_service = MagicMock()
        await scheduler.check_feature_flags_safety()

    service.async_rollback_feature_flag.assert_not_awaited()
    scheduler._notification_service.notify_safety_rollback.assert_not_called()
