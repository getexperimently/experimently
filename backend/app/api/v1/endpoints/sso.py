"""
SSO/SAML & OIDC Enterprise Authentication endpoints — EP-037.

Endpoints:
  GET  /auth/sso/saml/{config_id}/metadata  — SP metadata XML
  POST /auth/sso/saml/{config_id}/acs        — SAML Assertion Consumer Service
  GET  /auth/sso/oidc/{provider}/login       — Redirect to OIDC provider
  GET  /auth/sso/oidc/{provider}/callback    — OIDC callback / token issue
  GET  /auth/sso/configs                     — List SSO configs (admin)
  POST /auth/sso/configs                     — Create SSO config (admin)
  GET  /auth/sso/configs/{config_id}         — Get SSO config (admin)
  PUT  /auth/sso/configs/{config_id}         — Update SSO config (admin)
  DELETE /auth/sso/configs/{config_id}       — Delete SSO config (admin)

Note: the router is mounted at /api/v1/auth/sso in api.py, so the
endpoint paths below are relative to that prefix.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.models.sso_config import SSOConfig, SSOProviderType
from backend.app.models.user import User, UserRole
from backend.app.services import sso_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class SSOConfigCreate(BaseModel):
    """Schema for creating a new SSO configuration."""

    org_name: str = Field(..., description="Human-readable organization name")
    org_domain: str = Field(..., description="Organization email domain (e.g. acme.com)")
    provider_type: SSOProviderType
    entity_id: Optional[str] = Field(
        None, description="SAML Entity ID or OIDC client_id"
    )
    sso_url: Optional[str] = Field(
        None, description="IdP SSO URL (SAML) or OIDC issuer URL"
    )
    x509_certificate: Optional[str] = Field(
        None, description="SAML IdP signing certificate (PEM)"
    )
    client_secret: Optional[str] = Field(None, description="OIDC client secret")
    role_mapping: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description='Map IdP groups to roles: {"admin-group": "admin"}',
    )
    is_enforced: bool = Field(
        False,
        description="Block password login when True",
    )
    is_active: bool = Field(True)


class SSOConfigUpdate(BaseModel):
    """Schema for updating an existing SSO configuration."""

    org_name: Optional[str] = None
    org_domain: Optional[str] = None
    provider_type: Optional[SSOProviderType] = None
    entity_id: Optional[str] = None
    sso_url: Optional[str] = None
    x509_certificate: Optional[str] = None
    client_secret: Optional[str] = None
    role_mapping: Optional[Dict[str, str]] = None
    is_enforced: Optional[bool] = None
    is_active: Optional[bool] = None


class SSOConfigResponse(BaseModel):
    """Schema for returning SSO config data (secrets redacted)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_name: str
    org_domain: str
    provider_type: SSOProviderType
    entity_id: Optional[str]
    sso_url: Optional[str]
    x509_certificate: Optional[str]
    role_mapping: Optional[Dict[str, Any]]
    is_enforced: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SAMLLoginResponse(BaseModel):
    """Response after a successful SAML ACS callback."""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    role: str


class OIDCLoginResponse(BaseModel):
    """Response after a successful OIDC callback."""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    role: str
    provider: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_admin(current_user: User) -> User:
    """Raise 403 if the caller is not ADMIN or superuser."""
    if not current_user.is_superuser and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SSO configurations",
        )
    return current_user


def _issue_jwt(user: User) -> str:
    """Issue a simple JWT for the provisioned user.

    Uses the platform SECRET_KEY as the signing secret.  In production this
    should go through the same Cognito / token infrastructure as regular login.
    """
    from jose import jwt as jose_jwt

    payload = {
        "sub": str(user.id),
        "email": user.email,
        "username": user.username,
        "role": user.role.value if user.role else "viewer",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    token = jose_jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token


def _get_redirect_uri(request: Request, provider: str, config_id: Optional[str] = None) -> str:
    """Build the OIDC callback redirect URI."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/auth/sso/oidc/{provider}/callback"


# ---------------------------------------------------------------------------
# SAML endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/saml/{config_id}/metadata",
    response_class=Response,
    summary="SAML SP metadata",
    tags=["sso"],
)
def saml_metadata(
    config_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
) -> Response:
    """Return the Service-Provider metadata XML for the given SSO config."""
    config = sso_service.get_sso_config_by_id(db, config_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SSO config '{config_id}' not found",
        )
    if config.provider_type != SSOProviderType.SAML:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This SSO config is not a SAML provider",
        )
    xml = sso_service.generate_saml_metadata(config)
    return Response(content=xml, media_type="application/xml")


@router.post(
    "/saml/{config_id}/acs",
    response_model=SAMLLoginResponse,
    summary="SAML Assertion Consumer Service",
    tags=["sso"],
)
def saml_acs(
    config_id: uuid.UUID,
    SAMLResponse: Optional[str] = Form(None),
    db: Session = Depends(deps.get_db),
) -> SAMLLoginResponse:
    """Receive and process a SAML assertion from the IdP.

    On success, provisions/updates the user and returns a JWT.
    """
    config = sso_service.get_sso_config_by_id(db, config_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SSO config '{config_id}' not found",
        )
    if config.provider_type != SSOProviderType.SAML:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This SSO config is not a SAML provider",
        )

    saml_response_b64 = SAMLResponse
    if not saml_response_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SAMLResponse is required",
        )

    user_info = sso_service.parse_saml_response(config, saml_response_b64)
    user = sso_service.provision_user(db, user_info, config)
    token = _issue_jwt(user)

    return SAMLLoginResponse(
        access_token=token,
        user_id=str(user.id),
        email=user.email,
        role=user.role.value if user.role else "viewer",
    )


# ---------------------------------------------------------------------------
# OIDC endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/oidc/{provider}/login",
    summary="Initiate OIDC login",
    tags=["sso"],
)
async def oidc_login(
    provider: str,
    request: Request,
    org_domain: Optional[str] = Query(None, description="Org domain for config lookup"),
    db: Session = Depends(deps.get_db),
) -> RedirectResponse:
    """Redirect the user to the OIDC provider's authorization endpoint."""
    # Find config by provider type and optional org_domain
    configs = sso_service.list_sso_configs(db)
    config = None
    for c in configs:
        if c.provider_type.value == provider and c.is_active:
            if not org_domain or c.org_domain == org_domain:
                config = c
                break

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active SSO config found for provider '{provider}'",
        )

    state = sso_service.generate_state_token()
    redirect_uri = _get_redirect_uri(request, provider)
    auth_url = sso_service.build_oidc_authorization_url(config, provider, redirect_uri, state)

    return RedirectResponse(url=auth_url, status_code=302)


