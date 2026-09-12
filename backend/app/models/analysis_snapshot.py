"""
AnalysisSnapshot model — an audit row for every analysis the platform serves.

Each time a results endpoint computes fresh numbers (frequentist results,
Bayesian posteriors, CUPED, sequential testing) or the bandit scheduler
recomputes weights, one row is written here with the engine version, the
RNG seed and sample count that produced it, the time the data was read, and
the full payload.  Together with ``backend.app.core.stats_engine`` this makes
every number a customer has seen reproducible after the fact.

Writes are best-effort (see ``services/analysis_snapshot_service.py``): a
failure to persist a snapshot never fails the request that produced it.
"""

import enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declared_attr

from backend.app.core.database_config import get_schema_name
from backend.app.models.base import Base, BaseModel


class AnalysisKind(str, enum.Enum):
    """Which engine produced a snapshot."""

    FREQUENTIST = "frequentist"
    BAYESIAN = "bayesian"
    CUPED = "cuped"
    SEQUENTIAL = "sequential"
    BANDIT = "bandit"


ANALYSIS_KINDS = tuple(kind.value for kind in AnalysisKind)


class AnalysisSnapshot(Base, BaseModel):
    """One persisted analysis result for an experiment.

    Attributes:
        experiment_id: Experiment the analysis belongs to (cascade delete).
        kind: One of ``frequentist|bayesian|cuped|sequential|bandit``.
        engine_version: ``backend.app.core.stats_engine.ENGINE_VERSION`` at
            the time of computation.
        seed: RNG seed used for Monte Carlo draws; ``NULL`` for closed-form
            analyses (frequentist, CUPED, sequential).
        n_samples: Monte Carlo samples per variant; ``NULL`` when no sampling.
        as_of: Time the underlying data was read (UTC).  The results
            endpoints store the UTC calendar day (the bucket the RNG seed is
            derived from), so ``(experiment_id, kind, as_of)`` holds one row
            per analysis per day and a polling dashboard refreshes that row
            instead of adding one per request; the bandit scheduler stores the
            exact tick instant, so each tick keeps its own row.
        payload: The response body (or scheduler state) as served.
    """

    __tablename__ = "analysis_snapshots"

    experiment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(String(20), nullable=False)
    engine_version = Column(String(20), nullable=False)
    seed = Column(BigInteger, nullable=True)
    n_samples = Column(Integer, nullable=True)
    as_of = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(
                f"{schema_name}_analysis_snapshot_exp_kind_created",
                "experiment_id",
                "kind",
                "created_at",
            ),
            CheckConstraint(
                "kind IN ('frequentist', 'bayesian', 'cuped', 'sequential', 'bandit')",
                name="check_analysis_snapshot_kind",
            ),
            UniqueConstraint(
                "experiment_id",
                "kind",
                "as_of",
                name="uq_analysis_snapshot_experiment_kind_as_of",
            ),
            {"schema": schema_name},
        )

    def __repr__(self) -> str:
        return (
            f"<AnalysisSnapshot experiment_id={self.experiment_id} "
            f"kind={self.kind} engine_version={self.engine_version}>"
        )
