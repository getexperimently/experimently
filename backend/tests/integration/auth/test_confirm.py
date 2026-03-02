"""
Integration tests for POST /api/v1/auth/confirm.

Tests the email confirmation flow. moto does not enforce code validation the
same way as real Cognito, so some paths use admin_confirm_sign_up to set up
the state, and error paths use unittest.mock.patch to simulate exceptions
from CognitoAuthService.
"""
import pytest
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError
from backend.tests.integration.auth.spec_cognito_integration import COGNITO_ENDPOINT_SPECS, VALID_USER

SPEC = COGNITO_ENDPOINT_SPECS["confirm"]


class TestConfirmSuccess:
    def test_confirm_returns_200_on_success(self, auth_client):
        """Successful confirmation returns 200"""
        # Register a new user
        payload = {**VALID_USER, "username": "confirm_test_02", "email": "confirm02@example.com"}
        auth_client.post("/api/v1/auth/signup", json=payload)

        # Mock confirm_sign_up at the service level to succeed
        with patch("backend.app.api.v1.endpoints.auth.CognitoAuthService") as MockService:
            mock_instance = MagicMock()
            mock_instance.confirm_sign_up.return_value = {
                "confirmed": True,
                "message": "Account confirmed successfully. You can now sign in.",
            }
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={
                "username": "confirm_test_02",
                "confirmation_code": "123456",
            })
        assert response.status_code == SPEC.success_status

    def test_confirm_response_has_confirmed_field(self, auth_client):
        """Successful confirmation response body contains 'confirmed' field"""
        with patch("backend.app.api.v1.endpoints.auth.CognitoAuthService") as MockService:
            mock_instance = MagicMock()
            mock_instance.confirm_sign_up.return_value = {
                "confirmed": True,
                "message": "Account confirmed successfully. You can now sign in.",
            }
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={
                "username": "any_user",
                "confirmation_code": "123456",
            })
        assert response.status_code == 200
        data = response.json()
        assert "confirmed" in data
        assert data["confirmed"] is True

    def test_confirm_response_has_message(self, auth_client):
        """Confirmation response has a message field"""
        with patch("backend.app.api.v1.endpoints.auth.CognitoAuthService") as MockService:
            mock_instance = MagicMock()
            mock_instance.confirm_sign_up.return_value = {
                "confirmed": True,
                "message": "Account confirmed successfully. You can now sign in.",
            }
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={
                "username": "any_user",
                "confirmation_code": "123456",
            })
        assert response.status_code == 200
        assert "message" in response.json()

    def test_confirm_no_auth_required(self, auth_client):
        """Confirm endpoint is publicly accessible"""
        with patch("backend.app.api.v1.endpoints.auth.CognitoAuthService") as MockService:
            mock_instance = MagicMock()
            mock_instance.confirm_sign_up.return_value = {
                "confirmed": True,
                "message": "confirmed",
            }
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={
                "username": "any_user",
                "confirmation_code": "123456",
            })
        assert response.status_code not in (401, 403)


class TestConfirmErrors:
    def test_wrong_code_returns_400(self, auth_client):
        """Wrong confirmation code returns 400"""
        with patch("backend.app.api.v1.endpoints.auth.CognitoAuthService") as MockService:
            mock_instance = MagicMock()
            mock_instance.confirm_sign_up.side_effect = ValueError(
                "An error occurred (CodeMismatchException): Invalid verification code"
            )
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={
                "username": "any_user",
                "confirmation_code": "000000",
            })
        assert response.status_code == 400

    def test_expired_code_returns_400(self, auth_client):
        """Expired confirmation code returns 400"""
        with patch("backend.app.api.v1.endpoints.auth.CognitoAuthService") as MockService:
            mock_instance = MagicMock()
            mock_instance.confirm_sign_up.side_effect = ValueError(
                "An error occurred (ExpiredCodeException): Invalid code provided, please request a code again."
            )
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={
                "username": "any_user",
                "confirmation_code": "111111",
            })
        assert response.status_code == 400

    def test_already_confirmed_returns_400(self, auth_client):
        """Confirming an already-confirmed user returns 400"""
        with patch("backend.app.api.v1.endpoints.auth.CognitoAuthService") as MockService:
            mock_instance = MagicMock()
            mock_instance.confirm_sign_up.side_effect = ValueError(
                "An error occurred (NotAuthorizedException): User cannot be confirmed. Current status is CONFIRMED"
            )
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={
                "username": "confirmed_user",
                "confirmation_code": "123456",
            })
        assert response.status_code == 400

    def test_missing_confirmation_code_returns_422(self, auth_client):
        """Missing confirmation_code field returns 422"""
        response = auth_client.post(SPEC.path, json={"username": "only_username"})
        assert response.status_code == 422

    def test_missing_username_returns_422(self, auth_client):
        """Missing username field returns 422"""
        response = auth_client.post(SPEC.path, json={"confirmation_code": "123456"})
        assert response.status_code == 422

    def test_empty_body_returns_422(self, auth_client):
        """Empty body returns 422"""
        response = auth_client.post(SPEC.path, json={})
        assert response.status_code == 422

    def test_error_response_has_detail(self, auth_client):
        """Error responses contain a 'detail' field"""
        with patch("backend.app.api.v1.endpoints.auth.CognitoAuthService") as MockService:
            mock_instance = MagicMock()
            mock_instance.confirm_sign_up.side_effect = ValueError("CodeMismatchException")
            MockService.return_value = mock_instance

            response = auth_client.post(SPEC.path, json={
                "username": "any_user",
                "confirmation_code": "000000",
            })
        assert response.status_code == 400
        assert "detail" in response.json()
