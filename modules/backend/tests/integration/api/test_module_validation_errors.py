"""Module routes get the application's 422 too (#500).

The application's handler for request validation errors is registered on the
app, so it answers for every route the modules' registration includes. The
warehouse routes answer their own validation errors first
(``_ValuesOmittedRoute``: ``type``, ``loc`` and ``msg``, no ``ctx``), and
that stays as it was.

Real users, real local JWTs, and only ``deps.get_db`` overridden.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.regression]

SUBMITTED = "Vx7-q2Lr-9mTz-probe500"


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


@pytest.fixture(scope="module")
def superuser_token(test_db):
    factory = sessionmaker(bind=test_db, expire_on_commit=False)
    session = factory()
    session.execute(text("SET search_path TO test_experimentation"))
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"m500_su_{suffix}",
        email=f"m500_su_{suffix}@validation.test",
        full_name="Validation Probe",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=True,
        role=UserRole.ADMIN,
    )
    session.add(user)
    session.commit()
    try:
        yield create_local_access_token(user)
    finally:
        session.close()


@pytest.fixture
def client(db_session):
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

    app.dependency_overrides[deps.get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


def test_sso_config_missing_field(client, superuser_token):
    body = {
        "org_domain": f"probe500-{uuid.uuid4().hex[:6]}.com",
        "provider_type": "google",
        "entity_id": "google-client-id",
        "client_secret": SUBMITTED,
        "role_mapping": {},
    }
    response = client.post(
        "/api/v1/auth/sso/configs",
        json=body,
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert response.status_code == 422, response.text
    assert SUBMITTED not in response.text, response.text
    detail = response.json()["detail"]
    assert ["body", "org_name"] in [e["loc"] for e in detail]
    for error in detail:
        assert set(error) <= {"type", "loc", "msg", "ctx"}, error


def test_warehouse_route_keeps_its_own_shape(client, superuser_token):
    """``max_bytes_per_query`` below its floor carries a ``ctx``; the
    application's handler would keep it, the warehouse route does not."""
    response = client.post(
        "/api/v1/warehouse/analysis/connections",
        json={
            "warehouse_type": "bigquery",
            "billing_project": "acme-analytics",
            "location": "US",
            "max_bytes_per_query": -1,
            "service_account_json": SUBMITTED,
        },
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert response.status_code == 422, response.text
    assert SUBMITTED not in response.text, response.text
    detail = response.json()["detail"]
    assert detail, response.text
    for error in detail:
        assert set(error) == {"type", "loc", "msg"}, error
