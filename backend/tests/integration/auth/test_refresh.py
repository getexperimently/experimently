"""
Integration tests for POST /api/v1/auth/refresh.

Tests token refresh using a valid refresh_token obtained from the token endpoint.
moto supports REFRESH_TOKEN_AUTH flow.

NOTE: The refresh endpoint returns a TokenResponse which requires id_token.
moto's REFRESH_TOKEN_AUTH response includes AccessToken and IdToken.
The refresh_token field in the response is Optional per the schema.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.tests.integration.auth.spec_cognito_integration import (
    COGNITO_ENDPOINT_SPECS,
)

SPEC = COGNITO_ENDPOINT_SPECS["refresh"]


class TestRefreshSuccess:
    def test_refresh_returns_200(self, auth_client, auth_tokens):
        """Valid refresh token returns 200"""
        response = auth_client.post(
            SPEC.path,
            json={
                "refresh_token": auth_tokens["refresh_token"],
            },
        )
        assert response.status_code == SPEC.success_status

    def test_refresh_returns_new_access_token(self, auth_client, auth_tokens):
        """Refresh returns a new access_token"""
        response = auth_client.post(
            SPEC.path,
            json={
                "refresh_token": auth_tokens["refresh_token"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["access_token"]

    def test_refresh_returns_id_token(self, auth_client, auth_tokens):
        """Refresh returns an id_token (required by TokenResponse schema)"""
        response = auth_client.post(
            SPEC.path,
            json={
                "refresh_token": auth_tokens["refresh_token"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id_token" in data
        assert data["id_token"]

    def test_refresh_returns_expires_in(self, auth_client, auth_tokens):
        """Refresh response includes expires_in"""
        response = auth_client.post(
            SPEC.path,
            json={
                "refresh_token": auth_tokens["refresh_token"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "expires_in" in data
        assert data["expires_in"] > 0

    def test_refresh_returns_token_type(self, auth_client, auth_tokens):
        """Refresh response includes token_type"""
        response = auth_client.post(
            SPEC.path,
            json={
                "refresh_token": auth_tokens["refresh_token"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "token_type" in data
        assert data["token_type"].lower() == "bearer"

    def test_refresh_no_auth_required(self, auth_client, auth_tokens):
        """Refresh endpoint is publicly accessible"""
        response = auth_client.post(
            SPEC.path,
            json={
                "refresh_token": auth_tokens["refresh_token"],
            },
        )
        assert response.status_code not in (401, 403)


class TestRefreshErrors:
    def test_invalid_refresh_token_returns_401(self, auth_client):
        """Invalid refresh token returns 401"""
        with patch(
            "backend.app.api.v1.endpoints.auth.CognitoAuthService"
        ) as MockService:
            mock_instance = MagicMock()
            mock_instance.refresh_token.side_effect = ValueError(
                "An error occurred (NotAuthorizedException): Invalid Refresh Token"
            )
            MockService.return_value = mock_instance

            response = auth_client.post(
                SPEC.path, json={"refresh_token": "invalid.fake.token"}
            )
        assert response.status_code == 401

    def test_expired_refresh_token_returns_401(self, auth_client):
        """Expired refresh token returns 401"""
        with patch(
            "backend.app.api.v1.endpoints.auth.CognitoAuthService"
        ) as MockService:
            mock_instance = MagicMock()
            mock_instance.refresh_token.side_effect = ValueError(
                "An error occurred (NotAuthorizedException): Refresh Token has expired"
            )
            MockService.return_value = mock_instance

            response = auth_client.post(
                SPEC.path, json={"refresh_token": "expired.refresh.token"}
            )
        assert response.status_code == 401

    def test_missing_refresh_token_returns_422(self, auth_client):
        """Missing refresh_token field returns 422"""
        response = auth_client.post(SPEC.path, json={})
        assert response.status_code == 422

    def test_error_response_has_detail(self, auth_client):
        """401 error response has detail field"""
        with patch(
            "backend.app.api.v1.endpoints.auth.CognitoAuthService"
        ) as MockService:
            mock_instance = MagicMock()
            mock_instance.refresh_token.side_effect = ValueError(
                "NotAuthorizedException"
            )
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={"refresh_token": "bad.token"})
        assert response.status_code == 401
        assert "detail" in response.json()

    def test_401_has_www_authenticate_header(self, auth_client):
        """401 responses include WWW-Authenticate: Bearer header"""
        with patch(
            "backend.app.api.v1.endpoints.auth.CognitoAuthService"
        ) as MockService:
            mock_instance = MagicMock()
            mock_instance.refresh_token.side_effect = ValueError(
                "NotAuthorizedException"
            )
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={"refresh_token": "bad.token"})
        assert response.status_code == 401
        headers_lower = {k.lower(): v for k, v in response.headers.items()}
        assert "www-authenticate" in headers_lower
