"""``org_domain`` is stored normalised, and one configuration per normalised domain.

A configuration's ``org_domain`` is compared normalised when a user signs in
(``sso_service.normalise_domain``: stripped, lower-cased, no leading ``@``), but
it used to be stored as typed and was unique only exactly -- so ``Acme.com``
and ``acme.com`` could both exist, and a dashboard sign-in for that domain was
refused as ambiguous. Create and update now store the normalised value and
refuse, with 409, a domain another row normalises to, counting rows written
before this change (compared normalised in SQL).

Against Postgres, not a mock: the collision check is a SQL expression, and a
mock answers whatever it is given whatever the filter says.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from modules.backend.app.models.sso_config import SSOConfig, SSOProviderType
from modules.backend.app.services import sso_service

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

BASE = "/api/v1/auth/sso"


def _domain() -> str:
    return f"norm-{uuid.uuid4().hex[:10]}.example.com"


def _payload(org_domain: str) -> dict:
    return {
        "org_name": "Norm Org",
        "org_domain": org_domain,
        "provider_type": "google",
        "entity_id": "client-id",
        "client_secret": "client-secret",
        "role_mapping": {},
    }


def _legacy_row(db: Session, org_domain: str) -> SSOConfig:
    """A row as a release before normalise-on-write could have stored it."""
    cfg = SSOConfig(
        org_name="Legacy Org",
        org_domain=org_domain,
        provider_type=SSOProviderType.SAML,
        entity_id="https://idp.example.com",
        sso_url="https://idp.example.com/sso",
        x509_certificate="MIIC...cert",
        role_mapping={},
        is_enforced=False,
        is_active=True,
    )
    db.add(cfg)
    db.commit()
    return cfg


def _stored(db: Session, config_id) -> str:
    db.expire_all()
    return db.get(SSOConfig, uuid.UUID(str(config_id))).org_domain


def _rows_for(db: Session, domain: str) -> int:
    db.expire_all()
    return (
        db.query(SSOConfig)
        .filter(sso_service._stored_domain_normalised() == domain)
        .count()
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_create_stores_the_normalised_domain(
    admin_client: TestClient, db_session: Session
):
    domain = _domain()
    resp = admin_client.post(f"{BASE}/configs", json=_payload(f"  @{domain.upper()} "))

    assert resp.status_code == 201, resp.text
    assert resp.json()["org_domain"] == domain
    assert _stored(db_session, resp.json()["id"]) == domain


@pytest.mark.regression
@pytest.mark.parametrize("legacy", ["{D}", "{U}", " {D} ", "@{D}", " @{U}"])
def test_create_is_refused_when_a_legacy_row_normalises_to_the_domain(
    admin_client: TestClient, db_session: Session, legacy: str
):
    domain = _domain()
    _legacy_row(db_session, legacy.format(D=domain, U=domain.upper()))

    resp = admin_client.post(f"{BASE}/configs", json=_payload(domain))

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == sso_service.ORG_DOMAIN_TAKEN_DETAIL
    assert _rows_for(db_session, domain) == 1


@pytest.mark.regression
def test_create_is_refused_for_a_domain_that_differs_only_in_case(
    admin_client: TestClient, db_session: Session
):
    domain = _domain()
    first = admin_client.post(f"{BASE}/configs", json=_payload(domain))
    assert first.status_code == 201, first.text

    resp = admin_client.post(f"{BASE}/configs", json=_payload(domain.upper()))

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == sso_service.ORG_DOMAIN_TAKEN_DETAIL
    assert _rows_for(db_session, domain) == 1


@pytest.mark.parametrize("empty", ["", "   ", "@", " @ "])
def test_create_with_a_domain_that_normalises_to_nothing_is_refused(
    admin_client: TestClient, empty: str
):
    resp = admin_client.post(f"{BASE}/configs", json=_payload(empty))

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == sso_service.ORG_DOMAIN_REQUIRED_DETAIL


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_update_stores_the_normalised_domain(
    admin_client: TestClient, db_session: Session
):
    """Including a row's own domain in another spelling: not a collision with itself."""
    domain = _domain()
    legacy = _legacy_row(db_session, f" @{domain.upper()}")

    resp = admin_client.put(
        f"{BASE}/configs/{legacy.id}", json={"org_domain": domain.upper()}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["org_domain"] == domain
    assert _stored(db_session, legacy.id) == domain


@pytest.mark.regression
def test_update_is_refused_when_another_row_normalises_to_the_domain(
    admin_client: TestClient, db_session: Session
):
    taken = _domain()
    _legacy_row(db_session, taken.upper())
    mine = _legacy_row(db_session, _domain())
    before = _stored(db_session, mine.id)

    resp = admin_client.put(f"{BASE}/configs/{mine.id}", json={"org_domain": taken})

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == sso_service.ORG_DOMAIN_TAKEN_DETAIL
    assert _stored(db_session, mine.id) == before


@pytest.mark.regression
def test_normalising_one_of_two_legacy_rows_onto_the_other_is_refused(
    admin_client: TestClient, db_session: Session
):
    """Two legacy rows that differ only in case: writing one's normalised form
    would collide with the other, so it is a 409, not a unique-constraint 500."""
    domain = _domain()
    _legacy_row(db_session, domain)
    upper = _legacy_row(db_session, domain.upper())

    resp = admin_client.put(f"{BASE}/configs/{upper.id}", json={"org_domain": domain})

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == sso_service.ORG_DOMAIN_TAKEN_DETAIL
    assert _stored(db_session, upper.id) == domain.upper()


def test_an_update_that_does_not_name_org_domain_leaves_it_as_stored(
    admin_client: TestClient, db_session: Session
):
    """No data migration: a legacy row keeps its value until org_domain is written."""
    domain = _domain()
    legacy = _legacy_row(db_session, domain.upper())

    resp = admin_client.put(f"{BASE}/configs/{legacy.id}", json={"is_active": False})

    assert resp.status_code == 200, resp.text
    assert _stored(db_session, legacy.id) == domain.upper()


def test_update_with_a_domain_that_normalises_to_nothing_is_refused(
    admin_client: TestClient, db_session: Session
):
    domain = _domain()
    cfg = _legacy_row(db_session, domain)

    resp = admin_client.put(f"{BASE}/configs/{cfg.id}", json={"org_domain": " @ "})

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == sso_service.ORG_DOMAIN_REQUIRED_DETAIL
    assert _stored(db_session, cfg.id) == domain
