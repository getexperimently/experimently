"""
Integration tests for the Third-Party Integrations API (EP-034).

Tests the full HTTP request/response cycle for:
  GET    /api/v1/integrations              — list all configs
  GET    /api/v1/integrations/{type}       — get single config by type
  POST   /api/v1/integrations             — create config (ADMIN only)
  PUT    /api/v1/integrations/{type}       — update config (ADMIN only)
  DELETE /api/v1/integrations/{type}       — delete config (ADMIN only)
  POST   /api/v1/integrations/webhooks/jira      — Jira webhook handler
  POST   /api/v1/integrations/webhooks/salesforce — Salesforce webhook
  POST   /api/v1/integrations/webhooks/github    — GitHub webhook (HMAC)

Permission model:
  - GET endpoints: ADMIN or DEVELOPER
  - POST/PUT/DELETE: ADMIN only
  - Webhook endpoints: unauthenticated (no auth required)

All tests use the conftest.py role-specific client fixtures.
"""

import hashlib
import hmac as hmac_lib
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.integration_config import IntegrationConfig, IntegrationType
from backend.app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_integration_in_db(
    db_session: Session,
    integration_type: IntegrationType = IntegrationType.JIRA,
    is_active: bool = True,
    encrypted_config: dict = None,
) -> IntegrationConfig:
    """Insert an IntegrationConfig directly into the test DB.

    Removes any existing config for the same integration_type first to
    avoid the unique-constraint violation across tests.
    """
    # Remove any pre-existing row for this type so we don't hit the unique constraint.
    db_session.query(IntegrationConfig).filter(
        IntegrationConfig.integration_type == integration_type
    ).delete()
    db_session.commit()

    config = IntegrationConfig(
        id=uuid.uuid4(),
        integration_type=integration_type,
        is_active=is_active,
        encrypted_config=encrypted_config or {"url": "https://jira.example.com"},
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


def _jira_payload() -> dict:
    """Minimal valid Jira webhook payload."""
    return {
        "webhookEvent": "jira:issue_updated",
        "issue": {
            "key": "EXP-123",
            "fields": {"status": {"name": "In Progress"}},
        },
    }


def _github_payload() -> bytes:
    """Minimal valid GitHub webhook payload as bytes."""
    return json.dumps({"action": "opened", "ref": "refs/heads/main"}).encode()


def _compute_github_signature(secret: str, body: bytes) -> str:
    """Compute the HMAC-SHA256 signature for a GitHub webhook."""
    sig = hmac_lib.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


# ---------------------------------------------------------------------------
# GET /api/v1/integrations — list all
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestListIntegrations:
    """Tests for GET /api/v1/integrations."""

    def test_admin_can_list_integrations(self, admin_client, db_session):
        """Admin gets 200 with a list of integration configs."""
        _create_integration_in_db(db_session, IntegrationType.JIRA)
        response = admin_client.get("/api/v1/integrations")
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)

    def test_developer_can_list_integrations(self, developer_client, db_session):
        """Developer role can read integrations list."""
        response = developer_client.get("/api/v1/integrations")
        assert response.status_code == 200, response.text

    def test_analyst_cannot_list_integrations(self, analyst_client):
        """Analyst role is forbidden from viewing integrations."""
        response = analyst_client.get("/api/v1/integrations")
        assert response.status_code == 403, response.text

    def test_viewer_cannot_list_integrations(self, viewer_client):
        """Viewer role is forbidden from viewing integrations."""
        response = viewer_client.get("/api/v1/integrations")
        assert response.status_code == 403, response.text

    def test_list_returns_integration_fields(self, admin_client, db_session):
        """Response items include expected integration config fields."""
        _create_integration_in_db(db_session, IntegrationType.GITHUB)
        response = admin_client.get("/api/v1/integrations")
        assert response.status_code == 200, response.text
        items = response.json()
        if items:
            item = items[0]
            assert "id" in item
            assert "integration_type" in item
            assert "is_active" in item
            assert "created_at" in item


