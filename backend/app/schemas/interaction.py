"""
Pydantic schemas for the cross-experiment interaction detection API.

These schemas define the request/response shapes for:
- Single-pair interaction analysis
- Active-experiment scan results
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


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


class ActiveInteractionScanResponse(BaseModel):
    """Summary response for a scan of all active experiment pairs."""

    model_config = ConfigDict(from_attributes=True)

    total_active_experiments: int
    pairs_analyzed: int
    high_risk_pairs: int
    analyses: List[InteractionAnalysisResponse]
