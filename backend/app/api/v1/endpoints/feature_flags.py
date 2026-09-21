"""
Feature Flag API endpoints.

This module provides RESTful API endpoints for creating, reading, updating, and deleting
feature flags in the experimentation platform. It implements functionality to toggle and
manage feature flags for gradual rollouts and A/B testing.
"""

import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.core.metrics import (
    record_cache_hit,
    record_cache_miss,
    record_flag_evaluation,
)
from backend.app.core.permissions import Action, ResourceType, check_permission
from backend.app.crud import crud_feature_flag
from backend.app.models.audit_log import ActionType, EntityType
from backend.app.models.compliance_audit_event import AuditAction, AuditOutcome
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.user import User
from backend.app.schemas.audit_log import ToggleRequest, ToggleResponse
from backend.app.schemas.feature_flag import (
    FeatureFlagCreate,
    FeatureFlagListResponse,
    FeatureFlagUpdate,
)
from backend.app.services.audit_log_service import AuditLogService
from backend.app.services.audit_service import AuditService
from backend.app.services.feature_flag_service import FeatureFlagService

# Setup logger
logger = logging.getLogger(__name__)

# Create router with tag for documentation grouping
router = APIRouter(
    tags=["Feature Flags"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Authentication failed",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "status_code": 401,
                            "message": "Could not validate credentials",
                        }
                    }
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Permission denied",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "status_code": 403,
                            "message": "Not enough permissions",
                        }
                    }
                }
            },
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "status_code": 500,
                            "message": "Internal server error",
                        }
                    }
                }
            },
        },
    },
)


@router.get(
    "/",
    response_model=FeatureFlagListResponse,
    summary="List feature flags",
    response_description="Returns a paginated list of feature flags",
)
async def list_feature_flags(
    *,
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    search: Optional[str] = None,
    current_user=Depends(deps.get_current_active_user),
) -> FeatureFlagListResponse:
    """
    Retrieve feature flags.
    - **skip**: Number of feature flags to skip in pagination
    - **limit**: Maximum number of feature flags to return
    - **status**: Filter by status (ACTIVE, INACTIVE)
    - **search**: Filter by name or key
    """
    # Check if user has permission to list feature flags
    if not check_permission(current_user, ResourceType.FEATURE_FLAG, Action.LIST):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to list feature flags",
        )

    cache_key = f"feature_flags:{current_user.id}:{skip}:{limit}:{status}:{search}"

    # Check if we have cached data
    if settings.CACHE_CONTROL.get("enabled", False):
        redis_client = settings.CACHE_CONTROL.get("redis")
        cached_data = redis_client.get(cache_key)
        if cached_data:
            record_cache_hit("feature_flag_list")
            cached_response = json.loads(cached_data)
            # Convert cached data to FeatureFlagListResponse
            return FeatureFlagListResponse(
                items=cached_response["items"],
                total=cached_response["total"],
                skip=cached_response["skip"],
                limit=cached_response["limit"],
            )
        record_cache_miss("feature_flag_list")

    # Everyone the LIST check above admitted sees the whole platform.
    #
    # This had a third access model again, different from both the role table
    # and the experiments endpoint: superuser -> all; UPDATE permission
    # (ADMIN, DEVELOPER) -> all; otherwise own rows only. Its comment read
    # "Analyst/Viewer can only see their own", which inverts the role the docs
    # describe -- ANALYST exists to "view all data but not create or modify"
    # (CLAUDE.md), so it was the one role guaranteed to be wrong.
    #
    # All four roles carry Action.LIST on feature flags, a deployment is single
    # tenant (founder, 2026-09-21), and tenant isolation belongs to the
    # workspaces module rather than to row ownership. See #83.
    feature_flags_data = crud_feature_flag.get_multi(
        db, skip=skip, limit=limit, status=status, search=search
    )
    total = crud_feature_flag.count(db, status=status, search=search)

    # Create response with pagination
    response = FeatureFlagListResponse(
        items=feature_flags_data, total=total, skip=skip, limit=limit
    )

    # Cache the response if caching is enabled
    if settings.CACHE_CONTROL.get("enabled", False):
        redis_client = settings.CACHE_CONTROL.get("redis")
        redis_client.setex(
            cache_key,
            settings.CACHE_CONTROL.get("ttl", 3600),  # Default to 1 hour
            json.dumps(response.model_dump()),
        )

    return response


