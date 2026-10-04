"""
Pydantic schemas for the cross-experiment interaction detection API.

These schemas define the response shapes for:
- Single-pair interaction analysis (beta, #219)
- Active-experiment scan results

``InteractionAnalysisResponse`` and the three sub-result schemas are part of the
stable ``GET /interactions/scan`` response, so their shape does not change: the
scan does not test interactions, and its sub-results are null.  The beta pair
route answers with its own schema, ``InteractionPairResponse``.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.core import analysis_status as analysis_table
from backend.app.core.analysis_status import AnalysisStatusValue


class RiskLevel(str, Enum):
    """Aggregated risk level for an experiment pair interaction analysis."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InteractionResultSchema(BaseModel):
    """Schema for the result of a 2×2 chi-squared interaction test."""

    model_config = ConfigDict(from_attributes=True)

    has_interaction: bool
    p_value: float
    interaction_effect_size: float
    warning_message: Optional[str] = None


class NoveltyResultSchema(BaseModel):
    """Schema for novelty effect detection results."""

    model_config = ConfigDict(from_attributes=True)

    has_novelty: bool
    decline_rate: float
    recommendation: str


class SUTVAResultSchema(BaseModel):
    """Schema for SUTVA (Stable Unit Treatment Value Assumption) violation results."""

    model_config = ConfigDict(from_attributes=True)

    has_violation: bool
    contamination_rate: float
    warning_message: Optional[str] = None


class InteractionAnalysisResponse(BaseModel):
    """Full interaction analysis response for a pair of experiments."""

    model_config = ConfigDict(from_attributes=True)

    experiment_a_id: str
    experiment_b_id: str
    overlap_coefficient: float = Field(..., ge=0.0, le=1.0)
    has_significant_overlap: bool
    interaction_result: Optional[InteractionResultSchema] = None
    novelty_result: Optional[NoveltyResultSchema] = None
    sutva_result: Optional[SUTVAResultSchema] = None
    overall_risk: RiskLevel
    recommendations: List[str] = Field(default_factory=list)


class InteractionArm(BaseModel):
    """One arm of the other experiment, among the users in both experiments."""

    other_variant_id: str
    other_variant_name: str
    n_control: int = Field(
        ..., description="Users in this experiment's control and in this arm."
    )
    converted_control: int = Field(..., description="Of those, users who converted.")
    n_treatment: int = Field(
        ..., description="Users in the row's treatment and in this arm."
    )
    converted_treatment: int = Field(..., description="Of those, users who converted.")
    control_rate: Optional[float] = Field(
        None, description="converted_control / n_control; null when n_control is 0."
    )
    treatment_rate: Optional[float] = Field(
        None,
        description="converted_treatment / n_treatment; null when n_treatment is 0.",
    )
    effect: Optional[float] = Field(
        None,
        description=(
            "treatment_rate - control_rate, as a rate (0.05 is 5 percentage "
            "points). This is the lift the test compares across arms."
        ),
    )
    relative_lift: Optional[float] = Field(
        None,
        description=(
            "effect / control_rate, for reading only: the test does not use it. "
            "Null when control_rate is 0 or null."
        ),
    )


