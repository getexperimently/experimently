"""
Pydantic schemas for the Experiment Wizard API.

These schemas define the request and response shapes for the step-by-step
no-code experiment creation wizard.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WizardStepUpdate(BaseModel):
    """Request body for updating a draft with a completed step."""

    step: str = Field(..., description="The wizard step name being completed.")
    data: Dict[str, Any] = Field(
        ..., description="Step-specific data payload."
    )


class WizardDraftCreate(BaseModel):
    """Request body for creating a new wizard draft."""

    experiment_type: str = Field(
        default="ab",
        description="Initial experiment type: 'ab', 'multivariate', or 'feature_flag_rollout'.",
    )


class WizardDraftResponse(BaseModel):
    """Response schema for a wizard draft."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    current_step: str
    experiment_type: Optional[str] = None
    hypothesis: Optional[str] = None
    primary_metric_id: Optional[str] = None
    guardrail_metric_ids: List[str] = Field(default_factory=list)
    targeting_rules: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_rate: Optional[float] = None
    mde: Optional[float] = None
    name: Optional[str] = None
    description: Optional[str] = None


class WizardValidationRequest(BaseModel):
    """Request body for validating a wizard step."""

    step: str = Field(..., description="The wizard step name to validate.")
    data: Dict[str, Any] = Field(
        ..., description="Step data to validate."
    )


class WizardValidationResponse(BaseModel):
    """Response schema for a wizard step validation result."""

    is_valid: bool
    errors: List[str] = Field(default_factory=list)


class WizardSubmitResponse(BaseModel):
    """Response schema for wizard draft submission."""

    success: bool
    experiment_id: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


class WizardDraftListResponse(BaseModel):
    """Response schema for listing wizard drafts."""

    drafts: List[WizardDraftResponse] = Field(default_factory=list)
    total: int = 0
