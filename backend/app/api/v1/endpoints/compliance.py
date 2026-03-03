"""
Compliance audit log API endpoints.

Provides read access to the SOC 2 / ISO 27001 compliance audit trail.
Access is restricted to ADMIN and ANALYST roles.

Endpoints:
  GET /audit-events      — Paginated audit event listing (ADMIN/ANALYST)
  GET /reports/{standard} — On-demand compliance report (ADMIN/ANALYST)
  GET /export             — Full audit export as JSON or CSV (ADMIN only)
"""
import logging
from dataclasses import asdict as dataclasses_asdict
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.db.session import get_db
from backend.app.models.compliance_audit_event import AuditAction
from backend.app.models.user import User, UserRole
from backend.app.schemas.compliance_audit import (
    ComplianceAuditEventListResponse,
)
from backend.app.services.audit_log_service import AuditLogService
from backend.app.services.compliance_report_service import ComplianceReportService

logger = logging.getLogger(__name__)

router = APIRouter()

# Roles that may read compliance audit data (reports + event listing)
_ALLOWED_ROLES = (UserRole.ADMIN, UserRole.ANALYST)

# Supported compliance standards for report generation
_SUPPORTED_STANDARDS = {"soc2", "iso27001"}


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


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

@router.get(
    "/reports/{standard}",
    summary="Generate compliance report",
    response_description="Returns a compliance audit summary report",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Unknown compliance standard",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Caller does not have ADMIN or ANALYST role",
        },
    },
)
def generate_compliance_report(
    standard: str,
    start_time: Optional[datetime] = Query(
        None,
        description="Start of reporting period (ISO 8601 UTC). Defaults to standard look-back.",
    ),
    end_time: Optional[datetime] = Query(
        None,
        description="End of reporting period (ISO 8601 UTC). Defaults to now.",
    ),
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Generate an on-demand compliance report.

    Supported standards:
    - **soc2**: SOC 2 Type 2 — default look-back is 365 days.
    - **iso27001**: ISO 27001 — default look-back is 730 days.

    The response includes event breakdowns by action, outcome, and resource
    type, as well as HMAC integrity verification statistics.

    **Access control**: Requires ADMIN or ANALYST role.
    """
    # Permission check
    is_superuser = hasattr(current_user, "is_superuser") and current_user.is_superuser
    has_allowed_role = hasattr(current_user, "role") and current_user.role in _ALLOWED_ROLES
    if not is_superuser and not has_allowed_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compliance reports require ADMIN or ANALYST role",
        )

    # Validate the requested standard
    if standard not in _SUPPORTED_STANDARDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown compliance standard '{standard}'. Supported: {sorted(_SUPPORTED_STANDARDS)}",
        )

    service = ComplianceReportService(db)
    report = service.generate_report(
        standard=standard,
        start_time=start_time,
        end_time=end_time,
    )

    return dataclasses_asdict(report)


# ---------------------------------------------------------------------------
# Audit export
# ---------------------------------------------------------------------------

@router.get(
    "/export",
    summary="Export audit events",
    response_description="Download audit events as JSON or CSV",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": "Caller does not have ADMIN role",
        },
    },
)
def export_audit_events(
    format: str = Query(
        "json",
        description="Export format: 'json' or 'csv'",
        regex="^(json|csv)$",
    ),
    start_time: Optional[datetime] = Query(
        None,
        description="Only export events at or after this UTC datetime (ISO 8601)",
    ),
    end_time: Optional[datetime] = Query(
        None,
        description="Only export events at or before this UTC datetime (ISO 8601)",
    ),
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
) -> Response:
    """Export all audit events for chain-of-custody review.

    Returns a downloadable file containing all matching audit events with
    their HMAC signatures.

    **Access control**: Requires ADMIN role only (stricter than report
    generation — this is a full data dump).

    **Format**: 'json' (default) or 'csv'.
    """
    # Only ADMIN (or superuser) may perform full exports
    is_superuser = hasattr(current_user, "is_superuser") and current_user.is_superuser
    is_admin = hasattr(current_user, "role") and current_user.role == UserRole.ADMIN
    if not is_superuser and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Audit export requires ADMIN role",
        )

    service = ComplianceReportService(db)
    content = service.export_events(
        format=format,
        start_time=start_time,
        end_time=end_time,
    )

    media_type = "text/csv" if format == "csv" else "application/json"
    filename = f"audit_export.{format}"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