# ---------------------------------------------------------------------------
# GET /api/v1/integrations/{type} — single config
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestGetIntegration:
    """Tests for GET /api/v1/integrations/{integration_type}."""

    def test_admin_can_get_existing_integration(self, admin_client, db_session):
        """Admin gets 200 when the integration type exists."""
        _create_integration_in_db(db_session, IntegrationType.JIRA)
        response = admin_client.get("/api/v1/integrations/jira")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["integration_type"] == "jira"

    def test_developer_can_get_existing_integration(self, developer_client, db_session):
        """Developer role can retrieve a specific integration config."""
        _create_integration_in_db(db_session, IntegrationType.SALESFORCE)
        response = developer_client.get("/api/v1/integrations/salesforce")
        assert response.status_code == 200, response.text

    def test_get_nonexistent_integration_returns_404(self, admin_client, db_session):
        """GET for an integration type not yet configured returns 404."""
        # Make sure there's no github config in the DB for this test
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.GITHUB
        ).delete()
        db_session.commit()
        response = admin_client.get("/api/v1/integrations/github")
        assert response.status_code == 404, response.text

    def test_analyst_cannot_get_integration(self, analyst_client, db_session):
        """Analyst role cannot access integration details."""
        response = analyst_client.get("/api/v1/integrations/jira")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# POST /api/v1/integrations — create
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestCreateIntegration:
    """Tests for POST /api/v1/integrations."""

    def test_admin_can_create_jira_integration(self, admin_client, db_session):
        """Admin creates a Jira integration config — returns 201."""
        # Clean up any existing jira config
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.JIRA
        ).delete()
        db_session.commit()

        payload = {
            "integration_type": "jira",
            "is_active": True,
            "encrypted_config": {"url": "https://jira.example.com", "token": "abc"},
        }
        response = admin_client.post("/api/v1/integrations", json=payload)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["integration_type"] == "jira"
        assert data["is_active"] is True

    def test_admin_can_create_github_integration(self, admin_client, db_session):
        """Admin creates a GitHub integration config."""
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.GITHUB
        ).delete()
        db_session.commit()

        payload = {
            "integration_type": "github",
            "is_active": False,
            "encrypted_config": {"owner": "acme", "repo": "experiments"},
        }
        response = admin_client.post("/api/v1/integrations", json=payload)
        assert response.status_code == 201, response.text
        assert response.json()["integration_type"] == "github"

    def test_duplicate_type_returns_409(self, admin_client, db_session):
        """Creating a duplicate integration type returns 409 Conflict."""
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.SALESFORCE
        ).delete()
        db_session.commit()

        payload = {
            "integration_type": "salesforce",
            "is_active": False,
        }
        admin_client.post("/api/v1/integrations", json=payload)
        response2 = admin_client.post("/api/v1/integrations", json=payload)
        assert response2.status_code == 409, response2.text

    def test_developer_cannot_create_integration(self, developer_client):
        """Developer role is forbidden from creating integrations."""
        payload = {"integration_type": "jira", "is_active": False}
        response = developer_client.post("/api/v1/integrations", json=payload)
        assert response.status_code == 403, response.text

    def test_analyst_cannot_create_integration(self, analyst_client):
        """Analyst role is forbidden from creating integrations."""
        payload = {"integration_type": "jira", "is_active": False}
        response = analyst_client.post("/api/v1/integrations", json=payload)
        assert response.status_code == 403, response.text

    def test_viewer_cannot_create_integration(self, viewer_client):
        """Viewer role is forbidden from creating integrations."""
        payload = {"integration_type": "jira", "is_active": False}
        response = viewer_client.post("/api/v1/integrations", json=payload)
        assert response.status_code == 403, response.text

    def test_create_returns_id_field(self, admin_client, db_session):
        """Created integration response includes a valid UUID id field."""
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.JIRA
        ).delete()
        db_session.commit()

        payload = {"integration_type": "jira", "is_active": False}
        response = admin_client.post("/api/v1/integrations", json=payload)
        assert response.status_code == 201, response.text
        data = response.json()
        assert "id" in data
        uuid.UUID(data["id"])  # Should parse without error


