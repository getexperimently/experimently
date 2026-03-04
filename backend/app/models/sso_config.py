"""SSOConfig model — stores SSO/SAML and OIDC provider configuration per organization."""
import uuid
import enum
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text, Index, UniqueConstraint
from sqlalchemy import Enum as SQLAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from backend.app.models.base import Base
from backend.app.core.database_config import get_schema_name


class SSOProviderType(str, enum.Enum):
    SAML = "saml"
    GOOGLE = "google"
    GITHUB = "github"
    MICROSOFT = "microsoft"
    OKTA = "okta"
    AZURE_AD = "azure_ad"
    ONELOGIN = "onelogin"


class SSOConfig(Base):
    """SSO configuration for an organization (SAML 2.0 or OIDC/OAuth2)."""

    __tablename__ = "sso_configs"
    __table_args__ = (
        Index("ix_sso_configs_org_domain", "org_domain"),
        Index("ix_sso_configs_provider_type", "provider_type"),
        UniqueConstraint("org_domain", name="uq_sso_configs_org_domain"),
        {"schema": get_schema_name()},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Organization info
    org_name = Column(String(255), nullable=False)
    org_domain = Column(String(255), nullable=False)  # e.g. "acme.com"

    # Provider type
    provider_type = Column(SQLAEnum(SSOProviderType), nullable=False)

    # Common fields (used for both SAML and OIDC)
    # For SAML: entity_id = SP/IdP entity ID
    # For OIDC: entity_id = client_id
    entity_id = Column(String(1024), nullable=True)

    # For SAML: IdP SSO URL
    # For OIDC: issuer URL / authorization endpoint base
    sso_url = Column(String(2048), nullable=True)

    # SAML-specific fields
    x509_certificate = Column(Text, nullable=True)  # IdP signing certificate (PEM)

    # OIDC-specific fields
    client_secret = Column(String(1024), nullable=True)  # Encrypted in production

    # Role mapping: {"admin-group": "ADMIN", "dev-group": "DEVELOPER"}
    role_mapping = Column(JSONB, nullable=True, default={})

    # Behavior
    is_enforced = Column(Boolean, default=False, nullable=False)  # Block password login when True
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<SSOConfig org={self.org_name!r} provider={self.provider_type}>"
