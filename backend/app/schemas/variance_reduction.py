"""
Variance Reduction schemas — Issue #21.

Pydantic v2 schemas for CUPED variance-reduction configuration and results.
Supports CUPED, CUPED+, and Winsorization methods.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VarianceReductionMethod(str, Enum):
    """Method used for variance reduction in experiment analysis."""

    NONE = "none"
    CUPED = "cuped"
    CUPED_PLUS = "cuped_plus"
    WINSORIZATION = "winsorization"


# ---------------------------------------------------------------------------
# Configuration schema
# ---------------------------------------------------------------------------


class VarianceReductionConfig(BaseModel):
    """Configuration for variance reduction on an experiment.

    This config is stored as JSONB in the experiments table and controls
    which variance-reduction method is applied when computing results.

    Attributes:
        method: Which variance-reduction method to use.
        covariate_metric_id: ID of the pre-experiment metric to use as covariate
            (required for CUPED and CUPED_PLUS methods).
        covariate_lookback_days: Number of days of pre-experiment data to use
            when building the covariate (1–90, default 7).
        winsorization_percentile: Upper percentile for Winsorization clipping
            (50–100, default 99.0).
    """

    model_config = ConfigDict(from_attributes=True)

    method: VarianceReductionMethod = Field(
        default=VarianceReductionMethod.NONE,
        description="Variance-reduction method to apply.",
    )
    covariate_metric_id: Optional[str] = Field(
        default=None,
        description=(
            "ID of the pre-experiment metric used as the CUPED covariate. "
            "Required when method is 'cuped' or 'cuped_plus'."
        ),
    )
    covariate_lookback_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description=(
            "Number of days of pre-experiment history to use when building the "
            "covariate. Must be between 1 and 90."
        ),
    )
    winsorization_percentile: float = Field(
        default=99.0,
        ge=50.0,
        le=100.0,
        description=(
            "Upper percentile threshold for Winsorization (50–100). "
            "Values above this percentile are clipped to the threshold value."
        ),
    )


# ---------------------------------------------------------------------------
# Per-metric CUPED result
# ---------------------------------------------------------------------------


class CupedMetricResult(BaseModel):
    """CUPED-adjusted statistics for a single metric.

    Produced by the CUPED results endpoint for each metric in an experiment,
    containing both the variance-reduction statistics and the adjusted
    treatment effect estimate.
    """

    model_config = ConfigDict(from_attributes=True)

    metric_id: str = Field(..., description="Unique identifier of the metric.")
    metric_name: str = Field(..., description="Human-readable name of the metric.")
    adjusted_control_mean: float = Field(
        ..., description="Mean of the CUPED-adjusted control observations."
    )
    adjusted_treatment_mean: float = Field(
        ..., description="Mean of the CUPED-adjusted treatment observations."
    )
    adjusted_effect: float = Field(
        ...,
        description="adjusted_treatment_mean - adjusted_control_mean.",
    )
    adjusted_se: float = Field(
        ..., description="Pooled standard error of the adjusted effect estimate."
    )
    adjusted_p_value: float = Field(
        ...,
        description="Two-tailed p-value from a z-test on the adjusted effect.",
    )
    adjusted_ci_lower: float = Field(
        ..., description="Lower bound of the 95% confidence interval."
    )
    adjusted_ci_upper: float = Field(
        ..., description="Upper bound of the 95% confidence interval."
    )
    variance_reduction_pct: float = Field(
        ...,
        description=(
            "Percentage of variance removed by CUPED relative to the raw "
            "control variance. Positive values indicate reduction."
        ),
    )
    theta: float = Field(
        ...,
        description="OLS coefficient θ = Cov(Y,X) / Var(X) used for adjustment.",
    )
    method: VarianceReductionMethod = Field(
        ..., description="The variance-reduction method that was applied."
    )


# ---------------------------------------------------------------------------
# Top-level CUPED results response
# ---------------------------------------------------------------------------


class CupedResultsResponse(BaseModel):
    """Response schema for the CUPED variance-reduced results endpoint.

    Returned by ``GET /api/v1/results/{experiment_id}/cuped``.
    Contains per-metric CUPED-adjusted results for an experiment.
    """

    model_config = ConfigDict(from_attributes=True)

    experiment_id: str = Field(
        ..., description="Unique identifier of the experiment."
    )
    method: VarianceReductionMethod = Field(
        ..., description="Variance-reduction method that was applied."
    )
    metrics: List[CupedMetricResult] = Field(
        ..., description="Per-metric CUPED-adjusted results."
    )
    computed_at: str = Field(
        ..., description="ISO 8601 UTC timestamp of when the results were computed."
    )
