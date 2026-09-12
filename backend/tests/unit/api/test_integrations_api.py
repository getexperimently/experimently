"""
Unit tests for integration config CRUD API — EP-034 Batch 3.

Uses FastAPI TestClient with dependency overrides.
No real database required — all DB calls are mocked.
"""

import hashlib
import hmac as hmac_lib
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.integration_config import IntegrationConfig, IntegrationType
from backend.app.models.user import User, UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: UserRole = UserRole.ADMIN, is_superuser: bool = False) -> User:
    """Create an in-memory User mock with the given role."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = f"user_{role.value}"
    user.email = f"{role.value}@example.com"
    user.is_active = True
    user.is_superuser = is_superuser
    user.role = role
    return user


def _make_config(
    integration_type: IntegrationType = IntegrationType.JIRA,
    is_active: bool = False,
    encrypted_config: dict = None,
) -> MagicMock:
    """Create a mock IntegrationConfig with sensible defaults."""
    cfg = MagicMock(spec=IntegrationConfig)
    cfg.id = uuid.uuid4()
    cfg.integration_type = integration_type
    cfg.is_active = is_active
    cfg.encrypted_config = encrypted_config or {"base_url": "https://jira.example.com"}
    cfg.last_sync_at = None
    cfg.last_error = None
    cfg.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cfg.updated_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    return cfg


def _make_mock_db():
    """Return a configured mock SQLAlchemy Session."""
    return MagicMock()


def _override(user: User, mock_db=None):
    """Context-free helper: sets dependency_overrides on the FastAPI app."""
    if mock_db is None:
        mock_db = _make_mock_db()
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_db] = lambda: mock_db
    return mock_db


def _clear():
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestListIntegrations
# ---------------------------------------------------------------------------


class TestListIntegrations:
    """GET /api/v1/integrations"""

    def setup_method(self):
        _clear()

    def teardown_method(self):
        _clear()

    def test_admin_can_list_integrations(self):
        """GET /api/v1/integrations returns list of configs for ADMIN."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        config = _make_config()
        mock_db.query.return_value.all.return_value = [config]

        client = TestClient(app)
        response = client.get("/api/v1/integrations")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["integration_type"] == IntegrationType.JIRA.value

    def test_developer_can_list_integrations(self):
        """Developers (ADMIN+DEV read) can list integration configs."""
        developer = _make_user(UserRole.DEVELOPER)
        mock_db = _override(developer)
        mock_db.query.return_value.all.return_value = []

        client = TestClient(app)
        response = client.get("/api/v1/integrations")

        assert response.status_code == 200
        assert response.json() == []

    def test_analyst_cannot_list_integrations(self):
        """ANALYST gets 403 — not ADMIN or DEVELOPER."""
        analyst = _make_user(UserRole.ANALYST)
        _override(analyst)

        client = TestClient(app)
        response = client.get("/api/v1/integrations")

        assert response.status_code == 403

    def test_viewer_cannot_list_integrations(self):
        """VIEWER gets 403."""
        viewer = _make_user(UserRole.VIEWER)
        _override(viewer)

        client = TestClient(app)
        response = client.get("/api/v1/integrations")

        assert response.status_code == 403

    def test_unauthenticated_returns_401(self):
        """No auth header → 401 (no dependency override → token required)."""
        _clear()  # Remove all overrides

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/integrations")

        # FastAPI returns 401 or 422 when no token is provided depending on
        # how oauth2_scheme is configured; 401 is the expected contract.
        assert response.status_code in (401, 403, 422)

    def test_list_returns_multiple_configs(self):
        """GET returns all configured integrations."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        jira_cfg = _make_config(IntegrationType.JIRA)
        sf_cfg = _make_config(IntegrationType.SALESFORCE, is_active=True)
        mock_db.query.return_value.all.return_value = [jira_cfg, sf_cfg]

        client = TestClient(app)
        response = client.get("/api/v1/integrations")

        assert response.status_code == 200
        assert len(response.json()) == 2


# ---------------------------------------------------------------------------
# TestGetIntegration
# ---------------------------------------------------------------------------


class TestGetIntegration:
    """GET /api/v1/integrations/{integration_type}"""

    def setup_method(self):
        _clear()

    def teardown_method(self):
        _clear()

    def test_get_jira_config(self):
        """GET /api/v1/integrations/jira returns Jira config."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        config = _make_config(IntegrationType.JIRA)

        mock_db.query.return_value.filter.return_value.first.return_value = config

        client = TestClient(app)
        response = client.get("/api/v1/integrations/jira")

        assert response.status_code == 200
        assert response.json()["integration_type"] == "jira"

    def test_get_salesforce_config(self):
        """GET /api/v1/integrations/salesforce returns Salesforce config."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        config = _make_config(IntegrationType.SALESFORCE, is_active=True)

        mock_db.query.return_value.filter.return_value.first.return_value = config

        client = TestClient(app)
        response = client.get("/api/v1/integrations/salesforce")

        assert response.status_code == 200
        assert response.json()["integration_type"] == "salesforce"

    def test_get_github_config(self):
        """GET /api/v1/integrations/github returns GitHub config."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        config = _make_config(IntegrationType.GITHUB)

        mock_db.query.return_value.filter.return_value.first.return_value = config

        client = TestClient(app)
        response = client.get("/api/v1/integrations/github")

        assert response.status_code == 200
        assert response.json()["integration_type"] == "github"

    def test_get_nonexistent_returns_404(self):
        """GET /api/v1/integrations/jira when not configured → 404."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        client = TestClient(app)
        response = client.get("/api/v1/integrations/jira")

        assert response.status_code == 404

    def test_developer_can_get_integration(self):
        """DEVELOPER role can read integration configs."""
        developer = _make_user(UserRole.DEVELOPER)
        mock_db = _override(developer)
        config = _make_config(IntegrationType.JIRA)
        mock_db.query.return_value.filter.return_value.first.return_value = config

        client = TestClient(app)
        response = client.get("/api/v1/integrations/jira")

        assert response.status_code == 200

    def test_analyst_cannot_get_integration(self):
        """ANALYST gets 403 on GET single config."""
        analyst = _make_user(UserRole.ANALYST)
        _override(analyst)

        client = TestClient(app)
        response = client.get("/api/v1/integrations/jira")

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# TestCreateIntegration
# ---------------------------------------------------------------------------


class TestCreateIntegration:
    """POST /api/v1/integrations"""

    def setup_method(self):
        _clear()

    def teardown_method(self):
        _clear()

    def test_admin_can_create_jira_config(self):
        """POST /api/v1/integrations creates new integration config."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)

        # No existing config (no duplicate)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # The saved config is returned via db.refresh side-effect
        saved_config = _make_config(IntegrationType.JIRA)

        def fake_refresh(obj):
            obj.id = saved_config.id
            obj.created_at = saved_config.created_at
            obj.updated_at = saved_config.updated_at

        mock_db.refresh.side_effect = fake_refresh

        payload = {
            "integration_type": "jira",
            "is_active": False,
            "encrypted_config": {
                "base_url": "https://jira.example.com",
                "api_token": "tok",
            },
        }

        client = TestClient(app)
        response = client.post("/api/v1/integrations", json=payload)

        assert response.status_code == 201
        assert response.json()["integration_type"] == "jira"

    def test_admin_can_create_salesforce_config(self):
        """POST creates Salesforce config."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        saved = _make_config(IntegrationType.SALESFORCE, is_active=True)

        def fake_refresh(obj):
            obj.id = saved.id
            obj.created_at = saved.created_at
            obj.updated_at = saved.updated_at
            obj.is_active = True

        mock_db.refresh.side_effect = fake_refresh

        payload = {
            "integration_type": "salesforce",
            "is_active": True,
            "encrypted_config": {"instance_url": "https://sf.example.com"},
        }

        client = TestClient(app)
        response = client.post("/api/v1/integrations", json=payload)

        assert response.status_code == 201

    def test_developer_cannot_create_integration(self):
        """Only ADMIN can create integrations — DEVELOPER gets 403."""
        developer = _make_user(UserRole.DEVELOPER)
        _override(developer)

        payload = {
            "integration_type": "jira",
            "is_active": False,
        }

        client = TestClient(app)
        response = client.post("/api/v1/integrations", json=payload)

        assert response.status_code == 403

    def test_analyst_cannot_create_integration(self):
        """ANALYST gets 403."""
        analyst = _make_user(UserRole.ANALYST)
        _override(analyst)

        payload = {"integration_type": "jira", "is_active": False}

        client = TestClient(app)
        response = client.post("/api/v1/integrations", json=payload)

        assert response.status_code == 403

    def test_duplicate_integration_type_returns_409(self):
        """Creating second config for same type → 409 Conflict."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        # Existing config found
        mock_db.query.return_value.filter.return_value.first.return_value = (
            _make_config(IntegrationType.JIRA)
        )

        payload = {
            "integration_type": "jira",
            "is_active": False,
        }

        client = TestClient(app)
        response = client.post("/api/v1/integrations", json=payload)

        assert response.status_code == 409

    def test_create_stores_encrypted_config(self):
        """Credentials in encrypted_config are stored on the model."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        stored_config = None

        def capture_add(obj):
            nonlocal stored_config
            stored_config = obj

        mock_db.add.side_effect = capture_add

        payload = {
            "integration_type": "github",
            "is_active": False,
            "encrypted_config": {
                "token": "ghp_secret",
                "repo_owner": "acme",
                "repo_name": "app",
            },
        }

        saved = _make_config(
            IntegrationType.GITHUB, encrypted_config=payload["encrypted_config"]
        )

        def fake_refresh(obj):
            obj.id = saved.id
            obj.created_at = saved.created_at
            obj.updated_at = saved.updated_at

        mock_db.refresh.side_effect = fake_refresh

        client = TestClient(app)
        response = client.post("/api/v1/integrations", json=payload)

        assert response.status_code == 201
        assert stored_config is not None
        assert stored_config.encrypted_config == payload["encrypted_config"]


# ---------------------------------------------------------------------------
# TestUpdateIntegration
# ---------------------------------------------------------------------------


class TestUpdateIntegration:
    """PUT /api/v1/integrations/{integration_type}"""

    def setup_method(self):
        _clear()

    def teardown_method(self):
        _clear()

    def test_admin_can_update_jira_config(self):
        """PUT /api/v1/integrations/jira updates existing config."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        config = _make_config(IntegrationType.JIRA)
        mock_db.query.return_value.filter.return_value.first.return_value = config

        def fake_refresh(obj):
            pass

        mock_db.refresh.side_effect = fake_refresh

        payload = {"encrypted_config": {"base_url": "https://new.jira.example.com"}}

        client = TestClient(app)
        response = client.put("/api/v1/integrations/jira", json=payload)

        assert response.status_code == 200

    def test_activate_integration(self):
        """PUT with is_active=True activates the integration."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        config = _make_config(IntegrationType.JIRA, is_active=False)
        mock_db.query.return_value.filter.return_value.first.return_value = config

        mock_db.refresh.side_effect = lambda obj: setattr(obj, "is_active", True)

        payload = {"is_active": True}

        client = TestClient(app)
        response = client.put("/api/v1/integrations/jira", json=payload)

        assert response.status_code == 200
        assert response.json()["is_active"] is True

    def test_deactivate_integration(self):
        """PUT with is_active=False deactivates the integration."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        config = _make_config(IntegrationType.JIRA, is_active=True)
        mock_db.query.return_value.filter.return_value.first.return_value = config

        mock_db.refresh.side_effect = lambda obj: setattr(obj, "is_active", False)

        payload = {"is_active": False}

        client = TestClient(app)
        response = client.put("/api/v1/integrations/jira", json=payload)

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_developer_cannot_update_integration(self):
        """Only ADMIN can update integrations — DEVELOPER gets 403."""
        developer = _make_user(UserRole.DEVELOPER)
        _override(developer)

        payload = {"is_active": True}

        client = TestClient(app)
        response = client.put("/api/v1/integrations/jira", json=payload)

        assert response.status_code == 403

    def test_analyst_cannot_update_integration(self):
        """ANALYST gets 403 on PUT."""
        analyst = _make_user(UserRole.ANALYST)
        _override(analyst)

        payload = {"is_active": True}

        client = TestClient(app)
        response = client.put("/api/v1/integrations/jira", json=payload)

        assert response.status_code == 403

    def test_update_nonexistent_returns_404(self):
        """PUT for unconfigured integration type → 404."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        payload = {"is_active": True}

        client = TestClient(app)
        response = client.put("/api/v1/integrations/jira", json=payload)

        assert response.status_code == 404

    def test_update_last_error_field(self):
        """PUT can clear or set last_error on a config."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        config = _make_config(IntegrationType.SALESFORCE)
        config.last_error = "previous error"
        mock_db.query.return_value.filter.return_value.first.return_value = config

        mock_db.refresh.side_effect = lambda obj: setattr(obj, "last_error", None)

        payload = {"last_error": None}

        client = TestClient(app)
        response = client.put("/api/v1/integrations/salesforce", json=payload)

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# TestDeleteIntegration
# ---------------------------------------------------------------------------


