"""Pydantic v2 schemas for Bayesian experimentation (EP-035)."""
from typing import Optional, List
import enum
from pydantic import BaseModel, Field, field_validator, ConfigDict

from backend.app.core.stats_engine import ENGINE_VERSION


class PriorFamily(str, enum.Enum):
    """Supported conjugate prior families."""

    BETA = "beta"
    NORMAL = "normal"
    GAMMA = "gamma"


class BayesianDecision(str, enum.Enum):
    """Decision recommendation from Bayesian stopping rules."""

    CONTINUE = "CONTINUE"
    STOP_WINNER = "STOP_WINNER"
    STOP_EQUIVALENT = "STOP_EQUIVALENT"
    STOP_FUTILE = "STOP_FUTILE"


class BayesianConfig(BaseModel):
    """Configuration for the Bayesian analysis engine.

    Attributes:
        prior_family: Conjugate prior family (beta, normal, or gamma).
        alpha: Alpha hyperparameter for the prior (must be > 0).
        beta: Beta hyperparameter for the prior (must be > 0).
        loss_threshold: Expected loss threshold below which we stop (must be > 0).
        rope: Region of Practical Equivalence as [lower, upper]; if the
            posterior difference falls inside ROPE, the experiment is deemed
            equivalent and stopped.
        credible_level: HDI credible interval level in (0, 1), default 0.95.
    """

    prior_family: PriorFamily = PriorFamily.BETA
    alpha: float = Field(1.0, gt=0, description="Prior alpha hyperparameter (> 0)")
    beta: float = Field(1.0, gt=0, description="Prior beta hyperparameter (> 0)")
    loss_threshold: float = Field(
        0.001, gt=0, description="Expected loss threshold for stopping"
    )
    rope: Optional[List[float]] = Field(
        None,
        description="Region of Practical Equivalence [lower, upper]",
    )
    credible_level: float = Field(
        0.95,
        gt=0,
        lt=1,
        description="Credible interval level in (0, 1)",
    )

    @field_validator("rope")
    @classmethod
    def validate_rope(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        """Validate ROPE has exactly 2 floats and rope[0] < rope[1]."""
        if v is not None:
            if len(v) != 2:
                raise ValueError("rope must have exactly 2 values: [lower, upper]")
            if v[0] >= v[1]:
                raise ValueError("rope[0] must be strictly less than rope[1]")
        return v


class BayesianPosteriorResult(BaseModel):
    """Posterior distribution result for a Beta-Binomial model.

    Attributes:
        alpha: Posterior alpha (alpha_prior + conversions).
        beta: Posterior beta (beta_prior + non_conversions).
        mean: Posterior mean = alpha / (alpha + beta).
        credible_interval_lower: Lower bound of the HDI.
        credible_interval_upper: Upper bound of the HDI.
    """

    alpha: float
    beta: float
    mean: float
    credible_interval_lower: float
    credible_interval_upper: float


class BayesianVariantResult(BaseModel):
    """Full Bayesian analysis result for a single variant.

    Attributes:
        variant_key: Unique identifier/key of this variant.
        posterior: Posterior distribution parameters and credible interval.
        probability_to_be_best: Monte Carlo probability this variant is best.
        expected_loss: Expected regret if this variant is selected.
        bayes_factor: Savage-Dickey Bayes factor (optional).
    """

    variant_key: str
    posterior: BayesianPosteriorResult
    probability_to_be_best: float
    expected_loss: float
    bayes_factor: Optional[float] = None


class BayesianResultsResponse(BaseModel):
    """Top-level response for Bayesian experiment analysis.

    Attributes:
        is_enabled: Whether Bayesian analysis is enabled for this experiment.
        decision: Stopping decision based on Bayesian stopping rules.
        variant_results: Per-variant Bayesian results.
        seed: Deterministic RNG seed used for the Monte Carlo draws
            (``blake2b(experiment_id | as_of day | n_samples)``); ``None``
            when no sampling was performed.
        n_samples: Number of Monte Carlo samples drawn per variant.
        engine_version: Version of the statistics engine that produced
            these numbers.
    """

    model_config = ConfigDict(from_attributes=True)

    is_enabled: bool
    decision: Optional[BayesianDecision] = None
    variant_results: List[BayesianVariantResult] = []
    seed: Optional[int] = Field(
        None,
        ge=0,
        description="Deterministic RNG seed used for the Monte Carlo draws.",
    )
    n_samples: Optional[int] = Field(
        None,
        ge=1,
        description="Monte Carlo samples drawn per variant.",
    )
    engine_version: str = Field(
        ENGINE_VERSION,
        description="Statistics engine version that produced these results.",
    )
