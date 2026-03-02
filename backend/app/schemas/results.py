"""
Pydantic v2 schemas for the experiment results API (EP-016).

This module defines all request/response schemas for the Analytics &
Experiment Results Engine, including per-variant statistics, metric
aggregations, time-series data, sample-size calculations, and the
top-level experiment results response.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.dimensional import DimensionalBreakdownResponse
from backend.app.schemas.sequential import SequentialTestingResponse


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RecommendationAction(str, Enum):
    """Decision recommendation for an experiment after analysis.

    SHIP_VARIANT    - A treatment variant has won; ship it.
    KEEP_CONTROL    - No variant beat the control; keep the status quo.
    CONTINUE_TESTING - Results are directional but not yet conclusive.
    INCONCLUSIVE    - Results are mixed or otherwise uninterpretable.
    """

    SHIP_VARIANT = "SHIP_VARIANT"
    KEEP_CONTROL = "KEEP_CONTROL"
    CONTINUE_TESTING = "CONTINUE_TESTING"
    INCONCLUSIVE = "INCONCLUSIVE"


class CorrectionMethod(str, Enum):
    """Multiple-comparison correction method applied to p-values.

    NONE               - No correction applied (raw p-values).
    BONFERRONI         - Conservative family-wise error rate control.
    BENJAMINI_HOCHBERG - False discovery rate (FDR) control; less conservative.
    """

    NONE = "none"
    BONFERRONI = "bonferroni"
    BENJAMINI_HOCHBERG = "benjamini_hochberg"


class EffectSizeLabel(str, Enum):
    """Qualitative label for the magnitude of an effect size.

    Based on Cohen's conventional thresholds (h or d):
      NEGLIGIBLE - |d| < 0.2
      SMALL      - 0.2 <= |d| < 0.5
      MEDIUM     - 0.5 <= |d| < 0.8
      LARGE      - |d| >= 0.8
    """

    NEGLIGIBLE = "negligible"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class StatisticalTest(str, Enum):
    """Statistical test used when computing significance for a variant result.

    FISHER_EXACT       - Fisher's exact test (small-sample conversion data).
    Z_TEST_PROPORTIONS - Two-proportion z-test (large-sample conversions).
    WELCH_T_TEST       - Welch's t-test (continuous/revenue metrics).
    """

    FISHER_EXACT = "fisher_exact"
    Z_TEST_PROPORTIONS = "z_test_proportions"
    WELCH_T_TEST = "welch_t_test"


# ---------------------------------------------------------------------------
# VariantResult
# ---------------------------------------------------------------------------


class VariantResult(BaseModel):
    """Statistical results for a single variant on a single metric.

    Contains all per-variant statistics produced by the analysis engine,
    including sample counts, point estimates, confidence intervals,
    significance tests, and effect-size characterisation.

    For the control variant, fields that represent a comparison vs. the
    control (``p_value``, ``adjusted_p_value``, ``relative_improvement_pct``,
    ``effect_size``, ``effect_size_label``, ``power``, and
    ``statistical_test_used``) are ``None``.

    For conversion metrics ``std_dev`` and ``conversions`` are both set;
    ``mean`` holds the observed conversion rate in [0, 1].  For continuous
    metrics (revenue, duration, custom) ``conversions`` is ``None`` and
    ``mean`` holds the raw arithmetic mean.
    """

    model_config = ConfigDict(from_attributes=True)

    variant_id: UUID = Field(..., description="Unique identifier of the variant.")
    variant_name: str = Field(..., description="Human-readable name of the variant.")
    is_control: bool = Field(
        ...,
        description="True when this is the control (baseline) variant.",
    )
    sample_size: Annotated[int, Field(ge=0)] = Field(
        ...,
        description="Number of unique users assigned to this variant.",
    )
    conversions: Optional[int] = Field(
        None,
        description=(
            "Number of conversion events observed.  None for non-conversion "
            "metric types (revenue, duration, custom)."
        ),
    )
    mean: float = Field(
        ...,
        description=(
            "For conversion metrics: observed conversion rate in [0, 1].  "
            "For continuous metrics: raw arithmetic mean of observed values."
        ),
    )
    std_dev: Optional[float] = Field(
        None,
        description=(
            "Sample standard deviation of observed values.  "
            "None for conversion metrics (variance is implied by the rate)."
        ),
    )
    confidence_interval: tuple[float, float] = Field(
        ...,
        description=(
            "Two-sided confidence interval as (lower, upper).  "
            "The confidence level is specified at the experiment level."
        ),
    )
    p_value: Optional[float] = Field(
        None,
        description=(
            "Unadjusted p-value from the chosen statistical test.  "
            "None for the control variant."
        ),
    )
    adjusted_p_value: Optional[float] = Field(
        None,
        description=(
            "p-value after applying the experiment-level multiple-comparison "
            "correction method.  None for the control variant or when "
            "correction_method is NONE."
        ),
    )
    is_significant: bool = Field(
        ...,
        description=(
            "True when the adjusted (or raw, if no correction) p-value is "
            "below the experiment's significance threshold (1 - confidence_level)."
        ),
    )
    effect_size: Optional[float] = Field(
        None,
        description=(
            "Standardised effect size: Cohen's h for conversion metrics, "
            "Cohen's d for continuous metrics.  None for the control variant."
        ),
    )
    effect_size_label: Optional[EffectSizeLabel] = Field(
        None,
        description=(
            "Qualitative label derived from the Cohen's convention thresholds.  "
            "None for the control variant."
        ),
    )
    relative_improvement_pct: Optional[float] = Field(
        None,
        description=(
            "Relative change in the metric mean compared with the control, "
            "expressed as a percentage: ((variant_mean - control_mean) / "
            "control_mean) * 100.  None for the control variant."
        ),
    )
    power: Optional[float] = Field(
        None,
        description=(
            "Achieved statistical power (1 - beta) for detecting the observed "
            "effect at the configured significance level.  None for the control "
            "variant."
        ),
    )
    statistical_test_used: Optional[StatisticalTest] = Field(
        None,
        description=(
            "The statistical test that produced p_value.  "
            "None for the control variant."
        ),
    )

    @field_validator("p_value", "adjusted_p_value", mode="before")
    @classmethod
    def validate_p_value_range(cls, v: Optional[float]) -> Optional[float]:
        """Validate that p-values are either None or in [0.0, 1.0]."""
        if v is None:
            return v
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"p-value must be in the range [0.0, 1.0], got {v!r}."
            )
        return v


# ---------------------------------------------------------------------------
# MetricResult
# ---------------------------------------------------------------------------


class MetricResult(BaseModel):
    """Aggregated results for one metric across all experiment variants.

    Holds the per-variant ``VariantResult`` objects together with summary
    flags that indicate whether the experiment produced a statistically
    significant winner for this metric.
    """

    model_config = ConfigDict(from_attributes=True)

    metric_id: UUID = Field(..., description="Unique identifier of the metric definition.")
    metric_name: str = Field(..., description="Human-readable name of the metric.")
    metric_type: str = Field(
        ...,
        description=(
            "Metric category: one of 'conversion', 'revenue', 'count', "
            "'duration', or 'custom'."
        ),
    )
    is_primary: bool = Field(
        ...,
        description=(
            "True when this is the primary (decision) metric for the experiment."
        ),
    )
    variants: List[VariantResult] = Field(
        ...,
        description="Per-variant statistical results, one entry per variant.",
    )
    has_significant_result: bool = Field(
        ...,
        description=(
            "True when at least one non-control variant has is_significant=True "
            "for this metric."
        ),
    )
    winning_variant_id: Optional[UUID] = Field(
        None,
        description=(
            "ID of the variant with the best significant result, or None if no "
            "variant achieved significance."
        ),
    )

    @property
    def control_variant(self) -> Optional[VariantResult]:
        """Return the control VariantResult, or None if not present."""
        for variant in self.variants:
            if variant.is_control:
                return variant
        return None


# ---------------------------------------------------------------------------
# ExperimentSummary
# ---------------------------------------------------------------------------


class ExperimentSummary(BaseModel):
    """High-level summary of an experiment's overall performance.

    Provides aggregate counts and the engine's recommendation, allowing
    consumers to present a quick decision overview without inspecting
    individual metric results.
    """

    model_config = ConfigDict(from_attributes=True)

    total_users: int = Field(
        ...,
        description="Total unique users enrolled across all variants.",
    )
    total_events: int = Field(
        ...,
        description="Total metric-relevant events recorded across all variants.",
    )
    total_conversions: Optional[int] = Field(
        None,
        description=(
            "Total conversion events across all variants.  None when the "
            "experiment has no conversion metric."
        ),
    )
    duration_days: Optional[int] = Field(
        None,
        description=(
            "Number of calendar days the experiment has been (or was) running.  "
            "None when start_date is not yet known."
        ),
    )
    has_winner: bool = Field(
        ...,
        description=(
            "True when at least one variant achieved significance on the primary "
            "metric."
        ),
    )
    winning_variant_id: Optional[UUID] = Field(
        None,
        description=(
            "ID of the winning variant on the primary metric, or None if no "
            "winner was found."
        ),
    )
    recommendation: RecommendationAction = Field(
        ...,
        description="The engine's recommended action for this experiment.",
    )
    recommendation_reason: str = Field(
        ...,
        description=(
            "Human-readable explanation of why this recommendation was made."
        ),
    )


# ---------------------------------------------------------------------------
# ExperimentResultsResponse
# ---------------------------------------------------------------------------


class ExperimentResultsResponse(BaseModel):
    """Top-level response schema for the experiment results endpoint.

    Returned by ``GET /api/v1/experiments/{experiment_id}/results``.
    Contains experiment metadata, analysis configuration, a high-level
    summary, and the full per-metric breakdown.
    """

    model_config = ConfigDict(from_attributes=True)

    experiment_id: UUID = Field(
        ...,
        description="Unique identifier of the experiment.",
    )
    experiment_name: str = Field(
        ...,
        description="Human-readable name of the experiment.",
    )
    status: str = Field(
        ...,
        description=(
            "Current lifecycle status of the experiment: 'draft', 'active', "
            "'paused', 'completed', or 'archived'."
        ),
    )
    start_date: Optional[datetime] = Field(
        None,
        description="UTC timestamp when the experiment started, or None if not yet started.",
    )
    end_date: Optional[datetime] = Field(
        None,
        description="UTC timestamp when the experiment ended, or None if still running.",
    )
    confidence_level: Annotated[float, Field(ge=0.80, le=0.99)] = Field(
        default=0.95,
        description=(
            "Statistical confidence level used for significance testing and "
            "confidence interval construction.  Must be in [0.80, 0.99]."
        ),
    )
    correction_method: CorrectionMethod = Field(
        default=CorrectionMethod.NONE,
        description=(
            "Multiple-comparison correction method applied when there are "
            "multiple metrics or variants."
        ),
    )
    sample_size_adequate: bool = Field(
        ...,
        description=(
            "True when every variant has reached the minimum required sample "
            "size for the configured power and effect size targets."
        ),
    )
    computed_at: datetime = Field(
        ...,
        description="UTC timestamp at which these results were computed.",
    )
    summary: ExperimentSummary = Field(
        ...,
        description="High-level experiment summary and recommendation.",
    )
    metrics: List[MetricResult] = Field(
        ...,
        description="Full per-metric statistical results.",
    )

    # EP-021: Sequential testing (backward compatible — null for non-sequential)
    sequential_testing: Optional[SequentialTestingResponse] = Field(
        None,
        description=(
            "Sequential testing analysis data (mSPRT, confidence sequences, "
            "evidence trajectory). Null when sequential testing is not enabled."
        ),
    )

    # Issue #28: Dimensional breakdown (backward compatible — null when not requested)
    breakdown: Optional[DimensionalBreakdownResponse] = Field(
        None,
        description=(
            "Dimensional breakdown of results by user segment. "
            "Populated only when the ?breakdown=<dimension> query parameter is supplied."
        ),
    )

    @field_validator("confidence_level", mode="before")
    @classmethod
    def validate_confidence_level(cls, v: float) -> float:
        """Validate that confidence_level is in the range [0.80, 0.99]."""
        if not (0.80 <= v <= 0.99):
            raise ValueError(
                f"confidence_level must be between 0.80 and 0.99 inclusive, got {v!r}."
            )
        return v


# ---------------------------------------------------------------------------
# DailyDataPoint
# ---------------------------------------------------------------------------


class DailyDataPoint(BaseModel):
    """A single day's worth of metric observations for one variant.

    Used both for raw daily snapshots (``VariantTimeSeries.values``) and
    for running cumulative totals (``VariantTimeSeries.cumulative``).
    """

    model_config = ConfigDict(from_attributes=True)

    date: str = Field(
        ...,
        description=(
            "Calendar date of this data point in ISO 8601 format: 'YYYY-MM-DD'."
        ),
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    sample_size: int = Field(
        ...,
        description="Number of users included in this data point.",
    )
    conversions: Optional[int] = Field(
        None,
        description=(
            "Number of conversion events in this data point.  None for "
            "non-conversion metric types."
        ),
    )
    mean: float = Field(
        ...,
        description=(
            "For conversion metrics: conversion rate for this data point.  "
            "For continuous metrics: arithmetic mean of observed values."
        ),
    )


# ---------------------------------------------------------------------------
# VariantTimeSeries
# ---------------------------------------------------------------------------


class VariantTimeSeries(BaseModel):
    """Time-series data for a single variant on a single metric.

    Provides both a daily view (``values``) and a running cumulative view
    (``cumulative``) so that consumers can render both chart types without
    additional computation.
    """

    model_config = ConfigDict(from_attributes=True)

    variant_id: UUID = Field(..., description="Unique identifier of the variant.")
    variant_name: str = Field(..., description="Human-readable name of the variant.")
    is_control: bool = Field(
        ...,
        description="True when this is the control (baseline) variant.",
    )
    values: List[DailyDataPoint] = Field(
        ...,
        description=(
            "Ordered list of daily metric observations, one entry per calendar "
            "day the experiment was active."
        ),
    )
    cumulative: List[DailyDataPoint] = Field(
        ...,
        description=(
            "Ordered list of cumulative metric totals, one entry per calendar "
            "day.  Each entry accumulates all observations from experiment start "
            "through that day."
        ),
    )


# ---------------------------------------------------------------------------
# DailyResultsResponse
# ---------------------------------------------------------------------------


class DailyResultsResponse(BaseModel):
    """Response schema for the experiment time-series endpoint.

    Returned by
    ``GET /api/v1/experiments/{experiment_id}/results/daily``.

    When ``metric_id`` is supplied, ``series`` contains data for that
    single metric; when omitted, the endpoint returns data for the primary
    metric (behaviour defined by the endpoint implementation).
    """

    model_config = ConfigDict(from_attributes=True)

    experiment_id: UUID = Field(
        ...,
        description="Unique identifier of the experiment.",
    )
    metric_id: Optional[UUID] = Field(
        None,
        description=(
            "Metric for which time-series data is returned.  None when the "
            "response covers the primary metric and the client did not filter "
            "by metric."
        ),
    )
    series: List[VariantTimeSeries] = Field(
        ...,
        description="Per-variant time-series data, one entry per variant.",
    )


# ---------------------------------------------------------------------------
# SampleSizeResult
# ---------------------------------------------------------------------------


class SampleSizeResult(BaseModel):
    """Result of a sample-size / statistical-power analysis.

    Returned by the sample-size calculation endpoint and embedded in
    experiment results to convey whether the experiment has sufficient data
    to draw conclusions.
    """

    model_config = ConfigDict(from_attributes=True)

    required_sample_size_per_variant: Annotated[int, Field(ge=1)] = Field(
        ...,
        description=(
            "Minimum number of users required per variant to achieve the target "
            "power at the configured MDE and confidence level."
        ),
    )
    current_sample_size_per_variant: int = Field(
        ...,
        description=(
            "Actual number of users currently assigned to the smallest variant "
            "(used as the conservative reference)."
        ),
    )
    is_adequate: bool = Field(
        ...,
        description=(
            "True when current_sample_size_per_variant >= "
            "required_sample_size_per_variant."
        ),
    )
    achieved_power: float = Field(
        ...,
        description=(
            "Estimated statistical power (1 - beta) achievable with the current "
            "sample size, at the configured MDE and confidence level."
        ),
    )
    days_to_significance: Optional[int] = Field(
        None,
        description=(
            "Projected number of additional calendar days until the required "
            "sample size is reached, based on the current enrolment rate.  "
            "None when the required size is already met or the rate cannot be "
            "estimated."
        ),
    )
    projected_completion_date: Optional[datetime] = Field(
        None,
        description=(
            "UTC timestamp of the projected date on which the required sample "
            "size will be reached.  None when days_to_significance is None."
        ),
    )
    baseline_rate: float = Field(
        ...,
        description=(
            "Baseline conversion rate (or mean) used as the reference point for "
            "effect-size and power calculations."
        ),
    )
    mde: float = Field(
        ...,
        description=(
            "Minimum detectable effect (MDE) expressed as an absolute difference "
            "from the baseline rate."
        ),
    )
    confidence_level: float = Field(
        ...,
        description=(
            "Statistical confidence level used in this power analysis, in [0, 1]."
        ),
    )
    power_target: float = Field(
        ...,
        description=(
            "Target statistical power (1 - beta) used when computing the "
            "required sample size, typically 0.80."
        ),
    )

    @field_validator("required_sample_size_per_variant", mode="before")
    @classmethod
    def validate_required_sample_size(cls, v: int) -> int:
        """Validate that required_sample_size_per_variant is at least 1."""
        if v < 1:
            raise ValueError(
                "required_sample_size_per_variant must be >= 1, "
                f"got {v!r}."
            )
        return v
