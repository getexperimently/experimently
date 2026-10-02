"""An SSO sign-in with values longer than the account columns can hold (#662).

A name is shortened to the column; an email address is refused, never
shortened; a provider identifier that the ``external_id`` column cannot store
is refused. Each refusal names its ``sso_error`` code at every place a sign-in
provisions an account -- the SAML ACS, the OIDC callback's JSON answer and its
dashboard redirect -- instead of a 500 or ``sso_failed``.

Against Postgres: SQLite does not enforce ``varchar(n)``, so only a real
database shows the failure this pins.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api import deps
from backend.app.core.config import settings as core_settings
from backend.app.db.session import get_db as _session_get_db
from backend.app.main import app
from backend.app.models.user import User, UserRole
from modules.backend.app.models.sso_config import SSOConfig, SSOProviderType
from modules.backend.app.services import sso_service

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

BASE = "/api/v1/auth/sso"
DASH = "https://dash-662.example.com"
#: The hand-off hash of the known-answer secret in test_sso_dashboard_sign_in.py.
HH = "Yw3NKWbEM2aRElRIu7JbT_QSpJxzLbLIq8G4WBvXEN0"

EMAIL_TOO_LONG_TEXT = (
    "This account's email address is longer than 100 characters, the most an "
    "account can hold. Ask an administrator."
)


def _domain() -> str:
    return f"long-{uuid.uuid4().hex[:10]}.example.com"


def _email_of_length(domain: str, length: int) -> str:
    local = "a" * (length - 1 - len(domain))
    email = f"{local}@{domain}"
    assert len(email) == length
    return email


def _config(db: Session, domain: str, provider=SSOProviderType.SAML) -> SSOConfig:
    cfg = SSOConfig(
        org_name="Long Values Org",
        org_domain=domain,
        provider_type=provider,
        entity_id="long-client",
        client_secret="long-secret",
        sso_url="https://idp.example.com/sso",
        x509_certificate="MIIC...cert",
        role_mapping={},
        is_enforced=False,
        is_active=True,
    )
    db.add(cfg)
    db.commit()
    return cfg


def _count(db: Session, email: str) -> int:
    return db.query(User).filter(func.lower(User.email) == email.lower()).count()


def _stored(db: Session, email: str) -> User:
    db.expire_all()
    return db.query(User).filter(func.lower(User.email) == email.lower()).one()


def _refusal(db: Session, info: Dict[str, Any], cfg: SSOConfig):
    with pytest.raises(sso_service.SSORefusal) as exc_info:
        sso_service.provision_user(db, info, cfg)
    return exc_info.value


# ---------------------------------------------------------------------------
# The bounds are the columns
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_the_bounds_are_read_from_the_columns():
    columns = User.__table__.c
    assert sso_service.EMAIL_MAX == columns.email.type.length == 100
    assert sso_service.NAME_MAX == columns.first_name.type.length == 100
    assert sso_service.NAME_MAX == columns.last_name.type.length
    assert sso_service.EXTERNAL_ID_MAX == columns.external_id.type.length == 255
    assert sso_service.EMAIL_TOO_LONG_DETAIL == EMAIL_TOO_LONG_TEXT


# ---------------------------------------------------------------------------
# Names: shortened, never a failed sign-in
# ---------------------------------------------------------------------------

#: (where the name comes from, the user info carrying ``value``, the column)
NAME_SOURCES = [
    ("first_name", lambda v: {"first_name": v}, "first_name"),
    ("last_name", lambda v: {"last_name": v}, "last_name"),
    ("name, first word", lambda v: {"name": v}, "first_name"),
    ("name, the rest", lambda v: {"name": f"Ada {v}"}, "last_name"),
    ("raw given_name", lambda v: {"raw": {"given_name": v}}, "first_name"),
    ("raw family_name", lambda v: {"raw": {"family_name": v}}, "last_name"),
]


@pytest.mark.regression
@pytest.mark.parametrize("length", [100, 101, 500])
@pytest.mark.parametrize(
    "source,info_of,column", NAME_SOURCES, ids=[s[0] for s in NAME_SOURCES]
)
def test_a_long_name_from_any_source_is_shortened_to_the_column(
    db_session: Session, source, info_of, column, length
):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = f"named@{domain}"
    value = "N" + "x" * (length - 1)
    info = {"email": email, "name_id": email, "groups": [], **info_of(value)}

    sso_service.provision_user(db_session, info, cfg)

    stored = getattr(_stored(db_session, email), column)
    assert stored == value[:100]
    assert len(stored) == min(length, 100)


@pytest.mark.regression
def test_the_bound_counts_characters_not_bytes(db_session: Session):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = f"accent@{domain}"
    sso_service.provision_user(
        db_session, {"email": email, "first_name": "é" * 101}, cfg
    )
    assert _stored(db_session, email).first_name == "é" * 100


@pytest.mark.regression
@pytest.mark.parametrize(
    "given,expected",
    [
        ("ab\ud800", "ab"),  # a lone surrogate: json.loads makes one from "\\ud800"
        ("a\x00b", "ab"),
        ("\udfff\x00", None),
        ("   ", None),
        (42, None),
        (["Ada"], None),
    ],
    ids=["surrogate", "nul", "nothing-left", "blank", "int", "list"],
)
def test_a_name_the_database_cannot_store_is_cleaned_not_a_500(
    db_session: Session, given, expected
):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = f"odd@{domain}"
    info = {"email": email, "raw": {"given_name": given}, "name": given}

    sso_service.provision_user(db_session, info, cfg)

    assert _stored(db_session, email).first_name == expected


@pytest.mark.regression
def test_an_existing_accounts_names_are_left_alone(db_session: Session):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = f"existing@{domain}"
    user = User(
        username=f"u_{uuid.uuid4().hex[:10]}",
        email=email,
        hashed_password="not-a-real-hash",
        is_active=True,
        role=UserRole.VIEWER,
        first_name="Old",
        last_name="Name",
    )
    db_session.add(user)
    db_session.commit()

    result = sso_service.provision_user(
        db_session,
        {"email": email, "first_name": "F" * 150, "last_name": "L\ud800" * 80},
        cfg,
    )

    assert result.id == user.id
    stored = _stored(db_session, email)
    assert (stored.first_name, stored.last_name) == ("Old", "Name")


def test_the_username_fits_for_a_64_character_local_part(db_session: Session):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = f"{'u' * 64}@{domain}"
    user = sso_service.provision_user(db_session, {"email": email}, cfg)
    assert len(user.username) <= 50


# ---------------------------------------------------------------------------
# Email: refused when too long, never shortened
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_an_email_of_101_characters_is_refused_and_nothing_is_written(
    db_session: Session,
):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = _email_of_length(domain, 101)

    refusal = _refusal(db_session, {"email": email, "name_id": email}, cfg)

    assert refusal.status_code == 400
    assert refusal.detail == EMAIL_TOO_LONG_TEXT
    assert refusal.sso_error == sso_service.SSO_EMAIL
    assert _count(db_session, email) == 0
    assert _count(db_session, email[:100]) == 0


def test_an_email_of_exactly_100_characters_signs_in(db_session: Session):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = _email_of_length(domain, 100)
    user = sso_service.provision_user(db_session, {"email": email}, cfg)
    assert user.email == email


def test_a_long_email_outside_the_domain_is_still_sso_domain(db_session: Session):
    cfg = _config(db_session, _domain())
    email = _email_of_length(_domain(), 150)
    refusal = _refusal(db_session, {"email": email}, cfg)
    assert refusal.status_code == 403
    assert refusal.sso_error == sso_service.SSO_DOMAIN
    assert _count(db_session, email) == 0


@pytest.mark.regression
def test_a_nul_in_the_email_is_sso_email(db_session: Session):
    domain = _domain()
    cfg = _config(db_session, domain)
    refusal = _refusal(db_session, {"email": f"a\x00b@{domain}"}, cfg)
    assert refusal.status_code == 400
    assert refusal.detail == sso_service.EMAIL_INVALID_DETAIL
    assert refusal.sso_error == sso_service.SSO_EMAIL


# ---------------------------------------------------------------------------
# The provider's identifier (external_id)
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "info_of",
    [
        lambda: {"sub": "s" * 256},
        lambda: {"sub": "subject\x00one"},
        lambda: {"sub": "subject\ud800"},
        lambda: {"sub": 12345},
        lambda: {"name_id": ["not", "text"]},
        lambda: {"name_id": "n" * 256},
    ],
    ids=["256-chars", "nul", "surrogate", "int-sub", "list-name-id", "256-name-id"],
)
def test_an_identifier_the_column_cannot_store_is_sso_account(
    db_session: Session, info_of
):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = f"ident@{domain}"

    refusal = _refusal(db_session, {"email": email, **info_of()}, cfg)

    assert refusal.status_code == 400
    assert refusal.detail == sso_service.IDENTITY_UNUSABLE_DETAIL
    assert refusal.sso_error == sso_service.SSO_ACCOUNT
    assert _count(db_session, email) == 0


def test_an_identifier_of_255_characters_signs_in(db_session: Session):
    domain = _domain()
    cfg = _config(db_session, domain)
    user = sso_service.provision_user(
        db_session, {"email": f"max@{domain}", "sub": "s" * 255}, cfg
    )
    assert user.external_id == "s" * 255


# ---------------------------------------------------------------------------
# Through each place a sign-in provisions an account
# ---------------------------------------------------------------------------


@pytest.fixture
def anonymous(db_session: Session, monkeypatch) -> Iterator[TestClient]:
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

    monkeypatch.setattr(core_settings, "DASHBOARD_ORIGINS", [DASH])
    monkeypatch.setattr(core_settings, "PUBLIC_BASE_URL", None)
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[_session_get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def _saml_acs(client: TestClient, cfg: SSOConfig, email: str, **names):
    parsed = {
        "email": email,
        "name_id": email,
        "groups": [],
        "attributes": {},
        "first_name": names.get("first_name"),
        "last_name": names.get("last_name"),
    }
    with patch.object(sso_service, "parse_saml_response", return_value=parsed):
        return client.post(f"{BASE}/saml/{cfg.id}/acs", data={"SAMLResponse": "eA=="})


def _oidc_callback(
    client: TestClient,
    cfg: SSOConfig,
    email: str,
    *,
    dashboard: bool,
    sub: str = "okta-sub",
    user_info: Dict[str, Any] | None = None,
):
    """The Okta callback with the provider's answers stubbed; the rest is real."""
    started = (
        sso_service.start_oidc_login(cfg, "okta", return_to=DASH, handoff=HH)
        if dashboard
        else sso_service.start_oidc_login(cfg, "okta")
    )
    claims = {"sub": sub, "email": email, "email_verified": True}
    with (
        patch.object(
            sso_service,
            "exchange_oidc_code",
            AsyncMock(return_value={"access_token": "t", "id_token": "i"}),
        ),
        patch.object(sso_service, "verify_id_token", return_value=claims),
        patch.object(
            sso_service,
            "get_oidc_user_info",
            AsyncMock(return_value={"sub": sub, "email": email, **(user_info or {})}),
        ),
    ):
        return client.get(
            f"{BASE}/oidc/okta/callback",
            params={"code": "c", "state": started.state},
            headers={
                "cookie": f"{sso_service.OIDC_STATE_COOKIE}={started.cookie_value}"
            },
            follow_redirects=False,
        )