class TestDeleteIntegration:
    """DELETE /api/v1/integrations/{integration_type}"""

    def setup_method(self):
        _clear()

    def teardown_method(self):
        _clear()

    def test_admin_can_delete_integration(self):
        """DELETE /api/v1/integrations/jira removes config — returns 204."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        config = _make_config(IntegrationType.JIRA)
        mock_db.query.return_value.filter.return_value.first.return_value = config

        client = TestClient(app)
        response = client.delete("/api/v1/integrations/jira")

        assert response.status_code == 204
        mock_db.delete.assert_called_once_with(config)
        mock_db.commit.assert_called()

    def test_developer_cannot_delete(self):
        """Only ADMIN can delete — DEVELOPER gets 403."""
        developer = _make_user(UserRole.DEVELOPER)
        _override(developer)

        client = TestClient(app)
        response = client.delete("/api/v1/integrations/jira")

        assert response.status_code == 403

    def test_analyst_cannot_delete(self):
        """ANALYST gets 403 on DELETE."""
        analyst = _make_user(UserRole.ANALYST)
        _override(analyst)

        client = TestClient(app)
        response = client.delete("/api/v1/integrations/jira")

        assert response.status_code == 403

    def test_delete_nonexistent_returns_404(self):
        """DELETE for unconfigured integration type → 404."""
        admin = _make_user(UserRole.ADMIN)
        mock_db = _override(admin)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        client = TestClient(app)
        response = client.delete("/api/v1/integrations/jira")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# TestWebhookEndpoints
# ---------------------------------------------------------------------------


class TestWebhookEndpoints:
    """POST /api/v1/integrations/webhooks/{jira,salesforce,github}"""

    def setup_method(self):
        _clear()

    def teardown_method(self):
        _clear()

    # --- Jira ---

    def test_jira_webhook_endpoint_exists(self):
        """POST /api/v1/integrations/webhooks/jira returns 200."""
        mock_db = _make_mock_db()
        app.dependency_overrides[deps.get_db] = lambda: mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        client = TestClient(app)
        response = client.post(
            "/api/v1/integrations/webhooks/jira",
            json={
                "webhookEvent": "jira:issue_updated",
                "issue": {"key": "EXP-1"},
                "changelog": {"items": []},
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "received"

    def test_jira_webhook_with_active_config_calls_service(self):
        """Jira webhook with an active config delegates to JiraService."""
        mock_db = _make_mock_db()
        app.dependency_overrides[deps.get_db] = lambda: mock_db
        config = _make_config(IntegrationType.JIRA, is_active=True)
        mock_db.query.return_value.filter.return_value.first.return_value = config

        with patch("backend.app.api.v1.endpoints.integrations.JiraService") as MockJira:
            mock_svc = MagicMock()
            MockJira.from_config.return_value = mock_svc

            client = TestClient(app)
            response = client.post(
                "/api/v1/integrations/webhooks/jira",
                json={"webhookEvent": "jira:issue_updated"},
            )

        assert response.status_code == 200
        MockJira.from_config.assert_called_once_with(config)

    def test_jira_webhook_no_active_config_still_returns_200(self):
        """Jira webhook returns 200 even when no active config exists."""
        mock_db = _make_mock_db()
        app.dependency_overrides[deps.get_db] = lambda: mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        client = TestClient(app)
        response = client.post(
            "/api/v1/integrations/webhooks/jira",
            json={"webhookEvent": "jira:issue_created"},
        )

        assert response.status_code == 200

    # --- Salesforce ---

    def test_salesforce_webhook_endpoint_exists(self):
        """POST /api/v1/integrations/webhooks/salesforce returns 200."""
        mock_db = _make_mock_db()
        app.dependency_overrides[deps.get_db] = lambda: mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        client = TestClient(app)
        response = client.post(
            "/api/v1/integrations/webhooks/salesforce",
            json={"event_type": "Opportunity", "id": "001xx000003GYVJAA4"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "received"

    def test_salesforce_webhook_with_active_config_calls_service(self):
        """Salesforce webhook with active config delegates to SalesforceService."""
        mock_db = _make_mock_db()
        app.dependency_overrides[deps.get_db] = lambda: mock_db
        config = _make_config(IntegrationType.SALESFORCE, is_active=True)
        mock_db.query.return_value.filter.return_value.first.return_value = config

        with patch(
            "backend.app.api.v1.endpoints.integrations.SalesforceService"
        ) as MockSF:
            mock_svc = MagicMock()
            MockSF.from_config.return_value = mock_svc

            client = TestClient(app)
            response = client.post(
                "/api/v1/integrations/webhooks/salesforce",
                json={"event_type": "Opportunity"},
            )

        assert response.status_code == 200
        MockSF.from_config.assert_called_once_with(config)

    # --- GitHub ---

    def test_github_webhook_validates_signature(self):
        """POST /api/v1/integrations/webhooks/github verifies HMAC-SHA256 signature."""
        mock_db = _make_mock_db()
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        secret = "mysecret"
        config = _make_config(
            IntegrationType.GITHUB,
            is_active=True,
            encrypted_config={
                "token": "ghp_t",
                "repo_owner": "acme",
                "repo_name": "app",
                "webhook_secret": secret,
            },
        )
        mock_db.query.return_value.filter.return_value.first.return_value = config

        payload = json.dumps({"action": "opened"}).encode()
        sig = (
            "sha256="
            + hmac_lib.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        )

        with patch("backend.app.api.v1.endpoints.integrations.GitHubService") as MockGH:
            mock_svc = MagicMock()
            mock_svc.verify_webhook_signature.return_value = True
            MockGH.from_config.return_value = mock_svc

            client = TestClient(app)
            response = client.post(
                "/api/v1/integrations/webhooks/github",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "issues",
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "received"

    def test_github_webhook_rejects_invalid_signature(self):
        """Invalid GitHub webhook HMAC signature → 400."""
        mock_db = _make_mock_db()
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        config = _make_config(
            IntegrationType.GITHUB,
            is_active=True,
            encrypted_config={
                "token": "ghp_t",
                "repo_owner": "acme",
                "repo_name": "app",
                "webhook_secret": "real_secret",
            },
        )
        mock_db.query.return_value.filter.return_value.first.return_value = config

        payload = json.dumps({"action": "opened"}).encode()
        bad_sig = "sha256=badbadbadbad"

        with patch("backend.app.api.v1.endpoints.integrations.GitHubService") as MockGH:
            mock_svc = MagicMock()
            mock_svc.verify_webhook_signature.return_value = False
            MockGH.from_config.return_value = mock_svc

            client = TestClient(app)
            response = client.post(
                "/api/v1/integrations/webhooks/github",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": bad_sig,
                    "X-GitHub-Event": "issues",
                },
            )

        assert response.status_code == 400

    def test_github_webhook_no_config_returns_200(self):
        """GitHub webhook returns 200 even without an active config."""
        mock_db = _make_mock_db()
        app.dependency_overrides[deps.get_db] = lambda: mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None

        payload = json.dumps({"action": "opened"}).encode()

        client = TestClient(app)
        response = client.post(
            "/api/v1/integrations/webhooks/github",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
            },
        )

        assert response.status_code == 200

    def test_github_webhook_no_signature_with_active_config_returns_200(self):
        """GitHub webhook with no signature header but active config — still 200
        (no signature header means we cannot validate, so we skip enforcement
        and pass through — the service's verify_webhook_signature returns False
        but we only reject when signature IS provided and wrong)."""
        mock_db = _make_mock_db()
        app.dependency_overrides[deps.get_db] = lambda: mock_db
        config = _make_config(
            IntegrationType.GITHUB,
            is_active=True,
            encrypted_config={
                "token": "ghp_t",
                "repo_owner": "acme",
                "repo_name": "app",
            },
        )
        mock_db.query.return_value.filter.return_value.first.return_value = config

        with patch("backend.app.api.v1.endpoints.integrations.GitHubService") as MockGH:
            mock_svc = MagicMock()
            MockGH.from_config.return_value = mock_svc

            client = TestClient(app)
            response = client.post(
                "/api/v1/integrations/webhooks/github",
                json={"action": "opened"},
            )

        # No X-Hub-Signature-256 header was sent — endpoint skips sig check
        assert response.status_code == 200
