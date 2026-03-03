"""
Compliance audit log API endpoints.

Provides read access to the SOC 2 / ISO 27001 compliance audit trail.
Access is restricted to ADMIN and ANALYST roles.
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.db.session import get_db
from backend.app.models.compliance_audit_event import AuditAction
from backend.app.models.user import User, UserRole
from backend.app.schemas.compliance_audit import (
    ComplianceAuditEventListResponse,
)
from backend.app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)

router = APIRouter()

# Roles that may read compliance audit data
_ALLOWED_ROLES = (UserRole.ADMIN, UserRole.ANALYST)


@router.get(
    "/audit-events",
    response_model=ComplianceAuditEventListResponse,
    summary="List compliance audit events",
    response_description="Returns a paginated list of compliance audit events",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": "Caller does not have ADMIN or ANALYST role",
        },
    },
)
def list_audit_events(
    resource_type: Optional[str] = Query(
        None,
        description="Filter by resource type, e.g. feature_flag or experiment",
    ),
    actor_id: Optional[UUID] = Query(
        None,
        description="Filter by actor (user) UUID",
    ),
    action: Optional[AuditAction] = Query(
        None,
        description="Filter by action (CREATE, UPDATE, DELETE, LOGIN, …)",
    ),
    start_time: Optional[datetime] = Query(
        None,
        description="Only return events at or after this UTC datetime (ISO 8601)",
    ),
    end_time: Optional[datetime] = Query(
        None,
        description="Only return events at or before this UTC datetime (ISO 8601)",
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(50, ge=1, le=200, description="Records per page"),
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
) -> ComplianceAuditEventListResponse:
    """List compliance audit events.

    Returns a paginated, optionally filtered list of compliance-grade audit
    events. Each event is HMAC-signed for tamper-evidence.

    **Access control**: Requires ADMIN or ANALYST role. DEVELOPER and VIEWER
    roles will receive HTTP 403.

    **Filtering**: All query parameters are optional and can be combined.

    **Pagination**: Use `page` and `limit`; the response includes `total` so
    callers can compute the number of pages.
    """
    if not hasattr(current_user, "role") or current_user.role not in _ALLOWED_ROLES:
        # Superusers always get access regardless of role field
        if not (hasattr(current_user, "is_superuser") and current_user.is_superuser):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Compliance audit logs require ADMIN or ANALYST role",
            )

    service = AuditLogService(db)
    result = service.get_events(
        resource_type=resource_type,
        actor_id=str(actor_id) if actor_id else None,
        action=action,
        start_time=start_time,
        end_time=end_time,
        page=page,
        limit=limit,
    )
    return ComplianceAuditEventListResponse(**result)