@router.get(
    "/oidc/{provider}/callback",
    response_model=OIDCLoginResponse,
    summary="OIDC callback",
    tags=["sso"],
)
async def oidc_callback(
    provider: str,
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    org_domain: Optional[str] = Query(None),
    db: Session = Depends(deps.get_db),
) -> OIDCLoginResponse:
    """Handle the OIDC callback: exchange code for tokens, fetch user info, provision user."""
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OIDC provider returned error: {error}",
        )

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code is required",
        )

    if state:
        sso_service.verify_state_token(state)

    # Find config
    configs = sso_service.list_sso_configs(db)
    config = None
    for c in configs:
        if c.provider_type.value == provider and c.is_active:
            if not org_domain or c.org_domain == org_domain:
                config = c
                break

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active SSO config found for provider '{provider}'",
        )

    redirect_uri = _get_redirect_uri(request, provider)
    token_data = await sso_service.exchange_oidc_code(config, code, redirect_uri)
    access_token = token_data.get("access_token", "")

    user_info = await sso_service.get_oidc_user_info(config, access_token)
    user = sso_service.provision_user(db, user_info, config)
    jwt_token = _issue_jwt(user)

    return OIDCLoginResponse(
        access_token=jwt_token,
        user_id=str(user.id),
        email=user.email,
        role=user.role.value if user.role else "viewer",
        provider=provider,
    )


# ---------------------------------------------------------------------------
# Admin CRUD endpoints for SSO configs
# ---------------------------------------------------------------------------


@router.get(
    "/configs",
    response_model=List[SSOConfigResponse],
    summary="List SSO configs",
    tags=["sso"],
)
def list_sso_configs(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> List[SSOConfigResponse]:
    """Return all SSO configurations. Admin only."""
    _require_admin(current_user)
    configs = sso_service.list_sso_configs(db)
    return [SSOConfigResponse.model_validate(c) for c in configs]


@router.post(
    "/configs",
    response_model=SSOConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create SSO config",
    tags=["sso"],
)
def create_sso_config(
    config_data: SSOConfigCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> SSOConfigResponse:
    """Create a new SSO configuration. Admin only."""
    _require_admin(current_user)
    data_dict = config_data.model_dump(exclude_none=False)
    sso_config = sso_service.create_sso_config(db, data_dict)
    return SSOConfigResponse.model_validate(sso_config)


@router.get(
    "/configs/{config_id}",
    response_model=SSOConfigResponse,
    summary="Get SSO config",
    tags=["sso"],
)
def get_sso_config(
    config_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> SSOConfigResponse:
    """Get a specific SSO configuration by ID. Admin only."""
    _require_admin(current_user)
    sso_config = sso_service.get_sso_config_by_id(db, config_id)
    if not sso_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SSO config '{config_id}' not found",
        )
    return SSOConfigResponse.model_validate(sso_config)


@router.put(
    "/configs/{config_id}",
    response_model=SSOConfigResponse,
    summary="Update SSO config",
    tags=["sso"],
)
def update_sso_config(
    config_id: uuid.UUID,
    update_data: SSOConfigUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> SSOConfigResponse:
    """Update an existing SSO configuration. Admin only."""
    _require_admin(current_user)
    data_dict = update_data.model_dump(exclude_none=True)
    sso_config = sso_service.update_sso_config(db, config_id, data_dict)
    return SSOConfigResponse.model_validate(sso_config)


@router.delete(
    "/configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete SSO config",
    tags=["sso"],
    response_model=None,
)
def delete_sso_config(
    config_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Response:
    """Delete an SSO configuration. Admin only."""
    _require_admin(current_user)
    deleted = sso_service.delete_sso_config(db, config_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SSO config '{config_id}' not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
