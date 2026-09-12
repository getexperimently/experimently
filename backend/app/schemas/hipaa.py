"""
Pydantic schemas for EP-050: HIPAA Compliance.

Covers PHI audit logging, BAA configuration management,
HIPAA status reporting, and PHI encryption/decryption operations.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

# ---------------------------------------------------------------------------
# PHI Audit Log Schemas
# ---------------------------------------------------------------------------


class PHIAuditLogCreate(BaseModel):
    """Schema for creating a PHI audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    action: str
    phi_fields_accessed: List[str]
    purpose: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        allowed = {"READ", "WRITE", "DELETE", "EXPORT"}
        if v.upper() not in allowed:
            raise ValueError(f"action must be one of {allowed}")
        return v.upper()

    @field_validator("purpose")
    @classmethod
    def validate_purpose(cls, v: str) -> str:
        allowed = {"treatment", "operations", "research"}
        if v.lower() not in allowed:
            raise ValueError(f"purpose must be one of {allowed}")
        return v.lower()

    @field_validator("resource_type")
    @classmethod
    def validate_resource_type(cls, v: str) -> str:
        allowed = {"experiment", "feature_flag", "user_data"}
        if v.lower() not in allowed:
            raise ValueError(f"resource_type must be one of {allowed}")
        return v.lower()


class PHIAuditLogResponse(BaseModel):
    """Schema for returning a PHI audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    action: str
    phi_fields_accessed: List[str]
    purpose: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: datetime
    retention_years: int


class PHIAuditLogListResponse(BaseModel):
    """Schema for paginated PHI audit log list."""

    model_config = ConfigDict(from_attributes=True)

    items: List[PHIAuditLogResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# BAA Configuration Schemas
# ---------------------------------------------------------------------------


class BAAConfigCreate(BaseModel):
    """Schema for creating a Business Associate Agreement configuration."""

    model_config = ConfigDict(from_attributes=True)

    organization_name: str
    signatory_name: str
    signatory_email: EmailStr
    effective_date: date
    expiry_date: Optional[date] = None
    data_residency_region: str
    phi_categories: List[str]
    signed_document_hash: str

    @field_validator("phi_categories")
    @classmethod
    def validate_phi_categories(cls, v: List[str]) -> List[str]:
        allowed = {"demographics", "diagnosis", "treatment", "billing"}
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"Invalid PHI categories: {invalid}. Allowed: {allowed}")
        return v

    @field_validator("phi_categories")
    @classmethod
    def phi_categories_not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("phi_categories must contain at least one category")
        return v


class BAAConfigResponse(BaseModel):
    """Schema for returning a BAA configuration."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_name: str
    signatory_name: str
    signatory_email: str
    effective_date: date
    expiry_date: Optional[date] = None
    data_residency_region: str
    phi_categories: List[str]
    is_active: bool
    signed_document_hash: str
    created_at: datetime
    created_by: uuid.UUID

    @property
    def is_expired(self) -> bool:
        """Check if BAA has expired."""
        if self.expiry_date is None:
            return False
        return self.expiry_date < date.today()


# ---------------------------------------------------------------------------
# HIPAA Report Schema
# ---------------------------------------------------------------------------


class HIPAAReportResponse(BaseModel):
    """Schema for HIPAA compliance report."""

    model_config = ConfigDict(from_attributes=True)

    total_phi_access_events: int
    access_by_purpose: Dict[str, int]
    access_by_resource_type: Dict[str, int]
    unique_users_accessing_phi: int
    potential_violations: List[Dict[str, Any]]
    baa_coverage: Dict[str, Any]
    report_period_start: Optional[str] = None
    report_period_end: Optional[str] = None


# ---------------------------------------------------------------------------
# HIPAA Status Schema
# ---------------------------------------------------------------------------


class HIPAAStatusResponse(BaseModel):
    """Schema for HIPAA readiness status check."""

    model_config = ConfigDict(from_attributes=True)

    has_active_baa: bool
    phi_encryption_configured: bool
    audit_logging_enabled: bool
    data_residency_configured: bool
    overall_hipaa_ready: bool


# ---------------------------------------------------------------------------
# PHI Encrypt / Decrypt Schemas
# ---------------------------------------------------------------------------


class PHIEncryptRequest(BaseModel):
    """Schema for encrypting a PHI field value."""

    field: str
    value: str


class PHIEncryptResponse(BaseModel):
    """Schema for the encrypted PHI field response."""

    field: str
    ciphertext: str


class PHIDecryptRequest(BaseModel):
    """Schema for decrypting a PHI field value."""

    field: str
    ciphertext: str


class PHIDecryptResponse(BaseModel):
    """Schema for the decrypted PHI field response."""

    field: str
    plaintext: str


# ---------------------------------------------------------------------------
# Data Residency Schema
# ---------------------------------------------------------------------------


class DataResidencyResponse(BaseModel):
    """Schema for data residency configuration response."""

    model_config = ConfigDict(from_attributes=True)

    allowed_regions: List[str]
    current_region: str
    hipaa_enabled: bool
