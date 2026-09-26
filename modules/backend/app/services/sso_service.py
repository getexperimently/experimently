"""
SSO Service — EP-037 SSO/SAML & OIDC authentication.

Provides helpers for:
  - CRUD operations on SSOConfig records
  - SAML 2.0 SP metadata generation and assertion parsing
  - OIDC/OAuth2 authorization-code exchange and user-info fetch
  - Just-In-Time (JIT) user provisioning
  - Role mapping from IdP groups to platform roles
  - The OIDC login's state: a signed cookie binding the callback to the
    browser that started the login, carrying the PKCE verifier

SAML operations degrade to stub implementations when the ``python3-saml``
(onelogin) package is not installed, so the service remains importable in
CI/test environments that skip the optional dependency -- but the stub only
*runs* in development and test.  It reads the NameID out of the POSTed XML
without checking a signature, an issuer, an audience or an expiry, so anywhere
else a missing library is an error and every SAML route answers 501
(:func:`_require_saml_support`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse

# defusedxml guards against entity-expansion / external-entity attacks when
# parsing IdP-supplied SAML responses (Bandit B314, Semgrep use-defused-xml).
import jwt
from defusedxml import ElementTree as ET
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.core.config import settings as core_settings
from backend.app.models.user import User, UserRole
from modules.backend.app.models.sso_config import SSOConfig
from modules.backend.app.settings import settings

# Optional: python3-saml
try:
    from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore
    from onelogin.saml2.settings import OneLogin_Saml2_Settings  # type: ignore

    _SAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    OneLogin_Saml2_Auth = None  # type: ignore
    OneLogin_Saml2_Settings = None  # type: ignore
    _SAML_AVAILABLE = False

# Optional: authlib
try:
    from authlib.integrations.httpx_client import AsyncOAuth2Client  # type: ignore

    _AUTHLIB_AVAILABLE = True
except ImportError:  # pragma: no cover
    AsyncOAuth2Client = None  # type: ignore
    _AUTHLIB_AVAILABLE = False

logger = logging.getLogger(__name__)

#: Refusal used by every SAML route when ``python3-saml`` is not installed and
#: the environment is not one where the stub may stand in for it.  501 is the
#: same "this deployment does not have it" answer the core gives for a
#: capability no module registered (``backend/app/core/optional_modules.py``).
SAML_NOT_INSTALLED_DETAIL = (
    "SAML single sign-on is not available in this deployment: the optional "
    "'python3-saml' dependency is not installed, and without it assertions "
    "cannot be validated. Install python3-saml (it needs the system xmlsec1 "
    "and libxml2 libraries) and restart the API."
)


def saml_stub_allowed() -> bool:
    """Whether the signature-blind SAML stub below may stand in for the library.

    ``development`` and ``test`` only -- the allow-list
    ``settings.dev_fallbacks_allowed`` shares with the dev-admin auth bypass,
    read from the *core* settings singleton (the modules' settings only mirror
    ``ENVIRONMENT``).  Asked at call time rather than at import so a test can
    move the environment, and asked as a named allow-list rather than
    ``ENVIRONMENT == "production"`` so staging is hardened too and an
    unrecognised environment name fails closed.
    """
    return bool(core_settings.dev_fallbacks_allowed)


def _require_saml_support() -> None:
    """Raise 501 when neither python3-saml nor the stub may serve this request.

    The stub is a development convenience that reads the NameID out of the
    POSTed XML: it checks no signature, no issuer, no audience and no expiry,
    so an unauthenticated caller who knows an administrator's email address
    could mint a session with a SAML response they wrote themselves.  Anywhere
    but development and test, a missing library is an error, never a fallback.
    """
    if _SAML_AVAILABLE:
        return
    if saml_stub_allowed():
        logger.warning(
            "python3-saml is not installed; serving SAML with the stub parser, "
            "which does NOT validate assertion signatures. ENVIRONMENT=%s.",
            core_settings.ENVIRONMENT,
        )
        return
    logger.error(
        "Refusing a SAML request: python3-saml is not installed and "
        "ENVIRONMENT=%s does not permit the unvalidating stub parser.",
        core_settings.ENVIRONMENT,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=SAML_NOT_INSTALLED_DETAIL,
    )


# ---------------------------------------------------------------------------
# OIDC provider discovery metadata
# ---------------------------------------------------------------------------

_OIDC_PROVIDERS: Dict[str, Dict[str, str]] = {
    "google": {
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "authorization_endpoint": "https://github.com/login/oauth/authorize",
        "token_endpoint": "https://github.com/login/oauth/access_token",
        "userinfo_endpoint": "https://api.github.com/user",
        "scope": "read:user user:email",
    },
    "microsoft": {
        "authorization_endpoint": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_endpoint": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
        "scope": "openid email profile",
    },
    "okta": {
        "authorization_endpoint": "{sso_url}/v1/authorize",
        "token_endpoint": "{sso_url}/v1/token",
        "userinfo_endpoint": "{sso_url}/v1/userinfo",
        "scope": "openid email profile groups",
    },
    "azure_ad": {
        "authorization_endpoint": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_endpoint": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
        "scope": "openid email profile",
    },
    "onelogin": {
        "authorization_endpoint": "https://{subdomain}.onelogin.com/oidc/2/auth",
        "token_endpoint": "https://{subdomain}.onelogin.com/oidc/2/token",
        "userinfo_endpoint": "https://{subdomain}.onelogin.com/oidc/2/me",
        "scope": "openid email profile groups",
    },
}


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def create_sso_config(db: Session, config_data: Dict[str, Any]) -> SSOConfig:
    """Create a new SSOConfig record.

    Raises:
        HTTPException 409 if an SSOConfig already exists for ``org_domain``.
        HTTPException 400 on validation failure.
    """
    org_domain = config_data.get("org_domain", "")
    if not org_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="org_domain is required",
        )

    existing = db.query(SSOConfig).filter(SSOConfig.org_domain == org_domain).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SSO config already exists for domain '{org_domain}'",
        )

    sso_config = SSOConfig(**config_data)
    db.add(sso_config)
    db.commit()
    db.refresh(sso_config)
    return sso_config


def get_sso_config(db: Session, org_domain: str) -> Optional[SSOConfig]:
    """Return the SSOConfig for the given *org_domain*, or ``None``."""
    return db.query(SSOConfig).filter(SSOConfig.org_domain == org_domain).first()


def get_sso_config_by_id(db: Session, config_id: uuid.UUID) -> Optional[SSOConfig]:
    """Return the SSOConfig with the given *config_id*, or ``None``."""
    return db.query(SSOConfig).filter(SSOConfig.id == config_id).first()


def list_sso_configs(db: Session) -> List[SSOConfig]:
    """Return all SSOConfig records ordered by creation date."""
    return db.query(SSOConfig).order_by(SSOConfig.created_at).all()


def update_sso_config(
    db: Session,
    config_id: uuid.UUID,
    data: Dict[str, Any],
) -> SSOConfig:
    """Update an existing SSOConfig.

    Raises:
        HTTPException 404 if not found.
        HTTPException 409 if the new org_domain conflicts with another record.
    """
    sso_config = get_sso_config_by_id(db, config_id)
    if not sso_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SSO config '{config_id}' not found",
        )

    # Check domain uniqueness if it is being changed
    new_domain = data.get("org_domain")
    if new_domain and new_domain != sso_config.org_domain:
        conflict = (
            db.query(SSOConfig)
            .filter(SSOConfig.org_domain == new_domain, SSOConfig.id != config_id)
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"SSO config already exists for domain '{new_domain}'",
            )

    for key, value in data.items():
        setattr(sso_config, key, value)

    db.commit()
    db.refresh(sso_config)
    return sso_config


def delete_sso_config(db: Session, config_id: uuid.UUID) -> bool:
    """Delete an SSOConfig.

    Returns:
        True if deleted, False if not found.
    """
    sso_config = get_sso_config_by_id(db, config_id)
    if not sso_config:
        return False
    db.delete(sso_config)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# SAML helpers
# ---------------------------------------------------------------------------


def generate_saml_metadata(config: SSOConfig) -> str:
    """Generate Service-Provider (SP) metadata XML for the given SSOConfig.

    When the *python3-saml* library is available it delegates to
    ``OneLogin_Saml2_Settings``; in development and test it falls back to
    minimal XML so the endpoint works without the optional dependency.

    Raises:
        HTTPException 501 when the library is missing outside development/test.
        Metadata is the document that tells an IdP where to POST assertions,
        and a deployment that cannot validate one has no business advertising
        an ACS endpoint -- ``/saml/{id}/acs`` answers 501 there too.
    """
    _require_saml_support()
    sp_entity_id = getattr(
        settings, "SAML_SP_ENTITY_ID", "https://experimently.example.com"
    )
    sp_acs_url = getattr(
        settings,
        "SAML_SP_ACS_URL",
        f"https://experimently.example.com/api/v1/auth/sso/saml/{config.id}/acs",
    )

    if _SAML_AVAILABLE and OneLogin_Saml2_Settings is not None:
        saml_settings: Dict[str, Any] = {
            "sp": {
                "entityId": sp_entity_id,
                "assertionConsumerService": {
                    "url": sp_acs_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                },
                "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            },
            "idp": {
                "entityId": config.entity_id or "",
                "singleSignOnService": {
                    "url": config.sso_url or "",
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "x509cert": config.x509_certificate or "",
            },
            "strict": False,
            "debug": False,
        }
        try:
            settings_obj = OneLogin_Saml2_Settings(saml_settings)
            return settings_obj.get_sp_metadata()
        except Exception as exc:
            logger.warning("python3-saml metadata generation failed: %s", exc)

    # Fallback: minimal SP metadata XML
    return _build_minimal_sp_metadata(config, sp_entity_id, sp_acs_url)


def _build_minimal_sp_metadata(
    config: SSOConfig, sp_entity_id: str, sp_acs_url: str
) -> str:
    """Build a minimal SAML 2.0 SP metadata XML string without external libraries."""
    return (
        '<?xml version="1.0"?>\n'
        '<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"\n'
        f'  entityID="{sp_entity_id}">\n'
        "  <md:SPSSODescriptor\n"
        '    AuthnRequestsSigned="false"\n'
        '    WantAssertionsSigned="true"\n'
        '    protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">\n'
        "    <md:AssertionConsumerService\n"
        '      Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"\n'
        f'      Location="{sp_acs_url}"\n'
        '      index="1"/>\n'
        "  </md:SPSSODescriptor>\n"
        "</md:EntityDescriptor>"
    )


def parse_saml_response(config: SSOConfig, saml_response_b64: str) -> Dict[str, Any]:
    """Parse and validate a base-64-encoded SAML response.

    Returns a ``user_info`` dict with at minimum:
      - ``email``
      - ``name_id``
      - ``attributes`` (raw IdP attributes dict)
      - ``groups`` (list of group/role strings if present)

    Raises:
        HTTPException 400 for invalid/expired assertions.
        HTTPException 401 for signature validation failures.
        HTTPException 501 when *python3-saml* is not installed and the
        environment does not permit the stub parser (see
        :func:`_require_saml_support`).
    """
    if not saml_response_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SAML response is required",
        )

    if _SAML_AVAILABLE and OneLogin_Saml2_Auth is not None:
        return _parse_saml_response_with_library(config, saml_response_b64)

    # Stub implementation used when python3-saml is not installed.  It
    # validates nothing, so it may only run where _require_saml_support()
    # permits it; everywhere else this raises 501 instead.
    _require_saml_support()
    return _parse_saml_response_stub(config, saml_response_b64)


def _parse_saml_response_with_library(
    config: SSOConfig, saml_response_b64: str
) -> Dict[str, Any]:
    """Parse SAML response using the python3-saml library."""
    sp_entity_id = getattr(
        settings, "SAML_SP_ENTITY_ID", "https://experimently.example.com"
    )
    sp_acs_url = getattr(
        settings,
        "SAML_SP_ACS_URL",
        f"https://experimently.example.com/api/v1/auth/sso/saml/{config.id}/acs",
    )

    saml_settings_dict: Dict[str, Any] = {
        "sp": {
            "entityId": sp_entity_id,
            "assertionConsumerService": {
                "url": sp_acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
        },
        "idp": {
            "entityId": config.entity_id or "",
            "singleSignOnService": {
                "url": config.sso_url or "",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": config.x509_certificate or "",
        },
        "strict": True,
        "debug": False,
    }

    # Build a minimal request dict that OneLogin_Saml2_Auth expects
    request_data = {
        "https": "on",
        "http_host": urlparse(sp_acs_url).netloc,
        "server_port": "443",
        "script_name": urlparse(sp_acs_url).path,
        "get_data": {},
        "post_data": {"SAMLResponse": saml_response_b64},
    }

    try:
        auth = OneLogin_Saml2_Auth(request_data, saml_settings_dict)
        auth.process_response()
        errors = auth.get_errors()
        if errors:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"SAML validation failed: {', '.join(errors)}",
            )
        if not auth.is_authenticated():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SAML authentication failed",
            )
        attributes = auth.get_attributes()
        name_id = auth.get_nameid()
        email = (
            name_id
            if "@" in (name_id or "")
            else (
                attributes.get("email", [None])[0]
                or attributes.get(
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                    [None],
                )[0]
                or name_id
            )
        )
        groups = attributes.get("groups", []) or attributes.get(
            "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups", []
        )
        first_name = (attributes.get("firstName", [None]) or [None])[0]
        last_name = (attributes.get("lastName", [None]) or [None])[0]

        return {
            "email": email,
            "name_id": name_id,
            "attributes": attributes,
            "groups": groups,
            "first_name": first_name,
            "last_name": last_name,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("SAML parsing error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse SAML response: {exc}",
        )


def _parse_saml_response_stub(
    config: SSOConfig, saml_response_b64: str
) -> Dict[str, Any]:
    """Minimal stub parser used in test environments without python3-saml.

    Attempts to decode the base-64 payload as XML and extract a NameID/email.
    If the payload is not valid XML, raises 400.

    The stub treats a NameID starting with ``"invalid"`` or ``"expired"``
    as an error condition (used in unit tests).

    **This function trusts its input completely**: no signature, issuer,
    audience or expiry is checked, so whoever POSTs the assertion chooses the
    email it provisions.  It is reachable only through
    :func:`_require_saml_support`, which permits it in development and test and
    answers 501 everywhere else.  Never call it directly.
    """
    import base64

    try:
        xml_bytes = base64.b64decode(saml_response_b64)
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot decode SAML response: {exc}",
        )

    # Find NameID
    ns = {
        "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
        "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    }
    name_id_el = root.find(".//saml:NameID", ns)
    name_id = name_id_el.text if name_id_el is not None else None

    if name_id and name_id.startswith("invalid"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid SAML assertion signature",
        )
    if name_id and name_id.startswith("expired"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SAML assertion has expired",
        )

    email = name_id
    return {
        "email": email,
        "name_id": name_id,
        "attributes": {},
        "groups": [],
        "first_name": None,
        "last_name": None,
    }


# ---------------------------------------------------------------------------
# OIDC helpers
# ---------------------------------------------------------------------------


_OAUTH_ERROR_CODE = re.compile(r"[a-z_]{1,64}")


def _idp_error_code(exc: BaseException) -> Optional[str]:
    """The OAuth ``error`` code a provider sent, if any -- never its free text.

    A failed exchange or userinfo call carries text the caller must not see: the
    provider's ``error_description``, the token URL, connection errors naming
    internal hosts. Only the standard error code (``invalid_grant``, ...) is
    passed on, and only if it looks like one.
    """
    code = getattr(exc, "error", None)
    if code is None:
        response = getattr(exc, "response", None)
        try:
            code = response.json().get("error") if response is not None else None
        except Exception:
            code = None
    if isinstance(code, str) and _OAUTH_ERROR_CODE.fullmatch(code):
        return code
    return None


def _refusal(what: str, exc: BaseException) -> HTTPException:
    code = _idp_error_code(exc)
    logger.error("%s: %s%s", what, type(exc).__name__, f" ({code})" if code else "")
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{what}" + (f" ({code})" if code else ""),
    )


async def exchange_oidc_code(
    config: SSOConfig,
    code: str,
    redirect_uri: str,
    *,
    code_verifier: str,
    http_client: Any = None,
) -> Dict[str, Any]:
    """Exchange an OAuth2 authorization code for tokens.

    ``code_verifier`` is the PKCE verifier from the login's state cookie; it
    is sent on every branch, so a code intercepted on its way back to the
    callback cannot be redeemed without it.

    ``http_client`` is an optional injected HTTP client (e.g. an
    ``httpx.AsyncClient`` mock) used in tests.  When ``None`` and authlib is
    available a fresh ``AsyncOAuth2Client`` is used; otherwise falls back to
    a synchronous ``requests`` call.

    Returns the token response dict (access_token, id_token, …).

    Raises:
        HTTPException 400 on error.
    """
    provider_key = config.provider_type.value
    meta = _OIDC_PROVIDERS.get(provider_key)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown OIDC provider '{provider_key}'",
        )

    token_url = meta["token_endpoint"]
    if "{sso_url}" in token_url and config.sso_url:
        token_url = token_url.replace("{sso_url}", config.sso_url.rstrip("/"))

    token_params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": config.entity_id or "",
        "client_secret": config.client_secret or "",
        "code_verifier": code_verifier,
    }

    try:
        if http_client is not None:
            # Injected mock client (used in tests)
            response = await http_client.post(token_url, data=token_params)
            if hasattr(response, "json"):
                return response.json()
            return response

        if _AUTHLIB_AVAILABLE and AsyncOAuth2Client is not None:
            async with AsyncOAuth2Client(
                client_id=config.entity_id or "",
                client_secret=config.client_secret or "",
            ) as client:
                token = await client.fetch_token(
                    token_url,
                    code=code,
                    redirect_uri=redirect_uri,
                    code_verifier=code_verifier,
                )
                return dict(token)

        # Fallback: synchronous requests (always available in stdlib-adjacent)
        import requests  # type: ignore

        # No redirects: a redirected POST would re-send the client secret to
        # wherever the redirect points.
        resp = requests.post(
            token_url, data=token_params, timeout=10, allow_redirects=False
        )
        if resp.is_redirect:
            raise requests.HTTPError("token endpoint redirected", response=resp)
        resp.raise_for_status()
        return resp.json()

    except HTTPException:
        raise
    except Exception as exc:
        raise _refusal("OIDC token exchange failed", exc) from None


async def get_oidc_user_info(
    config: SSOConfig,
    access_token: str,
    http_client: Any = None,
) -> Dict[str, Any]:
    """Fetch user info from the OIDC provider using the given access token.

    Returns a normalized ``user_info`` dict with at minimum:
      - ``email``
      - ``name`` (optional)
      - ``groups`` (list, may be empty)
      - ``sub`` (provider-specific user identifier)

    Raises:
        HTTPException 400 on error.
    """
    provider_key = config.provider_type.value
    meta = _OIDC_PROVIDERS.get(provider_key)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown OIDC provider '{provider_key}'",
        )

    userinfo_url = meta["userinfo_endpoint"]
    if "{sso_url}" in userinfo_url and config.sso_url:
        userinfo_url = userinfo_url.replace("{sso_url}", config.sso_url.rstrip("/"))

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        if http_client is not None:
            response = await http_client.get(userinfo_url, headers=headers)
            if hasattr(response, "json"):
                raw = response.json()
            else:
                raw = response
        elif _AUTHLIB_AVAILABLE and AsyncOAuth2Client is not None:
            async with AsyncOAuth2Client(
                token={"access_token": access_token}
            ) as client:
                resp = await client.get(userinfo_url)
                resp.raise_for_status()  # an error body is not user info
                raw = resp.json()
        else:
            import requests  # type: ignore

            resp = requests.get(
                userinfo_url, headers=headers, timeout=10, allow_redirects=False
            )
            if resp.is_redirect:
                raise requests.HTTPError("userinfo endpoint redirected", response=resp)
            resp.raise_for_status()
            raw = resp.json()

        return _normalize_userinfo(provider_key, raw)

    except HTTPException:
        raise
    except Exception as exc:
        raise _refusal("OIDC userinfo fetch failed", exc) from None


def _normalize_userinfo(provider_key: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize provider-specific user-info into a common dict."""
    # Extract email from various provider-specific fields
    email = raw.get("email") or ""
    if not email and isinstance(raw.get("emails"), list):
        emails_list = raw.get("emails", [])
        if emails_list and isinstance(emails_list[0], dict):
            email = emails_list[0].get("value", "")
        elif emails_list and isinstance(emails_list[0], str):
            email = emails_list[0]

    name = raw.get("name") or raw.get("login") or raw.get("displayName") or ""
    sub = str(raw.get("sub") or raw.get("id") or raw.get("login") or "")
    groups = raw.get("groups", []) or []

    return {
        "email": email,
        "name": name,
        "sub": sub,
        "groups": groups,
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# User provisioning
# ---------------------------------------------------------------------------


#: Providers whose sign-in is refused until they are supported properly.
UNSUPPORTED_OIDC_PROVIDERS = frozenset({"microsoft", "azure_ad", "onelogin"})

UNSUPPORTED_PROVIDER_DETAIL = "This single sign-on provider is not supported yet"
EMAIL_INVALID_DETAIL = "SSO assertion did not contain a valid email address"
EMAIL_DOMAIN_DETAIL = (
    "This account's email is not in the domain this single sign-on is configured for"
)
EMAIL_AMBIGUOUS_DETAIL = (
    "More than one account matches this email address; ask an administrator"
)


def require_supported_provider(provider: str) -> None:
    """Refuse, with a fixed 400, a provider on the unsupported list."""
    if provider in UNSUPPORTED_OIDC_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UNSUPPORTED_PROVIDER_DETAIL,
        )


