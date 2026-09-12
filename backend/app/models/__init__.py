"""Community Edition model registry.

Importing this package registers **only** the Community models on
``Base.metadata``.  Enterprise models (workspaces, custom roles, SSO configs,
BAA configs, PHI audit logs, warehouse connections, integration configs) are
not imported here; they join the metadata through the open-core seam, by
calling ``backend.app.core.hooks.register_model_module()`` from the Enterprise
package's ``register()`` entry point (see ``backend/app/ee_loader.py``).

Package semantics make this file the single choke point for the schema:
importing *any* submodule runs this ``__init__`` first, so
``import backend.app.models.experiment`` alone is enough to give a caller the
complete Community metadata.  That is also why the boundary is easy to lose
invisibly — one Community module importing an Enterprise model would put its
table back on ``Base.metadata`` and ``create_all`` would silently keep
producing Enterprise tables.  ``backend/tests/smoke/test_core_model_registry.py``
asserts, in a fresh interpreter, that it does not.
"""

import importlib
from typing import Any

from .analysis_snapshot import AnalysisKind, AnalysisSnapshot
from .api_key import APIKey
from .assignment import Assignment
from .audit_log import ActionType, AuditLog, EntityType
from .bandit_state import BanditState, BanditStateHistory
from .base import Base, BaseModel, BaseModelMixin
from .compliance_audit_event import AuditAction, AuditOutcome, ComplianceAuditEvent
from .event import Event, EventType
from .experiment import (
    Experiment,
    ExperimentStatus,
    ExperimentType,
    Metric,
    MetricType,
    Variant,
)
from .feature_flag import FeatureFlag, FeatureFlagOverride, FeatureFlagStatus
from .global_holdout import GlobalHoldout
from .llm_experiment import (
    LLMEvaluation,
    LLMEvaluationMetric,
    LLMExperiment,
    LLMExperimentStatus,
    LLMProvider,
    LLMTaskType,
    LLMVariant,
)
from .metrics.metric import (
    AggregatedMetric,
    AggregationPeriod,
    ErrorLog,
    RawMetric,
)
from .metrics.metric import (
    MetricType as MetricsMetricType,
)
from .mutual_exclusion_group import MutualExclusionGroup, MutualExclusionGroupStatus
from .notification import (
    NotificationChannel,
    NotificationDeliveryLog,
    NotificationPreference,
    NotificationStatus,
)

# Several models reference these classes by name in relationship() strings
# (Report, FeatureFlagSafetyConfig, ...).  Importing every module here lets
# scripts that only import backend.app.models configure the mappers.
from .report import Report
from .rollout_schedule import (
    RolloutSchedule,
    RolloutScheduleStatus,
    RolloutStage,
    RolloutStageStatus,
    TriggerType,
)
from .safety import FeatureFlagSafetyConfig, SafetyRollbackRecord, SafetySettings
from .scheduler_run import SchedulerRun
from .seed_marker import SeedMarker
from .segment import Segment
from .user import (
    Permission,
    Role,
    User,
    UserRole,
    role_permission_association,
    user_role_association,
)

#: Every Community model module, relative to this package.  The ``from .x
#: import y`` statements above already import all of them; this tuple names
#: them so :func:`register_core_models` can state the requirement instead of
#: relying on that side effect, and so the boundary is one list to audit.
CORE_MODEL_MODULES = (
    "analysis_snapshot",
    "api_key",
    "assignment",
    "audit_log",
    "bandit_state",
    "base",
    "compliance_audit_event",
    "event",
    "experiment",
    "feature_flag",
    "global_holdout",
    "llm_experiment",
    "metrics.metric",
    "mutual_exclusion_group",
    "notification",
    "report",
    "rollout_schedule",
    "safety",
    "scheduler_run",
    "seed_marker",
    "segment",
    "user",
)


# `Any`, not `DeclarativeMeta`: `declarative_base()` is the legacy API and its
# stubs return Any, so a narrower annotation only produces a no-any-return.
def register_core_models() -> Any:
    """Register every Community model on ``Base.metadata``; returns ``Base``.

    Idempotent, and safe to call before or after anything else has imported a
    model module.  Callers that build a schema — ``db/bootstrap.py``, alembic's
    ``env.py``, ``backend/tests/conftest.py`` — call this rather than importing
    the package for its side effect, so that what they depend on is explicit.

    This registers Community models *only*.  Enterprise models arrive through
    ``backend.app.ee_loader.load_enterprise()``, which imports whatever the
    Enterprise package registered with ``hooks.register_model_module()``.
    """
    for module_name in CORE_MODEL_MODULES:
        importlib.import_module(f"{__name__}.{module_name}")
    return Base


# Explicitly list all models that should be part of the base metadata
__all__ = [
    "CORE_MODEL_MODULES",
    "APIKey",
    "ActionType",
    "AggregatedMetric",
    "AggregationPeriod",
    "AnalysisKind",
    "AnalysisSnapshot",
    "Assignment",
    "AuditAction",
    "AuditLog",
    "AuditOutcome",
    "BanditState",
    "BanditStateHistory",
    "Base",
    "BaseModel",
    "BaseModelMixin",
    "ComplianceAuditEvent",
    "EntityType",
    "ErrorLog",
    "Event",
    "EventType",
    "Experiment",
    "ExperimentStatus",
    "ExperimentType",
    "FeatureFlag",
    "FeatureFlagOverride",
    "FeatureFlagSafetyConfig",
    "FeatureFlagStatus",
    "GlobalHoldout",
    "LLMEvaluation",
    "LLMEvaluationMetric",
    "LLMExperiment",
    "LLMExperimentStatus",
    "LLMProvider",
    "LLMTaskType",
    "LLMVariant",
    "Metric",
    "MetricType",
    "MetricsMetricType",
    "MutualExclusionGroup",
    "MutualExclusionGroupStatus",
    "NotificationChannel",
    "NotificationDeliveryLog",
    "NotificationPreference",
    "NotificationStatus",
    "Permission",
    "RawMetric",
    "Report",
    "Role",
    "RolloutSchedule",
    "RolloutScheduleStatus",
    "RolloutStage",
    "RolloutStageStatus",
    "SafetyRollbackRecord",
    "SafetySettings",
    "SchedulerRun",
    "SeedMarker",
    "Segment",
    "TriggerType",
    "User",
    "UserRole",
    "Variant",
    "register_core_models",
    "role_permission_association",
    "user_role_association",
]
