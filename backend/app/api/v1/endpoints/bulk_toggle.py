"""
Bulk feature flag toggle endpoints (P1-B).

POST /api/v1/feature-flags/bulk-toggle  — enable/disable/archive multiple flags
GET  /api/v1/feature-flags/{id}/history — change history for a single flag
GET  /api/v1/audit-logs/stream          — SSE stream of recent audit events (last 100)
"""

import asyncio
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.permissions import Action, can_act_on_feature_flag
from backend.app.models.audit_log import ActionType
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.user import User
from backend.app.schemas.advanced_toggle import (
    BulkToggleRequest,
    BulkToggleResponse,
    BulkToggleResult,
    DetailedAuditLogResponse,
    FlagChangeHistoryResponse,
)
from backend.app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/feature-flags/bulk-toggle",
    response_model=BulkToggleResponse,
    summary="Bulk enable/disable/archive feature flags",
)
async def bulk_toggle_flags(
    request: BulkToggleRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Toggle multiple feature flags in a single operation.
    Each flag's result is reported individually.
    Requires UPDATE permission on feature_flag resource.
    Creates one audit log entry per successfully-processed flag.
    The operation is partial-success by design: if some flags fail,
    the endpoint still returns 200 with per-flag results.
    """
    results = []
    audit_log_ids = []

    for flag_id_str in request.flag_ids:
        try:
            flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id_str).first()
            if not flag:
                results.append(
                    BulkToggleResult(
                        flag_id=flag_id_str,
                        flag_key="unknown",
                        success=False,
                        error="Feature flag not found",
                    )
                )
                continue

            # Before any change to the row: a refused flag must be left exactly
            # as it was, because the final commit below covers every flag.
            # Archive is a status change, so all three actions need UPDATE.
            if not can_act_on_feature_flag(current_user, flag.owner_id, Action.UPDATE):
                results.append(
                    BulkToggleResult(
                        flag_id=str(flag.id),
                        flag_key=flag.key,
                        success=False,
                        error="Not enough permissions to change this feature flag",
                    )
                )
                continue

            old_status = (
                flag.status.value if hasattr(flag.status, "value") else str(flag.status)
            )

            if request.action == "enable":
                flag.status = FeatureFlagStatus.ACTIVE
                action_type = ActionType.TOGGLE_ENABLE
            elif request.action == "disable":
                flag.status = FeatureFlagStatus.INACTIVE
                action_type = ActionType.TOGGLE_DISABLE
            elif request.action == "archive":
                flag.status = FeatureFlagStatus.ARCHIVED
                action_type = ActionType.FEATURE_FLAG_UPDATE
            else:
                # Should not happen due to Pydantic validation, but guard anyway
                results.append(
                    BulkToggleResult(
                        flag_id=flag_id_str,
                        flag_key=flag.key,
                        success=False,
                        error=f"Unknown action: {request.action}",
                    )
                )
                continue

            new_status = (
                flag.status.value if hasattr(flag.status, "value") else str(flag.status)
            )
            db.flush()

            # Log to audit (one entry per flag)
            log_id = await AuditService.log_toggle_operation(
                db=db,
                user_id=current_user.id,
                user_email=current_user.email,
                action_type=action_type.value,
                entity_id=flag.id,
                entity_name=flag.name,
                old_value=old_status,
                new_value=new_status,
                reason=request.reason,
            )
            audit_log_ids.append(str(log_id))

            results.append(
                BulkToggleResult(
                    flag_id=str(flag.id),
                    flag_key=flag.key,
                    success=True,
                    old_status=old_status,
                    new_status=new_status,
                )
            )

        except Exception as e:
            logger.error(f"Error processing flag {flag_id_str} in bulk toggle: {e}")
            results.append(
                BulkToggleResult(
                    flag_id=flag_id_str,
                    flag_key="error",
                    success=False,
                    error=str(e),
                )
            )

    try:
        db.commit()
    except Exception as e:
        logger.error(f"Failed to commit bulk toggle transaction: {e}")
        db.rollback()

    succeeded = sum(1 for r in results if r.success)
    return BulkToggleResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
        audit_log_ids=audit_log_ids,
    )


@router.get(
    "/feature-flags/{flag_id}/history",
    response_model=FlagChangeHistoryResponse,
    summary="Get change history for a feature flag",
)
def get_flag_history(
    flag_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Returns all audit log entries for a specific feature flag.
    Ordered by timestamp descending (most recent first).
    Requires authentication; ADMIN/ANALYST roles can view all history,
    other roles can view flags they have access to.
    """
    flag = db.query(FeatureFlag).filter(FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(status_code=404, detail="Feature flag not found")

    logs, total = AuditService.get_flag_change_history(db, flag_id, limit, offset)

    return FlagChangeHistoryResponse(
        flag_id=str(flag.id),
        flag_key=flag.key,
        flag_name=flag.name,
        total_changes=total,
        history=[
            DetailedAuditLogResponse(
                id=str(log.id),
                timestamp=log.timestamp,
                user_id=str(log.user_id) if log.user_id else None,
                user_email=log.user_email,
                action_type=log.action_type,
                entity_type=log.entity_type,
                entity_id=str(log.entity_id),
                entity_name=log.entity_name,
                old_value=log.old_value,
                new_value=log.new_value,
                reason=log.reason,
            )
            for log in logs
        ],
    )


@router.get(
    "/audit-logs/stream",
    summary="SSE stream of recent audit log events",
)
async def stream_audit_logs(
    limit: int = Query(50, ge=1, le=100),
    entity_type: Optional[str] = Query(None),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Returns recent audit log entries as Server-Sent Events.
    Useful for real-time audit dashboards.
    Streams up to `limit` entries (default 50, max 100) then closes.
    """

    async def event_generator():
        from backend.app.models.audit_log import EntityType as EntityTypeEnum

        entity_type_enum = None
        if entity_type:
            try:
                entity_type_enum = EntityTypeEnum(entity_type)
            except ValueError:
                pass  # Ignore invalid entity_type silently in SSE stream

        # get_audit_logs uses page (1-based) rather than offset
        logs, _ = AuditService.get_audit_logs(
            db,
            limit=limit,
            entity_type=entity_type_enum,
            page=1,
        )
        for i, log in enumerate(logs):
            event_data = json.dumps(
                {
                    "id": str(log.id),
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    "user_email": log.user_email,
                    "action_type": log.action_type,
                    "entity_type": log.entity_type,
                    "entity_name": log.entity_name,
                    "old_value": log.old_value,
                    "new_value": log.new_value,
                }
            )
            yield f"data: {event_data}\n\n"
            await asyncio.sleep(0.01)
        yield 'data: {"event": "end"}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
