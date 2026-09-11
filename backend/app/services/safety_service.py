"""
Safety monitoring service for feature flags.

Responsibilities:

* global safety settings (``safety_settings`` table, a single row),
* per-flag safety configuration (``feature_flag_safety_configs``),
* evaluating the configured metric thresholds against the metrics the
  platform actually records (``raw_metrics`` / ``error_logs``),
* rolling a flag back to a safe rollout percentage and recording it in
  ``safety_rollback_records``.

The async methods are the API used by the endpoints and the
``SafetyScheduler``; the static ``*_record`` helpers are the thin CRUD layer
underneath them and are also handy in tests.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.metrics.metric import ErrorLog, MetricType, RawMetric
from backend.app.models.safety import (
    FeatureFlagSafetyConfig,
    RollbackTriggerType,
    SafetyRollbackRecord,
    SafetySettings,
)
from backend.app.schemas.safety import (
    FeatureFlagSafetyConfigCreate,
    FeatureFlagSafetyConfigResponse,
    FeatureFlagSafetyConfigUpdate,
    MetricStatus,
    MetricThreshold,
    RollbackResponse,
    SafetyCheckResponse,
    SafetyRollbackRecordCreate,
    SafetySettingsCreate,
    SafetySettingsResponse,
    SafetySettingsUpdate,
)
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Placeholder id returned when a flag has no stored safety configuration and
# the defaults from the global settings are used instead.
DEFAULT_CONFIG_ID = UUID("00000000-0000-0000-0000-000000000000")

# Metric names understood by check_feature_flag_safety(). Anything else is
# reported as "no data source" and treated as healthy.
_ERROR_METRICS = {"error_rate", "error_count", "total_evaluations"}
_LATENCY_METRICS = {"latency", "avg_latency", "p95_latency", "max_latency", "min_latency"}


def _metric_to_trigger(metric_name: str) -> RollbackTriggerType:
    if metric_name in _ERROR_METRICS:
        return RollbackTriggerType.ERROR_RATE
    if metric_name in _LATENCY_METRICS:
        return RollbackTriggerType.LATENCY
    return RollbackTriggerType.CUSTOM_METRIC


def _as_threshold(value: Any) -> MetricThreshold:
    """Config metrics are stored as JSON; accept dicts or MetricThreshold objects."""
    if isinstance(value, MetricThreshold):
        return value
    if isinstance(value, dict):
        return MetricThreshold(**value)
    return MetricThreshold()


def _breaches(value: float, limit: Optional[float], comparison: str) -> bool:
    if limit is None:
        return False
    if comparison == "less_than":
        return value < limit
    if comparison == "equal_to":
        return value == limit
    return value > limit  # "greater_than" (default)


class SafetyService:
    """Service for safety monitoring and rollback functionality."""

    def __init__(self, db: Session):
        """Initialize the safety service with a database session."""
        self.db = db

    # ------------------------------------------------------------------
    # Record-level helpers (sync)
    # ------------------------------------------------------------------

    @staticmethod
    def get_safety_settings_record(db: Session) -> Optional[SafetySettings]:
        """Return the global settings row, or None if it has not been created."""
        return db.query(SafetySettings).first()

    @staticmethod
    def create_safety_settings(db: Session, data: SafetySettingsCreate) -> SafetySettings:
        """Create the global settings row; raises ValueError if one exists."""
        if db.query(SafetySettings).first():
            raise ValueError("Safety settings already exist, use update instead")

        db_obj = SafetySettings(**_settings_columns(data.model_dump()))
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def update_safety_settings(
        db: Session, data: SafetySettingsUpdate
    ) -> Optional[SafetySettings]:
        """Update the global settings row; returns None if it does not exist."""
        db_obj = db.query(SafetySettings).first()
        if not db_obj:
            return None

        for field, value in _settings_columns(data.model_dump(exclude_unset=True)).items():
            setattr(db_obj, field, value)

        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def get_feature_flag_safety_config_record(
        db: Session, feature_flag_id: UUID
    ) -> Optional[FeatureFlagSafetyConfig]:
        """Return the stored config for a flag, or None."""
        return (
            db.query(FeatureFlagSafetyConfig)
            .filter(FeatureFlagSafetyConfig.feature_flag_id == feature_flag_id)
            .first()
        )

    @staticmethod
    def create_feature_flag_safety_config(
        db: Session,
        data: FeatureFlagSafetyConfigCreate,
        feature_flag_id: Optional[UUID] = None,
    ) -> FeatureFlagSafetyConfig:
        """
        Create the safety config for a flag.

        ``feature_flag_id`` may be passed explicitly or carried by ``data``
        (``FeatureFlagSafetyConfigBase`` has the field, the create schema does
        not). Raises ValueError when the flag does not exist or already has a
        config.
        """
        flag_id = feature_flag_id or getattr(data, "feature_flag_id", None)
        if flag_id is None:
            raise ValueError("feature_flag_id is required to create a safety config")

        if SafetyService.get_feature_flag_safety_config_record(db, flag_id):
            raise ValueError(f"Safety config already exists for feature flag {flag_id}")

        if not db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first():
            raise ValueError(f"Feature flag {flag_id} does not exist")

        payload = _config_columns(data.model_dump())
        payload.pop("feature_flag_id", None)
        db_obj = FeatureFlagSafetyConfig(feature_flag_id=flag_id, **payload)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def update_feature_flag_safety_config(
        db: Session, feature_flag_id: UUID, data: FeatureFlagSafetyConfigUpdate
    ) -> Optional[FeatureFlagSafetyConfig]:
        """Update a flag's safety config; returns None if there is none."""
        db_obj = SafetyService.get_feature_flag_safety_config_record(db, feature_flag_id)
        if not db_obj:
            return None

        for field, value in _config_columns(data.model_dump(exclude_unset=True)).items():
            setattr(db_obj, field, value)

        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    @staticmethod
    def get_or_create_safety_config(db: Session, feature_flag_id: UUID) -> FeatureFlagSafetyConfig:
        """Return the flag's config, creating a default one if missing."""
        config = SafetyService.get_feature_flag_safety_config_record(db, feature_flag_id)
        if config:
            return config

        if not db.query(FeatureFlag).filter(FeatureFlag.id == feature_flag_id).first():
            raise ValueError(f"Feature flag {feature_flag_id} does not exist")

        config = FeatureFlagSafetyConfig(feature_flag_id=feature_flag_id, metrics={})
        db.add(config)
        db.commit()
        db.refresh(config)
        return config

    @staticmethod
    def create_rollback_record(
        db: Session,
        data: SafetyRollbackRecordCreate,
        success: bool = True,
        executed_by_user_id: Optional[UUID] = None,
    ) -> SafetyRollbackRecord:
        """Persist a rollback record (the flag's config is created if needed)."""
        safety_config = SafetyService.get_or_create_safety_config(db, data.feature_flag_id)
        db_obj = SafetyRollbackRecord(
            feature_flag_id=data.feature_flag_id,
            safety_config_id=safety_config.id,
            trigger_type=str(getattr(data.trigger_type, "value", data.trigger_type)),
            trigger_reason=data.trigger_reason,
            previous_percentage=data.previous_percentage,
            target_percentage=data.target_percentage,
            success=success,
            executed_by_user_id=executed_by_user_id,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_error_metrics(
        self, db: Session, feature_flag_id: UUID, timeframe_minutes: int = 15
    ) -> Dict[str, Any]:
        """Error counts and error rate for a flag over the last ``timeframe_minutes``."""
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=timeframe_minutes)

        if not db.query(FeatureFlag).filter(FeatureFlag.id == feature_flag_id).first():
            raise ValueError(f"Feature flag {feature_flag_id} does not exist")

        error_logs = (
            db.query(ErrorLog)
            .filter(
                ErrorLog.feature_flag_id == feature_flag_id,
                ErrorLog.timestamp.between(start_time, end_time),
            )
            .all()
        )

        total_evaluations = (
            db.query(func.coalesce(func.sum(RawMetric.count), 0))
            .filter(
                RawMetric.feature_flag_id == feature_flag_id,
                RawMetric.metric_type == MetricType.FLAG_EVALUATION.value,
                RawMetric.timestamp.between(start_time, end_time),
            )
            .scalar()
            or 0
        )

        error_types: Dict[str, int] = {}
        for log in error_logs:
            error_types[log.error_type] = error_types.get(log.error_type, 0) + 1

        error_count = len(error_logs)
        error_rate = 0.0 if total_evaluations == 0 else error_count / total_evaluations

        return {
            "error_count": error_count,
            "total_evaluations": int(total_evaluations),
            "error_rate": error_rate,
            "error_types": error_types,
            "timeframe_minutes": timeframe_minutes,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        }

    def get_latency_metrics(
        self, db: Session, feature_flag_id: UUID, timeframe_minutes: int = 15
    ) -> Dict[str, Any]:
        """Latency statistics (ms) for a flag over the last ``timeframe_minutes``."""
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=timeframe_minutes)

        if not db.query(FeatureFlag).filter(FeatureFlag.id == feature_flag_id).first():
            raise ValueError(f"Feature flag {feature_flag_id} does not exist")

        rows = (
            db.query(RawMetric.value)
            .filter(
                RawMetric.feature_flag_id == feature_flag_id,
                RawMetric.metric_type == MetricType.LATENCY.value,
                RawMetric.value.isnot(None),
                RawMetric.timestamp.between(start_time, end_time),
            )
            .all()
        )
        latencies = sorted(float(v) for (v,) in rows)

        stats: Dict[str, Any] = {
            "avg_latency": 0,
            "max_latency": 0,
            "min_latency": 0,
            "p95_latency": 0,
            "total_requests": len(latencies),
            "timeframe_minutes": timeframe_minutes,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        }
        if latencies:
            p95_index = min(int(len(latencies) * 0.95), len(latencies) - 1)
            stats.update(
                avg_latency=sum(latencies) / len(latencies),
                max_latency=latencies[-1],
                min_latency=latencies[0],
                p95_latency=latencies[p95_index],
            )
        return stats

    def _get_metric_value(self, feature_flag_id: UUID, metric_name: str) -> Optional[float]:
        """Current value of a named metric, or None when the platform has no source for it."""
        if metric_name in _ERROR_METRICS:
            return float(self.get_error_metrics(self.db, feature_flag_id)[metric_name])
        if metric_name in _LATENCY_METRICS:
            latency = self.get_latency_metrics(self.db, feature_flag_id)
            key = "avg_latency" if metric_name == "latency" else metric_name
            return float(latency[key])
        return None

    # ------------------------------------------------------------------
    # Global settings (async API)
    # ------------------------------------------------------------------

    async def get_safety_settings(self) -> SafetySettingsResponse:
        """Return the global settings, creating the default row on first use."""
        settings = self.db.query(SafetySettings).first()
        if not settings:
            settings = SafetySettings(enable_automatic_rollbacks=False, default_metrics=None)
            self.db.add(settings)
            self.db.commit()
            self.db.refresh(settings)
        return SafetySettingsResponse.model_validate(settings)

    async_get_safety_settings = get_safety_settings

    async def create_or_update_safety_settings(
        self, settings: SafetySettingsCreate
    ) -> SafetySettingsResponse:
        """Create or update the global settings."""
        existing = self.db.query(SafetySettings).first()
        payload = _settings_columns(settings.model_dump(exclude_unset=True))

        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
        else:
            existing = SafetySettings(**_settings_columns(settings.model_dump()))
            self.db.add(existing)

        self.db.commit()
        self.db.refresh(existing)
        return SafetySettingsResponse.model_validate(existing)

    # ------------------------------------------------------------------
    # Per-flag configuration (async API)
    # ------------------------------------------------------------------

    def _require_flag(self, feature_flag_id: UUID) -> FeatureFlag:
        feature_flag = self.db.query(FeatureFlag).filter(FeatureFlag.id == feature_flag_id).first()
        if not feature_flag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feature flag with ID {feature_flag_id} not found",
            )
        return feature_flag

    async def get_feature_flag_safety_config(
        self, feature_flag_id: UUID
    ) -> FeatureFlagSafetyConfigResponse:
        """
        Return the flag's safety config.

        When no config has been stored, a default built from the global
        settings is returned with ``DEFAULT_CONFIG_ID`` as its id (nothing is
        written).
        """
        self._require_flag(feature_flag_id)

        config = self.get_feature_flag_safety_config_record(self.db, feature_flag_id)
        if config:
            return FeatureFlagSafetyConfigResponse.model_validate(config)

        settings = await self.get_safety_settings()
        now = datetime.utcnow()
        return FeatureFlagSafetyConfigResponse(
            id=DEFAULT_CONFIG_ID,
            feature_flag_id=feature_flag_id,
            enabled=True,
            metrics=settings.default_metrics or {},
            rollback_percentage=0,
            created_at=now,
            updated_at=now,
        )

    async_get_feature_flag_safety_config = get_feature_flag_safety_config

    async def create_or_update_feature_flag_safety_config(
        self, feature_flag_id: UUID, config: FeatureFlagSafetyConfigCreate
    ) -> FeatureFlagSafetyConfigResponse:
        """Create or update the flag's safety config."""
        self._require_flag(feature_flag_id)

        existing = self.get_feature_flag_safety_config_record(self.db, feature_flag_id)
        if existing:
            for key, value in _config_columns(config.model_dump(exclude_unset=True)).items():
                setattr(existing, key, value)
        else:
            payload = _config_columns(config.model_dump())
            payload.pop("feature_flag_id", None)
            existing = FeatureFlagSafetyConfig(feature_flag_id=feature_flag_id, **payload)
            self.db.add(existing)

        self.db.commit()
        self.db.refresh(existing)
        return FeatureFlagSafetyConfigResponse.model_validate(existing)

    # ------------------------------------------------------------------
    # Safety checks
    # ------------------------------------------------------------------

    async def check_feature_flag_safety(self, feature_flag_id: UUID) -> SafetyCheckResponse:
        """
        Evaluate every configured metric threshold for the flag.

        A metric is unhealthy when its current value breaches the critical
        threshold (per ``comparison_type``). Metrics the platform cannot
        measure are reported with ``current_value`` 0 and noted in details.
        """
        feature_flag = self._require_flag(feature_flag_id)
        config = await self.get_feature_flag_safety_config(feature_flag_id)

        if not config.enabled:
            return SafetyCheckResponse(
                feature_flag_id=feature_flag_id,
                is_healthy=True,
                metrics=[],
                last_checked=datetime.utcnow(),
                details={"message": "Safety monitoring is disabled for this feature flag"},
            )

        statuses: List[MetricStatus] = []
        unavailable: List[str] = []
        is_healthy = True

        for name, raw_threshold in (config.metrics or {}).items():
            threshold = _as_threshold(raw_threshold)
            value = self._get_metric_value(feature_flag_id, name)

            if value is None:
                unavailable.append(name)
                value = 0.0
                critical = warning = False
            else:
                critical = _breaches(value, threshold.critical_threshold, threshold.comparison_type)
                warning = _breaches(value, threshold.warning_threshold, threshold.comparison_type)

            if critical:
                is_healthy = False

            limit = (
                threshold.critical_threshold
                if threshold.critical_threshold is not None
                else (threshold.warning_threshold or 0.0)
            )
            statuses.append(
                MetricStatus(
                    name=name,
                    current_value=value,
                    threshold=limit,
                    is_healthy=not critical,
                    details={
                        "comparison_type": threshold.comparison_type,
                        "warning_threshold": threshold.warning_threshold,
                        "critical_threshold": threshold.critical_threshold,
                        "warning": warning,
                        "measured": name not in unavailable,
                    },
                )
            )

        details: Dict[str, Any] = {"feature_flag_key": feature_flag.key}
        if unavailable:
            details["unmeasured_metrics"] = unavailable

        return SafetyCheckResponse(
            feature_flag_id=feature_flag_id,
            is_healthy=is_healthy,
            metrics=statuses,
            last_checked=datetime.utcnow(),
            details=details,
        )

    async def should_rollback(
        self, db: Session, feature_flag_id: UUID
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Decide whether an automatic rollback is warranted.

        Requires: an ACTIVE flag with rollout > 0, monitoring enabled for the
        flag, automatic rollbacks enabled globally, and a failing safety check.
        """
        feature_flag = (
            db.query(FeatureFlag)
            .filter(FeatureFlag.id == feature_flag_id, FeatureFlag.status == FeatureFlagStatus.ACTIVE)
            .first()
        )
        if not feature_flag or feature_flag.rollout_percentage == 0:
            return False, None, None

        config = await self.get_feature_flag_safety_config(feature_flag_id)
        if not config.enabled:
            return False, None, None

        settings = await self.get_safety_settings()
        if not settings.enable_automatic_rollbacks:
            return False, None, None

        try:
            safety_check = await self.check_feature_flag_safety(feature_flag_id)
        except Exception as exc:  # metric sources failing must not roll flags back
            logger.error(f"Error checking safety for feature flag {feature_flag_id}: {exc}")
            return False, None, None

        if safety_check.is_healthy:
            return False, None, None

        failing = next((m for m in safety_check.metrics if not m.is_healthy), None)
        if failing:
            reason = f"Metric '{failing.name}' exceeded threshold ({failing.current_value} vs {failing.threshold})"
            trigger_type = _metric_to_trigger(failing.name)
            trigger_value, threshold_value = failing.current_value, failing.threshold
        else:
            reason, trigger_type = "Multiple issues detected", RollbackTriggerType.AUTOMATIC
            trigger_value = threshold_value = None

        return True, reason, {
            "trigger_type": trigger_type,
            "trigger_value": trigger_value,
            "threshold_value": threshold_value,
            "safety_check": safety_check.model_dump(),
        }

    # ------------------------------------------------------------------
    # Rollbacks
    # ------------------------------------------------------------------

    def execute_rollback(
        self,
        db: Session,
        feature_flag_id: UUID,
        reason: str = "Manual rollback",
        trigger_type: RollbackTriggerType = RollbackTriggerType.MANUAL,
        metrics_data: Optional[Dict[str, Any]] = None,
        trigger_value: Optional[float] = None,
        threshold_value: Optional[float] = None,
        target_percentage: int = 0,
        executed_by_user_id: Optional[UUID] = None,
    ) -> RollbackResponse:
        """
        Set the flag's rollout to ``target_percentage`` (default 0, flag stays
        ACTIVE) and record the rollback. Never raises: failures are reported
        with ``success=False`` and the transaction is rolled back.
        """
        trigger_name = str(getattr(trigger_type, "value", trigger_type))
        try:
            feature_flag = (
                db.query(FeatureFlag).filter(FeatureFlag.id == feature_flag_id).with_for_update().first()
            )
            if not feature_flag:
                raise ValueError(f"Feature flag {feature_flag_id} does not exist")

            previous_percentage = feature_flag.rollout_percentage
            if previous_percentage <= target_percentage:
                # Already at (or below) the safe percentage: nothing to roll
                # back. Without this guard the safety monitor writes a new
                # rollback record every cycle while the error window is hot.
                db.rollback()
                return RollbackResponse(
                    success=False,
                    feature_flag_id=feature_flag_id,
                    message=(
                        f"Feature flag '{feature_flag.key}' is already at "
                        f"{previous_percentage}% (target {target_percentage}%); no rollback needed"
                    ),
                    trigger_type=trigger_name,
                    previous_percentage=previous_percentage,
                    new_percentage=previous_percentage,
                )
            safety_config = self.get_or_create_safety_config(db, feature_flag_id)

            feature_flag.rollout_percentage = target_percentage
            feature_flag.updated_at = datetime.utcnow()
            db.add(feature_flag)

            record = SafetyRollbackRecord(
                feature_flag_id=feature_flag_id,
                safety_config_id=safety_config.id,
                trigger_type=trigger_name,
                trigger_reason=reason,
                previous_percentage=previous_percentage,
                target_percentage=target_percentage,
                success=True,
                executed_by_user_id=executed_by_user_id,
            )
            db.add(record)
            db.commit()
            db.refresh(record)

            logger.info(
                f"Rolled back feature flag {feature_flag_id} from {previous_percentage}% "
                f"to {target_percentage}% due to {reason} (trigger: {trigger_name})"
            )
            return RollbackResponse(
                success=True,
                feature_flag_id=feature_flag_id,
                message=(
                    f"Feature flag '{feature_flag.key}' rolled back from "
                    f"{previous_percentage}% to {target_percentage}%"
                ),
                trigger_type=trigger_name,
                previous_percentage=previous_percentage,
                new_percentage=target_percentage,
                rollback_record_id=record.id,
                timestamp=datetime.utcnow(),
                details={
                    "reason": reason,
                    "trigger_value": trigger_value,
                    "threshold_value": threshold_value,
                    "metrics_data": metrics_data,
                },
            )

        except Exception as exc:
            db.rollback()
            logger.error(f"Error rolling back feature flag {feature_flag_id}: {exc}")
            return RollbackResponse(
                success=False,
                feature_flag_id=feature_flag_id,
                message=f"Rollback failed: {exc}",
                trigger_type=trigger_name,
                timestamp=datetime.utcnow(),
                details={"reason": reason},
            )

    async def rollback_feature_flag(
        self,
        feature_flag_id: UUID,
        percentage: Optional[int] = 0,
        reason: Optional[str] = "Manual rollback",
        trigger_type: RollbackTriggerType = RollbackTriggerType.MANUAL,
        executed_by_user_id: Optional[UUID] = None,
    ) -> RollbackResponse:
        """Roll the flag back to ``percentage`` and record it. 404 if the flag is unknown."""
        self._require_flag(feature_flag_id)
        return self.execute_rollback(
            self.db,
            feature_flag_id,
            reason=reason or "Manual rollback",
            trigger_type=trigger_type,
            target_percentage=percentage or 0,
            executed_by_user_id=executed_by_user_id,
        )

    async_rollback_feature_flag = rollback_feature_flag


# ----------------------------------------------------------------------
# Schema -> column mapping helpers
# ----------------------------------------------------------------------

def _settings_columns(data: Dict[str, Any]) -> Dict[str, Any]:
    """Serialise nested MetricThreshold models so they can be stored as JSONB."""
    out = dict(data)
    if out.get("default_metrics") is not None:
        out["default_metrics"] = {
            name: (t.model_dump() if hasattr(t, "model_dump") else t)
            for name, t in out["default_metrics"].items()
        }
    return out


def _config_columns(data: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(data)
    if out.get("metrics") is not None:
        out["metrics"] = {
            name: (t.model_dump() if hasattr(t, "model_dump") else t)
            for name, t in out["metrics"].items()
        }
    return out