def _sso_error_of(resp) -> str:
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    assert location.startswith(f"{DASH}/login?"), location
    return parse_qs(urlparse(location).query)["sso_error"][0]


@pytest.mark.regression
def test_the_saml_acs_refuses_a_101_character_email_with_the_detail(
    anonymous: TestClient, db_session: Session
):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = _email_of_length(domain, 101)

    resp = _saml_acs(anonymous, cfg, email)

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == EMAIL_TOO_LONG_TEXT
    assert _count(db_session, email) == 0


@pytest.mark.regression
def test_the_saml_acs_signs_in_with_long_names_shortened(
    anonymous: TestClient, db_session: Session
):
    domain = _domain()
    cfg = _config(db_session, domain)
    email = f"saml-names@{domain}"

    resp = _saml_acs(anonymous, cfg, email, first_name="F" * 101, last_name="L" * 300)

    assert resp.status_code == 200, resp.text
    stored = _stored(db_session, email)
    assert (stored.first_name, stored.last_name) == ("F" * 100, "L" * 100)


@pytest.mark.regression
def test_the_oidc_json_callback_refuses_a_101_character_email(
    anonymous: TestClient, db_session: Session
):
    domain = _domain()
    cfg = _config(db_session, domain, provider=SSOProviderType.OKTA)
    email = _email_of_length(domain, 101)

    resp = _oidc_callback(anonymous, cfg, email, dashboard=False)

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == EMAIL_TOO_LONG_TEXT
    assert _count(db_session, email) == 0