@router.post(
    "/",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create feature flag",
    response_description="Returns the created feature flag",
)
async def create_feature_flag(
    feature_flag_in: FeatureFlagCreate = Body(
        ..., description="Feature flag data to create"
    ),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    cache_control: Dict[str, Any] = Depends(deps.get_cache_control),
    _: bool = Depends(deps.can_create_feature_flag),  # Use the permission dependency
) -> Dict[str, Any]:
    """
    Create a new feature flag.

    This endpoint allows users to create a new feature flag. The current user
    is automatically set as the owner of the feature flag.

    The request must include:
    - A unique key for the feature flag
    - A name for the feature flag
    - Optional description
    - Optional targeting rules for specific user segments
    - Optional rollout percentage

    The feature flag is created in INACTIVE status by default.

    Returns:
        Dict[str, Any]: The newly created feature flag with all details

    Raises:
        HTTPException: If the feature flag data is invalid or creation fails
    """
    # Create feature flag service
    feature_flag_service = FeatureFlagService(db)

    # Check if feature flag with the same key already exists
    existing_flag = (
        db.query(FeatureFlag).filter(FeatureFlag.key == feature_flag_in.key).first()
    )
    if existing_flag:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Feature flag with key '{feature_flag_in.key}' already exists",
        )

    # Create feature flag
    try:
        # Create feature flag with updated owner_id
        # Set owner_id on the feature flag data
        feature_flag_in_dict = feature_flag_in.model_dump()
        feature_flag_in_dict["owner_id"] = current_user.id

        # Convert back to pydantic model
        updated_feature_flag_in = FeatureFlagCreate(**feature_flag_in_dict)

        # Create the feature flag using the service
        feature_flag = feature_flag_service.create_feature_flag(
            flag_data=updated_feature_flag_in
        )

        # Convert SQLAlchemy model to dictionary manually
        response_dict = {
            "id": str(feature_flag.id),
            "key": feature_flag.key,
            "name": feature_flag.name,
            "description": feature_flag.description,
            "status": feature_flag.status.value.lower()
            if hasattr(feature_flag.status, "value")
            else str(feature_flag.status).lower(),
            "owner_id": str(feature_flag.owner_id) if feature_flag.owner_id else None,
            "targeting_rules": feature_flag.targeting_rules,
            "rollout_percentage": feature_flag.rollout_percentage,
            "variants": feature_flag.variants,
            "tags": feature_flag.tags,
            "created_at": feature_flag.created_at.isoformat()
            if feature_flag.created_at
            else None,
            "updated_at": feature_flag.updated_at.isoformat()
            if feature_flag.updated_at
            else None,
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Compliance audit logging (non-fatal — do not fail the request if this fails)
    try:
        audit = AuditLogService(db)
        audit.log(
            action=AuditAction.CREATE,
            resource_type="feature_flag",
            outcome=AuditOutcome.SUCCESS,
            resource_id=response_dict.get("id"),
            actor_id=str(current_user.id) if current_user else None,
            new_value={
                "key": response_dict.get("key"),
                "name": response_dict.get("name"),
            },
        )
    except Exception as audit_error:
        logger.warning(
            f"Compliance audit logging failed for feature_flag create: {audit_error}"
        )

    # Invalidate cache if enabled
    try:
        if cache_control.enabled and cache_control.redis:
            pattern = f"feature_flags:{current_user.id}:*"
            for key in cache_control.redis.scan_iter(match=pattern):
                cache_control.redis.delete(key)
    except Exception as cache_error:
        logger.warning(
            f"Cache invalidation failed for create operation: {cache_error!s}"
        )

    return response_dict


@router.get(
    "/{flag_id}",
    response_model=Dict[str, Any],
    summary="Get feature flag",
    response_description="Returns the feature flag details",
)
async def get_feature_flag(
    flag_id: UUID = Path(..., description="The ID of the feature flag to retrieve"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    cache_control: Dict[str, Any] = Depends(deps.get_cache_control),
) -> Dict[str, Any]:
    """
    Get feature flag by ID.

    Retrieves the detailed information for a specific feature flag.
    Users can only access feature flags they own or have permission to view.

    Returns:
        Dict[str, Any]: The feature flag details

    Raises:
        HTTPException 404: If feature flag not found
        HTTPException 403: If user doesn't have access to this feature flag
    """
    # Check cache first if enabled
    if cache_control.enabled and cache_control.redis:
        cache_key = f"feature_flag:{flag_id}"
        cached_data = cache_control.redis.get(cache_key)
        if cached_data:
            import json

            record_cache_hit("feature_flag")
            return json.loads(cached_data)
        record_cache_miss("feature_flag")

    # Create feature flag service
    feature_flag_service = FeatureFlagService(db)

    # Get feature flag
    feature_flag = feature_flag_service.get_feature_flag(flag_id)
    if not feature_flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found"
        )

    # Check access permission (superusers can see all, regular users only their own)
    if not current_user.is_superuser and str(feature_flag["owner_id"]) != str(
        current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to access this feature flag",
        )

    # Cache result if enabled
    if cache_control.enabled and cache_control.redis:
        import json

        cache_control.redis.setex(
            f"feature_flag:{flag_id}",
            3600,  # Cache for 1 hour
            json.dumps(feature_flag),
        )

    return feature_flag


@router.put(
    "/{flag_id}",
    response_model=Dict[str, Any],
    summary="Update feature flag",
    response_description="Returns the updated feature flag",
)
async def update_feature_flag(
    flag_id: UUID = Path(..., description="The ID of the feature flag to update"),
    feature_flag_in: FeatureFlagUpdate = Body(
        ..., description="Feature flag data to update"
    ),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    cache_control: Dict[str, Any] = Depends(deps.get_cache_control),
) -> Dict[str, Any]:
    """
    Update a feature flag.

    This endpoint allows users to update an existing feature flag.
    The user must have access to the feature flag (be the owner or have permission).

    Fields that can be updated include:
    - Name and description
    - Status (active, inactive, archived)
    - Targeting rules
    - Rollout percentage

    Returns:
        Dict[str, Any]: The updated feature flag with all details

    Raises:
        HTTPException 400: If the update data is invalid
        HTTPException 403: If the user doesn't have permission to update this feature flag
    """
    # Create feature flag service
    feature_flag_service = FeatureFlagService(db)

    # Get feature flag
    flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found"
        )

    # Check access permission
    if not current_user.is_superuser and flag.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this feature flag",
        )

    # If key is being updated, check if it conflicts with another feature flag
    if feature_flag_in.key and feature_flag_in.key != flag.key:
        existing_flag = next(
            (
                f
                for f in feature_flag_service.get_feature_flags()
                if f["key"] == feature_flag_in.key and str(f["id"]) != str(flag_id)
            ),
            None,
        )
        if existing_flag:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Feature flag with key '{feature_flag_in.key}' already exists",
            )

    # Capture pre-update state for audit trail
    old_flag_snapshot = {
        "key": flag.key,
        "name": flag.name,
        "status": str(flag.status),
        "rollout_percentage": flag.rollout_percentage,
    }

    # Update feature flag
    try:
        updated_flag = feature_flag_service.update_feature_flag(flag, feature_flag_in)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Compliance audit logging (non-fatal)
    try:
        new_flag_snapshot = {
            "key": updated_flag.get("key")
            if isinstance(updated_flag, dict)
            else getattr(updated_flag, "key", None),
            "name": updated_flag.get("name")
            if isinstance(updated_flag, dict)
            else getattr(updated_flag, "name", None),
            "status": str(
                updated_flag.get("status")
                if isinstance(updated_flag, dict)
                else getattr(updated_flag, "status", None)
            ),
            "rollout_percentage": updated_flag.get("rollout_percentage")
            if isinstance(updated_flag, dict)
            else getattr(updated_flag, "rollout_percentage", None),
        }
        audit = AuditLogService(db)
        audit.log(
            action=AuditAction.UPDATE,
            resource_type="feature_flag",
            outcome=AuditOutcome.SUCCESS,
            resource_id=str(flag_id),
            actor_id=str(current_user.id) if current_user else None,
            old_value=old_flag_snapshot,
            new_value=new_flag_snapshot,
        )
    except Exception as audit_error:
        logger.warning(
            f"Compliance audit logging failed for feature_flag update: {audit_error}"
        )

    # Invalidate cache if enabled
    if cache_control.enabled and cache_control.redis:
        # Delete specific feature flag cache
        flag_cache_key = f"feature_flag:{flag_id}"
        cache_control.redis.delete(flag_cache_key)

        # Delete feature flag list caches
        pattern = f"feature_flags:{current_user.id}:*"
        for key in cache_control.redis.scan_iter(match=pattern):
            cache_control.redis.delete(key)

    return updated_flag


