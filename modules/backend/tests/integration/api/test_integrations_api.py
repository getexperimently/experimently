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
  - Webhook endpoints: no platform user, but not anonymous either — the sender
    is authenticated against the integration's own `webhook_secret` (GitHub's
    X-Hub-Signature-256, Jira Cloud's X-Hub-Signature, or the secret itself in
    X-Experimently-Webhook-Secret) and refused with 401 otherwise.

Every response carrying a configuration shows only its connection settings
and names the other stored keys in `stored_secrets`, for every caller; `PUT`
merges `encrypted_config` key by key (see TestStoredSecretsAreNotReturned).

Most tests use the conftest.py role-specific client fixtures; the stored
secrets tests sign in a superuser, an ADMIN who is not a superuser and a
DEVELOPER with make_client_for_user.
"""

import copy
import hashlib
import hmac as hmac_lib
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user
from modules.backend.app.models.integration_config import (
    IntegrationConfig,
    IntegrationType,
)
from modules.backend.app.schemas.integration import IntegrationConfigResponse

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


#: Header a sender that cannot sign its body presents the shared secret in.
SECRET_HEADER = "X-Experimently-Webhook-Secret"

#: The reply every refused webhook gets, whatever went wrong.
UNAUTHENTICATED = {"detail": "Webhook authentication failed"}

WEBHOOK_SECRET = "integration-test-webhook-secret"


def _jira_creds(secret: str = WEBHOOK_SECRET) -> dict:
    return {
        "base_url": "https://jira.example.com",
        "api_token": "tok",
        "email": "bot@example.com",
        "webhook_secret": secret,
    }


def _salesforce_creds(secret: str = WEBHOOK_SECRET) -> dict:
    return {
        "instance_url": "https://acme.my.salesforce.com",
        "client_id": "cid",
        "client_secret": "csecret",
        "webhook_secret": secret,
    }


def _github_creds(secret: str = WEBHOOK_SECRET) -> dict:
    return {
        "token": "ghp_test_token",
        "repo_owner": "acme",
        "repo_name": "experiments",
        "webhook_secret": secret,
    }


def _stored_config(db_session: Session, integration_type: IntegrationType) -> dict:
    """The configuration as the database holds it now, not as a session cached it."""
    db_session.expire_all()
    row = (
        db_session.query(IntegrationConfig)
        .filter(IntegrationConfig.integration_type == integration_type)
        .one()
    )
    return row.encrypted_config


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
        """Admin can update the encrypted_config JSONB field.

        The keys sent are stored, merged with the one already there; none is
        on the shown list, so the response names all three and returns none.
        """
        _create_integration_in_db(
            db_session, IntegrationType.SALESFORCE, encrypted_config={"old": "data"}
        )
        payload = {"encrypted_config": {"new": "data", "token": "xyz"}}
        response = admin_client.put("/api/v1/integrations/salesforce", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert "new" not in body["encrypted_config"]
        assert body["stored_secrets"] == ["new", "old", "token"]
        assert _stored_config(db_session, IntegrationType.SALESFORCE) == {
            "old": "data",
            "new": "data",
            "token": "xyz",
        }


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
#
# These three routes are the platform's only anonymous write path, so the
# question each class below asks first is "who is calling?".  The clients are
# the role fixtures only because that is what conftest offers — no bearer
# token is used or needed here; what matters is the webhook secret.


@pytest.mark.integration
@pytest.mark.requires_db
class TestJiraWebhook:
    """Tests for POST /api/v1/integrations/webhooks/jira."""

    @pytest.mark.regression
    def test_jira_webhook_without_a_secret_is_401(self, admin_client, db_session):
        """An anonymous POST no longer reaches the service: it is refused."""
        _create_integration_in_db(
            db_session,
            IntegrationType.JIRA,
            is_active=True,
            encrypted_config=_jira_creds(),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/jira", json=_jira_payload()
        )
        assert response.status_code == 401, response.text
        assert response.json() == UNAUTHENTICATED

    def test_jira_webhook_with_a_valid_signature_returns_200(
        self, admin_client, db_session
    ):
        """Jira Cloud's X-Hub-Signature over the raw body is accepted."""
        _create_integration_in_db(
            db_session,
            IntegrationType.JIRA,
            is_active=True,
            encrypted_config=_jira_creds(),
        )
        body = json.dumps(_jira_payload()).encode()
        response = admin_client.post(
            "/api/v1/integrations/webhooks/jira",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature": _compute_github_signature(WEBHOOK_SECRET, body),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "received"

    def test_jira_webhook_with_the_shared_secret_returns_200(
        self, admin_client, db_session
    ):
        """A relay that cannot sign presents the secret itself."""
        _create_integration_in_db(
            db_session,
            IntegrationType.JIRA,
            is_active=True,
            encrypted_config=_jira_creds(),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/jira",
            json=_jira_payload(),
            headers={SECRET_HEADER: WEBHOOK_SECRET},
        )
        assert response.status_code == 200, response.text

    @pytest.mark.regression
    def test_jira_webhook_without_config_is_401(self, admin_client, db_session):
        """No configured integration answers exactly what a bad secret does."""
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.JIRA
        ).delete()
        db_session.commit()

        response = admin_client.post(
            "/api/v1/integrations/webhooks/jira",
            json=_jira_payload(),
            headers={SECRET_HEADER: WEBHOOK_SECRET},
        )
        assert response.status_code == 401, response.text
        assert response.json() == UNAUTHENTICATED

    def test_jira_webhook_invalid_json_returns_400_once_authenticated(
        self, admin_client, db_session
    ):
        """A malformed body is the caller's fault only after we know the caller."""
        _create_integration_in_db(
            db_session,
            IntegrationType.JIRA,
            is_active=True,
            encrypted_config=_jira_creds(),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/jira",
            content=b"not-json",
            headers={
                "Content-Type": "application/json",
                SECRET_HEADER: WEBHOOK_SECRET,
            },
        )
        assert response.status_code in (400, 422), response.text

    @pytest.mark.regression
    def test_jira_webhook_invalid_json_unauthenticated_is_401(
        self, admin_client, db_session
    ):
        """Authentication is decided before the body is parsed."""
        _create_integration_in_db(
            db_session,
            IntegrationType.JIRA,
            is_active=True,
            encrypted_config=_jira_creds(),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/jira",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 401, response.text


@pytest.mark.integration
@pytest.mark.requires_db
class TestSalesforceWebhook:
    """Tests for POST /api/v1/integrations/webhooks/salesforce."""

    @pytest.mark.regression
    def test_salesforce_webhook_without_a_secret_is_401(self, admin_client, db_session):
        """The handler used to verify nothing at all."""
        _create_integration_in_db(
            db_session,
            IntegrationType.SALESFORCE,
            is_active=True,
            encrypted_config=_salesforce_creds(),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/salesforce",
            json={"sObject": "Opportunity", "id": "abc123"},
        )
        assert response.status_code == 401, response.text
        assert response.json() == UNAUTHENTICATED

    def test_salesforce_webhook_with_the_shared_secret_returns_200(
        self, admin_client, db_session
    ):
        """An outbound message cannot sign, so the header is what it sends."""
        _create_integration_in_db(
            db_session,
            IntegrationType.SALESFORCE,
            is_active=True,
            encrypted_config=_salesforce_creds(),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/salesforce",
            json={"sObject": "Opportunity", "id": "abc123"},
            headers={SECRET_HEADER: WEBHOOK_SECRET},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "received"

    @pytest.mark.regression
    def test_salesforce_webhook_with_the_wrong_secret_is_401(
        self, admin_client, db_session
    ):
        _create_integration_in_db(
            db_session,
            IntegrationType.SALESFORCE,
            is_active=True,
            encrypted_config=_salesforce_creds(),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/salesforce",
            json={"sObject": "Opportunity"},
            headers={SECRET_HEADER: "not-the-secret"},
        )
        assert response.status_code == 401, response.text


@pytest.mark.integration
@pytest.mark.requires_db
class TestGitHubWebhook:
    """Tests for POST /api/v1/integrations/webhooks/github."""

    @pytest.mark.regression
    def test_github_webhook_no_signature_is_401(self, admin_client, db_session):
        """Omitting the header used to skip the check entirely."""
        _create_integration_in_db(
            db_session,
            IntegrationType.GITHUB,
            is_active=True,
            encrypted_config=_github_creds(),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/github",
            content=_github_payload(),
            headers={"Content-Type": "application/json", "X-GitHub-Event": "push"},
        )
        assert response.status_code == 401, response.text
        assert response.json() == UNAUTHENTICATED

    def test_github_webhook_valid_signature_returns_200(self, admin_client, db_session):
        """A correctly signed delivery is processed."""
        body = _github_payload()
        _create_integration_in_db(
            db_session,
            IntegrationType.GITHUB,
            is_active=True,
            encrypted_config=_github_creds(),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": _compute_github_signature(WEBHOOK_SECRET, body),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "received"

    def test_github_webhook_invalid_signature_is_401(self, admin_client, db_session):
        """A wrong HMAC is refused — and as 401, which is what the docs say."""
        body = _github_payload()
        _create_integration_in_db(
            db_session,
            IntegrationType.GITHUB,
            is_active=True,
            encrypted_config=_github_creds(),
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
        assert response.status_code == 401, response.text

    @pytest.mark.regression
    def test_github_webhook_config_without_a_secret_is_401(
        self, admin_client, db_session
    ):
        """Nothing to verify against means nothing is accepted."""
        body = _github_payload()
        _create_integration_in_db(
            db_session,
            IntegrationType.GITHUB,
            is_active=True,
            encrypted_config=_github_creds(secret=""),
        )
        response = admin_client.post(
            "/api/v1/integrations/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": _compute_github_signature(WEBHOOK_SECRET, body),
            },
        )
        assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# Stored secrets: named in every response, never returned
# ---------------------------------------------------------------------------
#
# Every response carrying a configuration shows the keys on
# schemas.integration.SHOWN_CONFIG_KEYS with their values and names every
# other stored key, sorted, in `stored_secrets`.  The caller makes no
# difference, so each test runs as a superuser, as an ADMIN who is not a
# superuser (the `admin_user` fixture is a superuser, which would hide a check
# keyed on the role), and, where the route lets it, as a DEVELOPER.

#: The values each configuration shows.
SHOWN = {
    IntegrationType.JIRA: {
        "base_url": "https://jira.example.com",
        "email": "bot@example.com",
        "project_key": "EXP",
    },
    IntegrationType.SALESFORCE: {
        "instance_url": "https://acme.my.salesforce.com",
        "client_id": "cid-shown",
    },
    IntegrationType.GITHUB: {"repo_owner": "acme", "repo_name": "experiments"},
}

#: The stored keys each configuration holds besides the shown ones.
SECRET_KEYS = {
    IntegrationType.JIRA: ["api_token", "webhook_secret"],
    IntegrationType.SALESFORCE: ["client_secret", "webhook_secret"],
    IntegrationType.GITHUB: ["token", "webhook_secret"],
}

READERS = ["superuser", "admin", "reader"]
WRITERS = ["superuser", "admin"]


def _sentinel(label: str) -> str:
    """A value that is in no response unless a stored secret was returned."""
    return f"SENTINEL-{label}-{uuid.uuid4().hex}"


def _caller(db_session: Session, kind: str) -> User:
    """A committed user: a superuser, or an ADMIN or DEVELOPER who is not one."""
    role = UserRole.DEVELOPER if kind == "reader" else UserRole.ADMIN
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"secrets_{kind}_{suffix}",
        email=f"secrets_{kind}_{suffix}@int.test",
        full_name=f"Stored secrets {kind}",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=kind == "superuser",
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _seed_all(db_session: Session, extra: dict = None) -> dict:
    """Store one configuration of each type, every secret a fresh sentinel.

    *extra* adds stored keys per type.  Returns every stored configuration.
    """
    stored = {}
    for integration_type, shown in SHOWN.items():
        config = dict(shown)
        for key in SECRET_KEYS[integration_type]:
            config[key] = _sentinel(f"{integration_type.value}-{key}")
        config.update((extra or {}).get(integration_type, {}))
        _create_integration_in_db(
            db_session, integration_type, is_active=True, encrypted_config=config
        )
        stored[integration_type] = config
    return stored


def _secret_values(stored: dict) -> list:
    """Every stored value that is not a shown setting."""
    return [
        value
        for integration_type, config in stored.items()
        for key, value in config.items()
        if key not in SHOWN[integration_type]
    ]


def _assert_none_returned(response, secrets: list) -> None:
    """No secret appears anywhere in the response body, in any field."""
    for value in secrets:
        assert value not in response.text, (
            f"a stored secret value is in the {response.request.method} "
            f"{response.request.url.path} response"
        )


@pytest.mark.integration
@pytest.mark.requires_db
class TestStoredSecretsAreNotReturned:
    """The responses name the stored secrets and never carry their values."""

    @pytest.mark.regression
    @pytest.mark.parametrize("kind", READERS)
    def test_reads_return_no_stored_secret_value(self, kind, db_session):
        """GET list and GET of each type: settings shown, secrets named only."""
        stored = _seed_all(db_session)
        secrets = _secret_values(stored)
        client = make_client_for_user(db_session, _caller(db_session, kind))

        listed = client.get("/api/v1/integrations")
        assert listed.status_code == 200, listed.text
        _assert_none_returned(listed, secrets)
        by_type = {item["integration_type"]: item for item in listed.json()}
        for integration_type in SHOWN:
            item = by_type[integration_type.value]
            assert item["encrypted_config"] == SHOWN[integration_type]
            assert item["stored_secrets"] == SECRET_KEYS[integration_type]

        for integration_type in SHOWN:
            one = client.get(f"/api/v1/integrations/{integration_type.value}")
            assert one.status_code == 200, one.text
            _assert_none_returned(one, secrets)
            assert one.json()["encrypted_config"] == SHOWN[integration_type]
            assert one.json()["stored_secrets"] == SECRET_KEYS[integration_type]

    @pytest.mark.regression
    @pytest.mark.parametrize("kind", WRITERS)
    def test_writes_return_no_stored_secret_value(self, kind, db_session):
        """POST and PUT answer with the same shape: no value they were sent."""
        stored = _seed_all(db_session)
        db_session.query(IntegrationConfig).filter(
            IntegrationConfig.integration_type == IntegrationType.JIRA
        ).delete()
        db_session.commit()
        client = make_client_for_user(db_session, _caller(db_session, kind))

        posted = dict(SHOWN[IntegrationType.JIRA])
        posted["api_token"] = _sentinel("posted-api-token")
        posted["webhook_secret"] = _sentinel("posted-webhook")
        created = client.post(
            "/api/v1/integrations",
            json={
                "integration_type": "jira",
                "is_active": True,
                "encrypted_config": posted,
            },
        )
        assert created.status_code == 201, created.text
        _assert_none_returned(created, [posted["api_token"], posted["webhook_secret"]])
        assert created.json()["encrypted_config"] == SHOWN[IntegrationType.JIRA]
        assert created.json()["stored_secrets"] == ["api_token", "webhook_secret"]

        new_token = _sentinel("put-token")
        updated = client.put(
            "/api/v1/integrations/github",
            json={"encrypted_config": {"token": new_token}},
        )
        assert updated.status_code == 200, updated.text
        _assert_none_returned(updated, [new_token] + _secret_values(stored))
        assert updated.json()["encrypted_config"] == SHOWN[IntegrationType.GITHUB]
        assert updated.json()["stored_secrets"] == ["token", "webhook_secret"]

    @pytest.mark.regression
    @pytest.mark.parametrize("kind", READERS)
    def test_a_key_not_on_the_shown_list_is_named_not_returned(self, kind, db_session):
        """What is shown is listed; any other key, however named, is withheld."""
        password = _sentinel("password")
        access_token = _sentinel("access-token")
        stored = _seed_all(
            db_session,
            extra={
                IntegrationType.GITHUB: {"password": password},
                IntegrationType.SALESFORCE: {"access_token": access_token},
            },
        )
        client = make_client_for_user(db_session, _caller(db_session, kind))

        listed = client.get("/api/v1/integrations")
        assert listed.status_code == 200, listed.text
        _assert_none_returned(listed, _secret_values(stored))

        github = client.get("/api/v1/integrations/github")
        assert github.status_code == 200, github.text
        _assert_none_returned(github, [password])
        assert github.json()["stored_secrets"] == [
            "password",
            "token",
            "webhook_secret",
        ]

        salesforce = client.get("/api/v1/integrations/salesforce")
        assert salesforce.status_code == 200, salesforce.text
        _assert_none_returned(salesforce, [access_token])
        assert salesforce.json()["stored_secrets"] == [
            "access_token",
            "client_secret",
            "webhook_secret",
        ]

    @pytest.mark.regression
    @pytest.mark.parametrize("kind", WRITERS)
    def test_reading_back_adding_a_key_and_sending_it_keeps_the_secrets(
        self, kind, db_session
    ):
        """The read-modify-write upgrade recipe keeps the stored API token.

        An integration created without a `webhook_secret` gets one the way the
        earlier documentation said: GET it, add the key to `encrypted_config`
        (`jq '{encrypted_config: (.encrypted_config + {webhook_secret: $s})}'`)
        and PUT the result.  The body sent carries no API token, because the
        GET returned none, and the stored one must survive; then a delivery
        signed with the new secret is accepted.
        """
        api_token = _sentinel("api-token")
        _create_integration_in_db(
            db_session,
            IntegrationType.JIRA,
            is_active=True,
            encrypted_config={**SHOWN[IntegrationType.JIRA], "api_token": api_token},
        )
        client = make_client_for_user(db_session, _caller(db_session, kind))
        new_secret = _sentinel("new-webhook")

        read = client.get("/api/v1/integrations/jira")
        assert read.status_code == 200, read.text
        body = {
            "encrypted_config": {
                **read.json()["encrypted_config"],
                "webhook_secret": new_secret,
            }
        }
        assert api_token not in json.dumps(body)

        written = client.put("/api/v1/integrations/jira", json=body)
        assert written.status_code == 200, written.text
        assert written.json()["stored_secrets"] == ["api_token", "webhook_secret"]
        assert _stored_config(db_session, IntegrationType.JIRA) == {
            **SHOWN[IntegrationType.JIRA],
            "api_token": api_token,
            "webhook_secret": new_secret,
        }

        delivery = json.dumps(_jira_payload()).encode()
        accepted = client.post(
            "/api/v1/integrations/webhooks/jira",
            content=delivery,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature": _compute_github_signature(new_secret, delivery),
            },
        )
        assert accepted.status_code == 200, accepted.text

    @pytest.mark.regression
    @pytest.mark.parametrize("kind", WRITERS)
    def test_put_merges_key_by_key_and_null_removes(self, kind, db_session):
        """A key sent as null is removed; a stored key not sent is kept."""
        api_token = _sentinel("api-token")
        webhook_secret = _sentinel("webhook")
        _create_integration_in_db(
            db_session,
            IntegrationType.JIRA,
            is_active=True,
            encrypted_config={
                **SHOWN[IntegrationType.JIRA],
                "api_token": api_token,
                "webhook_secret": webhook_secret,
            },
        )
        client = make_client_for_user(db_session, _caller(db_session, kind))

        removed = client.put(
            "/api/v1/integrations/jira", json={"encrypted_config": {"api_token": None}}
        )
        assert removed.status_code == 200, removed.text
        assert _stored_config(db_session, IntegrationType.JIRA) == {
            **SHOWN[IntegrationType.JIRA],
            "webhook_secret": webhook_secret,
        }
        assert removed.json()["stored_secrets"] == ["webhook_secret"]

        replacement = _sentinel("replacement-webhook")
        replaced = client.put(
            "/api/v1/integrations/jira",
            json={"encrypted_config": {"webhook_secret": replacement}},
        )
        assert replaced.status_code == 200, replaced.text
        assert _stored_config(db_session, IntegrationType.JIRA) == {
            **SHOWN[IntegrationType.JIRA],
            "webhook_secret": replacement,
        }

    @pytest.mark.regression
    @pytest.mark.parametrize("kind", READERS)
    def test_withheld_values_stay_stored(self, kind, db_session):
        """A secret left out of a response is still stored, and still used.

        The response is built from a copy: the configuration object it was
        built from, and the row, still hold every value after the reads.
        """
        stored = _seed_all(db_session)
        client = make_client_for_user(db_session, _caller(db_session, kind))

        assert client.get("/api/v1/integrations").status_code == 200
        for integration_type in SHOWN:
            one = client.get(f"/api/v1/integrations/{integration_type.value}")
            assert one.status_code == 200, one.text
            assert one.json()["stored_secrets"] == SECRET_KEYS[integration_type]
            assert (
                _stored_config(db_session, integration_type) == stored[integration_type]
            )

        row = (
            db_session.query(IntegrationConfig)
            .filter(IntegrationConfig.integration_type == IntegrationType.JIRA)
            .one()
        )
        before = copy.deepcopy(row.encrypted_config)
        response = IntegrationConfigResponse.model_validate(row)
        assert response.stored_secrets == SECRET_KEYS[IntegrationType.JIRA]
        assert row.encrypted_config == before
        assert response.encrypted_config is not row.encrypted_config
