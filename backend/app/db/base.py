# backend/app/db/base.py
"""
Base module for SQLAlchemy models.

Convenience re-exports of ``Base`` and the handful of models that tests and
scripts import from here; they are listed in ``__all__`` so the imports are not
flagged as unused.

This is **not** the full metadata. Alembic's ``env.py`` imports
``backend.app.models``, whose ``__init__`` imports every model module; pointing
``target_metadata`` at this module instead would autogenerate a migration that
drops the twenty-odd tables it does not import.
"""

from backend.app.models.assignment import Assignment
from backend.app.models.base import Base, BaseModel
from backend.app.models.event import Event
from backend.app.models.experiment import Experiment, Metric, Variant
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagOverride
from backend.app.models.metrics.metric import AggregatedMetric, ErrorLog, RawMetric
from backend.app.models.user import Permission, Role, User

__all__ = [
    "AggregatedMetric",
    "Assignment",
    "Base",
    "BaseModel",
    "ErrorLog",
    "Event",
    "Experiment",
    "FeatureFlag",
    "FeatureFlagOverride",
    "Metric",
    "Permission",
    "RawMetric",
    "Role",
    "User",
    "Variant",
]