def normalise_domain(value: Optional[str]) -> str:
    """``org_domain`` as compared: stripped, lower-cased, no leading ``@``."""
    return (value or "").strip().lstrip("@").lower()


def _sso_email(user_info: Dict[str, Any], config: SSOConfig) -> str:
    """The email a sign-in may use: well-formed, ASCII, in the config's domain.

    ASCII is checked before lower-casing: ``str.lower`` folds some non-ASCII
    characters into ASCII ones (U+212A KELVIN SIGN becomes ``k``), which would
    let an address that is not in the domain compare equal to one that is.
    """
    raw = user_info.get("email")
    email = raw.strip() if isinstance(raw, str) else ""
    if not email or not email.isascii():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=EMAIL_INVALID_DETAIL
        )
    email = email.lower()
    local, _, domain = email.rpartition("@")
    if not local or not domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=EMAIL_INVALID_DETAIL
        )
    expected = normalise_domain(config.org_domain)
    if not expected or domain != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=EMAIL_DOMAIN_DETAIL
        )
    return email


def provision_user(
    db: Session,
    user_info: Dict[str, Any],
    config: SSOConfig,
) -> User:
    """Find or create (JIT provision) a User from SSO user_info.

    - The email must be in the configuration's ``org_domain``, exactly (no
      subdomains): one configuration per domain.
    - Looks the user up by email, case-insensitively; more than one match is
      refused rather than guessed.
    - An existing user's role changes only when one of their groups matches
      the configuration's ``role_mapping``. A sign-in with no matching group
      leaves the role as it is; to demote someone through SSO, map one of
      their groups to ``viewer``. ``is_superuser`` is never changed.
    - A new user gets the mapped role, or ``viewer``.

    Returns the existing or newly-created User object.
    """
    email = _sso_email(user_info, config)
    groups = user_info.get("groups", []) or []
    mapped = mapped_role(config, groups)

    matches = db.query(User).filter(func.lower(User.email) == email).limit(2).all()
    if len(matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=EMAIL_AMBIGUOUS_DETAIL
        )
    if matches:
        existing_user = matches[0]
        if mapped is not None:
            existing_user.role = UserRole(mapped)
            db.commit()
            db.refresh(existing_user)
        return existing_user

    # JIT provisioning
    role = UserRole(mapped) if mapped else UserRole.VIEWER

    # Derive a username from email local part + random suffix to avoid collisions
    local_part = email.split("@")[0].replace(".", "_").replace("+", "_")[:40]
    username = f"{local_part}_{uuid.uuid4().hex[:8]}"

    raw = user_info.get("raw") or {}
    name_parts = (user_info.get("name") or "").split()
    first_name = (
        user_info.get("first_name")
        or raw.get("given_name")
        or (name_parts[0] if name_parts else None)
    )
    last_name = (
        user_info.get("last_name")
        or raw.get("family_name")
        or (" ".join(name_parts[1:]) if len(name_parts) > 1 else None)
    )

    new_user = User(
        username=username,
        email=email,
        hashed_password=None,  # No password for SSO users
        is_active=True,
        is_superuser=False,
        role=role,
        first_name=first_name,
        last_name=last_name,
        external_id=user_info.get("sub") or user_info.get("name_id"),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


def mapped_role(config: SSOConfig, groups: List[str]) -> Optional[str]:
    """The role the first group with a mapping maps to, or ``None`` if none does."""
    mapping: Dict[str, str] = config.role_mapping or {}
    for group in groups or []:
        role = mapping.get(group)
        if role:
            return role.lower()
    return None


def map_role(config: SSOConfig, groups: List[str]) -> str:
    """Map a list of IdP group names to a platform role string.

    The ``role_mapping`` JSONB on ``SSOConfig`` maps group names to role strings,
    e.g. ``{"admins": "admin", "devs": "developer"}``.

    Priority: first matching group wins.  Falls back to ``"viewer"`` when no
    group matches (or mapping is empty / absent). This is the role for a NEW
    account; an existing account keeps its role unless a group matches
    (:func:`provision_user`).
    """
    return mapped_role(config, groups) or "viewer"


# ---------------------------------------------------------------------------
# The OIDC login's state (#66)
# ---------------------------------------------------------------------------
#
# The login route used to mint a random state and remember it in a
# process-local dictionary. That state was bound to no browser -- any
# callback carrying any unredeemed state was accepted, so an attacker could
# complete a login with their own code in a victim's browser -- it did not
# survive more than one API task, and the route that filled the dictionary is
# unauthenticated.
#
# Now the server holds nothing. The login route sets a signed, short-lived
# cookie in the browser that started the login; the callback accepts only a
# `state` that matches the one inside that cookie. The cookie also carries the
# PKCE verifier, so a code intercepted on its way back is useless without it,
# and names the SSO configuration the login was started for.

#: `__Host-`: the browser accepts it only with `Secure`, `Path=/` and no
#: `Domain`, so no other host -- a sibling subdomain included -- can set or
#: overwrite it.
OIDC_STATE_COOKIE = "__Host-experimently_oidc"

#: How long a started login stays redeemable.
OIDC_STATE_TTL_SECONDS = 600

#: Clock skew allowed on the cookie's `exp` and `iat`.
_STATE_LEEWAY_SECONDS = 30

_STATE_AUDIENCE = "experimently:oidc-state"


def _state_key() -> bytes:
    """The cookie's signing key: derived from SECRET_KEY, used for nothing else.

    A token signed with this key can never pass for an access token, and an
    access token can never pass for one of these, even though both are HS256
    under the same secret.
    """
    return hmac.new(
        core_settings.SECRET_KEY.encode("utf-8"),
        b"experimently:oidc-state:v1",
        hashlib.sha256,
    ).digest()


def pkce_challenge(verifier: str) -> str:
    """The S256 code challenge for *verifier* (RFC 7636 s.4.2)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class OIDCLoginStart:
    """What the login route needs: the URL's `state` and the cookie to set."""

    state: str
    code_verifier: str
    cookie_value: str


@dataclass(frozen=True)
class OIDCLoginState:
    """What the callback gets back from a cookie that verified."""

    config_id: uuid.UUID
    provider: str
    code_verifier: str


def start_oidc_login(config: SSOConfig, provider: str) -> OIDCLoginStart:
    """Mint the state, the PKCE verifier and the signed cookie that holds both."""
    state = secrets.token_urlsafe(32)
    # 64 random bytes -> 86 characters, inside RFC 7636's 43..128.
    verifier = secrets.token_urlsafe(64)
    now = int(time.time())
    claims = {
        "aud": _STATE_AUDIENCE,
        "iat": now,
        "exp": now + OIDC_STATE_TTL_SECONDS,
        "st": state,
        "cv": verifier,
        "cfg": str(config.id),
        "prv": provider,
    }
    cookie = jwt.encode(claims, _state_key(), algorithm="HS256")
    return OIDCLoginStart(state=state, code_verifier=verifier, cookie_value=cookie)


def _state_refusal(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def redeem_oidc_state(
    cookie_value: Optional[str], url_state: Optional[str]
) -> OIDCLoginState:
    """Accept a callback only from the browser that started this login.

    Refuses, with a fixed 400: no cookie; a cookie that does not verify, has
    expired or is not one of ours; and a URL `state` that is absent or is not
    the one in the cookie. Single use is the identity provider's side of it:
    an authorization code is redeemable once, and the callback expires the
    cookie whatever the outcome.
    """
    if not cookie_value:
        raise _state_refusal(
            "OIDC sign-in was not started in this browser, or its cookie was not sent"
        )
    try:
        claims = jwt.decode(
            cookie_value,
            _state_key(),
            algorithms=["HS256"],
            audience=_STATE_AUDIENCE,
            leeway=_STATE_LEEWAY_SECONDS,
            options={"require": ["aud", "iat", "exp", "st", "cv", "cfg", "prv"]},
        )
    except jwt.ExpiredSignatureError:
        raise _state_refusal("OIDC sign-in expired; start it again") from None
    except jwt.PyJWTError:
        raise _state_refusal("OIDC sign-in state is not valid") from None

    expected = str(claims["st"]).encode("utf-8")
    if not url_state or not hmac.compare_digest(url_state.encode("utf-8"), expected):
        raise _state_refusal("OIDC state does not match this browser's sign-in")
    try:
        config_id = uuid.UUID(str(claims["cfg"]))
    except ValueError:
        raise _state_refusal("OIDC sign-in state is not valid") from None
    return OIDCLoginState(
        config_id=config_id,
        provider=str(claims["prv"]),
        code_verifier=str(claims["cv"]),
    )


def build_oidc_authorization_url(
    config: SSOConfig,
    provider_key: str,
    redirect_uri: str,
    state: str,
    code_verifier: str,
) -> str:
    """Build the authorization URL to redirect the user to the OIDC provider.

    Always with a PKCE S256 challenge (RFC 9700 s.2.1.1). A provider that does
    not support PKCE ignores the parameters.
    """
    meta = _OIDC_PROVIDERS.get(provider_key)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown OIDC provider '{provider_key}'",
        )

    auth_url = meta["authorization_endpoint"]
    if "{sso_url}" in auth_url and config.sso_url:
        auth_url = auth_url.replace("{sso_url}", config.sso_url.rstrip("/"))

    params = {
        "client_id": config.entity_id or "",
        "response_type": "code",
        "scope": meta.get("scope", "openid email profile"),
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{auth_url}?{urlencode(params)}"
