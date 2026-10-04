"""
Global Holdout API endpoints (EP-022).

REST endpoints for managing global holdout configurations that reserve a
percentage of users from all experiments.

Routes:
    GET    /api/v1/holdout            — get active holdout
    GET    /api/v1/holdout/all        — list all holdouts (ADMIN)
    POST   /api/v1/holdout            — create holdout (ADMIN)
    PUT    /api/v1/holdout/{id}       — update holdout (ADMIN)
    GET    /api/v1/holdout/check/{uid} — check if user is in holdout
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.permissions import Action, ResourceType, check_permission
from backend.app.models.audit_log import ActionType, EntityType
from backend.app.models.user import User
from backend.app.schemas.global_holdout import (
    GlobalHoldoutCreate,
    GlobalHoldoutListResponse,
    GlobalHoldoutResponse,
    GlobalHoldoutUpdate,
    HoldoutCheckResponse,
)
from backend.app.services.audit_service import (
    AuditService,
    audit_changes,
    audit_identity,
    audit_snapshot,
)
from backend.app.services.global_holdout_service import GlobalHoldoutService

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_developer(user: User) -> None:
    """Raise 403 if user lacks DEVELOPER-level access."""
    if not check_permission(user, ResourceType.EXPERIMENT, Action.CREATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to access holdout configuration",
        )


def _require_admin(user: User) -> None:
    """Raise 403 if user is not an ADMIN / superuser."""
    if not check_permission(user, ResourceType.EXPERIMENT, Action.DELETE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permissions required for this action",
        )


def _record(db: Session, user: User, action: ActionType, holdout_id, name, **values):
    AuditService.record_after_commit(
        db,
        actor=user,
        action=action,
        entity_type=EntityType.HOLDOUT,
        entity_id=holdout_id,
        entity_name=name,
        **values,
    )


def _record_implicit_deactivations(
    db: Session, user: User, service: GlobalHoldoutService, changed_id
) -> None:
    """One ``holdout_deactivate`` for each other holdout this request turned off."""
    for holdout_id, name in service.implicitly_deactivated:
        if holdout_id == changed_id:
            continue
        _record(
            db,
            user,
            ActionType.HOLDOUT_DEACTIVATE,
            holdout_id,
            name,
            before={"is_active": True},
            after={"is_active": False},
            reason="another holdout was activated",
        )


# ---------------------------------------------------------------------------
# Get active holdout
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=Optional[GlobalHoldoutResponse],
    summary="Get the active global holdout",
    description="Return the currently active global holdout, or null if none is active.",
    tags=["Global Holdout"],
)
def get_active_holdout(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Optional[GlobalHoldoutResponse]:
    """Return the active holdout, or null."""
    _require_developer(current_user)
    service = GlobalHoldoutService(db)
    holdout = service.get_active_holdout()
    if not holdout:
        return None
    return GlobalHoldoutResponse.model_validate(holdout)


# ---------------------------------------------------------------------------
# List all holdouts
# ---------------------------------------------------------------------------


@router.get(
    "/all",
    response_model=GlobalHoldoutListResponse,
    summary="List all global holdouts",
    description="Return a paginated list of all holdout configurations. Requires ADMIN role.",
    tags=["Global Holdout"],
)
def list_all_holdouts(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> GlobalHoldoutListResponse:
    """List all holdout configurations."""
    _require_admin(current_user)
    service = GlobalHoldoutService(db)
    items = service.list_holdouts(skip=skip, limit=limit)
    total = service.count_holdouts()
    return GlobalHoldoutListResponse(items=items, total=total)


# ---------------------------------------------------------------------------
# Create holdout
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=GlobalHoldoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a global holdout",
    description="Create a new global holdout configuration. Requires ADMIN role.",
    tags=["Global Holdout"],
)
def create_holdout(
    data: GlobalHoldoutCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> GlobalHoldoutResponse:
    """Create a new global holdout."""
    _require_admin(current_user)
    service = GlobalHoldoutService(db)
    holdout = service.create_holdout(
        name=data.name,
        description=data.description,
        holdout_percentage=data.holdout_percentage,
        is_active=data.is_active,
        owner_id=current_user.id,
    )
    response = GlobalHoldoutResponse.model_validate(holdout)
    _record(
        db,
        current_user,
        ActionType.HOLDOUT_CREATE,
        response.id,
        response.name,
        after=audit_identity(audit_snapshot(EntityType.HOLDOUT, holdout)),
    )
    _record_implicit_deactivations(db, current_user, service, response.id)
    return response


# ---------------------------------------------------------------------------
# Update holdout
# ---------------------------------------------------------------------------


@router.put(
    "/{holdout_id}",
    response_model=GlobalHoldoutResponse,
    summary="Update a global holdout",
    description="Update a global holdout configuration. Requires ADMIN role.",
    tags=["Global Holdout"],
)
def update_holdout(
    holdout_id: UUID,
    data: GlobalHoldoutUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> GlobalHoldoutResponse:
    """Update a holdout configuration."""
    _require_admin(current_user)
    service = GlobalHoldoutService(db)
    existing = service.get_holdout(holdout_id)
    before = audit_snapshot(EntityType.HOLDOUT, existing) if existing else None
    holdout = service.update_holdout(
        holdout_id=holdout_id,
        name=data.name,
        description=data.description,
        holdout_percentage=data.holdout_percentage,
        is_active=data.is_active,
    )
    if not holdout:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Holdout {holdout_id} not found",
        )
    response = GlobalHoldoutResponse.model_validate(holdout)
    _record_holdout_update(db, current_user, before, holdout)
    _record_implicit_deactivations(db, current_user, service, holdout_id)
    return response


def _record_holdout_update(db: Session, user: User, before, holdout) -> None:
    """One entry per verb: activate or deactivate, and update for the rest.

    ``holdout`` is the stored row after the change, ``before`` its snapshot
    before it. Nothing allow-listed changed, nothing is recorded.
    """
    holdout_id, name = holdout.id, holdout.name
    old, new = audit_changes(before or {}, audit_snapshot(EntityType.HOLDOUT, holdout))
    old, new = old or {}, new or {}
    if "is_active" in new:
        _record(
            db,
            user,
            ActionType.HOLDOUT_ACTIVATE
            if new["is_active"]
            else ActionType.HOLDOUT_DEACTIVATE,
            holdout_id,
            name,
            before={"is_active": old.pop("is_active")},
            after={"is_active": new.pop("is_active")},
        )
    if new:
        _record(
            db,
            user,
            ActionType.HOLDOUT_UPDATE,
            holdout_id,
            name,
            before=old or None,
            after=new,
        )


# ---------------------------------------------------------------------------
# Check user holdout status
# ---------------------------------------------------------------------------


@router.get(
    "/check/{user_id}",
    response_model=HoldoutCheckResponse,
    summary="Check if a user is in the global holdout",
    description="Return whether a user falls within the global holdout bucket.",
    tags=["Global Holdout"],
)
def check_user_holdout(
    user_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> HoldoutCheckResponse:
    """Check whether a user is in the global holdout."""
    _require_developer(current_user)
    service = GlobalHoldoutService(db)
    is_in_holdout, holdout_percentage, bucket = service.is_user_in_holdout(user_id)
    return HoldoutCheckResponse(
        user_id=user_id,
        is_in_holdout=is_in_holdout,
        holdout_percentage=holdout_percentage,
        bucket=bucket,
    )