class InteractionRow(BaseModel):
    """One treatment of one experiment, tested against the other's arms (beta).

    Computed exactly when ``unavailable_reason`` is null: then ``statistic``,
    ``degrees_of_freedom``, ``p_value`` and ``is_significant`` are set, and
    with a reason they are all null.  A null ``is_significant`` means not
    tested, never "no interaction".
    """

    experiment_id: str = Field(..., description="The experiment whose lift is tested.")
    other_experiment_id: str
    metric_id: Optional[str] = Field(
        None, description="The tested experiment's primary metric."
    )
    metric_name: Optional[str] = None
    variant_id: Optional[str] = Field(
        None,
        description=(
            "The treatment compared with control. Null when the reason applies "
            "to the whole experiment."
        ),
    )
    variant_name: Optional[str] = None
    control_variant_id: Optional[str] = None
    arms: List[InteractionArm] = Field(
        default_factory=list,
        description=(
            "One entry per arm of the other experiment that shares users with "
            "this one, control first, then by name."
        ),
    )
    statistic: Optional[float] = Field(
        None,
        description=(
            "Pearson X^2 of the counts against the model in which the lift in "
            "percentage points is the same in every arm."
        ),
    )
    degrees_of_freedom: Optional[int] = Field(
        None, description="Number of arms minus one."
    )
    p_value: Optional[float] = Field(
        None, description="Uncorrected p-value of the test; null when not tested."
    )
    corrected_p_value: Optional[float] = Field(
        None,
        description=(
            "p_value corrected with correction_method across this experiment's "
            "tested rows; null when the method is none or the row is not tested."
        ),
    )
    correction_method: str = Field(
        ..., description="The tested experiment's stored correction method."
    )
    confidence_level: float = Field(
        ..., description="The tested experiment's stored confidence level."
    )
    is_significant: Optional[bool] = Field(
        None,
        description=(
            "True when the corrected p-value (the p-value under correction "
            "method none) is below 1 - confidence_level. Null when not tested: "
            "null never means no interaction."
        ),
    )
    unavailable_reason: Optional[str] = Field(
        None,
        description=(
            "Null when tested; otherwise the first of these that applies: "
            "mutual_exclusion_group, no_shared_users, no_metric, "
            "not_a_proportion_metric, no_control_variant, too_few_shared_users, "
            "too_few_conversions."
        ),
    )

    @model_validator(mode="after")
    def _tested_exactly_without_a_reason(self) -> "InteractionRow":
        computed = (
            self.statistic,
            self.degrees_of_freedom,
            self.p_value,
            self.is_significant,
        )
        if self.unavailable_reason is None:
            if any(value is None for value in computed):
                raise ValueError("a tested row needs its statistic and decision")
        elif any(value is not None for value in computed) or (
            self.corrected_p_value is not None
        ):
            raise ValueError("a row with an unavailable_reason carries no result")
        return self


class InteractionPairResponse(BaseModel):
    """``GET /interactions/{a}/{b}``: overlap, and the interaction test (beta, #219)."""

    model_config = ConfigDict(from_attributes=True)

    experiment_a_id: str
    experiment_b_id: str
    shared_users: int = Field(..., description="Users assigned to both experiments.")
    share_of_a: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of experiment A's users who are also in experiment B.",
    )
    share_of_b: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of experiment B's users who are also in experiment A.",
    )
    overlap_coefficient: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Jaccard overlap: shared users / users in either experiment.",
    )
    has_significant_overlap: bool = Field(
        ..., description="overlap_coefficient is above 0.3."
    )
    mutual_exclusion_group_id: Optional[str] = Field(
        None,
        description=(
            "The mutual exclusion group both experiments are in; null unless "
            "they are in the same one."
        ),
    )
    min_users_per_cell: int = Field(
        ..., description="Fewest users per combination of arms for a row to be tested."
    )
    min_expected_per_cell: int = Field(
        ...,
        description=(
            "Fewest expected converters and non-converters per combination of "
            "arms for a row to be tested."
        ),
    )
    interaction_results: List[InteractionRow] = Field(default_factory=list)
    has_interaction: Optional[bool] = Field(
        None,
        description=(
            "True when any row is significant; false only when every row was "
            "tested and none is; null otherwise."
        ),
    )
    recommendations: List[str] = Field(default_factory=list)
    analysis_status: AnalysisStatusValue = Field(
        default_factory=lambda: analysis_table.analysis_status("interactions"),
        description=(
            "'ga' when these numbers are what their names say; 'beta' when part "
            "of the analysis is not computed yet (see analysis_notice).  About "
            "the numbers, not the response shape."
        ),
    )
    analysis_notice: Optional[str] = Field(
        default_factory=lambda: analysis_table.analysis_notice("interactions"),
        description=(
            "Present exactly when analysis_status is 'beta': what the numbers "
            "are and are not, with the issue that tracks it."
        ),
    )


class ActiveInteractionScanResponse(BaseModel):
    """Summary response for a scan of all active experiment pairs."""

    model_config = ConfigDict(from_attributes=True)

    total_active_experiments: int
    pairs_analyzed: int
    high_risk_pairs: int
    analyses: List[InteractionAnalysisResponse]
