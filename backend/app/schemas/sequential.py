"""
Pydantic v2 schemas for Sequential Testing & Early Stopping (EP-021).

Defines request/response models for mSPRT-based sequential analysis,
always-valid confidence intervals, alpha spending, and evidence trajectories.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.core.analysis_status import AnalysisStatus

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SequentialTestingMethod(str, Enum):
    """Sequential testing algorithm to use."""

    MSPRT = "msprt"
    ALWAYS_VALID = "always_valid"


class SpendingFunction(str, Enum):
    """Alpha spending function for group sequential boundaries."""

    OBRIEN_FLEMING = "obrien_fleming"
    POCOCK = "pocock"


class EvidenceStrength(str, Enum):
    """Qualitative strength of evidence from sequential monitoring."""

    STRONG_FOR_EFFECT = "strong_for_effect"
    MODERATE_FOR_EFFECT = "moderate_for_effect"
    INCONCLUSIVE = "inconclusive"
    MODERATE_FOR_NULL = "moderate_for_null"
    STRONG_FOR_NULL = "strong_for_null"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class SequentialTestingConfig(BaseModel):
    """Configuration for sequential testing on an experiment."""

    model_config = ConfigDict(from_attributes=True)

    tau_squared: float = Field(
        default=0.001,
        gt=0.0,
        le=1.0,
        description="mSPRT mixing parameter (variance of prior on effect size).",
    )
    spending_function: SpendingFunction = Field(
        default=SpendingFunction.OBRIEN_FLEMING,
        description="Alpha spending function for group sequential boundaries.",
    )
    planned_looks: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of planned interim analyses.",
    )
    alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=1.0,
        description="Overall Type I error rate.",
    )
    expected_duration_days: Optional[int] = Field(
        default=None,
        ge=1,
        description="Expected experiment duration in days (for long-running risk).",
    )
    required_sample_size: Optional[int] = Field(
        default=None,
        ge=1,
        description="Target sample size per variant (for long-running risk).",
    )

    @field_validator("tau_squared", mode="before")
    @classmethod
    def validate_tau_squared(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError("tau_squared must be positive")
        return v


# ---------------------------------------------------------------------------
# Response Sub-models
# ---------------------------------------------------------------------------


class MSPRTResultResponse(BaseModel):
    """Result of an mSPRT computation."""

    model_config = ConfigDict(from_attributes=True)

    lambda_ratio: float = Field(..., description="mSPRT likelihood ratio (Lambda_n).")
    always_valid_p_value: float = Field(
        ..., description="Always-valid p-value: min(1, 1/Lambda_n)."
    )
    can_stop: bool = Field(
        ..., description="Whether the experiment can be stopped early."
    )
    evidence_strength: EvidenceStrength = Field(
        ..., description="Qualitative strength of evidence."
    )
    boundary: float = Field(..., description="Stopping boundary (1/alpha).")


class ConfidenceSequenceResponse(BaseModel):
    """Always-valid confidence interval (confidence sequence)."""

    model_config = ConfigDict(from_attributes=True)

    lower: float = Field(..., description="Lower bound of confidence sequence.")
    upper: float = Field(..., description="Upper bound of confidence sequence.")
    width: float = Field(
        ..., description="Width of confidence sequence (upper - lower)."
    )
    sample_size: int = Field(
        ..., ge=0, description="Sample size at which CI was computed."
    )


class AlphaSpendingBoundaryResponse(BaseModel):
    """Alpha spending boundary at a single interim look."""

    model_config = ConfigDict(from_attributes=True)

    look_number: int = Field(..., ge=1, description="Interim analysis number.")
    cumulative_alpha: float = Field(
        ..., description="Cumulative alpha spent up to this look."
    )
    boundary_z: float = Field(..., description="Critical z-value at this look.")
    boundary_p: float = Field(..., description="Critical p-value at this look.")


class EvidencePointResponse(BaseModel):
    """A single point on the evidence trajectory."""

    model_config = ConfigDict(from_attributes=True)

    sample_size: int = Field(
        ..., ge=0, description="Cumulative sample size at this look."
    )
    lambda_ratio: float = Field(..., description="mSPRT Lambda ratio at this look.")
    always_valid_p_value: float = Field(
        ..., description="Always-valid p-value at this look."
    )
    can_stop: bool = Field(
        ..., description="Whether stopping is justified at this look."
    )


class LongRunningRiskResponse(BaseModel):
    """Risk assessment for experiments running longer than expected."""

    model_config = ConfigDict(from_attributes=True)

    is_at_risk: bool = Field(
        ..., description="Whether the experiment is at risk of running too long."
    )
    expected_duration_days: int = Field(
        ..., ge=0, description="Expected duration in days."
    )
    actual_duration_days: int = Field(
        ..., ge=0, description="Actual duration so far in days."
    )
    risk_ratio: float = Field(..., description="Ratio of actual to expected duration.")
    recommendation: str = Field(..., description="Recommendation for the experiment.")


# ---------------------------------------------------------------------------
# Top-level Sequential Testing Response
# ---------------------------------------------------------------------------

#: The recommended_action value set.  The dashboard's ``RecommendedAction``
#: type (frontend/src/types/sequential.ts) is this exact set, and a test pins
#: the two together.  ``stop_for_futility`` stays in it although the analysis
#: no longer emits it: removing a value a stored snapshot or a client may hold
#: is not an additive change.
RECOMMENDED_ACTIONS = frozenset({"stop_for_effect", "stop_for_futility", "continue"})


class SequentialTestingResponse(BaseModel):
    """Full sequential testing analysis returned alongside experiment results."""

    model_config = ConfigDict(from_attributes=True)

    method: SequentialTestingMethod = Field(
        ...,
        description=(
            "Sequential testing method used. Always 'msprt': a stored "
            "'always_valid' is an alias of it and is echoed as 'msprt'."
        ),
    )
    msprt_result: Optional[MSPRTResultResponse] = Field(
        None, description="mSPRT result (when method is msprt)."
    )
    confidence_sequence: Optional[ConfidenceSequenceResponse] = Field(
        None, description="Always-valid confidence interval."
    )
    evidence_trajectory: List[EvidencePointResponse] = Field(
        default_factory=list,
        description="Evidence ratio over time for charting.",
    )
    alpha_spending: List[AlphaSpendingBoundaryResponse] = Field(
        default_factory=list,
        description=(
            "Always empty: the planned-looks (alpha-spending) table is not "
            "computed yet. See analysis_notice."
        ),
    )
    long_running_risk: Optional[LongRunningRiskResponse] = Field(
        None, description="Long-running risk assessment."
    )
    recommended_action: str = Field(
        ...,
        description=(
            "Recommended action: 'stop_for_effect', 'stop_for_futility', or "
            "'continue'. The mSPRT decides; an experiment that runs long is "
            "reported in at_risk, not as 'stop_for_futility'."
        ),
    )
    at_risk: Optional[bool] = Field(
        None,
        description=(
            "Advisory: the experiment is running well past its expected "
            "duration or collecting samples slowly. Not a stopping rule and "
            "not evidence of no effect."
        ),
    )
    analysis_status: Optional[AnalysisStatus] = Field(
        None,
        description=(
            "'ga' when these numbers are established, 'beta' when part of the "
            "analysis is still being corrected or is not computed."
        ),
    )
    analysis_notice: Optional[str] = Field(
        None,
        description="What is beta and why; present exactly when analysis_status is 'beta'.",
    )

    @field_validator("recommended_action", mode="before")
    @classmethod
    def validate_recommended_action(cls, v: str) -> str:
        if v not in RECOMMENDED_ACTIONS:
            raise ValueError(
                f"recommended_action must be one of {sorted(RECOMMENDED_ACTIONS)}, "
                f"got {v!r}"
            )
        return v
