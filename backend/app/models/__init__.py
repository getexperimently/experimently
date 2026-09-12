# Centralized model imports and initialization

from .analysis_snapshot import AnalysisKind, AnalysisSnapshot
from .api_key import APIKey
from .assignment import Assignment
from .audit_log import ActionType, AuditLog, EntityType
from .baa_config import BAAConfig
from .bandit_state import BanditState, BanditStateHistory
from .base import Base, BaseModel, BaseModelMixin
from .compliance_audit_event import AuditAction, AuditOutcome, ComplianceAuditEvent
from .custom_role import CustomRole
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
from .integration_config import (
    IntegrationConfig,
)
from .integration_config import (
    IntegrationType as IntegrationTypeEnum,
)
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
from .phi_audit_log import PHIAuditLog

# Several models reference these classes by name in relationship() strings
# (Report, FeatureFlagSafetyConfig, CustomRole, ...). Importing every module
# here lets scripts that only import backend.app.models configure the mappers.
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
from .segment import Segment
from .sso_config import SSOConfig
from .user import (
    Permission,
    Role,
    User,
    UserRole,
    role_permission_association,
    user_role_association,
)
from .warehouse_connection import WarehouseConnection
from .workspace import (
    Workspace,
    WorkspaceAPIKey,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceMemberRole,
    WorkspacePlan,
)

# Explicitly list all models that should be part of the base metadata
__all__ = [
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
    "FeatureFlagStatus",
    "GlobalHoldout",
    "IntegrationConfig",
    "IntegrationTypeEnum",
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
    "Role",
    "RolloutSchedule",
    "RolloutScheduleStatus",
    "RolloutStage",
    "RolloutStageStatus",
    "Segment",
    "TriggerType",
    "User",
    "UserRole",
    "Variant",
    "WarehouseConnection",
    "Workspace",
    "WorkspaceAPIKey",
    "WorkspaceInvite",
    "WorkspaceMember",
    "WorkspaceMemberRole",
    "WorkspacePlan",
    "role_permission_association",
    "user_role_association",
]

# Remove or comment out any premature configuration
# configure_mappers()
from .seed_marker import SeedMarker
