# backend/app/models/experiment.py
"""
Experiment-related database models for the experimentation platform.

This module defines models for experiments, variants, and metrics.
"""

import enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

from backend.app.core.database_config import get_schema_name

from .base import Base, BaseModel


class ExperimentStatus(enum.Enum):
    """Experiment status enum."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ExperimentType(enum.Enum):
    """Types of experiments."""

    A_B = "a_b"  # Simple A/B test
    MULTIVARIATE = "mv"  # Test with multiple variants
    SPLIT_URL = "split_url"  # Split test with different URLs
    BANDIT = "bandit"  # Multi-armed bandit


class MetricType(enum.Enum):
    """Types of metrics."""

    CONVERSION = "conversion"  # Binary conversion event
    REVENUE = "revenue"  # Revenue/monetary value
    COUNT = "count"  # Event count
    DURATION = "duration"  # Time duration
    CUSTOM = "custom"  # Custom metric


class Experiment(Base, BaseModel):
    """Experiment model for A/B testing."""

    __tablename__ = "experiments"

    name = Column(String(100), nullable=False)
    # Stable, human-readable identifier used by the SDK-facing tracking API
    # (`experiment_key`).  Generated from the name on create when not given.
    key = Column(String(100), unique=True, nullable=True, index=True)
    description = Column(Text)
    hypothesis = Column(Text)
    status = Column(
        SQLAEnum(ExperimentStatus),
        default=ExperimentStatus.DRAFT,
        nullable=False,
        index=True,
    )
    experiment_type = Column(
        SQLAEnum(ExperimentType),
        default=ExperimentType.A_B,
        nullable=False,
    )
    owner_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
    )
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    targeting_rules = Column(JSONB)  # For user segmentation
    metrics = Column(JSONB)  # Metrics to track
    tags = Column(JSONB)  # For categorization
    # Free-form notes/insights managed via POST /experiments/{id}/metadata.
    # (Named experiment_metadata because `metadata` is reserved by SQLAlchemy.)
    experiment_metadata = Column(JSONB, nullable=True)

    # Issue #22: MAB optimization type
    optimization_type = Column(
        SQLAEnum(
            "fixed",
            "thompson_sampling",
            "ucb1",
            "epsilon_greedy",
            name="optimization_type_enum",
        ),
        nullable=False,
        default="fixed",
    )

    # EP-021: Sequential testing configuration
    sequential_testing_enabled = Column(Boolean, default=False, nullable=False)
    sequential_testing_method = Column(
        SQLAEnum("msprt", "always_valid", name="sequential_testing_method_enum"),
        nullable=True,
    )
    sequential_testing_config = Column(JSONB, nullable=True)

    # Issue #21: CUPED variance reduction configuration
    variance_reduction_config = Column(JSONB, nullable=True)

    # EP-022: Mutual exclusion group membership
    mutual_exclusion_group_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{get_schema_name()}.mutual_exclusion_groups.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    # EP-035: Bayesian experimentation columns
    bayesian_enabled = Column(Boolean, default=False, nullable=False)
    bayesian_config = Column(JSONB, nullable=True)  # BayesianConfig serialized as JSON
    bayesian_decision = Column(String(32), nullable=True)  # BayesianDecision value

    # EP-036: Split URL testing configuration
    # Example: {"variants": [{"url": "https://example.com/a", "traffic_allocation": 50},
    #                         {"url": "https://example.com/b", "traffic_allocation": 50}],
    #           "cookie_name": "split_url_exp_key"}
    split_url_config = Column(JSONB, nullable=True)

    # EP-057: Multi-Tenant Workspace isolation (nullable for backwards-compatibility).
    # Open-core seam: a bare indexed UUID, not a ForeignKey. `workspaces` is an
    # Enterprise table, and a ForeignKey here is the only thing in the Community
    # ORM that reaches across the boundary — with it, importing this module
    # without the Enterprise models raises NoReferencedTableError. The
    # constraint is attached from the Enterprise side instead -- see
    # models/workspace.py, which appends it (use_alter, ON DELETE SET NULL)
    # whenever the Enterprise models are loaded; Community leaves the column
    # unconstrained and nothing reads it.
    workspace_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )

    # Relationships
    owner = relationship("User", back_populates="experiments")
    variants = relationship(
        "Variant", back_populates="experiment", cascade="all, delete-orphan"
    )
    metric_definitions = relationship(
        "Metric", back_populates="experiment", cascade="all, delete-orphan"
    )
    events = relationship(
        "Event", back_populates="experiment", cascade="all, delete-orphan"
    )
    reports = relationship("Report", back_populates="experiment", cascade="all, delete")

    # Add assignments relationship
    assignments = relationship(
        "Assignment", back_populates="experiment", cascade="all, delete-orphan"
    )

    # EP-022: Mutual exclusion group relationship
    mutual_exclusion_group = relationship(
        "MutualExclusionGroup", back_populates="experiments"
    )

    # Issue #22: MAB bandit state (one-to-one)
    bandit_state = relationship(
        "BanditState", back_populates="experiment", uselist=False
    )

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            # Composite index for finding active experiments within a date range
            Index(
                f"{schema_name}_experiment_status_dates",
                "status",
                "start_date",
                "end_date",
            ),
            # Owner + status index for quickly finding a user's active experiments
            Index(f"{schema_name}_experiment_owner_status", "owner_id", "status"),
            # Ensure end_date is after start_date
            CheckConstraint(
                "end_date IS NULL OR start_date IS NULL OR end_date > start_date",
                name="check_experiment_dates",
            ),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<Experiment {self.name}>"


class Variant(Base, BaseModel):
    """Variant model for experiment variations."""

    __tablename__ = "variants"

    experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    description = Column(Text)
    is_control = Column(Boolean, default=False)
    traffic_allocation = Column(Integer, default=50)  # Percentage of traffic
    configuration = Column(JSONB)  # Settings specific to this variant

    # Relationships
    experiment = relationship("Experiment", back_populates="variants")
    assignments = relationship(
        "Assignment", back_populates="variant", cascade="all, delete-orphan"
    )
    # Add events relationship
    events = relationship(
        "Event", back_populates="variant", cascade="all, delete-orphan"
    )

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            # Composite index for quickly finding variants of an experiment
            Index(f"{schema_name}_variant_experiment", "experiment_id"),
            # Check that traffic allocation is between 0 and 100
            CheckConstraint(
                "traffic_allocation >= 0 AND traffic_allocation <= 100",
                name="check_traffic_allocation",
            ),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<Variant {self.name}>"


class Metric(Base, BaseModel):
    """Metric model for experiment measurements."""

    __tablename__ = "metrics"

    experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    description = Column(Text)
    event_name = Column(String(100), nullable=False, index=True)
    metric_type = Column(
        SQLAEnum(MetricType), default=MetricType.CONVERSION, nullable=False
    )
    is_primary = Column(Boolean, default=False)
    aggregation_method = Column(String(50), default="average")
    minimum_sample_size = Column(Integer, default=100)
    expected_effect = Column(Float)
    event_value_path = Column(String(100))
    lower_is_better = Column(Boolean, default=False)

    # Relationships
    experiment = relationship("Experiment", back_populates="metric_definitions")

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            # Composite index for experiment + event
            Index(
                f"{schema_name}_metric_experiment_event", "experiment_id", "event_name"
            ),
            # Ensure unique metric names within an experiment
            Index(
                f"{schema_name}_metric_experiment_name",
                "experiment_id",
                "name",
                unique=True,
            ),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<Metric {self.name}>"
