"""
Experiment Wizard API endpoints.

Provides a step-by-step guided interface for non-technical users to design
and launch experiments without engineering involvement.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.permissions import (
    Action,
    ResourceType,
    check_permission,
    get_permission_error_message,
)
from backend.app.models.user import User
from backend.app.schemas.experiment_wizard import (
    WizardDraftCreate,
    WizardDraftListResponse,
    WizardDraftResponse,
    WizardStepUpdate,
    WizardSubmitResponse,
    WizardValidationRequest,
    WizardValidationResponse,
)
from backend.app.services.experiment_wizard_service import ExperimentWizardService

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Experiment Wizard"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Authentication required"},
        status.HTTP_403_FORBIDDEN: {"description": "Permission denied"},
        status.HTTP_404_NOT_FOUND: {"description": "Draft not found"},
    },
)


def _draft_to_response(draft) -> WizardDraftResponse:
    """Convert a WizardDraft dataclass to a WizardDraftResponse schema."""
    return WizardDraftResponse(
        id=draft.id,
        user_id=draft.user_id,
        current_step=draft.current_step,
        experiment_type=draft.experiment_type,
        hypothesis=draft.hypothesis,
        primary_metric_id=draft.primary_metric_id,
        guardrail_metric_ids=draft.guardrail_metric_ids or [],
        targeting_rules=draft.targeting_rules or [],
        baseline_rate=draft.baseline_rate,
        mde=draft.mde,
        name=draft.name,
        description=draft.description,
    )


@router.post(
    "/drafts",
    response_model=WizardDraftResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new experiment wizard draft",
    description=(
        "Initialise a new wizard draft for the authenticated user. "
        "The draft starts at the 'choose_type' step and accumulates data "
        "as the user progresses through the wizard."
    ),
)
def create_draft(
    body: WizardDraftCreate,
    current_user: User = Depends(deps.get_current_active_user),
) -> WizardDraftResponse:
    """Create a new wizard draft."""
    user_id = str(current_user.id)
    draft = ExperimentWizardService.create_draft(
        user_id=user_id,
        experiment_type=body.experiment_type,
    )
    logger.info(
        "Wizard draft created",
        extra={"draft_id": draft.id, "user_id": user_id},
    )
    return _draft_to_response(draft)


@router.get(
    "/drafts",
    response_model=WizardDraftListResponse,
    summary="List wizard drafts for the current user",
    description="Returns all in-progress wizard drafts belonging to the authenticated user.",
)
def list_drafts(
    current_user: User = Depends(deps.get_current_active_user),
) -> WizardDraftListResponse:
    """List all drafts for the authenticated user."""
    user_id = str(current_user.id)
    drafts = ExperimentWizardService.list_drafts(user_id)
    draft_responses = [_draft_to_response(d) for d in drafts]
    return WizardDraftListResponse(drafts=draft_responses, total=len(draft_responses))


@router.get(
    "/drafts/{draft_id}",
    response_model=WizardDraftResponse,
    summary="Get a wizard draft by ID",
    description="Retrieve a specific wizard draft including all accumulated step data.",
)
def get_draft(
    draft_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> WizardDraftResponse:
    """Get a specific wizard draft."""
    draft = ExperimentWizardService.get_draft(draft_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft '{draft_id}' not found.",
        )
    return _draft_to_response(draft)


@router.put(
    "/drafts/{draft_id}/step",
    response_model=WizardDraftResponse,
    summary="Update a wizard draft with step data",
    description=(
        "Submit data for the current wizard step and advance to the next step. "
        "The draft accumulates data across all steps."
    ),
)
def update_draft_step(
    draft_id: str,
    body: WizardStepUpdate,
    current_user: User = Depends(deps.get_current_active_user),
) -> WizardDraftResponse:
    """Update a wizard draft step and advance to the next step."""
    draft = ExperimentWizardService.update_draft(
        draft_id=draft_id,
        step=body.step,
        data=body.data,
    )
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft '{draft_id}' not found.",
        )
    return _draft_to_response(draft)


@router.post(
    "/validate",
    response_model=WizardValidationResponse,
    summary="Validate wizard step data",
    description=(
        "Validate data for a specific wizard step without modifying any draft. "
        "Returns is_valid flag and list of validation errors."
    ),
)
def validate_step(
    body: WizardValidationRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> WizardValidationResponse:
    """Validate data for a specific wizard step."""
    result = ExperimentWizardService.validate_wizard_step(
        step=body.step,
        data=body.data,
    )
    return WizardValidationResponse(
        is_valid=result.is_valid,
        errors=result.errors,
    )


@router.post(
    "/drafts/{draft_id}/submit",
    response_model=WizardSubmitResponse,
    summary="Submit a completed wizard draft to create an experiment",
    description=(
        "Validate the completed draft and create the experiment it describes "
        "(status DRAFT, owned by the caller), then discard the draft. Returns "
        "the new experiment_id on success or validation errors on failure."
    ),
)
def submit_draft(
    draft_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> WizardSubmitResponse:
    """Submit a completed wizard draft and create the experiment."""
    # Submitting writes a real experiment, so it needs the same permission as
    # POST /api/v1/experiments/ — a VIEWER must not be able to create one here.
    if not check_permission(current_user, ResourceType.EXPERIMENT, Action.CREATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.EXPERIMENT, Action.CREATE),
        )

    # Check draft exists before attempting submission
    draft = ExperimentWizardService.get_draft(draft_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Draft '{draft_id}' not found.",
        )

    result = ExperimentWizardService.validate_and_submit(
        draft_id, db=db, user_id=current_user.id
    )

    return WizardSubmitResponse(
        success=result["success"],
        experiment_id=result.get("experiment_id"),
        errors=result.get("errors", []),
    )