@pytest.mark.regression
def test_the_dashboard_redirect_says_sso_email_for_a_101_character_email(
    anonymous: TestClient, db_session: Session
):
    """What the user sees: ``sso_email``, not ``sso_failed`` (#662)."""
    domain = _domain()
    cfg = _config(db_session, domain, provider=SSOProviderType.OKTA)
    email = _email_of_length(domain, 101)

    resp = _oidc_callback(anonymous, cfg, email, dashboard=True)

    assert _sso_error_of(resp) == sso_service.SSO_EMAIL
    assert _count(db_session, email) == 0


@pytest.mark.regression
def test_the_dashboard_redirect_signs_in_with_a_long_name(
    anonymous: TestClient, db_session: Session
):
    domain = _domain()
    cfg = _config(db_session, domain, provider=SSOProviderType.OKTA)
    email = f"oidc-names@{domain}"

    resp = _oidc_callback(
        anonymous,
        cfg,
        email,
        dashboard=True,
        user_info={"name": "G" * 120 + " " + "H" * 120},
    )

    assert resp.status_code == 302, resp.text
    assert resp.headers["location"].startswith(f"{DASH}/sso/complete#code=")
    stored = _stored(db_session, email)
    assert (stored.first_name, stored.last_name) == ("G" * 100, "H" * 100)


@pytest.mark.regression
@pytest.mark.parametrize(
    "sub", ["s" * 256, "sub\x00x", "sub\ud800"], ids=["256", "nul", "surrogate"]
)
def test_the_dashboard_redirect_says_sso_account_for_an_unusable_identifier(
    anonymous: TestClient, db_session: Session, sub
):
    domain = _domain()
    cfg = _config(db_session, domain, provider=SSOProviderType.OKTA)
    email = f"oidc-ident@{domain}"

    resp = _oidc_callback(anonymous, cfg, email, dashboard=True, sub=sub)

    assert _sso_error_of(resp) == sso_service.SSO_ACCOUNT
    assert _count(db_session, email) == 0
