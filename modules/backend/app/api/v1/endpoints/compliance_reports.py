"""
Compliance report generation and audit export — EP-033.

MODULE: compliance. This module holds the *bodies* of

  GET /api/v1/compliance/reports/{standard}   — on-demand SOC 2 / ISO 27001 report
  GET /api/v1/compliance/export               — full audit export (JSON or CSV)

both of which depend on ``services/compliance_report_service`` and on the
HMAC signature verification that goes with it.

The routes themselves stay declared on the core compliance router
(``api/v1/endpoints/compliance.py``), which reaches these handlers through
``core/optional_modules`` and answers HTTP 501 when this module is not
installed.

``GET /api/v1/compliance/audit-events`` is core and lives entirely in
``compliance.py`` — it reads ``audit_events_v2`` through the core
``AuditLogService`` and has no dependency on this module.
"""

from dataclasses import asdict as dataclasses_asdict
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.models.user import User, UserRole
from modules.backend.app.services.compliance_report_service import (
    ComplianceReportService,
)

# Roles that may read compliance audit data (reports + event listing)
_ALLOWED_ROLES = (UserRole.ADMIN, UserRole.ANALYST)

# Supported compliance standards for report generation
_SUPPORTED_STANDARDS = {"soc2", "iso27001"}


def generate_compliance_report(
    standard: str,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    current_user: User,
    db: Session,
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
    has_allowed_role = (
        hasattr(current_user, "role") and current_user.role in _ALLOWED_ROLES
    )
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


def export_audit_events(
    format: str,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    current_user: User,
    db: Session,
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
