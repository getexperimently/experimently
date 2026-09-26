"""
SSO/SAML & OIDC authentication endpoints — EP-037.

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

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.core.security import create_local_access_token
from backend.app.models.user import User, UserRole
from modules.backend.app.models.sso_config import SSOConfig, SSOProviderType
from modules.backend.app.services import sso_service

router = APIRouter()

#: The login flow: SP metadata, the SAML ACS and the OIDC login/callback.
#: Reached by a browser that has no session yet, so it carries no user
#: authentication; the registration mounts it behind nothing.  The
#: configuration CRUD stays on `router`, which is mounted behind
#: authentication.
public_router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class SSOConfigCreate(BaseModel):
    """Schema for creating a new SSO configuration."""

    org_name: str = Field(..., description="Human-readable organization name")
    org_domain: str = Field(
        ..., description="Organization email domain (e.g. acme.com)"
    )
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
    import jwt

    payload = {
        "sub": str(user.id),
        "email": user.email,
        "username": user.username,
        "role": user.role.value if user.role else "viewer",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow()
        + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token


def _get_redirect_uri(
    request: Request, provider: str, config_id: Optional[str] = None
) -> str:
    """Build the OIDC callback redirect URI.

    From ``PUBLIC_BASE_URL`` when it is set, and only then from the request.

    ``request.base_url`` is the scheme and the ``Host`` header, and both halves
    are client-controlled: ``Host`` on any path that reaches the app, and the
    scheme through ``X-Forwarded-Proto`` for as long as uvicorn is started with
    a permissive ``--forwarded-allow-ips`` (#237). This is the value an
    authorization code comes back to, so a crafted ``Host`` steered the code to
    an attacker's host -- authorization-code interception, #220.

    ``ALLOWED_HOSTS`` now refuses a foreign ``Host`` before this function is
    reached, so this is the second of two locks rather than the only one. It is
    still worth having: it is the difference between "no host we do not accept"
    and "exactly one host, the one we published to the IdP" -- and an OIDC
    ``redirect_uri`` must match the IdP's registration EXACTLY, so deriving it
    from whichever of several accepted hosts a particular request happened to
    use is a bug even with no attacker present.

    It also fixes the ordinary case behind a TLS-terminating proxy, where the
    request's own scheme is ``http`` and every absolute URL built from it is
    wrong in a way no test that talks to the app directly would show.
    """
    base = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    return f"{base}/api/v1/auth/sso/oidc/{provider}/callback"


def _active_saml_config(db: Session, config_id: uuid.UUID) -> SSOConfig:
    """The SAML config *config_id* names, or raise.

    ``is_active`` is checked here because it is the only administrative
    off-switch these two routes have: an operator whose IdP is compromised
    flips it false and expects the assertion consumer to stop minting
    platform sessions.  Both routes used to read the row and ignore the
    flag, so only deleting it stopped them -- and the metadata document kept
    advertising the ACS of a provider the operator had just disabled.

    A disabled config answers **404**, the same status (and the same shape of
    answer) the two OIDC routes already give for this exact condition: "no
    *active* config found".  A disabled provider is not there to serve you,
    and a scanner cannot tell "disabled" from "deleted" by status alone; the
    detail line names the difference for the operator reading their own logs,
    which costs nothing -- the row's existence is not a secret (the metadata
    it serves is a public document) and config ids are v4 UUIDs.
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
    if not config.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SSO config '{config_id}' is not active",
        )
    return config


# ---------------------------------------------------------------------------
# SAML endpoints
# ---------------------------------------------------------------------------


@public_router.get(
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
    config = _active_saml_config(db, config_id)
    xml = sso_service.generate_saml_metadata(config)
    return Response(content=xml, media_type="application/xml")


@public_router.post(
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
    config = _active_saml_config(db, config_id)

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


def _set_state_cookie(response: Response, value: str, max_age: int) -> None:
    """The login's state cookie; `max_age=0` with an empty value expires it.

    `Secure` even on `http://localhost`: the `__Host-` prefix requires it, and
    browsers treat localhost as a secure context. `SameSite=Lax`, because the
    callback is a top-level GET arriving from the identity provider's site --
    `Strict` would not send it.
    """
    response.set_cookie(
        sso_service.OIDC_STATE_COOKIE,
        value,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _expiring_state_cookie_header() -> str:
    """The `Set-Cookie` value that expires the state cookie, for an error response."""
    scratch = Response()
    _set_state_cookie(scratch, "", 0)
    return scratch.headers["set-cookie"]


@public_router.get(
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
    """Redirect the browser to the provider, holding the login's state in a cookie."""
    sso_service.require_supported_provider(provider)
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

    started = sso_service.start_oidc_login(config, provider)
    redirect_uri = _get_redirect_uri(request, provider)
    auth_url = sso_service.build_oidc_authorization_url(
        config, provider, redirect_uri, started.state, started.code_verifier
    )

    response = RedirectResponse(url=auth_url, status_code=302)
    _set_state_cookie(
        response, started.cookie_value, sso_service.OIDC_STATE_TTL_SECONDS
    )
    return response


@public_router.get(
    "/oidc/{provider}/callback",
    response_model=OIDCLoginResponse,
    summary="OIDC callback",
    tags=["sso"],
)
async def oidc_callback(
    provider: str,
    request: Request,
    response: Response,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: Session = Depends(deps.get_db),
) -> OIDCLoginResponse:
    """Finish a login this browser started: redeem the code, provision the user.

    Every outcome expires the state cookie, so a login is redeemable once from
    this browser; the provider refuses a second use of the code.
    """
    try:
        result = await _finish_oidc_login(provider, request, code, state, error, db)
    except HTTPException as exc:
        headers = dict(exc.headers or {})
        headers["set-cookie"] = _expiring_state_cookie_header()
        raise HTTPException(
            status_code=exc.status_code, detail=exc.detail, headers=headers
        ) from None
    _set_state_cookie(response, "", 0)
    return result


async def _finish_oidc_login(
    provider: str,
    request: Request,
    code: Optional[str],
    state: Optional[str],
    error: Optional[str],
    db: Session,
) -> OIDCLoginResponse:
    sso_service.require_supported_provider(provider)
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

    # The state must be the one in the cookie this browser was given when it
    # started the login (#66). A state alone proves nothing -- anyone can start
    # a login and get one -- so a callback from any other browser, including
    # one carrying an attacker's own code and state, is refused here.
    login = sso_service.redeem_oidc_state(
        request.cookies.get(sso_service.OIDC_STATE_COOKIE), state
    )

    # The configuration the login was started for, not whichever active one
    # matches the provider name now.
    config = sso_service.get_sso_config_by_id(db, login.config_id)
    if (
        config is None
        or not config.is_active
        or config.provider_type.value != provider
        or login.provider != provider
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active SSO config found for provider '{provider}'",
        )

    redirect_uri = _get_redirect_uri(request, provider)
    token_data = await sso_service.exchange_oidc_code(
        config, code, redirect_uri, code_verifier=login.code_verifier
    )
    access_token = token_data.get("access_token", "")

    user_info = await sso_service.get_oidc_user_info(config, access_token)
    user = sso_service.provision_user(db, user_info, config)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )

    return OIDCLoginResponse(
        # The same token a password login issues, so every auth path accepts it.
        access_token=create_local_access_token(user),
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
