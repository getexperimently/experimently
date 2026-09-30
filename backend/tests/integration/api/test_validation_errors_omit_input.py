"""A 422 does not repeat the values the client submitted (#500).

FastAPI's default handler put each rejected value in the error's ``input``;
for a missing field, or a body of the wrong type, that is the whole body, so a
422 returned every submitted field, including the valid ones. The
application's handler keeps ``type``, ``loc``, ``msg`` and ``ctx`` only.

Every probe asserts on the SERIALISED WHOLE BODY (``response.text``), not on
one error: the value must appear nowhere in what the client gets back.

Real ``User`` rows and real local JWTs from ``create_local_access_token``; the
only dependency override is ``deps.get_db``, so every request goes through the
real authentication and the real validation.
"""

from __future__ import annotations

import json
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

USERS = "/api/v1/users"
LOGIN = "/api/v1/auth/login"

#: A value that satisfies every password rule and appears nowhere else.
SUBMITTED = "Vx7-q2Lr-9mTz-probe500"
#: Too short for the 8-character minimum; the rule rejects it before it
#: becomes a SecretStr, so the default handler returned it verbatim.
SHORT = "Qz7kWu"

ALLOWED_KEYS = {"type", "loc", "msg", "ctx"}


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


@pytest.fixture(scope="module")
def people(test_db):
    """A superuser (the caller) and an ordinary user (the target of PUT)."""
    factory = sessionmaker(bind=test_db, expire_on_commit=False)
    session = factory()
    session.execute(text("SET search_path TO test_experimentation"))
    suffix = uuid.uuid4().hex[:8]

    def make(name, is_superuser):
        user = User(
            username=f"v500_{name}_{suffix}",
            email=f"v500_{name}_{suffix}@validation.test",
            full_name="Validation Probe",
            hashed_password="unused: these users sign in by token only",
            is_active=True,
            is_superuser=is_superuser,
            role=UserRole.ADMIN if is_superuser else UserRole.VIEWER,
        )
        session.add(user)
        return user

    users = {"superuser": make("su", True), "target": make("target", False)}
    session.commit()
    try:
        yield users
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


def _auth(user):
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


def _assert_422_without(response, secret):
    assert response.status_code == 422, response.text
    assert secret not in response.text, response.text
    body = response.json()
    assert list(body) == ["detail"], body
    assert body["detail"], body
    for error in body["detail"]:
        assert set(error) <= ALLOWED_KEYS, error
        assert {"type", "loc", "msg"} <= set(error), error


def test_missing_field_on_create_user(client, people):
    response = client.post(
        f"{USERS}/",
        json={"email": "new500@example.com", "password": SUBMITTED},
        headers=_auth(people["superuser"]),
    )
    _assert_422_without(response, SUBMITTED)
    assert ["body", "username"] in [e["loc"] for e in response.json()["detail"]]


def test_missing_field_on_update_user(client, people):
    response = client.put(
        f"{USERS}/{people['target'].id}",
        json={"username": "renamed500", "password": SUBMITTED},
        headers=_auth(people["superuser"]),
    )
    _assert_422_without(response, SUBMITTED)
    assert ["body", "email"] in [e["loc"] for e in response.json()["detail"]]


def test_missing_email_on_login(client):
    """Unauthenticated: anyone could post this."""
    response = client.post(LOGIN, json={"password": SUBMITTED})
    _assert_422_without(response, SUBMITTED)
    assert ["body", "email"] in [e["loc"] for e in response.json()["detail"]]


def test_list_body(client, people):
    response = client.post(
        f"{USERS}/",
        json=[
            {
                "email": "list500@example.com",
                "username": "list500",
                "password": SUBMITTED,
            }
        ],
        headers=_auth(people["superuser"]),
    )
    _assert_422_without(response, SUBMITTED)


def test_weak_password(client, people):
    response = client.post(
        f"{USERS}/",
        json={
            "email": "weak500@example.com",
            "username": "weak500",
            "password": SHORT,
        },
        headers=_auth(people["superuser"]),
    )
    _assert_422_without(response, SHORT)
    (error,) = [
        e for e in response.json()["detail"] if e["loc"] == ["body", "password"]
    ]
    assert error["type"] == "too_short", error
    # ctx is kept: it says what the rule was, not what was sent.
    assert error["ctx"]["min_length"] == 8, error


def test_lone_surrogate_on_login_is_422_not_500(client):
    """A lone surrogate cannot be encoded as UTF-8. The default handler put
    it in ``input`` and failed to render its own response: a 500."""
    raw = b'{"email":"\\ud800","password":"x"}'
    response = client.post(
        LOGIN, content=raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422, response.text
    body = json.loads(response.content)
    assert body["detail"], body
    for error in body["detail"]:
        assert "input" not in error, error


def test_the_documented_export_422(client, people):
    """The data export page's example 422 is exactly this body."""
    response = client.get(
        "/api/v1/export/experiments?format=xml",
        headers=_auth(people["superuser"]),
    )
    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": [
            {
                "type": "enum",
                "loc": ["query", "format"],
                "msg": "Input should be 'csv' or 'json'",
                "ctx": {"expected": "'csv' or 'json'"},
            }
        ]
    }
