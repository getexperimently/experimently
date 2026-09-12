"""
BanditState model — stores current allocation weights for MAB experiments.
Updated by the BanditScheduler every ``BANDIT_UPDATE_INTERVAL_MINUTES``.

BanditStateHistory keeps one row per (tick, variant) so the trajectory of
posteriors and weights can be replayed and audited.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

from backend.app.core.database_config import get_schema_name

from .base import Base, BaseModel


class BanditState(Base, BaseModel):
    """
    Persisted bandit state for a MAB experiment.

    Stores the current variant weights computed by the BanditScheduler,
    as well as accumulated per-variant statistics so that they can be
    displayed in the dashboard without hitting DynamoDB.
    """

    __tablename__ = "bandit_states"

    experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{get_schema_name()}.experiments.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
    )

    # Algorithm driving this state ("thompson_sampling" | "ucb1" | "epsilon_greedy")
    algorithm = Column(String(50), nullable=False, default="thompson_sampling")

    # JSON: {variant_id: {weight: float, successes: int, failures: int, pulls: int}}
    variant_weights = Column(JSONB, nullable=False, default=dict)

    # Aggregate pull count across all variants
    total_pulls = Column(Integer, nullable=False, default=0)

    # Estimated regret reduction vs. uniform allocation (percentage, may be NULL early on)
    regret_reduction_pct = Column(Float, nullable=True)

    # ISO-8601 timestamp of the last weight computation (stored as a plain string
    # to avoid timezone-handling complexity across DB drivers)
    last_computed_at = Column(String(50), nullable=True)

    # Provenance of the current weights (P0 statistical credibility).
    # seed / n_samples are NULL for deterministic algorithms (UCB1, epsilon-greedy)
    # and for manual overrides; engine_version is NULL for rows written before
    # the column existed.
    seed = Column(BigInteger, nullable=True)
    n_samples = Column(Integer, nullable=True)
    engine_version = Column(String(20), nullable=True)

    # Relationship back to the parent experiment
    experiment = relationship("Experiment", back_populates="bandit_state")

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(f"{schema_name}_bandit_state_exp_id", "experiment_id"),
            {"schema": schema_name},
        )

    def __repr__(self) -> str:
        return f"<BanditState experiment_id={self.experiment_id} algorithm={self.algorithm}>"


class BanditStateHistory(Base, BaseModel):
    """
    One row per (scheduler tick, variant): the posterior and weight the bandit
    used at that moment.

    ``alpha`` / ``beta`` are the Beta-Bernoulli posterior parameters
    (``prior + successes`` / ``prior + failures``) that Thompson sampling drew
    from; for UCB1 and epsilon-greedy they are recorded with the same formula
    so the row shape is uniform.  ``seed`` / ``n_samples`` are ``NULL`` for
    deterministic algorithms.
    """

    __tablename__ = "bandit_state_history"

    experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    algorithm = Column(String(50), nullable=False)
    alpha = Column(Float, nullable=False)
    beta = Column(Float, nullable=False)
    weight = Column(Float, nullable=False)
    successes = Column(Integer, nullable=False, default=0)
    failures = Column(Integer, nullable=False, default=0)
    pulls = Column(Integer, nullable=False, default=0)
    seed = Column(BigInteger, nullable=True)
    n_samples = Column(Integer, nullable=True)
    engine_version = Column(String(20), nullable=False)
    tick_at = Column(DateTime(timezone=True), nullable=False)

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(
                f"{schema_name}_bandit_history_exp_tick",
                "experiment_id",
                "tick_at",
            ),
            {"schema": schema_name},
        )

    def __repr__(self) -> str:
        return (
            f"<BanditStateHistory experiment_id={self.experiment_id} "
            f"variant_id={self.variant_id} weight={self.weight} tick_at={self.tick_at}>"
        )