# ---------------------------------------------------------------------------
# PUT /api/v1/integrations/{type} — update
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestUpdateIntegration:
    """Tests for PUT /api/v1/integrations/{integration_type}."""

    def test_admin_can_update_integration(self, admin_client, db_session):
        """Admin updates an existing integration config — returns 200."""
        config = _create_integration_in_db(
            db_session, IntegrationType.JIRA, is_active=False
        )
        payload = {"is_active": True}
        response = admin_client.put("/api/v1/integrations/jira", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["is_active"] is True

    def test_update_nonexistent_integration_returns_404(self, admin_client, db_session):
        """PUT for a type not configured returns 404."""
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.GITHUB
        ).delete()
        db_session.commit()

        payload = {"is_active": True}
        response = admin_client.put("/api/v1/integrations/github", json=payload)
        assert response.status_code == 404, response.text

    def test_developer_cannot_update_integration(self, developer_client, db_session):
        """Developer role is forbidden from updating integrations."""
        _create_integration_in_db(db_session, IntegrationType.JIRA)
        response = developer_client.put(
            "/api/v1/integrations/jira", json={"is_active": False}
        )
        assert response.status_code == 403, response.text

    def test_update_encrypted_config(self, admin_client, db_session):
        """Admin can update the encrypted_config JSONB field."""
        _create_integration_in_db(
            db_session, IntegrationType.SALESFORCE, encrypted_config={"old": "data"}
        )
        payload = {"encrypted_config": {"new": "data", "token": "xyz"}}
        response = admin_client.put("/api/v1/integrations/salesforce", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["encrypted_config"]["new"] == "data"


# ---------------------------------------------------------------------------
# DELETE /api/v1/integrations/{type} — delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestDeleteIntegration:
    """Tests for DELETE /api/v1/integrations/{integration_type}."""

    def test_admin_can_delete_integration(self, admin_client, db_session):
        """Admin deletes an existing integration config — returns 204."""
        _create_integration_in_db(db_session, IntegrationType.JIRA)
        response = admin_client.delete("/api/v1/integrations/jira")
        assert response.status_code == 204, response.text

    def test_delete_nonexistent_returns_404(self, admin_client, db_session):
        """Deleting a non-existent integration type returns 404."""
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.GITHUB
        ).delete()
        db_session.commit()

        response = admin_client.delete("/api/v1/integrations/github")
        assert response.status_code == 404, response.text

    def test_developer_cannot_delete_integration(self, developer_client, db_session):
        """Developer role is forbidden from deleting integrations."""
        _create_integration_in_db(db_session, IntegrationType.JIRA)
        response = developer_client.delete("/api/v1/integrations/jira")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Webhook endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestJiraWebhook:
    """Tests for POST /api/v1/integrations/webhooks/jira."""

    def test_jira_webhook_returns_200_with_active_config(
        self, admin_client, db_session
    ):
        """Jira webhook with active config returns 200 {status: received}."""
        _create_integration_in_db(
            db_session,
            IntegrationType.JIRA,
            is_active=True,
            encrypted_config={"url": "https://jira.example.com", "token": "t"},
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/jira", json=_jira_payload()
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "received"

    def test_jira_webhook_returns_200_without_config(self, admin_client, db_session):
        """Jira webhook returns 200 even when no Jira config exists."""
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.JIRA
        ).delete()
        db_session.commit()

        response = admin_client.post(
            "/api/v1/integrations/webhooks/jira", json=_jira_payload()
        )
        assert response.status_code == 200, response.text

    def test_jira_webhook_invalid_json_returns_400(self, admin_client):
        """Jira webhook with non-JSON body returns 400."""
        from fastapi.testclient import TestClient

        response = admin_client.post(
            "/api/v1/integrations/webhooks/jira",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in (400, 422), response.text


@pytest.mark.integration
@pytest.mark.requires_db
class TestSalesforceWebhook:
    """Tests for POST /api/v1/integrations/webhooks/salesforce."""

    def test_salesforce_webhook_returns_200(self, admin_client, db_session):
        """Salesforce webhook returns 200 regardless of active config state."""
        response = admin_client.post(
            "/api/v1/integrations/webhooks/salesforce",
            json={"sObject": "Opportunity", "id": "abc123"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "received"


@pytest.mark.integration
@pytest.mark.requires_db
class TestGitHubWebhook:
    """Tests for POST /api/v1/integrations/webhooks/github."""

    def test_github_webhook_no_signature_returns_200(self, admin_client, db_session):
        """GitHub webhook without signature header still returns 200 (skip check)."""
        body = _github_payload()
        response = admin_client.post(
            "/api/v1/integrations/webhooks/github",
            content=body,
            headers={"Content-Type": "application/json", "X-GitHub-Event": "push"},
        )
        assert response.status_code == 200, response.text

    def test_github_webhook_valid_signature_returns_200(self, admin_client, db_session):
        """GitHub webhook with correct HMAC-SHA256 signature returns 200.

        GitHubService.from_config() requires token, repo_owner, and repo_name
        to be present in encrypted_config. When all credentials are present AND
        a valid signature is provided, the endpoint processes the event and
        returns {status: received}.
        """
        secret = "mysecret"
        body = _github_payload()

        _create_integration_in_db(
            db_session,
            IntegrationType.GITHUB,
            is_active=True,
            encrypted_config={
                "token": "ghp_test_token",
                "repo_owner": "acme",
                "repo_name": "experiments",
                "webhook_secret": secret,
            },
        )

        sig = _compute_github_signature(secret, body)
        response = admin_client.post(
            "/api/v1/integrations/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": sig,
            },
        )
        # 200 on valid signature — parse_webhook_event may log warnings but returns 200
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "received"

    def test_github_webhook_invalid_signature_returns_400(
        self, admin_client, db_session
    ):
        """GitHub webhook with wrong HMAC signature returns 400.

        GitHubService.from_config() requires token, repo_owner, and repo_name
        to be present for the service to instantiate and verify signatures.
        An invalid signature raises HTTP 400.
        """
        secret = "mysecret"
        body = _github_payload()

        _create_integration_in_db(
            db_session,
            IntegrationType.GITHUB,
            is_active=True,
            encrypted_config={
                "token": "ghp_test_token",
                "repo_owner": "acme",
                "repo_name": "experiments",
                "webhook_secret": secret,
            },
        )

        bad_sig = (
            "sha256=deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": bad_sig,
            },
        )
        assert response.status_code == 400, response.text
