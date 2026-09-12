"""
Real-time counter REST endpoints (P2-B).

Provides live experiment assignment / event / conversion counts backed by
DynamoDB atomic counters so dashboards can show up-to-date data without
waiting for batch analytics jobs.

Endpoints:
    GET  /api/v1/counters/{experiment_id}          — read all counters
    POST /api/v1/counters/{experiment_id}/increment — atomic single increment
    POST /api/v1/counters/{experiment_id}/bulk      — atomic bulk increment
    POST /api/v1/counters/{experiment_id}/reset     — reset (ADMIN only)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api import deps
from backend.app.models.user import User, UserRole
from backend.app.schemas.realtime_counters import (
    BulkIncrementRequest,
    BulkIncrementResponse,
    CounterResetRequest,
    ExperimentCounters,
    IncrementRequest,
    IncrementResponse,
)
from backend.app.services.dynamodb_counter_service import DynamoDBCounterService

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Dependency — provides a shared DynamoDBCounterService instance
# ---------------------------------------------------------------------------

_counter_service: Optional[DynamoDBCounterService] = None


def get_counter_service() -> DynamoDBCounterService:
    """
    Dependency that returns a singleton DynamoDBCounterService.

    This can be overridden in tests via app.dependency_overrides.
    """
    global _counter_service
    if _counter_service is None:
        _counter_service = DynamoDBCounterService()
    return _counter_service


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{experiment_id}",
    response_model=ExperimentCounters,
    summary="Get real-time counters for an experiment",
    responses={
        200: {"description": "Experiment counters returned"},
        404: {"description": "No counter data found for this experiment"},
    },
)
def get_experiment_counters(
    experiment_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    svc: DynamoDBCounterService = Depends(get_counter_service),
) -> ExperimentCounters:
    """
    Return real-time counters for all variants of the given experiment.

    Returns HTTP 404 when the experiment has no counter data (i.e. no
    assignments, events, or conversions have been recorded yet).
    """
    counters = svc.get_experiment_counters(experiment_id)

    # Return 404 when there is no data at all
    if (
        counters.total_assignments == 0
        and counters.total_events == 0
        and counters.total_conversions == 0
        and not counters.variants
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No counter data found for experiment '{experiment_id}'",
        )

    return counters


@router.post(
    "/{experiment_id}/increment",
    response_model=IncrementResponse,
    summary="Atomically increment a single counter",
    status_code=status.HTTP_200_OK,
)
def increment_counter(
    experiment_id: str,
    request: IncrementRequest,
    current_user: User = Depends(deps.get_current_active_user),
    svc: DynamoDBCounterService = Depends(get_counter_service),
) -> IncrementResponse:
    """
    Atomically increment a counter (assignment, event, or conversion) for a
    specific experiment variant.

    Uses DynamoDB's ADD update expression — safe under concurrent writes.
    """
    try:
        new_value = svc.increment_counter(
            experiment_id=request.experiment_id,
            variant_id=request.variant_id,
            counter_type=request.counter_type,
            amount=request.amount,
        )
    except Exception as exc:
        logger.error(
            "Failed to increment counter for experiment=%s variant=%s type=%s: %s",
            experiment_id,
            request.variant_id,
            request.counter_type,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Counter increment failed: {exc}",
        )

    return IncrementResponse(
        experiment_id=request.experiment_id,
        variant_id=request.variant_id,
        counter_type=request.counter_type,
        new_value=new_value,
    )


@router.post(
    "/{experiment_id}/bulk",
    response_model=BulkIncrementResponse,
    summary="Bulk-increment multiple counters",
    status_code=status.HTTP_200_OK,
)
def bulk_increment(
    experiment_id: str,
    request: BulkIncrementRequest,
    current_user: User = Depends(deps.get_current_active_user),
    svc: DynamoDBCounterService = Depends(get_counter_service),
) -> BulkIncrementResponse:
    """
    Increment multiple counters in a single API call.

    Accepts up to 100 increment requests.  Partial failures are collected
    and reported in the response — the operation does not abort on first error.
    """
    return svc.bulk_increment(request.increments)


@router.post(
    "/{experiment_id}/reset",
    summary="Reset counters (ADMIN only)",
    status_code=status.HTTP_200_OK,
)
def reset_counters(
    experiment_id: str,
    request: CounterResetRequest,
    current_user: User = Depends(deps.get_current_active_user),
    svc: DynamoDBCounterService = Depends(get_counter_service),
) -> dict:
    """
    Reset one or more counters to zero.

    - If ``variant_id`` is omitted, resets all variants.
    - If ``counter_type`` is omitted, resets all counter types.
    - Requires ADMIN role.
    """
    # ADMIN-only: check superuser flag OR explicit ADMIN role
    is_admin = (
        getattr(current_user, "is_superuser", False)
        or getattr(current_user, "role", None) == UserRole.ADMIN
    )
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only ADMIN users can reset counters",
        )

    svc.reset_counters(
        experiment_id=request.experiment_id,
        variant_id=request.variant_id,
        counter_type=request.counter_type,
        reason=request.reason,
    )

    return {
        "status": "ok",
        "experiment_id": request.experiment_id,
        "message": "Counters reset successfully",
    }