@router.delete(
    "/{flag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete feature flag",
    response_description="No content, feature flag successfully deleted",
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": "Feature flag successfully deleted",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Not enough permissions to delete this feature flag",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "status_code": 403,
                            "message": "Not enough permissions",
                        }
                    }
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Feature flag not found",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "status_code": 404,
                            "message": "Feature flag not found",
                        }
                    }
                }
            },
        },
    },
)
async def delete_feature_flag(
    flag_id: UUID = Path(..., description="The ID of the feature flag to delete"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    cache_control: Dict[str, Any] = Depends(deps.get_cache_control),
) -> None:
    """
    Delete a feature flag.

    This endpoint allows users to delete an existing feature flag.
    The user must have access to the feature flag (be the owner or have permission).

    Deleting a feature flag has the following effects:
    - The feature flag and all its related data are permanently removed
    - Any cached data related to the feature flag is invalidated

    **Note**: This operation cannot be undone. For active feature flags, consider
    changing the status to 'archived' instead.

    Returns:
        None: No content, feature flag was successfully deleted

    Raises:
        HTTPException 403: If the user doesn't have permission to delete this feature flag
        HTTPException 404: If the feature flag doesn't exist
    """
    # Get feature flag
    flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found"
        )

    # Check if the user is either the owner or a superuser
    if flag.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be the owner or a superuser to delete this feature flag",
        )

    # Capture flag info before deletion for audit trail
    deleted_flag_snapshot = {
        "key": flag.key,
        "name": flag.name,
        "status": str(flag.status),
    }
    deleted_flag_id = str(flag.id)

    # Create feature flag service
    feature_flag_service = FeatureFlagService(db)

    # Delete feature flag
    feature_flag_service.delete_feature_flag(flag)

    # Compliance audit logging (non-fatal)
    try:
        audit = AuditLogService(db)
        audit.log(
            action=AuditAction.DELETE,
            resource_type="feature_flag",
            outcome=AuditOutcome.SUCCESS,
            resource_id=deleted_flag_id,
            actor_id=str(current_user.id) if current_user else None,
            old_value=deleted_flag_snapshot,
        )
    except Exception as audit_error:
        logger.warning(
            f"Compliance audit logging failed for feature_flag delete: {audit_error}"
        )

    # Invalidate cache if enabled
    if cache_control.enabled and cache_control.redis:
        # Delete specific feature flag cache
        flag_cache_key = f"feature_flag:{flag_id}"
        cache_control.redis.delete(flag_cache_key)

        # Delete feature flag list caches
        pattern = "feature_flags:*"
        for key in cache_control.redis.scan_iter(match=pattern):
            cache_control.redis.delete(key)

    # Return 204 No Content
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{flag_id}/activate",
    response_model=Dict[str, Any],
    summary="Activate feature flag",
    response_description="Returns the activated feature flag",
)
async def activate_feature_flag(
    flag_id: UUID = Path(..., description="The ID of the feature flag to activate"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    cache_control: Dict[str, Any] = Depends(deps.get_cache_control),
) -> Dict[str, Any]:
    """
    Activate a feature flag.

    This endpoint activates a feature flag, changing its status to ACTIVE.
    Activating a feature flag makes it available for use in applications.

    Returns:
        Dict[str, Any]: The updated feature flag with ACTIVE status

    Raises:
        HTTPException 400: If the feature flag cannot be activated
        HTTPException 403: If the user doesn't have permission to activate this feature flag
    """
    # Get feature flag
    flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found"
        )

    # Check access permission
    if not current_user.is_superuser and flag.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to activate this feature flag",
        )

    # Check if feature flag is already active
    if flag.status in (FeatureFlagStatus.ACTIVE, FeatureFlagStatus.ACTIVE.value):
        return {
            "id": str(flag.id),
            "key": flag.key,
            "name": flag.name,
            "description": flag.description,
            "status": "active",
            "rollout_percentage": flag.rollout_percentage,
            "targeting_rules": flag.targeting_rules,
            "owner_id": str(flag.owner_id),
            "created_at": flag.created_at,
            "updated_at": flag.updated_at,
        }

    # Create feature flag service
    feature_flag_service = FeatureFlagService(db)

    # Activate feature flag
    activated_flag = feature_flag_service.activate_feature_flag(flag)

    # Invalidate cache if enabled
    if cache_control.enabled and cache_control.redis:
        # Delete specific feature flag cache
        flag_cache_key = f"feature_flag:{flag_id}"
        cache_control.redis.delete(flag_cache_key)

        # Delete feature flag list caches
        pattern = "feature_flags:*"
        for key in cache_control.redis.scan_iter(match=pattern):
            cache_control.redis.delete(key)

    return activated_flag


