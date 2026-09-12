"""
DB-backed integration tests for the local authentication path (P0 open-core).

Real ``users`` rows, real bcrypt hashes, real ``deps.get_current_user`` — only
``deps.get_db`` is overridden (to the per-process test database).  Lives under
``integration/api`` (not ``integration/auth``) because it needs Postgres: the
``cognito-integration`` workflow runs ``integration/auth`` with moto only.
``_local_provider`` below pins ``AUTH_PROVIDER=local`` with the dev bypass off
and clean lockout counters.

Covers the acceptance flow from the P0 contract:
  unauthenticated /experiments -> 401; login -> token; /auth/me -> role;
  bearer on a protected endpoint -> 200; wrong password x N -> 423;
  WebSocket ?token= accepted / invalid -> close 4401; bypass on -> 200.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.core.security import create_local_access_token, get_password_hash
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.app.services.local_auth_service import login_attempt_tracker

pytestmark = pytest.mark.integration

PASSWORD = "Demo1234!"
WS_BASE = "/api/v1/ws/experiments"
PATCH_SNAPSHOT = (
    "backend.app.services.results_streaming_service."
    "ResultsStreamingService.get_live_snapshot"
)


@pytest.fixture(autouse=True)
def _local_provider(monkeypatch):
    """Local provider, fail-closed."""
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    login_attempt_tracker.clear()
    yield
    login_attempt_tracker.clear()


def _make_user(
    db_session,
    *,
    role=UserRole.ADMIN,
    is_superuser=True,
    is_active=True,
    password=PASSWORD,
):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"local_{suffix}",
        email=f"local_{suffix}@auth.test",
        full_name="Local Auth User",
        hashed_password=get_password_hash(password),
        is_active=is_active,
        is_superuser=is_superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin(db_session):
    return _make_user(db_session)


@pytest.fixture
def viewer(db_session):
    return _make_user(db_session, role=UserRole.VIEWER, is_superuser=False)


@pytest.fixture
def real_auth_client(db_session):
    """TestClient with a fresh DB session per request and NO auth overrides."""
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
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


def _login(client, email, password=PASSWORD):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


# ---------------------------------------------------------------------------
# Fail-closed by default
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_experiments_requires_auth(self, real_auth_client):
        resp = real_auth_client.get("/api/v1/experiments/")
        assert resp.status_code == 401, resp.text
        assert resp.json()["detail"]

    def test_api_keys_requires_auth(self, real_auth_client):
        assert real_auth_client.get("/api/v1/api-keys").status_code == 401

    def test_me_requires_auth(self, real_auth_client):
        assert real_auth_client.get("/api/v1/auth/me").status_code == 401

    def test_garbage_bearer_rejected(self, real_auth_client):
        resp = real_auth_client.get(
            "/api/v1/experiments/", headers={"Authorization": "Bearer not.a.token"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Login -> token -> me -> protected endpoint
# ---------------------------------------------------------------------------


class TestLoginFlow:
    def test_full_flow(self, real_auth_client, admin):
        resp = _login(real_auth_client, admin.email)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        token = body["access_token"]
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == settings.LOCAL_AUTH_TOKEN_TTL_MINUTES * 60
        assert body["user"]["email"] == admin.email
        assert body["user"]["role"] == "ADMIN"

        headers = {"Authorization": f"Bearer {token}"}
        me = real_auth_client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200, me.text
        assert me.json() == {
            "id": str(admin.id),
            "email": admin.email,
            "username": admin.username,
            "full_name": "Local Auth User",
            "role": "ADMIN",
            "is_superuser": True,
            "is_active": True,
            "auth_provider": "local",
        }

        listed = real_auth_client.get("/api/v1/experiments/", headers=headers)
        assert listed.status_code == 200, listed.text

        assert (
            real_auth_client.post("/api/v1/auth/logout", headers=headers).status_code
            == 204
        )

    def test_email_case_insensitive(self, real_auth_client, admin):
        resp = _login(real_auth_client, admin.email.upper())
        assert resp.status_code == 200, resp.text

    def test_viewer_role_in_me(self, real_auth_client, viewer):
        token = _login(real_auth_client, viewer.email).json()["access_token"]
        me = real_auth_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me.status_code == 200
        assert me.json()["role"] == "VIEWER"
        assert me.json()["is_superuser"] is False

    def test_oauth2_form_token_endpoint(self, real_auth_client, admin):
        resp = real_auth_client.post(
            "/api/v1/auth/token", data={"username": admin.email, "password": PASSWORD}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["user"]["id"] == str(admin.id)
        headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        assert (
            real_auth_client.get("/api/v1/auth/me", headers=headers).status_code == 200
        )

    def test_wrong_password(self, real_auth_client, admin):
        resp = _login(real_auth_client, admin.email, "wrong-password")
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid email or password"}

    def test_unknown_user_same_message(self, real_auth_client):
        resp = _login(real_auth_client, "nobody@auth.test")
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid email or password"}

    def test_inactive_user_cannot_log_in(self, real_auth_client, db_session):
        user = _make_user(db_session, is_active=False)
        resp = _login(real_auth_client, user.email)
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid email or password"}

    def test_deactivated_after_login_gets_400(
        self, real_auth_client, db_session, admin
    ):
        token = _login(real_auth_client, admin.email).json()["access_token"]
        admin.is_active = False
        db_session.commit()
        resp = real_auth_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Inactive user"

    def test_token_for_deleted_user_is_401(self, real_auth_client, db_session):
        user = _make_user(db_session)
        token = create_local_access_token(user)
        db_session.delete(user)
        db_session.commit()
        resp = real_auth_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401

    def test_token_signed_with_other_secret_is_rejected(
        self, real_auth_client, admin, monkeypatch
    ):
        monkeypatch.setattr(settings, "SECRET_KEY", "x" * 64)
        token = create_local_access_token(admin)
        monkeypatch.setattr(settings, "SECRET_KEY", "y" * 64)
        resp = real_auth_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------


class TestLockout:
    def test_423_after_max_failed_attempts(self, real_auth_client, admin):
        max_attempts = settings.LOCAL_AUTH_MAX_FAILED_ATTEMPTS
        for i in range(max_attempts):
            resp = _login(real_auth_client, admin.email, "wrong")
            assert resp.status_code == 401, f"attempt {i + 1}: {resp.text}"

        # Attempt N+1 is locked even with the correct password.
        resp = _login(real_auth_client, admin.email)
        assert resp.status_code == 423, resp.text
        assert "Retry-After" in resp.headers
        assert "locked" in resp.json()["detail"].lower()

        # /auth/token shares the counter.
        resp = real_auth_client.post(
            "/api/v1/auth/token", data={"username": admin.email, "password": PASSWORD}
        )
        assert resp.status_code == 423

    def test_successful_login_resets_counter(self, real_auth_client, admin):
        for _ in range(settings.LOCAL_AUTH_MAX_FAILED_ATTEMPTS - 1):
            assert _login(real_auth_client, admin.email, "wrong").status_code == 401
        assert _login(real_auth_client, admin.email).status_code == 200
        for _ in range(settings.LOCAL_AUTH_MAX_FAILED_ATTEMPTS - 1):
            assert _login(real_auth_client, admin.email, "wrong").status_code == 401
        assert _login(real_auth_client, admin.email).status_code == 200

    def test_lockout_is_per_email(self, real_auth_client, admin, viewer):
        for _ in range(settings.LOCAL_AUTH_MAX_FAILED_ATTEMPTS):
            _login(real_auth_client, admin.email, "wrong")
        assert _login(real_auth_client, admin.email).status_code == 423
        assert _login(real_auth_client, viewer.email).status_code == 200


# ---------------------------------------------------------------------------
# Dev-admin bypass
# ---------------------------------------------------------------------------


class TestBypass:
    def test_bypass_on_serves_dev_admin(
        self, real_auth_client, db_session, monkeypatch
    ):
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", True)
        resp = real_auth_client.get("/api/v1/experiments/")
        assert resp.status_code == 200, resp.text
        me = real_auth_client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == deps.DEV_BYPASS_USERNAME
        assert me.json()["role"] == "ADMIN"
        assert (
            db_session.query(User)
            .filter(User.username == deps.DEV_BYPASS_USERNAME)
            .first()
        )

    def test_bypass_ignored_outside_dev_test(self, real_auth_client, monkeypatch):
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", True)
        monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
        assert real_auth_client.get("/api/v1/experiments/").status_code == 401


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


class TestWebSocketAuth:
    def _snapshot(self):
        return {"event": "results_update", "experiment_id": "exp-1", "variants": []}

    def test_query_token_accepted(self, real_auth_client, admin):
        token = create_local_access_token(admin)
        with patch(PATCH_SNAPSHOT, return_value=self._snapshot()):
            with real_auth_client.websocket_connect(
                f"{WS_BASE}/exp-1/results?token={token}"
            ) as ws:
                data = ws.receive_json()
        assert data["event"] == "results_update"

    def test_subprotocol_token_accepted_and_echoed(self, real_auth_client, admin):
        """The dashboard sends the token as a WebSocket subprotocol (keeps it out of URL logs)."""
        token = create_local_access_token(admin)
        with patch(PATCH_SNAPSHOT, return_value=self._snapshot()):
            with real_auth_client.websocket_connect(
                f"{WS_BASE}/exp-1/results", subprotocols=["experimently.bearer", token]
            ) as ws:
                assert ws.accepted_subprotocol == "experimently.bearer"
                data = ws.receive_json()
        assert data["event"] == "results_update"

    def test_subprotocol_with_bad_token_closes_4401(self, real_auth_client):
        with real_auth_client.websocket_connect(
            f"{WS_BASE}/exp-1/results", subprotocols=["experimently.bearer", "garbage"]
        ) as ws:
            message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4401

    def test_subprotocol_wins_over_query_token(self, real_auth_client, admin):
        """A valid subprotocol token is used even when a stale ?token= is present."""
        token = create_local_access_token(admin)
        with patch(PATCH_SNAPSHOT, return_value=self._snapshot()):
            with real_auth_client.websocket_connect(
                f"{WS_BASE}/exp-1/results?token=stale",
                subprotocols=["experimently.bearer", token],
            ) as ws:
                data = ws.receive_json()
        assert data["event"] == "results_update"

    def test_bearer_header_accepted(self, real_auth_client, admin):
        token = create_local_access_token(admin)
        with patch(PATCH_SNAPSHOT, return_value=self._snapshot()):
            with real_auth_client.websocket_connect(
                f"{WS_BASE}/exp-1/results", headers={"Authorization": f"Bearer {token}"}
            ) as ws:
                data = ws.receive_json()
        assert data["event"] == "results_update"

    def test_missing_token_closes_4401(self, real_auth_client):
        with real_auth_client.websocket_connect(f"{WS_BASE}/exp-1/results") as ws:
            message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4401

    def test_invalid_token_closes_4401(self, real_auth_client):
        with real_auth_client.websocket_connect(
            f"{WS_BASE}/exp-1/results?token=garbage"
        ) as ws:
            message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4401

    def test_inactive_user_closes_4401(self, real_auth_client, db_session):
        user = _make_user(db_session, is_active=False)
        token = create_local_access_token(user)
        with real_auth_client.websocket_connect(
            f"{WS_BASE}/exp-1/results?token={token}"
        ) as ws:
            message = ws.receive()
        assert message["code"] == 4401

    def test_bypass_accepts_without_token(self, real_auth_client, monkeypatch):
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", True)
        with patch(PATCH_SNAPSHOT, return_value=self._snapshot()):
            with real_auth_client.websocket_connect(f"{WS_BASE}/exp-1/results") as ws:
                data = ws.receive_json()
        assert data["event"] == "results_update"
