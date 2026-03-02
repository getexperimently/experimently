"""
Audience Segmentation API endpoints (P3-C).

REST endpoints for managing audience segments and evaluating user membership.

Routes:
    GET    /api/v1/segments                 — list segments
    POST   /api/v1/segments                 — create segment (DEVELOPER+)
    GET    /api/v1/segments/{id}            — get segment
    PUT    /api/v1/segments/{id}            — update segment (DEVELOPER+)
    DELETE /api/v1/segments/{id}            — archive segment (DEVELOPER+)
    POST   /api/v1/segments/{id}/evaluate   — check user context membership
    POST   /api/v1/segments/bulk-evaluate   — check one user against N segments
    GET    /api/v1/segments/{id}/experiments — list experiments using this segment
    POST   /api/v1/segments/{id}/preview    — estimate audience size
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.permissions import Action, ResourceType, check_permission
from backend.app.models.user import User
from backend.app.schemas.segment import (
    AudiencePreviewResponse,
    BulkSegmentMembershipRequest,
    BulkSegmentMembershipResponse,
    SegmentCreate,
    SegmentExperimentResponse,
    SegmentMembershipRequest,
    SegmentMembershipResponse,
    SegmentResponse,
    SegmentStatus,
    SegmentUpdate,
)
from backend.app.services.audience_service import AudienceService, _segment_to_response_dict

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _require_permission(user: User, action: Action) -> None:
    """
    Raise HTTP 403 if the user lacks the given action on the EXPERIMENT resource.

    Segments are treated as an EXPERIMENT-class resource for permission checking
    because they are tightly coupled to experiment targeting.
    """
    if not check_permission(user, ResourceType.EXPERIMENT, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to perform this action on segments",
        )


# ---------------------------------------------------------------------------
# List segments
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=List[SegmentResponse],
    summary="List audience segments",
    description="Return a paginated list of audience segments. Accessible to all authenticated users.",
    tags=["Segments"],
)
def list_segments(
    segment_status: Optional[SegmentStatus] = Query(
        None, alias="status", description="Filter by segment status"
    ),
    limit: int = Query(50, ge=1, le=200, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> List[SegmentResponse]:
    """List segments with optional status filter."""
    _require_permission(current_user, Action.LIST)
    segments = AudienceService.list_segments(db, status=segment_status, limit=limit, offset=offset)
    return [SegmentResponse(**_segment_to_response_dict(s)) for s in segments]


# ---------------------------------------------------------------------------
# Create segment
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=SegmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an audience segment",
    description="Create a new audience segment with targeting rules. Requires DEVELOPER or ADMIN role.",
    tags=["Segments"],
)
def create_segment(
    data: SegmentCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> SegmentResponse:
    """Create a new audience segment."""
    _require_permission(current_user, Action.CREATE)
    segment = AudienceService.create_segment(db, data, created_by_id=current_user.id)
    return SegmentResponse(**_segment_to_response_dict(segment))


# ---------------------------------------------------------------------------
# Bulk evaluate — placed BEFORE /{id} routes to avoid path collision
# ---------------------------------------------------------------------------

@router.post(
    "/bulk-evaluate",
    response_model=BulkSegmentMembershipResponse,
    summary="Bulk segment membership evaluation",
    description=(
        "Evaluate one user context against multiple segments in a single request. "
        "Returns a membership dict {segment_id: is_member} for each requested segment."
    ),
    tags=["Segments"],
)
def bulk_evaluate_segments(
    request: BulkSegmentMembershipRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> BulkSegmentMembershipResponse:
    """Check user membership across multiple segments at once."""
    _require_permission(current_user, Action.READ)
    return AudienceService.bulk_evaluate_membership(db, request)


# ---------------------------------------------------------------------------
# Get segment
# ---------------------------------------------------------------------------

@router.get(
    "/{segment_id}",
    response_model=SegmentResponse,
    summary="Get an audience segment",
    description="Retrieve a single audience segment by its UUID.",
    tags=["Segments"],
)
def get_segment(
    segment_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> SegmentResponse:
    """Retrieve a segment by ID."""
    _require_permission(current_user, Action.READ)
    try:
        segment = AudienceService.get_segment(db, segment_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return SegmentResponse(**_segment_to_response_dict(segment))


# ---------------------------------------------------------------------------
# Update segment
# ---------------------------------------------------------------------------

@router.put(
    "/{segment_id}",
    response_model=SegmentResponse,
    summary="Update an audience segment",
    description="Update segment name, description, rules, or status. Requires DEVELOPER or ADMIN role.",
    tags=["Segments"],
)
def update_segment(
    segment_id: str,
    data: SegmentUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> SegmentResponse:
    """Update an existing segment."""
    _require_permission(current_user, Action.UPDATE)
    try:
        segment = AudienceService.update_segment(db, segment_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return SegmentResponse(**_segment_to_response_dict(segment))


# ---------------------------------------------------------------------------
# Delete segment (soft delete → ARCHIVED)
# ---------------------------------------------------------------------------

@router.delete(
    "/{segment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive an audience segment",
    description=(
        "Soft-delete a segment by setting its status to ARCHIVED. "
        "Requires DEVELOPER or ADMIN role."
    ),
    tags=["Segments"],
)
def delete_segment(
    segment_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> None:
    """Archive (soft-delete) a segment."""
    _require_permission(current_user, Action.DELETE)
    try:
        AudienceService.delete_segment(db, segment_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# Evaluate membership
# ---------------------------------------------------------------------------

@router.post(
    "/{segment_id}/evaluate",
    response_model=SegmentMembershipResponse,
    summary="Evaluate user membership in a segment",
    description=(
        "Check whether a user context (arbitrary attributes dict) satisfies "
        "this segment's targeting rules."
    ),
    tags=["Segments"],
)
def evaluate_segment_membership(
    segment_id: str,
    request: SegmentMembershipRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> SegmentMembershipResponse:
    """Evaluate if a user context matches the segment's rules."""
    _require_permission(current_user, Action.READ)
    try:
        return AudienceService.evaluate_membership(db, segment_id, request.user_context)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# Get linked experiments
# ---------------------------------------------------------------------------

@router.get(
    "/{segment_id}/experiments",
    response_model=SegmentExperimentResponse,
    summary="List experiments using this segment",
    description=(
        "Return all experiments and feature flags whose targeting_rules reference "
        "this segment's UUID."
    ),
    tags=["Segments"],
)
def get_segment_experiments(
    segment_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> SegmentExperimentResponse:
    """Fetch experiments and feature flags linked to this segment."""
    _require_permission(current_user, Action.READ)
    try:
        return AudienceService.get_segment_experiments(db, segment_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# Preview audience size
# ---------------------------------------------------------------------------

@router.post(
    "/{segment_id}/preview",
    response_model=AudiencePreviewResponse,
    summary="Preview estimated audience size",
    description=(
        "Estimate the percentage of users who would match the provided targeting rules "
        "by evaluating them against a sample of recent assignment records."
    ),
    tags=["Segments"],
)
def preview_audience_size(
    segment_id: str,
    data: SegmentCreate,
    sample_size: int = Query(1000, ge=10, le=10000, description="Sample size for estimation"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> AudiencePreviewResponse:
    """Estimate the audience size for a set of rules."""
    _require_permission(current_user, Action.READ)
    # Verify segment exists (informational, rules come from request body)
    try:
        AudienceService.get_segment(db, segment_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return AudienceService.preview_audience_size(db, data.rules, sample_size=sample_size)
