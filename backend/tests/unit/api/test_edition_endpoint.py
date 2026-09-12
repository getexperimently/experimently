"""
API tests for ``GET /api/v1/edition`` (``backend/app/api/v1/endpoints/edition.py``).

The endpoint is public, so these tests pin two things hard: the response shape
the dashboard chrome relies on, and that the response never leaks the customer
name or any part of the licence key.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.core.license import DEV_KID, reset_license_cache
from backend.app.main import app
from backend.app.models.audit_log import AuditLog

CUSTOMER = "Contoso Health Ltd"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _public_pem(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def _sign(private_key: Ed25519PrivateKey, claims: Dict[str, Any]) -> str:
    segment = _b64url(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{segment}.{_b64url(private_key.sign(segment.encode('ascii')))}"


def _claims(*, exp_offset_days: int, features=("hipaa", "sso"), kid: str = DEV_KID):
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=exp_offset_days)
    return {
        "customer": CUSTOMER,
        "plan": "enterprise",
        "features": list(features),
        "iat": int((now - timedelta(days=1)).timestamp()),
        "nbf": int((now - timedelta(days=1)).timestamp()),
        "exp": int(exp.timestamp()),
        "kid": kid,
        "grace_days": 14,
        "max_seats": 40,
    }


@pytest.fixture(autouse=True)
def clean_license_state():
    reset_license_cache()
    yield
    reset_license_cache()


@pytest.fixture
def signer():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def edition_client(monkeypatch, signer):
    """TestClient with a stubbed DB session and the dev signing key trusted."""
    monkeypatch.setattr(settings, "EXPERIMENTLY_LICENSE_KEY", "")
    monkeypatch.setattr(
        settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
    )
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")

    app.dependency_overrides[deps.get_db] = lambda: MagicMock()
    with patch(
        "backend.app.services.audit_service.AuditService.log_action",
        new_callable=AsyncMock,
    ):
        yield TestClient(app)
    app.dependency_overrides.pop(deps.get_db, None)


def _install(monkeypatch, signer, **claim_kwargs) -> str:
    key = _sign(signer, _claims(**claim_kwargs))
    monkeypatch.setattr(settings, "EXPERIMENTLY_LICENSE_KEY", key)
    return key


class TestEditionEndpointCommunity:
    def test_no_key_reports_community_edition(self, edition_client):
        response = edition_client.get("/api/v1/edition")

        assert response.status_code == 200
        body = response.json()
        assert body["edition"] == "ce"
        assert body["features"] == []
        assert body["status"] == "none"
        assert body["expires_at"] is None
        assert body["version"] == settings.VERSION

    def test_endpoint_is_unauthenticated(self, edition_client):
        """No Authorization header, no 401 -- the chrome asks before login."""
        assert edition_client.get("/api/v1/edition").status_code == 200

    def test_invalid_licence_reports_ce_with_status_invalid(
        self, edition_client, monkeypatch
    ):
        _install(monkeypatch, Ed25519PrivateKey.generate(), exp_offset_days=30)
        body = edition_client.get("/api/v1/edition").json()

        assert body["edition"] == "ce"
        assert body["features"] == []
        assert body["status"] == "invalid"
        assert body["expires_at"] is None


class TestEditionEndpointEnterprise:
    def test_valid_key_reports_enterprise(self, edition_client, monkeypatch, signer):
        _install(monkeypatch, signer, exp_offset_days=30)
        body = edition_client.get("/api/v1/edition").json()

        assert body["edition"] == "enterprise"
        assert body["features"] == ["hipaa", "sso"]
        assert body["status"] == "active"
        assert body["expires_at"] is not None
        assert set(body) == {"edition", "features", "status", "expires_at", "version"}

    @pytest.mark.parametrize(
        ("offset_days", "expected_status"),
        [(-3, "grace"), (-20, "expired"), (-90, "expired")],
    )
    def test_lapsed_licences_keep_enterprise_chrome(
        self, edition_client, monkeypatch, signer, offset_days, expected_status
    ):
        _install(monkeypatch, signer, exp_offset_days=offset_days)
        body = edition_client.get("/api/v1/edition").json()

        assert body["edition"] == "enterprise"
        assert body["status"] == expected_status
        # Features are still named so the banner can say what lapsed; the
        # client must consult `status` as well before enabling anything.
        assert body["features"] == ["hipaa", "sso"]


class TestEditionEndpointLeaks:
    @pytest.mark.parametrize("offset_days", [30, -3, -20, -90])
    def test_never_leaks_the_customer_or_the_key(
        self, edition_client, monkeypatch, signer, offset_days
    ):
        key = _install(monkeypatch, signer, exp_offset_days=offset_days)
        response = edition_client.get("/api/v1/edition")

        assert CUSTOMER not in response.text
        assert "Contoso" not in response.text
        assert key not in response.text
        # Not even a prefix of the key (or of its signature) survives.
        assert key.split(".")[0][:24] not in response.text
        assert key.split(".")[1][:24] not in response.text
        body = response.json()
        for leaky in ("customer", "plan", "max_seats", "kid", "key", "reason"):
            assert leaky not in body

    def test_invalid_licence_does_not_explain_why(
        self, edition_client, monkeypatch, signer
    ):
        """`reason` is diagnostic; a public probe does not get it."""
        _install(monkeypatch, Ed25519PrivateKey.generate(), exp_offset_days=30)
        response = edition_client.get("/api/v1/edition")
        assert "bad_signature" not in response.text


class TestEditionEndpointAudit:
    def test_state_change_writes_a_license_audit_row(
        self, monkeypatch, signer, db_session
    ):
        """End to end against the database: a `license.*` row lands."""
        monkeypatch.setattr(
            settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        monkeypatch.setattr(settings, "ENVIRONMENT", "test")
        key = _install(monkeypatch, signer, exp_offset_days=30)
        assert key

        def _override_db():
            yield db_session

        app.dependency_overrides[deps.get_db] = _override_db
        try:
            client = TestClient(app)
            assert client.get("/api/v1/edition").json()["status"] == "active"
        finally:
            app.dependency_overrides.pop(deps.get_db, None)

        rows = (
            db_session.query(AuditLog)
            .filter(AuditLog.entity_type == "license")
            .order_by(AuditLog.timestamp.desc())
            .all()
        )
        assert rows, "the licence transition was not audited"
        assert rows[0].action_type == "license.active"
        assert rows[0].new_value == "active"
        assert rows[0].user_id is None

    def test_repeat_requests_audit_once(self, monkeypatch, signer):
        """The chrome polls /edition; only a *change* of state is audited."""
        monkeypatch.setattr(
            settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        monkeypatch.setattr(settings, "ENVIRONMENT", "test")
        _install(monkeypatch, signer, exp_offset_days=30)

        app.dependency_overrides[deps.get_db] = lambda: MagicMock()
        try:
            with patch(
                "backend.app.services.audit_service.AuditService.log_action",
                new_callable=AsyncMock,
            ) as log_action:
                client = TestClient(app)
                for _ in range(3):
                    assert client.get("/api/v1/edition").status_code == 200
        finally:
            app.dependency_overrides.pop(deps.get_db, None)

        assert log_action.await_count == 1
        assert log_action.await_args.kwargs["action_type"].value == "license.active"
