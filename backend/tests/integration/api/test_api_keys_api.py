"""
Integration tests for the user-owned API keys router (``/api/v1/api-keys``).

Real database, real local-JWT authentication (only ``deps.get_db`` is
overridden).  The final class proves the created key authenticates SDK
traffic end to end via ``POST /api/v1/tracking/assign``.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.core.security import create_local_access_token, get_password_hash, hash_api_key
from backend.app.main import app
from backend.app.models.api_key import APIKey
from backend.app.models.assignment import Assignment
from backend.app.models.experiment import ExperimentStatus, Variant
from backend.app.models.user import User, UserRole

pytestmark = pytest.mark.integration

URL = "/api/v1/api-keys"


@pytest.fixture(autouse=True)
def _local_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")


def _make_user(db_session, role, is_superuser=False):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"keys_{role.value}_{suffix}",
        email=f"keys_{role.value}_{suffix}@keys.test",
        full_name="API Keys User",
        hashed_password=get_password_hash("Demo1234!"),
        is_active=True,
        is_superuser=is_superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin(db_session):
    return _make_user(db_session, UserRole.ADMIN, is_superuser=True)


@pytest.fixture
def developer(db_session):
    return _make_user(db_session, UserRole.DEVELOPER)


@pytest.fixture
def other_developer(db_session):
    return _make_user(db_session, UserRole.DEVELOPER)


@pytest.fixture
def client(db_session):
    engine = db_session.get_bind()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

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


def _create(client, user, **body):
    payload = {"name": f"key-{uuid.uuid4().hex[:6]}"}
    payload.update(body)
    return client.post(URL, json=payload, headers=_auth(user))


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_requires_auth(self, client):
        assert client.post(URL, json={"name": "x"}).status_code == 401

    def test_create_returns_plaintext_once(self, client, db_session, developer):
        resp = _create(
            client, developer, name="SDK key", description="ci", scopes=["read", "track"]
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert set(body) == {"id", "name", "key", "prefix", "created_at", "expires_at"}
        assert body["name"] == "SDK key"
        assert body["key"].startswith("eptk_") and len(body["key"]) == len("eptk_") + 32
        assert body["prefix"] == body["key"][:9]
        assert body["expires_at"] is None

        row = db_session.query(APIKey).filter(APIKey.id == uuid.UUID(body["id"])).first()
        assert row is not None
        assert row.user_id == developer.id
        assert row.key == hash_api_key(body["key"])  # only the hash is stored
        assert row.key != body["key"]
        assert row.scopes == "read,track"
        assert row.description == "ci"

    def test_create_with_expiry(self, client, developer):
        expires = (datetime.utcnow() + timedelta(days=30)).replace(microsecond=0)
        resp = _create(client, developer, expires_at=expires.isoformat())
        assert resp.status_code == 201, resp.text
        assert resp.json()["expires_at"].startswith(expires.isoformat()[:19])

    def test_validation(self, client, developer):
        assert client.post(URL, json={}, headers=_auth(developer)).status_code == 422
        assert client.post(URL, json={"name": "   "}, headers=_auth(developer)).status_code == 422
        assert (
            client.post(
                URL, json={"name": "x", "scopes": ["a,b"]}, headers=_auth(developer)
            ).status_code
            == 422
        )

    def test_two_keys_are_distinct(self, client, developer):
        a = _create(client, developer).json()
        b = _create(client, developer).json()
        assert a["key"] != b["key"] and a["id"] != b["id"]

    def test_trailing_slash_is_accepted(self, client, developer):
        resp = client.post(f"{URL}/", json={"name": "slash"}, headers=_auth(developer))
        assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestList:
    def test_requires_auth(self, client):
        assert client.get(URL).status_code == 401

    def test_lists_only_own_keys_without_secret(self, client, developer, other_developer):
        mine = _create(client, developer, name="mine").json()
        _create(client, other_developer, name="theirs")

        resp = client.get(URL, headers=_auth(developer))
        assert resp.status_code == 200, resp.text
        items = resp.json()
        ids = {item["id"] for item in items}
        assert mine["id"] in ids
        assert all(item["user_id"] == str(developer.id) for item in items)
        item = next(i for i in items if i["id"] == mine["id"])
        assert set(item) == {
            "id",
            "name",
            "description",
            "scopes",
            "is_active",
            "user_id",
            "created_at",
            "expires_at",
            "last_used_at",
        }
        assert "key" not in item

    def test_scopes_round_trip_as_list(self, client, developer):
        created = _create(client, developer, scopes=["read", "write"]).json()
        items = client.get(URL, headers=_auth(developer)).json()
        assert next(i for i in items if i["id"] == created["id"])["scopes"] == ["read", "write"]

    def test_all_requires_admin(self, client, developer):
        resp = client.get(f"{URL}?all=true", headers=_auth(developer))
        assert resp.status_code == 403

    def test_admin_all_sees_everyone(self, client, admin, developer, other_developer):
        a = _create(client, developer).json()["id"]
        b = _create(client, other_developer).json()["id"]
        own = _create(client, admin).json()["id"]

        resp = client.get(f"{URL}?all=true", headers=_auth(admin))
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()}
        assert {a, b, own} <= ids

        # Without ?all the admin sees only their own.
        ids = {item["id"] for item in client.get(URL, headers=_auth(admin)).json()}
        assert own in ids and a not in ids

    def test_inactive_keys_hidden_by_default(self, client, db_session, developer):
        created = _create(client, developer).json()
        row = db_session.query(APIKey).filter(APIKey.id == uuid.UUID(created["id"])).first()
        row.is_active = False
        db_session.commit()

        ids = {i["id"] for i in client.get(URL, headers=_auth(developer)).json()}
        assert created["id"] not in ids
        ids = {
            i["id"]
            for i in client.get(f"{URL}?include_inactive=true", headers=_auth(developer)).json()
        }
        assert created["id"] in ids


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_requires_auth(self, client):
        assert client.delete(f"{URL}/{uuid.uuid4()}").status_code == 401

    def test_owner_can_delete(self, client, db_session, developer):
        created = _create(client, developer).json()
        resp = client.delete(f"{URL}/{created['id']}", headers=_auth(developer))
        assert resp.status_code == 204
        assert resp.content == b""
        assert (
            db_session.query(APIKey).filter(APIKey.id == uuid.UUID(created["id"])).first() is None
        )

    def test_other_user_cannot_delete(self, client, db_session, developer, other_developer):
        created = _create(client, developer).json()
        resp = client.delete(f"{URL}/{created['id']}", headers=_auth(other_developer))
        assert resp.status_code == 403
        assert (
            db_session.query(APIKey).filter(APIKey.id == uuid.UUID(created["id"])).first()
            is not None
        )

    def test_admin_can_delete_anyones(self, client, db_session, admin, developer):
        created = _create(client, developer).json()
        resp = client.delete(f"{URL}/{created['id']}", headers=_auth(admin))
        assert resp.status_code == 204

    def test_unknown_id_404(self, client, developer):
        assert client.delete(f"{URL}/{uuid.uuid4()}", headers=_auth(developer)).status_code == 404

    def test_malformed_id_422(self, client, developer):
        assert client.delete(f"{URL}/not-a-uuid", headers=_auth(developer)).status_code == 422

    def test_deleted_key_no_longer_authenticates(self, client, developer):
        created = _create(client, developer).json()
        headers = {"X-API-Key": created["key"]}
        assert client.get("/api/v1/edge/bootstrap", headers=headers).status_code == 200
        client.delete(f"{URL}/{created['id']}", headers=_auth(developer))
        assert client.get("/api/v1/edge/bootstrap", headers=headers).status_code == 401


# ---------------------------------------------------------------------------
# The key works for SDK traffic
# ---------------------------------------------------------------------------


@pytest.fixture
def active_experiment(db_session, admin):
    from backend.app.models.experiment import Experiment, ExperimentType

    suffix = uuid.uuid4().hex[:8]
    experiment = Experiment(
        name=f"API key smoke {suffix}",
        key=f"api-key-smoke-{suffix}",
        description="created by test_api_keys_api",
        hypothesis="keys authenticate SDK calls",
        status=ExperimentStatus.ACTIVE,
        experiment_type=ExperimentType.A_B,
        owner_id=admin.id,
    )
    db_session.add(experiment)
    db_session.commit()
    db_session.refresh(experiment)
    for name, is_control in (("control", True), ("treatment", False)):
        db_session.add(
            Variant(
                experiment_id=experiment.id,
                name=name,
                description=name,
                is_control=is_control,
                traffic_allocation=50,
                configuration={},
            )
        )
    db_session.commit()
    db_session.refresh(experiment)
    yield experiment
    db_session.rollback()
    db_session.query(Assignment).filter(Assignment.experiment_id == experiment.id).delete()
    db_session.commit()


class TestKeyAuthenticatesSdkTraffic:
    def test_tracking_assign_with_created_key(self, client, developer, active_experiment):
        key = _create(client, developer, name="sdk").json()["key"]
        resp = client.post(
            "/api/v1/tracking/assign",
            json={"experiment_key": active_experiment.key, "user_id": f"u-{uuid.uuid4().hex[:6]}"},
            headers={"X-API-Key": key},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["experiment_key"] == active_experiment.key
        assert body["variant_name"] in ("control", "treatment")
        assert body["assigned"] is True

    def test_tracking_assign_rejects_unknown_key(self, client, active_experiment):
        resp = client.post(
            "/api/v1/tracking/assign",
            json={"experiment_key": active_experiment.key, "user_id": "u-1"},
            headers={"X-API-Key": "eptk_" + "0" * 32},
        )
        assert resp.status_code == 401

    def test_bearer_token_is_not_an_api_key(self, client, developer, active_experiment):
        """SDK endpoints take X-API-Key, not the dashboard bearer token."""
        resp = client.post(
            "/api/v1/tracking/assign",
            json={"experiment_key": active_experiment.key, "user_id": "u-1"},
            headers=_auth(developer),
        )
        assert resp.status_code == 401
