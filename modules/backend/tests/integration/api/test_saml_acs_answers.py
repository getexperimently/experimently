"""What the SAML ACS answers, through the HTTP route (#123).

* a response it cannot read: 400 with a fixed message and the request id the
  response's ``X-Request-ID`` carries;
* an assertion for a deactivated account: 400 "Inactive user", as the OIDC
  sign-in answers, and no token;
* the token a successful ACS returns is not a session yet.

Against Postgres; authentication is real (only the database is overridden).
"""

from __future__ import annotations

import base64
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.db.session import get_db as _session_get_db
from backend.app.main import app
from backend.app.models.user import User, UserRole
from modules.backend.app.models.sso_config import SSOConfig, SSOProviderType
from modules.backend.app.services import sso_service

pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.regression]

BASE = "/api/v1/auth/sso"


@pytest.fixture
def domain() -> str:
    return f"acs-{uuid.uuid4().hex[:10]}.example.com"


@pytest.fixture
def config(db_session: Session, domain: str) -> SSOConfig:
    cfg = SSOConfig(
        org_name="ACS Org",
        org_domain=domain,
        provider_type=SSOProviderType.SAML,
        entity_id="https://idp.example.com",
        sso_url="https://idp.example.com/sso",
        x509_certificate="MIIC...cert",
        role_mapping={},
        is_enforced=False,
        is_active=True,
    )
    db_session.add(cfg)
    db_session.commit()
    return cfg


@pytest.fixture
def anonymous(db_session: Session) -> Iterator[TestClient]:
    """Only the database is overridden; authentication is real."""
    factory = sessionmaker(
        bind=db_session.get_bind(), autocommit=False, autoflush=False
    )

    def override_get_db():
        session = factory()
        session.execute(text("SET search_path TO test_experimentation"))
        try:
            yield session
        finally:
            session.close()

    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[_session_get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def _post_parsed(client: TestClient, cfg: SSOConfig, email: str):
    """POST to the ACS with the parse mocked to have accepted *email*."""
    parsed = {
        "email": email,
        "name_id": email,
        "groups": [],
        "attributes": {},
        "first_name": None,
        "last_name": None,
    }
    with patch(
        "modules.backend.app.services.sso_service.parse_saml_response",
        return_value=parsed,
    ):
        return client.post(f"{BASE}/saml/{cfg.id}/acs", data={"SAMLResponse": "eA=="})


def test_an_unreadable_response_gets_the_fixed_message_with_the_request_id(
    anonymous: TestClient, config: SSOConfig
):
    assert sso_service._SAML_AVAILABLE is True, "python3-saml is not importable"
    marker = "MARKERq7z"
    body = base64.b64encode(f"<{marker}></r>".encode()).decode()

    resp = anonymous.post(f"{BASE}/saml/{config.id}/acs", data={"SAMLResponse": body})

    assert resp.status_code == 400, resp.text
    request_id = resp.headers["x-request-id"]
    # Spelled out: this is the text the browser shows, and docs/auth/sso.md
    # quotes it.
    assert resp.json() == {
        "detail": f"Failed to parse SAML response (request ID: {request_id})"
    }


def test_a_deactivated_account_is_refused_like_the_oidc_sign_in(
    anonymous: TestClient, db_session: Session, config: SSOConfig, domain: str
):
    email = f"former-{uuid.uuid4().hex[:6]}@{domain}"
    db_session.add(
        User(
            username=f"u_{uuid.uuid4().hex[:10]}",
            email=email,
            hashed_password="not-a-real-hash",
            is_active=False,
            role=UserRole.VIEWER,
        )
    )
    db_session.commit()

    resp = _post_parsed(anonymous, config, email)

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"detail": "Inactive user"}


def test_an_active_account_still_gets_the_acs_response(
    anonymous: TestClient, config: SSOConfig, domain: str
):
    """The positive control for the refusal above."""
    resp = _post_parsed(anonymous, config, f"active-{uuid.uuid4().hex[:6]}@{domain}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]


def test_the_token_the_acs_returns_is_not_a_session(
    anonymous: TestClient, config: SSOConfig, domain: str, monkeypatch
):
    """The ACS token must not authenticate anything yet.

    If this fails, the ACS token has been made usable. SAML sessions need the
    SAML request-binding work first; land that change together with it, and
    remove this test in the same diff.
    """
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    resp = _post_parsed(anonymous, config, f"judy-{uuid.uuid4().hex[:6]}@{domain}")
    assert resp.status_code == 200, resp.text

    me = anonymous.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {resp.json()['access_token']}"},
    )

    assert me.status_code == 401, (
        "The SAML ACS token was accepted by /api/v1/users/me. SAML sessions need "
        "the SAML request-binding work first; see the docstring of this test. "
        f"Got {me.status_code}: {me.text}"
    )
