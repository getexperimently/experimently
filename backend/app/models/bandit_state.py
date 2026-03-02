"""
BanditState model — stores current allocation weights for MAB experiments.
Updated by the BanditScheduler every 15 minutes.
"""

from sqlalchemy import Column, String, Float, Integer, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declared_attr

from .base import Base, BaseModel
from backend.app.core.database_config import get_schema_name


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
