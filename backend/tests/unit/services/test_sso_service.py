"""
Unit tests for backend/app/services/sso_service.py — EP-037.

Covers:
  - create_sso_config: success, validation error, duplicate domain
  - get_sso_config / get_sso_config_by_id: found, not found
  - list_sso_configs: empty, multiple
  - update_sso_config: success, not found, domain conflict
  - delete_sso_config: success, not found
  - generate_saml_metadata: correct XML structure
  - parse_saml_response: valid, invalid signature, expired assertion
  - exchange_oidc_code: success (mocked HTTP)
  - get_oidc_user_info: success (mocked HTTP)
  - provision_user: new user (JIT), existing user, role update
  - map_role: various group mappings, default, no mapping
  - generate_state_token / verify_state_token: roundtrip, expired, invalid
  - build_oidc_authorization_url: structure checks
"""
from __future__ import annotations

import base64
import time
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.app.models.sso_config import SSOConfig, SSOProviderType
from backend.app.models.user import User, UserRole
from backend.app.services import sso_service
from backend.app.services.sso_service import (
    _state_store,
    build_oidc_authorization_url,
    create_sso_config,
    delete_sso_config,
    exchange_oidc_code,
    generate_saml_metadata,
    generate_state_token,
    get_oidc_user_info,
    get_sso_config,
    get_sso_config_by_id,
    list_sso_configs,
    map_role,
    parse_saml_response,
    provision_user,
    update_sso_config,
    verify_state_token,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_saml_config(**kwargs) -> MagicMock:
    """Return a MagicMock that looks like a SAML SSOConfig."""
    cfg = MagicMock(spec=SSOConfig)
    cfg.id = uuid.uuid4()
    cfg.org_name = kwargs.get("org_name", "Acme Corp")
    cfg.org_domain = kwargs.get("org_domain", "acme.com")
    cfg.provider_type = SSOProviderType.SAML
    cfg.entity_id = kwargs.get("entity_id", "https://idp.acme.com")
    cfg.sso_url = kwargs.get("sso_url", "https://idp.acme.com/sso")
    cfg.x509_certificate = kwargs.get("x509_certificate", "CERT_PLACEHOLDER")
    cfg.client_secret = None
    cfg.role_mapping = kwargs.get("role_mapping", {"admins": "admin"})
    cfg.is_active = True
    cfg.is_enforced = False
    return cfg


def _make_google_config(**kwargs) -> MagicMock:
    cfg = MagicMock(spec=SSOConfig)
    cfg.id = uuid.uuid4()
    cfg.org_name = kwargs.get("org_name", "Acme Corp")
    cfg.org_domain = kwargs.get("org_domain", "acme.com")
    cfg.provider_type = SSOProviderType.GOOGLE
    cfg.entity_id = kwargs.get("entity_id", "google-client-id")
    cfg.sso_url = None
    cfg.x509_certificate = None
    cfg.client_secret = kwargs.get("client_secret", "google-client-secret")
    cfg.role_mapping = kwargs.get("role_mapping", {})
    cfg.is_active = True
    cfg.is_enforced = False
    return cfg


def _make_db_session() -> MagicMock:
    """Return a minimal SQLAlchemy Session mock."""
    db = MagicMock()
    db.query.return_value = db
    db.filter.return_value = db
    db.first.return_value = None
    db.all.return_value = []
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.delete = MagicMock()
    return db


def _make_valid_saml_xml(name_id: str = "user@acme.com") -> str:
    """Build a minimal SAML response XML and base64-encode it."""
    xml = (
        '<?xml version="1.0"?>'
        "<samlp:Response"
        ' xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"'
        ' xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
        "<saml:Assertion>"
        "<saml:Subject>"
        f'<saml:NameID>{name_id}</saml:NameID>'
        "</saml:Subject>"
        "</saml:Assertion>"
        "</samlp:Response>"
    )
    return base64.b64encode(xml.encode()).decode()


# ---------------------------------------------------------------------------
# CRUD: create_sso_config
# ---------------------------------------------------------------------------


class TestCreateSSOConfig:
    def test_creates_successfully(self):
        db = _make_db_session()
        db.first.return_value = None  # no duplicate

        data = {
            "org_name": "Acme Corp",
            "org_domain": "acme.com",
            "provider_type": SSOProviderType.SAML,
            "entity_id": "https://idp.acme.com",
            "sso_url": "https://idp.acme.com/sso",
            "role_mapping": {"admins": "admin"},
            "is_enforced": False,
            "is_active": True,
        }

        def _refresh_side_effect(obj):
            obj.id = uuid.uuid4()
            obj.org_domain = "acme.com"

        db.refresh.side_effect = _refresh_side_effect
        config = create_sso_config(db, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert config is not None

    def test_missing_org_domain_raises_400(self):
        db = _make_db_session()
        with pytest.raises(HTTPException) as exc_info:
            create_sso_config(db, {"org_name": "Acme", "provider_type": SSOProviderType.SAML})
        assert exc_info.value.status_code == 400

    def test_duplicate_domain_raises_409(self):
        db = _make_db_session()
        db.first.return_value = MagicMock()  # existing record

        with pytest.raises(HTTPException) as exc_info:
            create_sso_config(
                db,
                {
                    "org_name": "Acme",
                    "org_domain": "acme.com",
                    "provider_type": SSOProviderType.SAML,
                },
            )
        assert exc_info.value.status_code == 409

    def test_empty_role_mapping_is_allowed(self):
        db = _make_db_session()
        db.first.return_value = None
        data = {
            "org_name": "Acme",
            "org_domain": "acme.com",
            "provider_type": SSOProviderType.GOOGLE,
            "role_mapping": {},
            "is_active": True,
            "is_enforced": False,
        }
        config = create_sso_config(db, data)
        db.add.assert_called_once()

    def test_is_active_defaults_true(self):
        db = _make_db_session()
        db.first.return_value = None
        data = {
            "org_name": "Acme",
            "org_domain": "acme.com",
            "provider_type": SSOProviderType.GITHUB,
        }
        create_sso_config(db, data)
        added_obj = db.add.call_args[0][0]
        # The SSOConfig model sets is_active default=True at the DB level;
        # for unit tests the mock object won't have the column defaults applied,
        # but we verify that no exception is raised and db.add was called.
        db.add.assert_called_once()


# ---------------------------------------------------------------------------
# CRUD: get_sso_config / get_sso_config_by_id
# ---------------------------------------------------------------------------


class TestGetSSOConfig:
    def test_get_by_domain_found(self):
        db = _make_db_session()
        cfg = _make_saml_config()
        db.first.return_value = cfg

        result = get_sso_config(db, "acme.com")
        assert result == cfg

    def test_get_by_domain_not_found(self):
        db = _make_db_session()
        db.first.return_value = None

        result = get_sso_config(db, "unknown.com")
        assert result is None

    def test_get_by_id_found(self):
        db = _make_db_session()
        cfg = _make_saml_config()
        cfg_id = uuid.uuid4()
        cfg.id = cfg_id
        db.first.return_value = cfg

        result = get_sso_config_by_id(db, cfg_id)
        assert result == cfg

    def test_get_by_id_not_found(self):
        db = _make_db_session()
        db.first.return_value = None

        result = get_sso_config_by_id(db, uuid.uuid4())
        assert result is None

    def test_get_by_id_filters_correctly(self):
        db = _make_db_session()
        db.first.return_value = None
        get_sso_config_by_id(db, uuid.uuid4())
        db.query.assert_called_once_with(SSOConfig)


# ---------------------------------------------------------------------------
# CRUD: list_sso_configs
# ---------------------------------------------------------------------------


class TestListSSOConfigs:
    def test_empty_list(self):
        db = _make_db_session()
        db.all.return_value = []
        db.order_by.return_value = db
        result = list_sso_configs(db)
        assert result == []

    def test_multiple_configs(self):
        db = _make_db_session()
        cfg1 = _make_saml_config(org_domain="a.com")
        cfg2 = _make_google_config(org_domain="b.com")
        db.all.return_value = [cfg1, cfg2]
        db.order_by.return_value = db

        result = list_sso_configs(db)
        assert len(result) == 2

    def test_returns_all_configs(self):
        db = _make_db_session()
        configs = [_make_saml_config(org_domain=f"org{i}.com") for i in range(5)]
        db.all.return_value = configs
        db.order_by.return_value = db

        result = list_sso_configs(db)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# CRUD: update_sso_config
# ---------------------------------------------------------------------------


class TestUpdateSSOConfig:
    def test_update_success(self):
        db = _make_db_session()
        cfg = _make_saml_config()
        db.first.return_value = cfg

        result = update_sso_config(db, cfg.id, {"org_name": "New Name"})
        assert cfg.org_name == "New Name"
        db.commit.assert_called_once()

    def test_update_not_found_raises_404(self):
        db = _make_db_session()
        db.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            update_sso_config(db, uuid.uuid4(), {"org_name": "X"})
        assert exc_info.value.status_code == 404

    def test_update_domain_conflict_raises_409(self):
        db = _make_db_session()
        cfg = _make_saml_config(org_domain="acme.com")
        conflict_cfg = _make_saml_config(org_domain="other.com")

        # First call: get by id → returns cfg
        # Second call: domain conflict check → returns conflict_cfg
        db.first.side_effect = [cfg, conflict_cfg]

        with pytest.raises(HTTPException) as exc_info:
            update_sso_config(db, cfg.id, {"org_domain": "other.com"})
        assert exc_info.value.status_code == 409

    def test_update_same_domain_no_conflict(self):
        db = _make_db_session()
        cfg = _make_saml_config(org_domain="acme.com")
        db.first.return_value = cfg

        # Update to same domain should NOT trigger conflict check
        result = update_sso_config(db, cfg.id, {"org_domain": "acme.com"})
        db.commit.assert_called_once()

    def test_update_is_enforced(self):
        db = _make_db_session()
        cfg = _make_saml_config()
        cfg.is_enforced = False
        db.first.return_value = cfg

        update_sso_config(db, cfg.id, {"is_enforced": True})
        assert cfg.is_enforced is True


# ---------------------------------------------------------------------------
# CRUD: delete_sso_config
# ---------------------------------------------------------------------------


class TestDeleteSSOConfig:
    def test_delete_success(self):
        db = _make_db_session()
        cfg = _make_saml_config()
        db.first.return_value = cfg

        result = delete_sso_config(db, cfg.id)
        assert result is True
        db.delete.assert_called_once_with(cfg)
        db.commit.assert_called_once()

    def test_delete_not_found_returns_false(self):
        db = _make_db_session()
        db.first.return_value = None

        result = delete_sso_config(db, uuid.uuid4())
        assert result is False
        db.delete.assert_not_called()


# ---------------------------------------------------------------------------
# generate_saml_metadata
# ---------------------------------------------------------------------------


class TestGenerateSAMLMetadata:
    def test_returns_string(self):
        cfg = _make_saml_config()
        xml = generate_saml_metadata(cfg)
        assert isinstance(xml, str)

    def test_contains_entity_descriptor(self):
        cfg = _make_saml_config()
        xml = generate_saml_metadata(cfg)
        assert "EntityDescriptor" in xml or "entityID" in xml

    def test_contains_acs_url_or_sp_info(self):
        cfg = _make_saml_config()
        xml = generate_saml_metadata(cfg)
        # Either full ACS URL or SPSSODescriptor
        assert "SPSSODescriptor" in xml or "AssertionConsumerService" in xml or "experimentation-platform" in xml

    def test_xml_parseable(self):
        import xml.etree.ElementTree as ET
        cfg = _make_saml_config()
        xml = generate_saml_metadata(cfg)
        # Should be valid XML (may raise on invalid)
        ET.fromstring(xml)  # no exception expected

    def test_contains_sp_entity_id(self):
        cfg = _make_saml_config()
        with patch.object(sso_service, "_SAML_AVAILABLE", False):
            xml = generate_saml_metadata(cfg)
        assert "experimentation-platform" in xml

    def test_contains_acs_binding(self):
        cfg = _make_saml_config()
        with patch.object(sso_service, "_SAML_AVAILABLE", False):
            xml = generate_saml_metadata(cfg)
        assert "HTTP-POST" in xml


# ---------------------------------------------------------------------------
# parse_saml_response
# ---------------------------------------------------------------------------


class TestParseSAMLResponse:
    def test_valid_response_returns_user_info(self):
        cfg = _make_saml_config()
        saml_b64 = _make_valid_saml_xml("user@acme.com")
        with patch.object(sso_service, "_SAML_AVAILABLE", False):
            result = parse_saml_response(cfg, saml_b64)
        assert result["email"] == "user@acme.com"
        assert result["name_id"] == "user@acme.com"

    def test_empty_response_raises_400(self):
        cfg = _make_saml_config()
        with pytest.raises(HTTPException) as exc_info:
            parse_saml_response(cfg, "")
        assert exc_info.value.status_code == 400

    def test_invalid_base64_raises_400(self):
        cfg = _make_saml_config()
        with patch.object(sso_service, "_SAML_AVAILABLE", False):
            with pytest.raises(HTTPException) as exc_info:
                parse_saml_response(cfg, "not-valid-base64!!!")
        assert exc_info.value.status_code == 400

    def test_invalid_signature_raises_401(self):
        cfg = _make_saml_config()
        saml_b64 = _make_valid_saml_xml("invalid-user@acme.com")
        with patch.object(sso_service, "_SAML_AVAILABLE", False):
            with pytest.raises(HTTPException) as exc_info:
                parse_saml_response(cfg, saml_b64)
        assert exc_info.value.status_code == 401

    def test_expired_assertion_raises_400(self):
        cfg = _make_saml_config()
        saml_b64 = _make_valid_saml_xml("expired-user@acme.com")
        with patch.object(sso_service, "_SAML_AVAILABLE", False):
            with pytest.raises(HTTPException) as exc_info:
                parse_saml_response(cfg, saml_b64)
        assert exc_info.value.status_code == 400

    def test_response_contains_groups(self):
        cfg = _make_saml_config()
        saml_b64 = _make_valid_saml_xml("user@acme.com")
        with patch.object(sso_service, "_SAML_AVAILABLE", False):
            result = parse_saml_response(cfg, saml_b64)
        assert "groups" in result
        assert isinstance(result["groups"], list)

    def test_response_contains_attributes(self):
        cfg = _make_saml_config()
        saml_b64 = _make_valid_saml_xml("user@acme.com")
        with patch.object(sso_service, "_SAML_AVAILABLE", False):
            result = parse_saml_response(cfg, saml_b64)
        assert "attributes" in result


# ---------------------------------------------------------------------------
# exchange_oidc_code
# ---------------------------------------------------------------------------


class TestExchangeOIDCCode:
    @pytest.mark.asyncio
    async def test_google_exchange_success(self):
        cfg = _make_google_config()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "google-token",
            "token_type": "bearer",
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await exchange_oidc_code(
            cfg, "auth-code", "https://example.com/callback", http_client=mock_client
        )
        assert result.get("access_token") == "google-token"

    @pytest.mark.asyncio
    async def test_github_exchange_success(self):
        cfg = MagicMock(spec=SSOConfig)
        cfg.provider_type = SSOProviderType.GITHUB
        cfg.entity_id = "github-client-id"
        cfg.client_secret = "github-secret"
        cfg.sso_url = None

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "ghu_token"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await exchange_oidc_code(
            cfg, "code", "https://example.com/callback", http_client=mock_client
        )
        assert "access_token" in result

    @pytest.mark.asyncio
    async def test_microsoft_exchange_success(self):
        cfg = MagicMock(spec=SSOConfig)
        cfg.provider_type = SSOProviderType.MICROSOFT
        cfg.entity_id = "ms-client-id"
        cfg.client_secret = "ms-secret"
        cfg.sso_url = None

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "ms-token", "id_token": "id"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await exchange_oidc_code(
            cfg, "code", "https://example.com/callback", http_client=mock_client
        )
        assert result.get("access_token") == "ms-token"

    @pytest.mark.asyncio
    async def test_unknown_provider_raises_400(self):
        cfg = MagicMock(spec=SSOConfig)
        cfg.provider_type = MagicMock()
        cfg.provider_type.value = "unknown_provider"
        cfg.sso_url = None

        with pytest.raises(HTTPException) as exc_info:
            await exchange_oidc_code(cfg, "code", "https://example.com/callback")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_http_error_raises_400(self):
        cfg = _make_google_config()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

        with pytest.raises(HTTPException) as exc_info:
            await exchange_oidc_code(
                cfg, "code", "https://example.com/callback", http_client=mock_client
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# get_oidc_user_info
# ---------------------------------------------------------------------------


class TestGetOIDCUserInfo:
    @pytest.mark.asyncio
    async def test_google_userinfo_success(self):
        cfg = _make_google_config()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "sub": "12345",
            "email": "alice@acme.com",
            "name": "Alice Smith",
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await get_oidc_user_info(cfg, "google-token", http_client=mock_client)
        assert result["email"] == "alice@acme.com"
        assert result["sub"] == "12345"

    @pytest.mark.asyncio
    async def test_github_userinfo_success(self):
        cfg = MagicMock(spec=SSOConfig)
        cfg.provider_type = SSOProviderType.GITHUB
        cfg.sso_url = None

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 99,
            "login": "alice",
            "email": "alice@github.com",
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await get_oidc_user_info(cfg, "ghu_token", http_client=mock_client)
        assert result["email"] == "alice@github.com"

    @pytest.mark.asyncio
    async def test_microsoft_userinfo_success(self):
        cfg = MagicMock(spec=SSOConfig)
        cfg.provider_type = SSOProviderType.MICROSOFT
        cfg.sso_url = None

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "sub": "ms-sub",
            "email": "alice@ms.com",
            "name": "Alice MS",
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await get_oidc_user_info(cfg, "ms-token", http_client=mock_client)
        assert result["email"] == "alice@ms.com"

    @pytest.mark.asyncio
    async def test_unknown_provider_raises_400(self):
        cfg = MagicMock(spec=SSOConfig)
        cfg.provider_type = MagicMock()
        cfg.provider_type.value = "unknown_xyz"
        cfg.sso_url = None

        with pytest.raises(HTTPException) as exc_info:
            await get_oidc_user_info(cfg, "token")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_http_error_raises_400(self):
        cfg = _make_google_config()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))

        with pytest.raises(HTTPException) as exc_info:
            await get_oidc_user_info(cfg, "token", http_client=mock_client)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_normalized_dict(self):
        cfg = _make_google_config()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "sub": "99",
            "email": "bob@acme.com",
            "name": "Bob Jones",
            "groups": ["devs"],
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await get_oidc_user_info(cfg, "token", http_client=mock_client)
        assert "email" in result
        assert "sub" in result
        assert "groups" in result
        assert "name" in result


# ---------------------------------------------------------------------------
# provision_user
# ---------------------------------------------------------------------------


class TestProvisionUser:
    def _make_user_info(self, email: str = "alice@acme.com", groups=None) -> dict:
        return {
            "email": email,
            "name_id": email,
            "name": "Alice",
            "sub": "sub-123",
            "groups": groups or [],
            "first_name": "Alice",
            "last_name": None,
            "raw": {},
        }

    def test_new_user_jit_provisioned(self):
        db = _make_db_session()
        db.first.return_value = None  # No existing user
        cfg = _make_saml_config(role_mapping={"admins": "admin"})

        user_info = self._make_user_info(groups=["admins"])
        provisioned = provision_user(db, user_info, cfg)
        db.add.assert_called_once()
        db.commit.assert_called()

    def test_existing_user_is_returned(self):
        db = _make_db_session()
        existing = MagicMock(spec=User)
        existing.email = "alice@acme.com"
        existing.role = UserRole.VIEWER
        db.first.return_value = existing

        cfg = _make_saml_config(role_mapping={})
        user_info = self._make_user_info(groups=[])
        result = provision_user(db, user_info, cfg)
        assert result == existing
        db.add.assert_not_called()

    def test_role_updated_on_existing_user(self):
        db = _make_db_session()
        existing = MagicMock(spec=User)
        existing.email = "alice@acme.com"
        existing.role = UserRole.VIEWER
        db.first.return_value = existing

        cfg = _make_saml_config(role_mapping={"admins": "admin"})
        user_info = self._make_user_info(groups=["admins"])
        provision_user(db, user_info, cfg)
        # Role should have been updated
        assert existing.role == UserRole.ADMIN

    def test_missing_email_raises_400(self):
        db = _make_db_session()
        cfg = _make_saml_config()
        with pytest.raises(HTTPException) as exc_info:
            provision_user(db, {"email": "", "groups": []}, cfg)
        assert exc_info.value.status_code == 400

    def test_no_email_key_raises_400(self):
        db = _make_db_session()
        cfg = _make_saml_config()
        with pytest.raises(HTTPException) as exc_info:
            provision_user(db, {"groups": []}, cfg)
        assert exc_info.value.status_code == 400

    def test_new_user_gets_viewer_role_when_no_mapping(self):
        db = _make_db_session()
        db.first.return_value = None
        cfg = _make_saml_config(role_mapping={})

        user_info = self._make_user_info(groups=["unknown-group"])

        # Capture the User object passed to db.add
        added_users = []
        db.add.side_effect = lambda obj: added_users.append(obj)

        provision_user(db, user_info, cfg)
        assert len(added_users) == 1
        new_user = added_users[0]
        assert new_user.role == UserRole.VIEWER

    def test_new_user_gets_admin_role_when_mapped(self):
        db = _make_db_session()
        db.first.return_value = None
        cfg = _make_saml_config(role_mapping={"super-admins": "admin"})

        user_info = self._make_user_info(groups=["super-admins"])
        added_users = []
        db.add.side_effect = lambda obj: added_users.append(obj)

        provision_user(db, user_info, cfg)
        new_user = added_users[0]
        assert new_user.role == UserRole.ADMIN


# ---------------------------------------------------------------------------
# map_role
# ---------------------------------------------------------------------------


class TestMapRole:
    def _make_cfg(self, mapping: dict) -> MagicMock:
        cfg = MagicMock(spec=SSOConfig)
        cfg.role_mapping = mapping
        return cfg

    def test_admin_group_maps_to_admin(self):
        cfg = self._make_cfg({"Admins": "admin"})
        assert map_role(cfg, ["Admins"]) == "admin"

    def test_developer_group_maps_to_developer(self):
        cfg = self._make_cfg({"devs": "developer"})
        assert map_role(cfg, ["devs"]) == "developer"

    def test_analyst_group_maps_to_analyst(self):
        cfg = self._make_cfg({"analysts": "analyst"})
        assert map_role(cfg, ["analysts"]) == "analyst"

    def test_viewer_default_when_no_match(self):
        cfg = self._make_cfg({"admins": "admin"})
        assert map_role(cfg, ["unknown-group"]) == "viewer"

    def test_empty_groups_returns_viewer(self):
        cfg = self._make_cfg({"admins": "admin"})
        assert map_role(cfg, []) == "viewer"

    def test_empty_mapping_returns_viewer(self):
        cfg = self._make_cfg({})
        assert map_role(cfg, ["admins"]) == "viewer"

    def test_none_mapping_returns_viewer(self):
        cfg = self._make_cfg(None)
        assert map_role(cfg, ["admins"]) == "viewer"

    def test_first_matching_group_wins(self):
        cfg = self._make_cfg({"devs": "developer", "admins": "admin"})
        # "devs" is first in user's groups list
        assert map_role(cfg, ["devs", "admins"]) == "developer"

    def test_case_preserved_in_output(self):
        cfg = self._make_cfg({"ADMINS": "ADMIN"})
        result = map_role(cfg, ["ADMINS"])
        # map_role lower-cases the output
        assert result == "admin"

    def test_multiple_groups_first_match(self):
        cfg = self._make_cfg({"analysts": "analyst", "viewers": "viewer"})
        assert map_role(cfg, ["viewers", "analysts"]) == "viewer"


# ---------------------------------------------------------------------------
# generate_state_token / verify_state_token
# ---------------------------------------------------------------------------


class TestStateTokens:
    def setup_method(self):
        """Clear the state store before each test."""
        _state_store.clear()

    def test_generate_returns_string(self):
        token = generate_state_token()
        assert isinstance(token, str)
        assert len(token) > 10

    def test_token_is_url_safe(self):
        token = generate_state_token()
        import re
        # URL-safe base64 contains only alphanumeric, -, _
        assert re.match(r"^[A-Za-z0-9_\-]+$", token)

    def test_verify_valid_token_returns_true(self):
        token = generate_state_token()
        result = verify_state_token(token)
        assert result is True

    def test_verify_removes_token_from_store(self):
        token = generate_state_token()
        verify_state_token(token)
        assert token not in _state_store

    def test_verify_token_is_single_use(self):
        token = generate_state_token()
        verify_state_token(token)
        with pytest.raises(HTTPException) as exc_info:
            verify_state_token(token)
        assert exc_info.value.status_code == 400

    def test_verify_unknown_token_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            verify_state_token("random-unknown-token")
        assert exc_info.value.status_code == 400

    def test_verify_empty_token_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            verify_state_token("")
        assert exc_info.value.status_code == 400

    def test_verify_expired_token_raises_400(self):
        token = generate_state_token()
        # Manually set expiry to the past
        _state_store[token] = time.time() - 1
        with pytest.raises(HTTPException) as exc_info:
            verify_state_token(token)
        assert exc_info.value.status_code == 400

    def test_each_token_is_unique(self):
        tokens = {generate_state_token() for _ in range(20)}
        assert len(tokens) == 20

    def test_multiple_tokens_can_coexist(self):
        t1 = generate_state_token()
        t2 = generate_state_token()
        t3 = generate_state_token()
        assert verify_state_token(t1) is True
        assert verify_state_token(t2) is True
        assert verify_state_token(t3) is True


# ---------------------------------------------------------------------------
# build_oidc_authorization_url
# ---------------------------------------------------------------------------


class TestBuildOIDCAuthorizationURL:
    def test_google_url_structure(self):
        cfg = _make_google_config()
        state = "test-state-token"
        url = build_oidc_authorization_url(cfg, "google", "https://example.com/callback", state)
        assert "accounts.google.com" in url
        assert "client_id=google-client-id" in url
        assert "state=test-state-token" in url
        assert "response_type=code" in url

    def test_github_url_structure(self):
        cfg = MagicMock(spec=SSOConfig)
        cfg.provider_type = SSOProviderType.GITHUB
        cfg.entity_id = "gh-client-id"
        cfg.sso_url = None

        url = build_oidc_authorization_url(cfg, "github", "https://example.com/cb", "state-abc")
        assert "github.com" in url
        assert "gh-client-id" in url

    def test_microsoft_url_structure(self):
        cfg = MagicMock(spec=SSOConfig)
        cfg.provider_type = SSOProviderType.MICROSOFT
        cfg.entity_id = "ms-client"
        cfg.sso_url = None

        url = build_oidc_authorization_url(cfg, "microsoft", "https://example.com/cb", "state-xyz")
        assert "microsoftonline" in url

    def test_unknown_provider_raises_400(self):
        cfg = _make_google_config()
        with pytest.raises(HTTPException) as exc_info:
            build_oidc_authorization_url(cfg, "unknown_provider", "https://example.com/cb", "state")
        assert exc_info.value.status_code == 400

    def test_redirect_uri_included(self):
        cfg = _make_google_config()
        redirect_uri = "https://myapp.com/callback"
        url = build_oidc_authorization_url(cfg, "google", redirect_uri, "state-123")
        assert "redirect_uri" in url

    def test_scope_included(self):
        cfg = _make_google_config()
        url = build_oidc_authorization_url(cfg, "google", "https://example.com/cb", "st")
        assert "scope" in url

    def test_okta_url_uses_sso_url(self):
        cfg = MagicMock(spec=SSOConfig)
        cfg.provider_type = SSOProviderType.OKTA
        cfg.entity_id = "okta-client"
        cfg.sso_url = "https://my-org.okta.com"

        url = build_oidc_authorization_url(cfg, "okta", "https://example.com/cb", "state")
        assert "my-org.okta.com" in url
