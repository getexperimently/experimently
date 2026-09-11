"""
Tracking API endpoints.

This module provides API endpoints for experiment user assignment and event tracking.
These endpoints are designed to be called from client applications to participate
in experiments and record user interactions.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.assignment import Assignment
from backend.app.models.bandit_state import BanditState
from backend.app.models.event import Event, EventType
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.schemas.tracking import (
    AssignmentRequest,
    AssignmentResponse,
    VariantAssignmentResponse,
    EventCreate,
    EventRequest,
    EventResponse,
    EventBatchRequest,
    EventBatchResponse,
)
from backend.app.services.assignment_service import AssignmentService
from backend.app.services.event_service import EventService

# Create router
router = APIRouter()


def _event_response(event: Event) -> EventResponse:
    """Build the public response model from a stored Event row."""
    return EventResponse(
        id=str(event.id),
        event_type=event.event_type,
        event_name=event.event_name or event.event_type,
        user_id=event.user_id,
        experiment_id=str(event.experiment_id) if event.experiment_id else None,
        feature_flag_id=str(event.feature_flag_id) if event.feature_flag_id else None,
        variant_id=str(event.variant_id) if event.variant_id else None,
        value=event.value,
        properties=event.event_metadata,
        timestamp=event.created_at,
        created_at=event.created_at,
        updated_at=event.updated_at or datetime.now(timezone.utc),
    )


def _bandit_weight(raw: Any) -> float:
    """Extract a non-negative weight from a BanditState.variant_weights entry.

    The scheduler stores ``{"weight": float, "successes": ..., "pulls": ...}``
    per variant; plain numeric values are accepted as well.
    """
    if isinstance(raw, dict):
        raw = raw.get("weight", 0.0)
    try:
        weight = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return weight if weight > 0.0 else 0.0


def _select_bandit_variant(
    experiment: Experiment,
    bandit_state: Optional[BanditState],
    user_id: str,
) -> Optional[uuid.UUID]:
    """Pick a variant for a *new* user according to the bandit weights.

    Deterministic per ``(user_id, experiment.id)``: the user is hashed into a
    bucket in ``[0, 1)`` and the bucket is looked up in the cumulative
    distribution of the normalised weights, so repeated calls for the same
    user return the same variant before the sticky assignment row exists.

    Variants whose weight is missing or ``0`` receive no traffic.  Returns
    ``None`` (meaning: use the default traffic-allocation hashing) when the
    experiment is fixed-allocation, when there is no bandit state, or when
    every weight is zero.
    """
    if experiment is None:
        return None
    if (getattr(experiment, "optimization_type", "fixed") or "fixed") == "fixed":
        return None
    if bandit_state is None or not bandit_state.variant_weights:
        return None

    raw_weights = bandit_state.variant_weights
    if not isinstance(raw_weights, dict):
        return None

    # Stable ordering so the cumulative walk is reproducible across sessions.
    variants = sorted(experiment.variants or [], key=lambda v: str(v.id))
    weighted = [
        (variant.id, _bandit_weight(raw_weights.get(str(variant.id))))
        for variant in variants
    ]
    weighted = [(vid, w) for vid, w in weighted if w > 0.0]
    total = sum(w for _, w in weighted)
    if not weighted or total <= 0.0:
        return None

    digest = hashlib.md5(
        f"{user_id}:{experiment.id}:bandit".encode(), usedforsecurity=False
    ).hexdigest()
    bucket = int(digest, 16) % 10_000 / 10_000

    cumulative = 0.0
    for variant_id, weight in weighted:
        cumulative += weight / total
        if bucket < cumulative:
            return variant_id
    # Floating-point tail: bucket landed at/after the last threshold.
    return weighted[-1][0]


@router.get("/")
def get_tracking():
    """
    Tracking API information endpoint.

    Returns general information about the tracking API endpoints.
    """
    return {"message": "Tracking API Endpoints"}


@router.post(
    "/assign",
    response_model=VariantAssignmentResponse,
    summary="Assign user to experiment variant",
    response_description="Returns the variant assignment for the user",
)
async def assign_user_to_experiment(
    request: AssignmentRequest = Body(..., description="Assignment request data"),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
) -> VariantAssignmentResponse:
    """
    Assign a user to an experiment variant.

    This endpoint assigns a user to a variant of the specified experiment.
    It handles consistent assignment for returning users.

    The assignment is deterministic based on:
    - User ID
    - Experiment ID
    - Targeting rules
    - Traffic allocation percentages

    This means that the same user will always get the same variant assignment
    for a specific experiment, ensuring a consistent user experience.

    **Authentication**: Requires a valid API key in the X-API-Key header.

    Returns:
        AssignmentResponse: The variant assignment with configuration details

    Raises:
        HTTPException 401: If the API key is invalid
        HTTPException 404: If the experiment doesn't exist or is not active
        HTTPException 500: If there's an error during assignment
    """
    # Get experiment by key
    experiment = (
        db.query(Experiment)
        .filter(
            Experiment.key == request.experiment_key,
            Experiment.status == ExperimentStatus.ACTIVE,
        )
        .first()
    )

    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active experiment with key '{request.experiment_key}' not found",
        )

    # Create assignment service
    assignment_service = AssignmentService(db)

    # Multi-armed bandit experiments: route *new* users according to the
    # latest BanditState weights.  Existing (sticky) assignments always win
    # because assign_user returns the stored row before using the override.
    override_variant_id: Optional[uuid.UUID] = None
    if (experiment.optimization_type or "fixed") != "fixed":
        bandit_state = (
            db.query(BanditState)
            .filter(BanditState.experiment_id == experiment.id)
            .first()
        )
        override_variant_id = _select_bandit_variant(
            experiment, bandit_state, request.user_id
        )

    try:
        # Attempt to assign the user
        assignment_data = assignment_service.assign_user(
            user_id=request.user_id,
            experiment_id=str(experiment.id),
            context=request.context,
            override_variant_id=override_variant_id,
        )

        # Get the variant
        variant_id = assignment_data.get("variant_id")
        variant = next(
            (v for v in experiment.variants if str(v.id) == variant_id),
            None,
        )

        if not variant:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Assigned variant not found in experiment",
            )

        # Create response
        return VariantAssignmentResponse(
            experiment_key=request.experiment_key,
            user_id=request.user_id,
            variant_id=str(variant.id),
            variant_name=variant.name,
            is_control=bool(variant.is_control),
            configuration=variant.configuration,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error assigning user to experiment: {str(e)}",
        )


@router.post(
    "/track",
    response_model=EventResponse,
    summary="Track event",
    response_description="Returns confirmation of event tracking",
)
async def track_event(
    request: EventRequest = Body(..., description="Event data to track"),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
) -> EventResponse:
    """
    Track an event for an experiment.

    This endpoint records a user interaction event associated with an experiment.
    Events are used to measure experiment metrics and outcomes.

    Event tracking can be associated with:
    - A specific experiment (using experiment_key)
    - A feature flag (using feature_flag_key)
    - Or both

    Additional data can be included:
    - Numeric value (for revenue, durations, counts)
    - Metadata (additional contextual information)
    - Custom timestamp (defaults to server time if not provided)

    **Authentication**: Requires a valid API key in the X-API-Key header.

    Returns:
        EventResponse: Confirmation of successful event tracking with event ID

    Raises:
        HTTPException 401: If the API key is invalid
        HTTPException 422: If the event data is invalid
    """
    # Find experiment ID if specified
    experiment_id = None
    variant_id = None
    if request.experiment_key:
        experiment = (
            db.query(Experiment)
            .filter(Experiment.key == request.experiment_key)
            .first()
        )

        if experiment:
            experiment_id = experiment.id

            # Find variant if user has an assignment
            assignment = (
                db.query(Assignment)
                .filter(
                    Assignment.experiment_id == experiment_id,
                    Assignment.user_id == request.user_id,
                )
                .order_by(Assignment.created_at.desc())
                .first()
            )

            if assignment:
                variant_id = assignment.variant_id

    # Find feature flag ID if specified
    feature_flag_id = None
    if request.feature_flag_key:
        feature_flag = (
            db.query(FeatureFlag)
            .filter(FeatureFlag.key == request.feature_flag_key)
            .first()
        )

        if feature_flag:
            feature_flag_id = feature_flag.id

    # If neither found, return error
    if not experiment_id and not feature_flag_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Neither experiment key '{request.experiment_key}' nor feature flag key '{request.feature_flag_key}' found",
        )

    try:
        # Create event data
        event_data = EventCreate(
            user_id=request.user_id,
            event_type=request.event_type,
            event_name=request.event_name or request.event_type,
            experiment_id=str(experiment_id) if experiment_id else None,
            feature_flag_id=str(feature_flag_id) if feature_flag_id else None,
            variant_id=str(variant_id) if variant_id else None,
            value=request.value,
            properties=request.metadata,
            timestamp=request.timestamp or datetime.now(timezone.utc),
        )

        # Track the event
        event = EventService(db).track_event(event_data)
        return _event_response(event)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid event: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error tracking event: {str(e)}",
        )


@router.post(
    "/events",
    response_model=EventResponse,
    summary="Track event by ids",
    response_description="Returns the stored event",
)
async def track_event_by_ids(
    event_data: EventCreate = Body(..., description="Event data keyed by experiment/flag ids"),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
) -> EventResponse:
    """
    Track an event that already carries internal identifiers.

    Unlike ``/track`` (which resolves ``experiment_key``/``feature_flag_key``),
    this endpoint accepts ``experiment_id``/``feature_flag_id``/``variant_id``
    directly.  It is used by server-side integrations and the data seeding
    tooling that already hold the ids.

    **Authentication**: Requires a valid API key in the X-API-Key header.
    """
    try:
        event = EventService(db).track_event(event_data)
        return _event_response(event)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid event: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error tracking event: {str(e)}",
        )


@router.post(
    "/batch",
    response_model=EventBatchResponse,
    summary="Track multiple events in batch",
    response_description="Returns batch processing results",
)
async def track_events_batch(
    request: EventBatchRequest = Body(
        ...,
        description="Batch of events to track",
        examples={
            "default": {
                "summary": "Batch tracking example",
                "description": "A sample batch of events to track for an experiment",
                "value": {
                    "events": [
                        {
                            "event_type": "page_view",
                            "user_id": "user-123",
                            "experiment_key": "homepage-redesign",
                            "metadata": {"page": "/products", "referrer": "google"},
                        },
                        {
                            "event_type": "click",
                            "user_id": "user-123",
                            "experiment_key": "homepage-redesign",
                            "metadata": {"element": "buy-button"},
                        },
                    ]
                }
            }
        },
    ),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
) -> EventBatchResponse:
    """
    Track multiple events in a single batch operation.

    This endpoint allows tracking multiple events in a single request,
    improving performance for high-volume event tracking.

    The batch can contain up to 100 events. If any events fail validation,
    the response will include details about which events failed and why.

    **Authentication**: Requires a valid API key in the X-API-Key header.

    Returns:
        EventBatchResponse: Results of the batch processing operation

    Raises:
        HTTPException 401: If the API key is invalid
        HTTPException 413: If the batch size exceeds the limit
        HTTPException 422: If the batch request format is invalid
    """
    # Check batch size
    if len(request.events) > 100:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Batch size exceeds the limit of 100 events",
        )

    # Create event service
    event_service = EventService(db)

    # Initialize counters
    success_count = 0
    failure_count = 0
    errors = []

    # Process each event
    for index, event_request in enumerate(request.events):
        try:
            # Find experiment ID if specified
            experiment_id = None
            variant_id = None
            if event_request.experiment_key:
                experiment = (
                    db.query(Experiment)
                    .filter(Experiment.key == event_request.experiment_key)
                    .first()
                )

                if experiment:
                    experiment_id = experiment.id

                    # Find variant if user has an assignment
                    assignment = (
                        db.query(Assignment)
                        .filter(
                            Assignment.experiment_id == experiment_id,
                            Assignment.user_id == event_request.user_id,
                        )
                        .order_by(Assignment.created_at.desc())
                        .first()
                    )

                    if assignment:
                        variant_id = assignment.variant_id

            # Find feature flag ID if specified
            feature_flag_id = None
            if event_request.feature_flag_key:
                feature_flag = (
                    db.query(FeatureFlag)
                    .filter(FeatureFlag.key == event_request.feature_flag_key)
                    .first()
                )

                if feature_flag:
                    feature_flag_id = feature_flag.id

            # Skip if neither found
            if not experiment_id and not feature_flag_id:
                failure_count += 1
                errors.append(
                    {
                        "index": index,
                        "event_type": event_request.event_type,
                        "user_id": event_request.user_id,
                        "error": f"Neither experiment key '{event_request.experiment_key}' nor feature flag key '{event_request.feature_flag_key}' found",
                    }
                )
                continue

            # Create event data
            event_data = EventCreate(
                user_id=event_request.user_id,
                event_type=event_request.event_type,
                event_name=event_request.event_name or event_request.event_type,
                experiment_id=str(experiment_id) if experiment_id else None,
                feature_flag_id=str(feature_flag_id) if feature_flag_id else None,
                variant_id=str(variant_id) if variant_id else None,
                value=event_request.value,
                properties=event_request.metadata,
                timestamp=event_request.timestamp or datetime.now(timezone.utc),
            )

            # Track the event
            event_service.track_event(event_data)
            success_count += 1

        except Exception as e:
            failure_count += 1
            errors.append(
                {
                    "index": index,
                    "event_type": event_request.event_type,
                    "user_id": event_request.user_id,
                    "error": str(e),
                }
            )

    # Return batch response
    return EventBatchResponse(
        success_count=success_count,
        failure_count=failure_count,
        errors=errors if errors else None,
    )


@router.get(
    "/assignments/{user_id}",
    response_model=List[Dict[str, Any]],
    summary="Get user's experiment assignments",
    response_description="Returns all active experiment assignments for a user",
)
async def get_user_assignments(
    user_id: str = Path(..., description="ID of the user"),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
    active_only: bool = Query(
        True, description="Only return active experiment assignments"
    ),
) -> List[Dict[str, Any]]:
    """
    Get all experiment assignments for a user.

    This endpoint retrieves all experiment variants assigned to a specific user.
    By default, it only returns assignments for active experiments.

    **Authentication**: Requires a valid API key in the X-API-Key header.

    Returns:
        List[Dict[str, Any]]: List of assignment details for the user

    Raises:
        HTTPException 401: If the API key is invalid
        HTTPException 404: If user has no assignments
    """
    # Create assignment service
    assignment_service = AssignmentService(db)

    # Get user assignments
    assignments = assignment_service.get_user_assignments(
        user_id=user_id, active_only=active_only
    )

    if not assignments:
        return []

    return assignments
