"""
Pydantic schemas for scheduler health tracking, run history, and notifications.

This module defines schemas for:
- Scheduler run records and history
- Scheduler health responses
- Notification configuration and events
- Scheduler configuration updates
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SchedulerName(str, Enum):
    """Names of the background schedulers."""

    EXPERIMENT = "experiment"
    ROLLOUT = "rollout"
    METRICS = "metrics"
    SAFETY = "safety"
    BANDIT = "bandit"


class SchedulerRunStatus(str, Enum):
    """Possible outcomes of a scheduler run."""

    SUCCESS = "success"
    PARTIAL = "partial"  # some items processed, some failed
    FAILED = "failed"
    SKIPPED = "skipped"  # nothing to process


class SchedulerRunRecord(BaseModel):
    """Record of a single scheduler execution."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    scheduler_name: SchedulerName
    started_at: str  # ISO timestamp
    completed_at: Optional[str] = None
    status: SchedulerRunStatus
    items_processed: int = 0
    items_failed: int = 0
    error_message: Optional[str] = None
    metadata: dict = {}


class SchedulerHealthResponse(BaseModel):
    """Current health state of a scheduler."""

    scheduler_name: SchedulerName
    is_running: bool
    last_run_at: Optional[str] = None
    last_run_status: Optional[SchedulerRunStatus] = None
    consecutive_failures: int = 0
    next_run_at: Optional[str] = None
    average_duration_seconds: Optional[float] = None


class SchedulerNotificationConfig(BaseModel):
    """Configuration for webhook notifications from schedulers."""

    webhook_url: Optional[str] = Field(None, description="Slack/Teams webhook URL")
    notify_on: list[SchedulerRunStatus] = [SchedulerRunStatus.FAILED]
    experiment_id: Optional[str] = None  # None = all experiments


class NotificationEvent(BaseModel):
    """Event payload sent to webhook endpoints."""

    event_type: str  # "experiment_started", "experiment_ended", "rollout_advanced", "safety_rollback"
    experiment_id: Optional[str] = None
    feature_flag_id: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    message: str
    timestamp: str
    metadata: dict = {}


class SchedulerConfigUpdate(BaseModel):
    """Request body for updating scheduler configuration."""

    interval_minutes: Optional[int] = Field(None, ge=1, le=1440)
    enabled: bool = True
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_delay_seconds: int = Field(default=60, ge=10, le=3600)
