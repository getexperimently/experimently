"""
Integration tests for EP-037 SSO/SAML & OIDC API.

Tests the full HTTP request/response cycle for:
  GET    /api/v1/auth/sso/configs           — list configs (admin only)
  POST   /api/v1/auth/sso/configs           — create config (admin only)
  GET    /api/v1/auth/sso/configs/{id}      — get config (admin only)
  PUT    /api/v1/auth/sso/configs/{id}      — update config (admin only)
  DELETE /api/v1/auth/sso/configs/{id}      — delete config (admin only)
  GET    /api/v1/auth/sso/saml/{id}/metadata — SP metadata XML
  POST   /api/v1/auth/sso/saml/{id}/acs    — SAML ACS (mocked)
  GET    /api/v1/auth/sso/oidc/google/login — redirects to Google
  GET    /api/v1/auth/sso/oidc/google/callback — OIDC callback (mocked)

All tests use the conftest.py role-specific client fixtures from
backend/tests/integration/conftest.py.
"""
from __future__ import annotations

import base64
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.sso_config import SSOConfig, SSOProviderType
from backend.app.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


BASE = "/api/v1/auth/sso"


def _saml_config_payload(**overrides) -> Dict[str, Any]:
    base = {
        "org_name": "Acme Corp",
        "org_domain": f"acme-{uuid.uuid4().hex[:6]}.com",
        "provider_type": "saml",
        "entity_id": "https://idp.acme.com",
        "sso_url": "https://idp.acme.com/sso",
        "x509_certificate": "MIIC...cert",
        "role_mapping": {"Admins": "admin", "Developers": "developer"},
        "is_enforced": False,
        "is_active": True,
    }
    base.update(overrides)
    return base


def _google_config_payload(**overrides) -> Dict[str, Any]:
    base = {
        "org_name": "Acme Corp Google",
        "org_domain": f"acme-google-{uuid.uuid4().hex[:6]}.com",
        "provider_type": "google",
        "entity_id": "google-client-id",
        "client_secret": "google-client-secret",
        "role_mapping": {},
        "is_enforced": False,
        "is_active": True,
    }
    base.update(overrides)
    return base