@router.post(
    "/{flag_id}/deactivate",
    response_model=Dict[str, Any],
    summary="Deactivate feature flag",
    response_description="Returns the deactivated feature flag",
)
async def deactivate_feature_flag(
    flag_id: UUID = Path(..., description="The ID of the feature flag to deactivate"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    cache_control: Dict[str, Any] = Depends(deps.get_cache_control),
) -> Dict[str, Any]:
    """
    Deactivate a feature flag.

    This endpoint deactivates a feature flag, changing its status to INACTIVE.
    Deactivating a feature flag makes it unavailable for use in applications.

    Returns:
        Dict[str, Any]: The updated feature flag with INACTIVE status

    Raises:
        HTTPException 400: If the feature flag cannot be deactivated
        HTTPException 403: If the user doesn't have permission to deactivate this feature flag
    """
    # Get feature flag
    flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found"
        )

    # Check access permission
    if not current_user.is_superuser and flag.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to deactivate this feature flag",
        )

    # Check if feature flag is already inactive
    if flag.status in (FeatureFlagStatus.INACTIVE, FeatureFlagStatus.INACTIVE.value):
        return {
            "id": str(flag.id),
            "key": flag.key,
            "name": flag.name,
            "description": flag.description,
            "status": "inactive",
            "rollout_percentage": flag.rollout_percentage,
            "targeting_rules": flag.targeting_rules,
            "owner_id": str(flag.owner_id),
            "created_at": flag.created_at,
            "updated_at": flag.updated_at,
        }

    # Create feature flag service
    feature_flag_service = FeatureFlagService(db)

    # Deactivate feature flag
    deactivated_flag = feature_flag_service.deactivate_feature_flag(flag)

    # Invalidate cache if enabled
    if cache_control.enabled and cache_control.redis:
        # Delete specific feature flag cache
        flag_cache_key = f"feature_flag:{flag_id}"
        cache_control.redis.delete(flag_cache_key)

        # Delete feature flag list caches
        pattern = "feature_flags:*"
        for key in cache_control.redis.scan_iter(match=pattern):
            cache_control.redis.delete(key)

    return deactivated_flag


