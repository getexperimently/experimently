"""
Integration tests for POST /api/v1/auth/token.

Tests login/authentication. Uses moto Cognito with ALLOW_USER_PASSWORD_AUTH.

NOTE: The TokenResponse schema requires access_token, id_token, refresh_token
(optional), expires_in, and token_type. moto's initiate_auth with
USER_PASSWORD_AUTH returns all of these for a confirmed user.

NOTE: The token endpoint maps ALL ValueError to HTTP 401 (not 400), so
unconfirmed users and non-existent users also return 401.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from backend.tests.integration.auth.spec_cognito_integration import (
    COGNITO_ENDPOINT_SPECS,
    VALID_USER,
)

SPEC = COGNITO_ENDPOINT_SPECS["token"]


class TestTokenSuccess:
    def test_login_returns_200(self, auth_client, registered_user):
        """Valid credentials return 200"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": registered_user["password"],
            },
        )
        assert response.status_code == SPEC.success_status

    def test_login_returns_access_token(self, auth_client, registered_user):
        """Successful login returns access_token"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": registered_user["password"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["access_token"]

    def test_login_returns_token_type(self, auth_client, registered_user):
        """Token response includes token_type field"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": registered_user["password"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "token_type" in data
        # moto returns "Bearer" (capital B); check case-insensitively
        assert data["token_type"].lower() == "bearer"

    def test_login_returns_refresh_token(self, auth_client, registered_user):
        """Successful login returns refresh_token for session renewal"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": registered_user["password"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "refresh_token" in data

    def test_login_returns_id_token(self, auth_client, registered_user):
        """Successful login returns id_token (required by TokenResponse schema)"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": registered_user["password"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id_token" in data
        assert data["id_token"]

    def test_login_returns_expires_in(self, auth_client, registered_user):
        """Token response includes expires_in field"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": registered_user["password"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "expires_in" in data
        assert isinstance(data["expires_in"], int)
        assert data["expires_in"] > 0

    def test_login_accepts_form_data(self, auth_client, registered_user):
        """Token endpoint accepts application/x-www-form-urlencoded"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": registered_user["password"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200

    def test_login_no_auth_required(self, auth_client, registered_user):
        """Token endpoint is publicly accessible"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": registered_user["password"],
            },
        )
        # Should get 200, not 403
        assert response.status_code != 403


class TestTokenErrors:
    def test_wrong_password_returns_401(self, auth_client, registered_user):
        """Wrong password returns 401 Unauthorized"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": "WrongPassword999!",
            },
        )
        assert response.status_code == 401

    def test_nonexistent_user_returns_401(self, auth_client):
        """Non-existent user returns 401 (don't leak user existence)"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": "ghost_user_xyz_99",
                "password": "SomePass123!",
            },
        )
        assert response.status_code == 401

    def test_missing_username_returns_422(self, auth_client):
        """Missing username returns 422"""
        response = auth_client.post(SPEC.path, data={"password": "SomePass123!"})
        assert response.status_code == 422

    def test_missing_password_returns_422(self, auth_client, registered_user):
        """Missing password returns 422"""
        response = auth_client.post(
            SPEC.path, data={"username": registered_user["username"]}
        )
        assert response.status_code == 422

    def test_missing_credentials_returns_422(self, auth_client):
        """Missing username/password returns 422"""
        response = auth_client.post(SPEC.path, data={})
        assert response.status_code == 422

    def test_error_response_has_detail(self, auth_client, registered_user):
        """Error response includes a 'detail' field"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": "WrongPassword999!",
            },
        )
        assert response.status_code == 401
        assert "detail" in response.json()

    def test_unauthorized_response_has_www_authenticate_header(
        self, auth_client, registered_user
    ):
        """401 responses include WWW-Authenticate: Bearer header"""
        response = auth_client.post(
            SPEC.path,
            data={
                "username": registered_user["username"],
                "password": "WrongPassword999!",
            },
        )
        assert response.status_code == 401
        assert "www-authenticate" in {k.lower(): v for k, v in response.headers.items()}
