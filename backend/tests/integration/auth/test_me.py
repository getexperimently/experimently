"""
Integration tests for GET /api/v1/auth/me (current user info).

The /me endpoint uses deps.get_token to extract the Bearer token from
the Authorization header, then calls CognitoAuthService.get_user() with
that token. No database is involved — it's a pure Cognito call.

The get_token dependency raises HTTP 401 when:
- Authorization header is missing
- Scheme is not Bearer
- Token string is empty

With a token present, CognitoAuthService.get_user() is called. With moto,
a real Cognito access token from the token endpoint works. With an arbitrary
fake token, Cognito raises an error → ValueError → HTTP 401.

UserInfoResponse schema: {"username": str, "attributes": dict}
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.tests.integration.auth.spec_cognito_integration import (
    COGNITO_ENDPOINT_SPECS,
)

SPEC = COGNITO_ENDPOINT_SPECS["me"]


class TestMeEndpoint:
    def test_me_without_token_returns_401(self, auth_client):
        """No Authorization header returns 401"""
        response = auth_client.get(SPEC.path)
        assert response.status_code == 401

    def test_me_with_invalid_bearer_token_returns_401(self, auth_client):
        """Invalid/fake Bearer token returns 401 (Cognito rejects it)"""
        response = auth_client.get(
            SPEC.path,
            headers={"Authorization": "Bearer fake.token.here"},
        )
        assert response.status_code == 401

    def test_me_with_wrong_scheme_returns_401(self, auth_client):
        """Non-Bearer auth scheme returns 401"""
        response = auth_client.get(
            SPEC.path,
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert response.status_code == 401

    def test_me_with_empty_bearer_returns_401(self, auth_client):
        """'Bearer ' with no token value returns 401"""
        response = auth_client.get(
            SPEC.path,
            headers={"Authorization": "Bearer "},
        )
        assert response.status_code == 401

    def test_me_with_valid_moto_token_returns_200(self, auth_client, auth_tokens):
        """
        A real moto-issued access token returns 200 and correct user info.
        moto's get_user() validates the AccessToken issued by initiate_auth.
        """
        response = auth_client.get(
            SPEC.path,
            headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
        )
        assert response.status_code == SPEC.success_status

    def test_me_response_has_username(self, auth_client, auth_tokens):
        """Me response contains 'username' field"""
        response = auth_client.get(
            SPEC.path,
            headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "username" in data
        assert len(data["username"]) > 0

    def test_me_response_has_attributes(self, auth_client, auth_tokens):
        """Me response contains 'attributes' dict"""
        response = auth_client.get(
            SPEC.path,
            headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "attributes" in data
        assert isinstance(data["attributes"], dict)

    def test_me_response_attributes_contain_email(
        self, auth_client, auth_tokens, registered_user
    ):
        """User attributes from moto include the email set during signup"""
        response = auth_client.get(
            SPEC.path,
            headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
        )
        assert response.status_code == 200
        data = response.json()
        # moto stores standard attributes; email was set at sign_up
        attributes = data.get("attributes", {})
        assert "email" in attributes
        assert attributes["email"] == registered_user["email"]

    def test_me_with_mocked_service_returns_200(self, auth_client):
        """With CognitoAuthService mocked, any token returns 200 with user info"""
        with patch(
            "backend.app.api.v1.endpoints.auth.CognitoAuthService"
        ) as MockService:
            mock_instance = MagicMock()
            mock_instance.get_user.return_value = {
                "username": "mock_user",
                "attributes": {
                    "email": "mock@example.com",
                    "given_name": "Mock",
                    "family_name": "User",
                },
            }
            MockService.return_value = mock_instance

            response = auth_client.get(
                SPEC.path,
                headers={"Authorization": "Bearer any.valid.format.token"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "mock_user"
        assert data["attributes"]["email"] == "mock@example.com"

    def test_me_service_error_returns_401(self, auth_client):
        """CognitoAuthService.get_user raising ValueError returns 401"""
        with patch(
            "backend.app.api.v1.endpoints.auth.CognitoAuthService"
        ) as MockService:
            mock_instance = MagicMock()
            mock_instance.get_user.side_effect = ValueError(
                "An error occurred (NotAuthorizedException): Invalid Access Token"
            )
            MockService.return_value = mock_instance

            response = auth_client.get(
                SPEC.path,
                headers={"Authorization": "Bearer any.token.here"},
            )
        assert response.status_code == 401

    def test_me_error_response_has_detail(self, auth_client):
        """401 error response from /me contains 'detail' field"""
        response = auth_client.get(SPEC.path)
        assert response.status_code == 401
        assert "detail" in response.json()
