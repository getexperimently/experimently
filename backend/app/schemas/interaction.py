"""
Pydantic schemas for the cross-experiment interaction detection API.

These schemas define the request/response shapes for:
- Single-pair interaction analysis (beta, #219)
- The novelty sub-analysis (beta, #219)
- Active-experiment scan results

``InteractionAnalysisResponse`` and the three sub-result schemas are part of the
stable ``GET /interactions/scan`` response, so their shape does not change: the
sub-results are simply null until they are computed.  The beta routes answer
with their own schemas, which add ``analysis_status``/``analysis_notice``.
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


class InteractionPairResponse(InteractionAnalysisResponse):
    """``GET /interactions/{a}/{b}``: the pair analysis, labelled beta (#219).

    Only ``overlap_coefficient`` and ``has_significant_overlap`` are measured.
    ``interaction_result``, ``novelty_result`` and ``sutva_result`` are null
    (not computed), and ``overall_risk`` comes from the overlap alone.
    """

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
            "Present exactly when analysis_status is 'beta': what is not "
            "computed yet, with the issue that tracks it."
        ),
    )


class NoveltyAnalysisResponse(BaseModel):
    """``GET /interactions/{a}/{b}/novelty``: labelled beta, not computed (#219).

    ``has_novelty`` and ``decline_rate`` are null while ``computed`` is false:
    a null ``has_novelty`` means *not computed*, never *no novelty found*.
    """

    model_config = ConfigDict(from_attributes=True)

    computed: bool = Field(
        False,
        description="Whether novelty was computed.  False in this release.",
    )
    has_novelty: Optional[bool] = Field(
        None,
        description="Null when computed is false: not computed, not 'no novelty'.",
    )
    decline_rate: Optional[float] = Field(
        None,
        description="Slope of the daily treatment effect; null when not computed.",
    )
    recommendation: str
    analysis_status: AnalysisStatusValue = Field(
        default_factory=lambda: analysis_table.analysis_status("novelty"),
        description=(
            "'ga' when these numbers are what their names say; 'beta' when part "
            "of the analysis is not computed yet (see analysis_notice)."
        ),
    )
    analysis_notice: Optional[str] = Field(
        default_factory=lambda: analysis_table.analysis_notice("novelty"),
        description=(
            "Present exactly when analysis_status is 'beta': what is not "
            "computed yet, with the issue that tracks it."
        ),
    )

    @model_validator(mode="after")
    def _not_computed_means_null(self) -> "NoveltyAnalysisResponse":
        """A result only when computed: never ``has_novelty: false`` by default."""
        if self.computed and self.has_novelty is None:
            raise ValueError("a computed novelty result needs has_novelty")
        if not self.computed and (
            self.has_novelty is not None or self.decline_rate is not None
        ):
            raise ValueError(
                "has_novelty and decline_rate must be null when novelty is not computed"
            )
        return self


class ActiveInteractionScanResponse(BaseModel):
    """Summary response for a scan of all active experiment pairs."""

    model_config = ConfigDict(from_attributes=True)

    total_active_experiments: int
    pairs_analyzed: int
    high_risk_pairs: int
    analyses: List[InteractionAnalysisResponse]