def _create_config(client: TestClient, payload: Dict) -> Dict:
    resp = client.post(f"{BASE}/configs", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_saml_response_b64(name_id: str = "user@acme.com") -> str:
    xml = (
        '<?xml version="1.0"?>'
        "<samlp:Response"
        ' xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"'
        ' xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
        "<saml:Assertion>"
        "<saml:Subject>"
        f"<saml:NameID>{name_id}</saml:NameID>"
        "</saml:Subject>"
        "</saml:Assertion>"
        "</samlp:Response>"
    )
    return base64.b64encode(xml.encode()).decode()


# ---------------------------------------------------------------------------
# GET /configs — list SSO configs
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestListSSOConfigs:
    def test_admin_can_list_configs(self, admin_client: TestClient):
        resp = admin_client.get(f"{BASE}/configs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_developer_gets_403(self, developer_client: TestClient):
        resp = developer_client.get(f"{BASE}/configs")
        assert resp.status_code == 403

    def test_analyst_gets_403(self, analyst_client: TestClient):
        resp = analyst_client.get(f"{BASE}/configs")
        assert resp.status_code == 403

    def test_viewer_gets_403(self, viewer_client: TestClient):
        resp = viewer_client.get(f"{BASE}/configs")
        assert resp.status_code == 403

    def test_empty_list_returns_array(self, admin_client: TestClient):
        resp = admin_client.get(f"{BASE}/configs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_created_config_appears_in_list(self, admin_client: TestClient):
        payload = _saml_config_payload()
        _create_config(admin_client, payload)
        resp = admin_client.get(f"{BASE}/configs")
        assert resp.status_code == 200
        domains = [c["org_domain"] for c in resp.json()]
        assert payload["org_domain"] in domains


# ---------------------------------------------------------------------------
# POST /configs — create SSO config
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestCreateSSOConfig:
    def test_admin_creates_saml_config(self, admin_client: TestClient):
        payload = _saml_config_payload()
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["provider_type"] == "saml"
        assert data["org_domain"] == payload["org_domain"]

    def test_admin_creates_google_config(self, admin_client: TestClient):
        payload = _google_config_payload()
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["provider_type"] == "google"

    def test_developer_cannot_create_config(self, developer_client: TestClient):
        payload = _saml_config_payload()
        resp = developer_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 403

    def test_duplicate_domain_returns_409(self, admin_client: TestClient):
        payload = _saml_config_payload()
        _create_config(admin_client, payload)
        # Second creation with same org_domain
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 409

    def test_missing_org_name_returns_422(self, admin_client: TestClient):
        payload = _saml_config_payload()
        del payload["org_name"]
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 422

    def test_missing_org_domain_returns_422(self, admin_client: TestClient):
        payload = _saml_config_payload()
        del payload["org_domain"]
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 422

    def test_missing_provider_type_returns_422(self, admin_client: TestClient):
        payload = _saml_config_payload()
        del payload["provider_type"]
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 422

    def test_invalid_provider_type_returns_422(self, admin_client: TestClient):
        payload = _saml_config_payload()
        payload["provider_type"] = "invalid_provider"
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 422

    def test_created_config_has_id(self, admin_client: TestClient):
        payload = _saml_config_payload()
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        uuid.UUID(data["id"])

    def test_created_config_has_timestamps(self, admin_client: TestClient):
        payload = _saml_config_payload()
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        data = resp.json()
        assert "created_at" in data
        assert "updated_at" in data

    def test_role_mapping_preserved(self, admin_client: TestClient):
        mapping = {"Admins": "admin", "Devs": "developer"}
        payload = _saml_config_payload(role_mapping=mapping)
        resp = admin_client.post(f"{BASE}/configs", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["role_mapping"] == mapping


# ---------------------------------------------------------------------------
# GET /configs/{id} — get specific SSO config
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestGetSSOConfig:
    def test_admin_can_get_config_by_id(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)
        resp = admin_client.get(f"{BASE}/configs/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_developer_gets_403(self, developer_client: TestClient, db_session: Session):
        # Create config directly in DB so we don't need admin_client (which would
        # overwrite the global dependency overrides and confuse developer_client).
        from backend.app.models.sso_config import SSOConfig, SSOProviderType as PT
        import uuid as _uuid
        cfg = SSOConfig(
            org_name="Dev Test Org",
            org_domain=f"devtest-{_uuid.uuid4().hex[:6]}.com",
            provider_type=PT.SAML,
            is_active=True,
            is_enforced=False,
        )
        db_session.add(cfg)
        db_session.commit()
        db_session.refresh(cfg)
        resp = developer_client.get(f"{BASE}/configs/{cfg.id}")
        assert resp.status_code == 403

    def test_nonexistent_id_returns_404(self, admin_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = admin_client.get(f"{BASE}/configs/{fake_id}")
        assert resp.status_code == 404

    def test_config_fields_are_correct(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)
        resp = admin_client.get(f"{BASE}/configs/{created['id']}")
        data = resp.json()
        assert data["org_name"] == payload["org_name"]
        assert data["provider_type"] == payload["provider_type"]
        assert data["entity_id"] == payload["entity_id"]


# ---------------------------------------------------------------------------
# PUT /configs/{id} — update SSO config
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestUpdateSSOConfig:
    def test_admin_can_update_config(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)

        update = {"org_name": "Updated Org Name"}
        resp = admin_client.put(f"{BASE}/configs/{created['id']}", json=update)
        assert resp.status_code == 200, resp.text
        assert resp.json()["org_name"] == "Updated Org Name"

    def test_developer_cannot_update(self, developer_client: TestClient, db_session: Session):
        from backend.app.models.sso_config import SSOConfig, SSOProviderType as PT
        import uuid as _uuid
        cfg = SSOConfig(
            org_name="Dev Update Test Org",
            org_domain=f"devupdate-{_uuid.uuid4().hex[:6]}.com",
            provider_type=PT.SAML,
            is_active=True,
            is_enforced=False,
        )
        db_session.add(cfg)
        db_session.commit()
        db_session.refresh(cfg)
        resp = developer_client.put(f"{BASE}/configs/{cfg.id}", json={"org_name": "X"})
        assert resp.status_code == 403

    def test_update_nonexistent_returns_404(self, admin_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = admin_client.put(f"{BASE}/configs/{fake_id}", json={"org_name": "X"})
        assert resp.status_code == 404

    def test_update_role_mapping(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)

        new_mapping = {"super-admins": "admin"}
        resp = admin_client.put(
            f"{BASE}/configs/{created['id']}",
            json={"role_mapping": new_mapping},
        )
        assert resp.status_code == 200
        assert resp.json()["role_mapping"] == new_mapping

    def test_update_is_active(self, admin_client: TestClient):
        payload = _saml_config_payload(is_active=True)
        created = _create_config(admin_client, payload)

        resp = admin_client.put(
            f"{BASE}/configs/{created['id']}",
            json={"is_active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_update_is_enforced(self, admin_client: TestClient):
        payload = _saml_config_payload(is_enforced=False)
        created = _create_config(admin_client, payload)

        resp = admin_client.put(
            f"{BASE}/configs/{created['id']}",
            json={"is_enforced": True},
        )
        assert resp.status_code == 200
        assert resp.json()["is_enforced"] is True


# ---------------------------------------------------------------------------
# DELETE /configs/{id} — delete SSO config
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestDeleteSSOConfig:
    def test_admin_can_delete_config(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)

        resp = admin_client.delete(f"{BASE}/configs/{created['id']}")
        assert resp.status_code == 204

    def test_deleted_config_not_found(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)

        admin_client.delete(f"{BASE}/configs/{created['id']}")
        resp = admin_client.get(f"{BASE}/configs/{created['id']}")
        assert resp.status_code == 404

    def test_developer_cannot_delete(self, developer_client: TestClient, db_session: Session):
        from backend.app.models.sso_config import SSOConfig, SSOProviderType as PT
        import uuid as _uuid
        cfg = SSOConfig(
            org_name="Dev Delete Test Org",
            org_domain=f"devdelete-{_uuid.uuid4().hex[:6]}.com",
            provider_type=PT.SAML,
            is_active=True,
            is_enforced=False,
        )
        db_session.add(cfg)
        db_session.commit()
        db_session.refresh(cfg)
        resp = developer_client.delete(f"{BASE}/configs/{cfg.id}")
        assert resp.status_code == 403

    def test_delete_nonexistent_returns_404(self, admin_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = admin_client.delete(f"{BASE}/configs/{fake_id}")
        assert resp.status_code == 404

    def test_deleted_config_not_in_list(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)
        admin_client.delete(f"{BASE}/configs/{created['id']}")

        resp = admin_client.get(f"{BASE}/configs")
        domains = [c["org_domain"] for c in resp.json()]
        assert payload["org_domain"] not in domains


# ---------------------------------------------------------------------------
# GET /saml/{config_id}/metadata — SP metadata XML
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestSAMLMetadata:
    def test_returns_xml_for_saml_config(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)

        resp = admin_client.get(f"{BASE}/saml/{created['id']}/metadata")
        assert resp.status_code == 200
        assert "xml" in resp.headers.get("content-type", "").lower()

    def test_xml_content_contains_entity_descriptor(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)

        resp = admin_client.get(f"{BASE}/saml/{created['id']}/metadata")
        text = resp.text
        assert "EntityDescriptor" in text or "entityID" in text

    def test_nonexistent_config_returns_404(self, admin_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = admin_client.get(f"{BASE}/saml/{fake_id}/metadata")
        assert resp.status_code == 404

    def test_non_saml_config_returns_400(self, admin_client: TestClient):
        payload = _google_config_payload()
        created = _create_config(admin_client, payload)

        resp = admin_client.get(f"{BASE}/saml/{created['id']}/metadata")
        assert resp.status_code == 400

    def test_metadata_is_valid_xml(self, admin_client: TestClient):
        import xml.etree.ElementTree as ET

        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)

        resp = admin_client.get(f"{BASE}/saml/{created['id']}/metadata")
        assert resp.status_code == 200
        ET.fromstring(resp.text)  # Should not raise


# ---------------------------------------------------------------------------
# POST /saml/{config_id}/acs — ACS endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestSAMLACS:
    def test_valid_saml_response_issues_token(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)

        saml_b64 = _make_saml_response_b64("newuser@acme.com")

        # Mock parse_saml_response to bypass actual SAML validation
        with patch(
            "backend.app.services.sso_service.parse_saml_response",
            return_value={
                "email": "newuser@acme.com",
                "name_id": "newuser@acme.com",
                "groups": [],
                "attributes": {},
                "first_name": "New",
                "last_name": "User",
            },
        ):
            resp = admin_client.post(
                f"{BASE}/saml/{created['id']}/acs",
                data={"SAMLResponse": saml_b64},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data

    def test_acs_returns_user_email(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)
        saml_b64 = _make_saml_response_b64("acs_user@acme.com")

        with patch(
            "backend.app.services.sso_service.parse_saml_response",
            return_value={
                "email": "acs_user@acme.com",
                "name_id": "acs_user@acme.com",
                "groups": [],
                "attributes": {},
                "first_name": None,
                "last_name": None,
            },
        ):
            resp = admin_client.post(
                f"{BASE}/saml/{created['id']}/acs",
                data={"SAMLResponse": saml_b64},
            )
        assert resp.status_code == 200
        assert resp.json()["email"] == "acs_user@acme.com"

    def test_acs_missing_saml_response_returns_400(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)

        resp = admin_client.post(f"{BASE}/saml/{created['id']}/acs", data={})
        assert resp.status_code == 400

    def test_acs_nonexistent_config_returns_404(self, admin_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = admin_client.post(
            f"{BASE}/saml/{fake_id}/acs",
            data={"SAMLResponse": "foo"},
        )
        assert resp.status_code == 404

    def test_acs_non_saml_config_returns_400(self, admin_client: TestClient):
        payload = _google_config_payload()
        created = _create_config(admin_client, payload)

        resp = admin_client.post(
            f"{BASE}/saml/{created['id']}/acs",
            data={"SAMLResponse": _make_saml_response_b64()},
        )
        assert resp.status_code == 400

    def test_acs_response_contains_token_type(self, admin_client: TestClient):
        payload = _saml_config_payload()
        created = _create_config(admin_client, payload)
        saml_b64 = _make_saml_response_b64("tokentype@acme.com")

        with patch(
            "backend.app.services.sso_service.parse_saml_response",
            return_value={
                "email": "tokentype@acme.com",
                "name_id": "tokentype@acme.com",
                "groups": [],
                "attributes": {},
                "first_name": None,
                "last_name": None,
            },
        ):
            resp = admin_client.post(
                f"{BASE}/saml/{created['id']}/acs",
                data={"SAMLResponse": saml_b64},
            )
        assert resp.json()["token_type"] == "bearer"


# ---------------------------------------------------------------------------
# GET /oidc/google/login — OIDC login redirect
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestOIDCLogin:
    def test_google_login_redirects(self, admin_client: TestClient):
        payload = _google_config_payload()
        _create_config(admin_client, payload)

        resp = admin_client.get(
            f"{BASE}/oidc/google/login",
            params={"org_domain": payload["org_domain"]},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers.get("location", "")
        assert "google" in location.lower() or "accounts" in location.lower()

    def test_unknown_provider_returns_404(self, admin_client: TestClient):
        resp = admin_client.get(
            f"{BASE}/oidc/nonexistent_provider/login",
            follow_redirects=False,
        )
        assert resp.status_code == 404

    def test_login_redirect_contains_client_id(self, admin_client: TestClient):
        payload = _google_config_payload()
        _create_config(admin_client, payload)

        resp = admin_client.get(
            f"{BASE}/oidc/google/login",
            params={"org_domain": payload["org_domain"]},
            follow_redirects=False,
        )
        location = resp.headers.get("location", "")
        assert "client_id" in location

    def test_login_redirect_contains_state(self, admin_client: TestClient):
        payload = _google_config_payload()
        _create_config(admin_client, payload)

        resp = admin_client.get(
            f"{BASE}/oidc/google/login",
            params={"org_domain": payload["org_domain"]},
            follow_redirects=False,
        )
        location = resp.headers.get("location", "")
        assert "state=" in location


# ---------------------------------------------------------------------------
# GET /oidc/google/callback — OIDC callback
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestOIDCCallback:
    def test_google_callback_issues_token(self, admin_client: TestClient):
        payload = _google_config_payload()
        _create_config(admin_client, payload)

        with patch(
            "backend.app.services.sso_service.exchange_oidc_code",
            new_callable=AsyncMock,
            return_value={"access_token": "google-at"},
        ), patch(
            "backend.app.services.sso_service.get_oidc_user_info",
            new_callable=AsyncMock,
            return_value={
                "email": "alice@acme.com",
                "name": "Alice",
                "sub": "google-sub-123",
                "groups": [],
                "raw": {},
            },
        ):
            resp = admin_client.get(
                f"{BASE}/oidc/google/callback",
                params={
                    "code": "auth-code",
                    "org_domain": payload["org_domain"],
                },
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert data["provider"] == "google"

    def test_callback_missing_code_returns_400(self, admin_client: TestClient):
        resp = admin_client.get(
            f"{BASE}/oidc/google/callback",
            params={"state": "some-state"},
        )
        assert resp.status_code == 400

    def test_callback_with_error_param_returns_400(self, admin_client: TestClient):
        resp = admin_client.get(
            f"{BASE}/oidc/google/callback",
            params={"error": "access_denied"},
        )
        assert resp.status_code == 400

    def test_callback_unknown_provider_returns_404(self, admin_client: TestClient):
        with patch(
            "backend.app.services.sso_service.exchange_oidc_code",
            new_callable=AsyncMock,
            return_value={"access_token": "token"},
        ), patch(
            "backend.app.services.sso_service.get_oidc_user_info",
            new_callable=AsyncMock,
            return_value={"email": "alice@acme.com", "sub": "123", "groups": [], "raw": {}},
        ):
            resp = admin_client.get(
                f"{BASE}/oidc/nonexistent/callback",
                params={"code": "auth-code"},
            )
        assert resp.status_code == 404

    def test_callback_returns_user_email(self, admin_client: TestClient):
        payload = _google_config_payload()
        _create_config(admin_client, payload)

        with patch(
            "backend.app.services.sso_service.exchange_oidc_code",
            new_callable=AsyncMock,
            return_value={"access_token": "google-at"},
        ), patch(
            "backend.app.services.sso_service.get_oidc_user_info",
            new_callable=AsyncMock,
            return_value={
                "email": "bob@acme.com",
                "name": "Bob",
                "sub": "sub-456",
                "groups": [],
                "raw": {},
            },
        ):
            resp = admin_client.get(
                f"{BASE}/oidc/google/callback",
                params={
                    "code": "auth-code",
                    "org_domain": payload["org_domain"],
                },
            )
        assert resp.status_code == 200
        assert resp.json()["email"] == "bob@acme.com"

    def test_callback_returns_role(self, admin_client: TestClient):
        payload = _google_config_payload()
        _create_config(admin_client, payload)

        with patch(
            "backend.app.services.sso_service.exchange_oidc_code",
            new_callable=AsyncMock,
            return_value={"access_token": "google-at"},
        ), patch(
            "backend.app.services.sso_service.get_oidc_user_info",
            new_callable=AsyncMock,
            return_value={
                "email": f"role_user_{uuid.uuid4().hex[:4]}@acme.com",
                "name": "Role User",
                "sub": "sub-789",
                "groups": [],
                "raw": {},
            },
        ):
            resp = admin_client.get(
                f"{BASE}/oidc/google/callback",
                params={
                    "code": "auth-code",
                    "org_domain": payload["org_domain"],
                },
            )
        assert resp.status_code == 200
        assert "role" in resp.json()
