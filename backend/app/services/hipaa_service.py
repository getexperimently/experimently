"""
HIPAA Compliance Service for EP-050.

Provides business logic for:
  - PHI access audit logging (HIPAA §164.312(b))
  - Business Associate Agreement (BAA) management
  - HIPAA compliance reporting
  - PHI field encryption/decryption delegation
  - Data residency validation

All PHI access should be routed through log_phi_access() to maintain
a complete audit trail as required by HIPAA.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.phi_encryption import PHIEncryption
from backend.app.models.baa_config import BAAConfig
from backend.app.models.phi_audit_log import PHIAuditLog

logger = logging.getLogger(__name__)


class HIPAAService:
    """Service for HIPAA compliance operations."""

    # ------------------------------------------------------------------
    # PHI Audit Logging
    # ------------------------------------------------------------------

    def log_phi_access(
        self,
        db: Session,
        user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        action: str,
        phi_fields: List[str],
        purpose: str,
        request: Optional[Any] = None,
    ) -> PHIAuditLog:
        """
        Create a PHI access audit log entry.

        Args:
            db: SQLAlchemy database session.
            user_id: UUID of the user accessing PHI.
            resource_type: Type of resource (experiment, feature_flag, user_data).
            resource_id: UUID of the specific resource.
            action: One of READ, WRITE, DELETE, EXPORT.
            phi_fields: List of PHI field names accessed (minimum-necessary principle).
            purpose: One of treatment, operations, research.
            request: Optional FastAPI Request object for IP/UA extraction.

        Returns:
            The created PHIAuditLog instance.
        """
        ip_address: Optional[str] = None
        user_agent: Optional[str] = None

        if request is not None:
            try:
                ip_address = request.client.host if request.client else None
            except Exception:
                ip_address = None
            try:
                user_agent = request.headers.get("user-agent")
            except Exception:
                user_agent = None

        log_entry = PHIAuditLog(
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action.upper(),
            phi_fields_accessed=phi_fields,
            purpose=purpose.lower(),
            ip_address=ip_address,
            user_agent=user_agent,
            timestamp=datetime.utcnow(),
            retention_years=settings.HIPAA_AUDIT_LOG_RETENTION_YEARS,
        )

        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)

        logger.info(
            "PHI access logged",
            extra={
                "user_id": str(user_id),
                "resource_type": resource_type,
                "resource_id": str(resource_id),
                "action": action,
                "purpose": purpose,
            },
        )
        return log_entry

    def get_phi_audit_logs(
        self,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        resource_type: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """
        Retrieve paginated PHI audit logs with optional filters.

        Args:
            db: SQLAlchemy database session.
            start_date: Only return entries at or after this datetime.
            end_date: Only return entries at or before this datetime.
            resource_type: Filter by resource type.
            user_id: Filter by user UUID.
            page: 1-indexed page number.
            page_size: Number of records per page.

        Returns:
            Dict with keys: items, total, page, page_size.
        """
        query = db.query(PHIAuditLog)

        if start_date is not None:
            query = query.filter(PHIAuditLog.timestamp >= start_date)
        if end_date is not None:
            query = query.filter(PHIAuditLog.timestamp <= end_date)
        if resource_type is not None:
            query = query.filter(PHIAuditLog.resource_type == resource_type)
        if user_id is not None:
            query = query.filter(PHIAuditLog.user_id == user_id)

        total = query.count()
        offset = (page - 1) * page_size
        items = (
            query.order_by(PHIAuditLog.timestamp.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # BAA Configuration
    # ------------------------------------------------------------------

    def create_baa(
        self,
        db: Session,
        data: Dict[str, Any],
        created_by: uuid.UUID,
    ) -> BAAConfig:
        """
        Create a new Business Associate Agreement configuration.

        Args:
            db: SQLAlchemy database session.
            data: Dict matching BAAConfigCreate schema fields.
            created_by: UUID of the user creating the BAA record.

        Returns:
            The created BAAConfig instance.
        """
        baa = BAAConfig(
            organization_name=data["organization_name"],
            signatory_name=data["signatory_name"],
            signatory_email=str(data["signatory_email"]),
            effective_date=data["effective_date"],
            expiry_date=data.get("expiry_date"),
            data_residency_region=data["data_residency_region"],
            phi_categories=data["phi_categories"],
            signed_document_hash=data["signed_document_hash"],
            is_active=True,
            created_by=created_by,
        )
        db.add(baa)
        db.commit()
        db.refresh(baa)

        logger.info(
            "BAA configuration created",
            extra={
                "baa_id": str(baa.id),
                "organization": baa.organization_name,
                "created_by": str(created_by),
            },
        )
        return baa

    def get_baa_configs(
        self,
        db: Session,
        active_only: bool = True,
    ) -> List[BAAConfig]:
        """
        List BAA configurations.

        Args:
            db: SQLAlchemy database session.
            active_only: If True, only return active (non-deactivated) BAAs.

        Returns:
            List of BAAConfig instances.
        """
        query = db.query(BAAConfig)
        if active_only:
            query = query.filter(BAAConfig.is_active.is_(True))
        return query.order_by(BAAConfig.created_at.desc()).all()

    def get_baa_by_id(
        self,
        db: Session,
        baa_id: uuid.UUID,
    ) -> Optional[BAAConfig]:
        """Retrieve a specific BAA configuration by its UUID."""
        return db.query(BAAConfig).filter(BAAConfig.id == baa_id).first()

    def deactivate_baa(
        self,
        db: Session,
        baa_id: uuid.UUID,
    ) -> Optional[BAAConfig]:
        """
        Soft-delete a BAA by marking it inactive.

        Returns the updated BAAConfig, or None if not found.
        """
        baa = self.get_baa_by_id(db, baa_id)
        if baa is None:
            return None
        baa.is_active = False
        db.commit()
        db.refresh(baa)
        return baa

    # ------------------------------------------------------------------
    # HIPAA Compliance Report
    # ------------------------------------------------------------------

    def generate_hipaa_report(
        self,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Generate a HIPAA compliance summary report.

        Args:
            db: SQLAlchemy database session.
            start_date: Report period start (inclusive).
            end_date: Report period end (inclusive).

        Returns:
            Dict with keys defined by HIPAAReportResponse schema.
        """
        # Base audit log query
        audit_query = db.query(PHIAuditLog)
        if start_date is not None:
            audit_query = audit_query.filter(PHIAuditLog.timestamp >= start_date)
        if end_date is not None:
            audit_query = audit_query.filter(PHIAuditLog.timestamp <= end_date)

        all_logs: List[PHIAuditLog] = audit_query.all()

        # Count by purpose
        access_by_purpose: Dict[str, int] = {}
        for log in all_logs:
            purpose = log.purpose or "unknown"
            access_by_purpose[purpose] = access_by_purpose.get(purpose, 0) + 1

        # Count by resource type
        access_by_resource_type: Dict[str, int] = {}
        for log in all_logs:
            rt = log.resource_type or "unknown"
            access_by_resource_type[rt] = access_by_resource_type.get(rt, 0) + 1

        # Unique users
        unique_users = len({log.user_id for log in all_logs if log.user_id is not None})

        # Potential violations: access without a stated purpose
        potential_violations = [
            {
                "log_id": str(log.id),
                "user_id": str(log.user_id),
                "resource_type": log.resource_type,
                "resource_id": str(log.resource_id),
                "action": log.action,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "reason": "Access logged without a recognised purpose",
            }
            for log in all_logs
            if not log.purpose
            or log.purpose not in {"treatment", "operations", "research"}
        ]

        # BAA coverage summary
        all_baas = db.query(BAAConfig).all()
        active_baas = [b for b in all_baas if b.is_active]
        expired_baas = [b for b in all_baas if b.is_expired]

        baa_coverage = {
            "active_baas": len(active_baas),
            "expired_baas": len(expired_baas),
            "total_baas": len(all_baas),
            "active_organizations": [b.organization_name for b in active_baas],
        }

        return {
            "total_phi_access_events": len(all_logs),
            "access_by_purpose": access_by_purpose,
            "access_by_resource_type": access_by_resource_type,
            "unique_users_accessing_phi": unique_users,
            "potential_violations": potential_violations,
            "baa_coverage": baa_coverage,
            "report_period_start": start_date.isoformat() if start_date else None,
            "report_period_end": end_date.isoformat() if end_date else None,
        }

    # ------------------------------------------------------------------
    # PHI Encryption helpers
    # ------------------------------------------------------------------

    def encrypt_phi_field(self, value: str) -> str:
        """
        Encrypt a PHI field value.

        Delegates to PHIEncryption. Raises RuntimeError if the encryption
        key is not configured.
        """
        enc = PHIEncryption()
        return enc.encrypt(value)

    def decrypt_phi_field(self, value: str) -> str:
        """
        Decrypt a PHI field value.

        Delegates to PHIEncryption. Raises ValueError on decryption failure.
        """
        enc = PHIEncryption()
        return enc.decrypt(value)

    # ------------------------------------------------------------------
    # Data Residency
    # ------------------------------------------------------------------

    def check_data_residency(self, region: str) -> bool:
        """
        Validate that a region is in the HIPAA-allowed regions list.

        Args:
            region: AWS region string, e.g. "us-east-1".

        Returns:
            True if the region is allowed, False otherwise.
        """
        return region in settings.HIPAA_ALLOWED_REGIONS

    # ------------------------------------------------------------------
    # HIPAA Status
    # ------------------------------------------------------------------

    def get_hipaa_status(self, db: Session) -> Dict[str, Any]:
        """
        Return a HIPAA readiness status summary.

        Returns:
            Dict compatible with HIPAAStatusResponse schema.
        """
        # Check active BAA
        has_active_baa = (
            db.query(BAAConfig).filter(BAAConfig.is_active.is_(True)).count() > 0
        )

        # Check PHI encryption key is configured
        phi_encryption_configured = bool(settings.PHI_ENCRYPTION_KEY)

        # Audit logging is always enabled when HIPAA service is active
        audit_logging_enabled = True

        # Data residency is configured when HIPAA_ALLOWED_REGIONS is non-empty
        data_residency_configured = len(settings.HIPAA_ALLOWED_REGIONS) > 0

        overall_hipaa_ready = (
            has_active_baa
            and phi_encryption_configured
            and audit_logging_enabled
            and data_residency_configured
        )

        return {
            "has_active_baa": has_active_baa,
            "phi_encryption_configured": phi_encryption_configured,
            "audit_logging_enabled": audit_logging_enabled,
            "data_residency_configured": data_residency_configured,
            "overall_hipaa_ready": overall_hipaa_ready,
        }
