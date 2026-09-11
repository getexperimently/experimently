"""
Client error reporting endpoints (``POST /api/v1/tracking/errors``).

SDKs and demo simulators use these API-key endpoints to report errors that
happened *in the client* while a feature flag or experiment was active (a
crash in a redesigned screen, a failed request behind a flag, ...). Each report
becomes an :class:`~backend.app.models.metrics.metric.ErrorLog` row attached to
the flag, which is exactly what safety monitoring divides by the flag's
evaluation count to compute ``error_rate`` — so client-side errors can trigger
the same automatic rollback as server-side evaluation failures.

The router is mounted under the ``/tracking`` prefix next to the event
tracking endpoints (see ``backend/app/api/api.py``).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.models.experiment import Experiment
from backend.app.models.feature_flag import FeatureFlag
from backend.app.models.metrics.metric import ErrorLog
from backend.app.schemas.metrics import ErrorLogCreate
from backend.app.services.metrics_service import MetricsService

router = APIRouter()

#: Maximum number of reports accepted by the batch endpoint.
MAX_BATCH_SIZE = 100

# Column limits on ``error_logs`` (see ErrorLog model).
_ERROR_TYPE_MAX = 100
_MESSAGE_MAX = 1000


# ---------------------------------------------------------------------------
# Schemas (kept local: this module owns the client error contract)
# ---------------------------------------------------------------------------


class ClientErrorRequest(BaseModel):
    """One client-side error report."""

    feature_flag_key: Optional[str] = Field(
        None,
        description="Key of the feature flag that was active when the error happened",
    )
    experiment_key: Optional[str] = Field(
        None,
        description="Key of the experiment the user was in when the error happened",
    )
    user_id: Optional[str] = Field(None, max_length=255, description="User / device id")
    error_type: str = Field(
        ...,
        min_length=1,
        max_length=_ERROR_TYPE_MAX,
        description='Error class, e.g. "crash"',
    )
    message: str = Field(..., min_length=1, description="Human readable error message")
    stack_trace: Optional[str] = Field(None, description="Optional stack trace")
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional debug data (os, os_version, device_model, ...)"
    )
    timestamp: Optional[datetime] = Field(
        None, description="When the error happened (ISO 8601); defaults to now"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "feature_flag_key": "streampulse_player_v2",
                "user_id": "device-1234",
                "error_type": "crash",
                "message": "NullPointerException in PlayerV2Fragment",
                "metadata": {
                    "os": "Android",
                    "os_version": "12.0.0",
                    "app_version": "3.2.0",
                },
            }
        }
    )

    @model_validator(mode="after")
    def _require_a_target(self) -> "ClientErrorRequest":
        if not (self.feature_flag_key or self.experiment_key):
            raise ValueError(
                "At least one of feature_flag_key or experiment_key is required"
            )
        return self


class ClientErrorResponse(BaseModel):
    """Confirmation of a stored error report."""

    id: str
    error_type: str
    feature_flag_id: Optional[str] = None
    experiment_id: Optional[str] = None
    user_id: Optional[str] = None
    timestamp: datetime


class ClientErrorBatchRequest(BaseModel):
    """Batch of error reports."""

    errors: List[ClientErrorRequest] = Field(
        ..., min_length=1, description="Error reports"
    )


class ClientErrorBatchResponse(BaseModel):
    """Outcome of a batch of error reports."""

    success_count: int
    failure_count: int
    errors: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_targets(
    db: Session, report: ClientErrorRequest
) -> Tuple[Optional[UUID], Optional[UUID]]:
    """Resolve ``feature_flag_key`` / ``experiment_key`` to ids; ``LookupError`` when unknown."""
    feature_flag_id: Optional[UUID] = None
    experiment_id: Optional[UUID] = None

    if report.feature_flag_key:
        flag = (
            db.query(FeatureFlag)
            .filter(FeatureFlag.key == report.feature_flag_key)
            .first()
        )
        if flag is None:
            raise LookupError(
                f"Feature flag with key '{report.feature_flag_key}' not found"
            )
        feature_flag_id = flag.id

    if report.experiment_key:
        experiment = (
            db.query(Experiment).filter(Experiment.key == report.experiment_key).first()
        )
        if experiment is None:
            raise LookupError(
                f"Experiment with key '{report.experiment_key}' not found"
            )
        experiment_id = experiment.id

    return feature_flag_id, experiment_id


def _naive_utc(value: Optional[datetime]) -> datetime:
    """``error_logs.timestamp`` is a naive UTC column; normalise client timestamps to it."""
    if value is None:
        return datetime.utcnow()
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _request_data(
    report: ClientErrorRequest, experiment_id: Optional[UUID]
) -> Dict[str, Any]:
    """The ``request_data`` JSON stored with the row (what the client told us)."""
    data: Dict[str, Any] = {"source": "client"}
    if report.feature_flag_key:
        data["feature_flag_key"] = report.feature_flag_key
    if report.experiment_key:
        data["experiment_key"] = report.experiment_key
    if experiment_id is not None:
        data["experiment_id"] = str(experiment_id)
    return data


def _to_error_log_create(
    report: ClientErrorRequest,
    feature_flag_id: Optional[UUID],
    experiment_id: Optional[UUID],
) -> ErrorLogCreate:
    return ErrorLogCreate(
        error_type=report.error_type[:_ERROR_TYPE_MAX],
        feature_flag_id=feature_flag_id,
        user_id=report.user_id,
        message=report.message[:_MESSAGE_MAX],
        stack_trace=report.stack_trace,
        request_data=_request_data(report, experiment_id),
        metadata=report.metadata,
        timestamp=_naive_utc(report.timestamp),
    )


def _response(row: ErrorLog, experiment_id: Optional[UUID]) -> ClientErrorResponse:
    return ClientErrorResponse(
        id=str(row.id),
        error_type=row.error_type,
        feature_flag_id=str(row.feature_flag_id) if row.feature_flag_id else None,
        experiment_id=str(experiment_id) if experiment_id else None,
        user_id=row.user_id,
        timestamp=row.timestamp,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/errors",
    response_model=ClientErrorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report a client-side error",
    response_description="Returns the stored error log entry",
)
async def report_client_error(
    report: ClientErrorRequest = Body(..., description="Error report"),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
) -> ClientErrorResponse:
    """
    Record an error that happened in a client while a feature flag or
    experiment was active.

    The row is attached to the feature flag resolved from ``feature_flag_key``
    so safety monitoring counts it towards that flag's ``error_rate``
    (errors / flag evaluations in the monitoring window). ``experiment_key``
    is resolved and stored in ``request_data``.

    **Authentication**: Requires a valid API key in the X-API-Key header.

    Raises:
        HTTPException 401: If the API key is invalid
        HTTPException 404: If ``feature_flag_key`` or ``experiment_key`` is unknown
        HTTPException 422: If neither key is given or the body is invalid
    """
    try:
        feature_flag_id, experiment_id = _resolve_targets(db, report)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    try:
        row = MetricsService.log_error(
            db=db, data=_to_error_log_create(report, feature_flag_id, experiment_id)
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error storing client error: {exc}",
        )

    return _response(row, experiment_id)


@router.post(
    "/errors/batch",
    response_model=ClientErrorBatchResponse,
    summary="Report multiple client-side errors",
    response_description="Returns batch processing results",
)
async def report_client_errors_batch(
    request: ClientErrorBatchRequest = Body(..., description="Batch of error reports"),
    db: Session = Depends(deps.get_db),
    api_key_info: Dict[str, Any] = Depends(deps.get_api_key),
) -> ClientErrorBatchResponse:
    """
    Record up to 100 client-side errors in one request.

    Reports whose keys cannot be resolved are skipped and listed in ``errors``
    (with their index); the rest are stored in a single transaction.

    **Authentication**: Requires a valid API key in the X-API-Key header.

    Raises:
        HTTPException 401: If the API key is invalid
        HTTPException 413: If more than 100 reports are sent
        HTTPException 422: If the batch is malformed
    """
    if len(request.errors) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Batch size exceeds the limit of {MAX_BATCH_SIZE} errors",
        )

    success_count = 0
    failure_count = 0
    failures: List[Dict[str, Any]] = []
    rows: List[ErrorLog] = []

    for index, report in enumerate(request.errors):
        try:
            feature_flag_id, experiment_id = _resolve_targets(db, report)
            data = _to_error_log_create(report, feature_flag_id, experiment_id)
            rows.append(
                ErrorLog(
                    error_type=data.error_type,
                    timestamp=data.timestamp,
                    feature_flag_id=data.feature_flag_id,
                    user_id=data.user_id,
                    message=data.message,
                    stack_trace=data.stack_trace,
                    request_data=data.request_data,
                    meta_data=data.metadata,
                )
            )
            success_count += 1
        except Exception as exc:  # LookupError or validation problems
            failure_count += 1
            failures.append(
                {
                    "index": index,
                    "error_type": report.error_type,
                    "user_id": report.user_id,
                    "error": str(exc),
                }
            )

    if rows:
        try:
            db.add_all(rows)
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error storing client errors: {exc}",
            )

    return ClientErrorBatchResponse(
        success_count=success_count,
        failure_count=failure_count,
        errors=failures or None,
    )