CONTEXT_QUERY_DESCRIPTION = (
    "Optional targeting context as a URL-encoded JSON object, e.g. "
    '`{"country":"US","os_version":"17.4.0","employee":true}`. Nested objects are '
    "flattened to dotted keys (`app.version`) and top-level keys also answer "
    "`user.<key>`, `device.<key>` and `app.<key>` rule attributes."
)


def _parse_context_param(context: Optional[str]) -> Optional[Dict[str, Any]]:
    """Decode the ``context`` query parameter; 422 when it is not a JSON object."""
    if context is None or context == "":
        return None
    try:
        parsed = json.loads(context)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query parameter 'context' must be a URL-encoded JSON object",
        )
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query parameter 'context' must be a JSON object",
        )
    return parsed


class FlagEvaluationRequest(BaseModel):
    """Body for ``POST /feature-flags/evaluate/{flag_key}``."""

    user_id: str = Field(
        ..., min_length=1, description="ID of the user to evaluate the flag for"
    )
    context: Optional[Dict[str, Any]] = Field(
        None, description="Targeting context (user/device/app attributes)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "device-42",
                "context": {
                    "os": "iOS",
                    "os_version": "17.4.0",
                    "region": "US",
                    "tier": "premium",
                },
            }
        }
    )


def _evaluate_flag_by_key(
    db: Session, flag_key: str, user_id: str, context: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Shared body of the GET and POST evaluate endpoints.

    A flag that exists but is not ACTIVE (disabled with the kill switch,
    archived, ...) evaluates to ``enabled: false`` with ``reason: "inactive"``
    rather than 404: the client should treat it as "off", not as an error.
    Only an unknown key is a 404.
    """
    db_flag = db.query(FeatureFlag).filter(FeatureFlag.key == flag_key).first()
    if not db_flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag with key '{flag_key}' not found",
        )

    feature_flag_service = FeatureFlagService(db)
    evaluation = feature_flag_service.evaluate_flag_detailed(db_flag, user_id, context)
    record_flag_evaluation(flag_key, "enabled" if evaluation["enabled"] else "disabled")

    # ``config`` has always been ``None`` here (the flag dict has no ``value``);
    # kept for backwards compatibility with existing SDKs.
    return {
        "key": flag_key,
        "enabled": evaluation["enabled"],
        "config": None,
        "reason": evaluation["reason"],
    }


@router.get(
    "/evaluate/{flag_key}",
    response_model=Dict[str, Any],
    summary="Evaluate feature flag for a user",
    response_description="Returns the feature flag evaluation result",
)
async def evaluate_feature_flag(
    flag_key: str = Path(..., description="The key of the feature flag to evaluate"),
    user_id: str = Query(..., description="ID of the user to evaluate the flag for"),
    context: Optional[str] = Query(None, description=CONTEXT_QUERY_DESCRIPTION),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
) -> Dict[str, Any]:
    """
    Evaluate a feature flag for a specific user.

    This endpoint evaluates whether a feature flag is enabled for a specific user
    based on the flag's status, targeting rules, and rollout percentage. Pass the
    user's attributes as ``context=<url-encoded JSON object>`` so targeting rules
    (dashboard or native shape) can be matched.

    This endpoint is intended to be called by client applications to determine
    if a feature should be enabled for a specific user.

    **Authentication**: Requires a valid API key in the X-API-Key header.

    Returns:
        ``{"key", "enabled", "config", "reason"}`` where ``reason`` is one of
        ``targeting_rule`` (a rule matched and its rollout % decided),
        ``rollout`` (the global rollout % decided), ``inactive`` or ``error``.

    Raises:
        HTTPException 401: If the API key is invalid
        HTTPException 404: If the feature flag doesn't exist or is not active
        HTTPException 422: If ``context`` is not valid JSON object
    """
    parsed_context = _parse_context_param(context)
    return _evaluate_flag_by_key(db, flag_key, user_id, parsed_context)


@router.post(
    "/evaluate/{flag_key}",
    response_model=Dict[str, Any],
    summary="Evaluate feature flag for a user (with context body)",
    response_description="Returns the feature flag evaluation result",
)
async def evaluate_feature_flag_post(
    flag_key: str = Path(..., description="The key of the feature flag to evaluate"),
    request: FlagEvaluationRequest = Body(
        ..., description="User id and targeting context"
    ),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
) -> Dict[str, Any]:
    """
    Evaluate a feature flag for a specific user, sending the targeting context
    in the request body instead of the query string.

    Body: ``{"user_id": "...", "context": {...}}``. Returns the same
    ``{"key", "enabled", "config", "reason"}`` payload as the GET variant.

    **Authentication**: Requires a valid API key in the X-API-Key header.

    Raises:
        HTTPException 401: If the API key is invalid
        HTTPException 404: If the feature flag doesn't exist or is not active
        HTTPException 422: If the body is invalid
    """
    return _evaluate_flag_by_key(db, flag_key, request.user_id, request.context)


@router.get(
    "/user/{user_id}",
    response_model=Dict[str, bool],
    summary="Get all feature flags for a user",
    response_description="Returns all feature flags evaluated for a user",
)
async def get_user_flags(
    user_id: str = Path(..., description="ID of the user to get flags for"),
    context: Optional[str] = Query(None, description=CONTEXT_QUERY_DESCRIPTION),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
) -> Dict[str, bool]:
    """
    Get all active feature flags for a specific user.

    This endpoint evaluates all active feature flags for a specific user
    and returns a dictionary mapping flag keys to boolean values indicating
    whether each flag is enabled for the user. Pass the user's attributes as
    ``context=<url-encoded JSON object>`` so targeting rules can be matched.

    This endpoint is intended to be called by client applications to initialize
    feature flags for a user session.

    **Authentication**: Requires a valid API key in the X-API-Key header.

    Returns:
        Dict[str, bool]: Dictionary mapping flag keys to boolean values

    Raises:
        HTTPException 401: If the API key is invalid
        HTTPException 422: If ``context`` is not a valid JSON object
    """
    parsed_context = _parse_context_param(context)

    # Create feature flag service
    feature_flag_service = FeatureFlagService(db)

    # Get all flags for user
    flags = feature_flag_service.get_user_flags(user_id, parsed_context)

    return flags


@router.post(
    "/{flag_id}/toggle",
    response_model=ToggleResponse,
    summary="Toggle feature flag",
    response_description="Returns the toggled feature flag with audit log ID",
)
async def toggle_feature_flag(
    flag_id: UUID = Path(..., description="The ID of the feature flag to toggle"),
    toggle_request: ToggleRequest = Body(
        ..., description="Toggle request with optional reason"
    ),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    cache_control: Dict[str, Any] = Depends(deps.get_cache_control),
) -> ToggleResponse:
    """
    Toggle a feature flag between enabled and disabled states.

    This endpoint provides a unified way to toggle feature flags, automatically
    determining whether to activate or deactivate based on the current status.

    The toggle operation includes:
    - Status change (ACTIVE ↔ INACTIVE)
    - Complete audit logging with user information and optional reason
    - Cache invalidation
    - Response with new status and audit log ID

    **Authentication**: Requires valid user authentication.
    **Permissions**: User must own the feature flag or be a superuser.

    Returns:
        ToggleResponse: Updated feature flag details with audit log ID

    Raises:
        HTTPException 403: If user doesn't have permission to toggle this feature flag
        HTTPException 404: If feature flag doesn't exist
        HTTPException 500: If toggle operation fails
    """
    # Get feature flag
    flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found"
        )

    # Check access permission
    if not current_user.is_superuser and flag.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to toggle this feature flag",
        )

    try:
        # Determine new status based on current status
        old_status = flag.status
        if flag.status == FeatureFlagStatus.ACTIVE.value:
            new_status = FeatureFlagStatus.INACTIVE.value
            action_type = ActionType.TOGGLE_DISABLE
        else:
            new_status = FeatureFlagStatus.ACTIVE.value
            action_type = ActionType.TOGGLE_ENABLE

        # Update feature flag status
        flag.status = new_status
        db.commit()
        db.refresh(flag)

        # Log the toggle operation (don't fail if audit logging fails)
        audit_log_id = None
        try:
            audit_log_id = await AuditService.log_action(
                db=db,
                user_id=current_user.id,
                user_email=current_user.email,
                action_type=action_type,
                entity_type=EntityType.FEATURE_FLAG,
                entity_id=flag.id,
                entity_name=flag.name,
                old_value=old_status,
                new_value=new_status,
                reason=toggle_request.reason,
            )
        except Exception as audit_error:
            # Log audit error but don't fail the toggle operation
            logger.warning(
                f"Audit logging failed for toggle operation: {audit_error!s}"
            )

        # Invalidate cache if enabled (don't fail if cache invalidation fails)
        try:
            if cache_control.enabled and cache_control.redis:
                # Delete specific feature flag cache
                flag_cache_key = f"feature_flag:{flag_id}"
                cache_control.redis.delete(flag_cache_key)

                # Delete feature flag list caches
                pattern = "feature_flags:*"
                for key in cache_control.redis.scan_iter(match=pattern):
                    cache_control.redis.delete(key)
        except Exception as cache_error:
            # Log cache error but don't fail the toggle operation
            logger.warning(
                f"Cache invalidation failed for toggle operation: {cache_error!s}"
            )

        return ToggleResponse(
            id=flag.id,
            name=flag.name,
            key=flag.key,
            status=new_status,
            updated_at=flag.updated_at,
            audit_log_id=audit_log_id,
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to toggle feature flag: {e!s}",
        )


@router.post(
    "/{flag_id}/enable",
    response_model=ToggleResponse,
    summary="Enable feature flag",
    response_description="Returns the enabled feature flag with audit log ID",
)
async def enable_feature_flag(
    flag_id: UUID = Path(..., description="The ID of the feature flag to enable"),
    toggle_request: ToggleRequest = Body(
        ..., description="Enable request with optional reason"
    ),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    cache_control: Dict[str, Any] = Depends(deps.get_cache_control),
) -> ToggleResponse:
    """
    Enable a feature flag (set to ACTIVE status).

    This endpoint explicitly enables a feature flag, regardless of current status.
    Includes complete audit logging with user information and optional reason.

    **Authentication**: Requires valid user authentication.
    **Permissions**: User must own the feature flag or be a superuser.

    Returns:
        ToggleResponse: Updated feature flag details with audit log ID

    Raises:
        HTTPException 403: If user doesn't have permission to enable this feature flag
        HTTPException 404: If feature flag doesn't exist
        HTTPException 500: If enable operation fails
    """
    # Get feature flag
    flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found"
        )

    # Check access permission
    if not current_user.is_superuser and flag.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to enable this feature flag",
        )

    try:
        old_status = flag.status
        new_status = FeatureFlagStatus.ACTIVE.value

        # Update feature flag status
        flag.status = new_status
        db.commit()
        db.refresh(flag)

        # Log the enable operation
        audit_log_id = await AuditService.log_action(
            db=db,
            user_id=current_user.id,
            user_email=current_user.email,
            action_type=ActionType.TOGGLE_ENABLE,
            entity_type=EntityType.FEATURE_FLAG,
            entity_id=flag.id,
            entity_name=flag.name,
            old_value=old_status,
            new_value=new_status,
            reason=toggle_request.reason,
        )

        # Invalidate cache if enabled
        try:
            if cache_control.enabled and cache_control.redis:
                flag_cache_key = f"feature_flag:{flag_id}"
                cache_control.redis.delete(flag_cache_key)
                pattern = "feature_flags:*"
                for key in cache_control.redis.scan_iter(match=pattern):
                    cache_control.redis.delete(key)
        except Exception as cache_error:
            logger.warning(
                f"Cache invalidation failed for enable operation: {cache_error!s}"
            )

        return ToggleResponse(
            id=flag.id,
            name=flag.name,
            key=flag.key,
            status=new_status,
            updated_at=flag.updated_at,
            audit_log_id=audit_log_id,
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enable feature flag: {e!s}",
        )


@router.post(
    "/{flag_id}/disable",
    response_model=ToggleResponse,
    summary="Disable feature flag",
    response_description="Returns the disabled feature flag with audit log ID",
)
async def disable_feature_flag(
    flag_id: UUID = Path(..., description="The ID of the feature flag to disable"),
    toggle_request: ToggleRequest = Body(
        ..., description="Disable request with optional reason"
    ),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    cache_control: Dict[str, Any] = Depends(deps.get_cache_control),
) -> ToggleResponse:
    """
    Disable a feature flag (set to INACTIVE status).

    This endpoint explicitly disables a feature flag, regardless of current status.
    Includes complete audit logging with user information and optional reason.

    **Authentication**: Requires valid user authentication.
    **Permissions**: User must own the feature flag or be a superuser.

    Returns:
        ToggleResponse: Updated feature flag details with audit log ID

    Raises:
        HTTPException 403: If user doesn't have permission to disable this feature flag
        HTTPException 404: If feature flag doesn't exist
        HTTPException 500: If disable operation fails
    """
    # Get feature flag
    flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found"
        )

    # Check access permission
    if not current_user.is_superuser and flag.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to disable this feature flag",
        )

    try:
        old_status = flag.status
        new_status = FeatureFlagStatus.INACTIVE.value

        # Update feature flag status
        flag.status = new_status
        db.commit()
        db.refresh(flag)

        # Log the disable operation
        audit_log_id = await AuditService.log_action(
            db=db,
            user_id=current_user.id,
            user_email=current_user.email,
            action_type=ActionType.TOGGLE_DISABLE,
            entity_type=EntityType.FEATURE_FLAG,
            entity_id=flag.id,
            entity_name=flag.name,
            old_value=old_status,
            new_value=new_status,
            reason=toggle_request.reason,
        )

        # Invalidate cache if enabled
        try:
            if cache_control.enabled and cache_control.redis:
                flag_cache_key = f"feature_flag:{flag_id}"
                cache_control.redis.delete(flag_cache_key)
                pattern = "feature_flags:*"
                for key in cache_control.redis.scan_iter(match=pattern):
                    cache_control.redis.delete(key)
        except Exception as cache_error:
            logger.warning(
                f"Cache invalidation failed for disable operation: {cache_error!s}"
            )

        return ToggleResponse(
            id=flag.id,
            name=flag.name,
            key=flag.key,
            status=new_status,
            updated_at=flag.updated_at,
            audit_log_id=audit_log_id,
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disable feature flag: {e!s}",
        )
