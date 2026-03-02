"""
Mutual Exclusion Group API endpoints (EP-022).

REST endpoints for managing mutual exclusion groups that prevent users
from being in conflicting experiments.

Routes:
    GET    /api/v1/mutual-exclusion-groups                                — list groups
    POST   /api/v1/mutual-exclusion-groups                                — create group (DEVELOPER+)
    GET    /api/v1/mutual-exclusion-groups/{group_id}                     — get group
    PUT    /api/v1/mutual-exclusion-groups/{group_id}                     — update group (DEVELOPER+)
    DELETE /api/v1/mutual-exclusion-groups/{group_id}                     — archive group (ADMIN)
    POST   /api/v1/mutual-exclusion-groups/{group_id}/experiments         — add experiment
    DELETE /api/v1/mutual-exclusion-groups/{group_id}/experiments/{eid}   — remove experiment
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.permissions import Action, ResourceType, check_permission
from backend.app.models.user import User
from backend.app.schemas.mutual_exclusion_group import (
    AddExperimentToGroupRequest,
    MutualExclusionGroupCreate,
    MutualExclusionGroupListResponse,
    MutualExclusionGroupResponse,
    MutualExclusionGroupUpdate,
)
from backend.app.services.mutual_exclusion_service import MutualExclusionService

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_developer(user: User) -> None:
    """Raise 403 if user lacks DEVELOPER-level access to experiments."""
    if not check_permission(user, ResourceType.EXPERIMENT, Action.CREATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to manage mutual exclusion groups",
        )


def _require_admin(user: User) -> None:
    """Raise 403 if user is not an ADMIN / superuser."""
    if not check_permission(user, ResourceType.EXPERIMENT, Action.DELETE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permissions required for this action",
        )


# ---------------------------------------------------------------------------
# List groups
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=MutualExclusionGroupListResponse,
    summary="List mutual exclusion groups",
    description="Return a paginated list of mutual exclusion groups.",
    tags=["Mutual Exclusion Groups"],
)
def list_groups(
    status_filter: str = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> MutualExclusionGroupListResponse:
    """List mutual exclusion groups with optional status filter."""
    _require_developer(current_user)
    service = MutualExclusionService(db)
    items = service.list_groups(status=status_filter, skip=skip, limit=limit)
    total = service.count_groups(status=status_filter)
    return MutualExclusionGroupListResponse(items=items, total=total)


# ---------------------------------------------------------------------------
# Create group
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=MutualExclusionGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a mutual exclusion group",
    description="Create a new mutual exclusion group. Requires DEVELOPER or ADMIN role.",
    tags=["Mutual Exclusion Groups"],
)
def create_group(
    data: MutualExclusionGroupCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> MutualExclusionGroupResponse:
    """Create a new mutual exclusion group."""
    _require_developer(current_user)
    service = MutualExclusionService(db)
    group = service.create_group(
        name=data.name,
        description=data.description,
        traffic_allocation=data.traffic_allocation,
        owner_id=current_user.id,
    )
    return MutualExclusionGroupResponse.model_validate(group)


# ---------------------------------------------------------------------------
# Get group
# ---------------------------------------------------------------------------

@router.get(
    "/{group_id}",
    response_model=MutualExclusionGroupResponse,
    summary="Get a mutual exclusion group",
    description="Retrieve a single mutual exclusion group by UUID.",
    tags=["Mutual Exclusion Groups"],
)
def get_group(
    group_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> MutualExclusionGroupResponse:
    """Retrieve a mutual exclusion group by ID."""
    _require_developer(current_user)
    service = MutualExclusionService(db)
    group = service.get_group(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mutual exclusion group {group_id} not found",
        )
    return MutualExclusionGroupResponse.model_validate(group)


# ---------------------------------------------------------------------------
# Update group
# ---------------------------------------------------------------------------

@router.put(
    "/{group_id}",
    response_model=MutualExclusionGroupResponse,
    summary="Update a mutual exclusion group",
    description="Update a mutual exclusion group. Requires DEVELOPER or ADMIN role.",
    tags=["Mutual Exclusion Groups"],
)
def update_group(
    group_id: UUID,
    data: MutualExclusionGroupUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> MutualExclusionGroupResponse:
    """Update an existing mutual exclusion group."""
    _require_developer(current_user)
    service = MutualExclusionService(db)
    group = service.update_group(
        group_id=group_id,
        name=data.name,
        description=data.description,
        traffic_allocation=data.traffic_allocation,
        status=data.status.value if data.status else None,
    )
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mutual exclusion group {group_id} not found",
        )
    return MutualExclusionGroupResponse.model_validate(group)


# ---------------------------------------------------------------------------
# Archive (soft delete) group
# ---------------------------------------------------------------------------

@router.delete(
    "/{group_id}",
    response_model=MutualExclusionGroupResponse,
    summary="Archive a mutual exclusion group",
    description="Soft-delete a mutual exclusion group by archiving it. Requires ADMIN role.",
    tags=["Mutual Exclusion Groups"],
)
def archive_group(
    group_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> MutualExclusionGroupResponse:
    """Archive (soft-delete) a mutual exclusion group."""
    _require_admin(current_user)
    service = MutualExclusionService(db)
    group = service.archive_group(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mutual exclusion group {group_id} not found",
        )
    return MutualExclusionGroupResponse.model_validate(group)


# ---------------------------------------------------------------------------
# Add experiment to group
# ---------------------------------------------------------------------------

@router.post(
    "/{group_id}/experiments",
    status_code=status.HTTP_200_OK,
    summary="Add experiment to mutual exclusion group",
    description="Add an experiment to a mutual exclusion group. Requires DEVELOPER or ADMIN role.",
    tags=["Mutual Exclusion Groups"],
)
def add_experiment_to_group(
    group_id: UUID,
    data: AddExperimentToGroupRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Add an experiment to a mutual exclusion group."""
    _require_developer(current_user)
    service = MutualExclusionService(db)
    try:
        experiment = service.add_experiment_to_group(group_id, data.experiment_id)
        return {"status": "ok", "experiment_id": str(data.experiment_id), "group_id": str(group_id)}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Remove experiment from group
# ---------------------------------------------------------------------------

@router.delete(
    "/{group_id}/experiments/{experiment_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove experiment from mutual exclusion group",
    description="Remove an experiment from a mutual exclusion group. Requires DEVELOPER or ADMIN role.",
    tags=["Mutual Exclusion Groups"],
)
def remove_experiment_from_group(
    group_id: UUID,
    experiment_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Remove an experiment from a mutual exclusion group."""
    _require_developer(current_user)
    service = MutualExclusionService(db)
    try:
        service.remove_experiment_from_group(group_id, experiment_id)
        return {"status": "ok", "experiment_id": str(experiment_id), "group_id": str(group_id)}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
