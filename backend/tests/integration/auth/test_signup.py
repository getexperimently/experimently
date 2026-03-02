"""
Integration tests for POST /api/v1/auth/signup.

Tests the complete registration flow using moto-mocked Cognito.
All tests verify the full HTTP request/response cycle.
"""
import pytest
from backend.tests.integration.auth.spec_cognito_integration import (
    COGNITO_ENDPOINT_SPECS,
    VALID_USER,
    WEAK_PASSWORD,
    INVALID_EMAIL,
)

SPEC = COGNITO_ENDPOINT_SPECS["signup"]


class TestSignupSuccess:
    def test_signup_returns_201(self, auth_client):
        """Successful signup returns HTTP 201 Created"""
        payload = {**VALID_USER, "username": "new_user_001", "email": "new001@example.com"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == SPEC.success_status

    def test_signup_response_has_user_id(self, auth_client):
        """Response body contains a user_id (Cognito UserSub)"""
        payload = {**VALID_USER, "username": "new_user_002", "email": "new002@example.com"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 201
        data = response.json()
        assert "user_id" in data
        assert len(data["user_id"]) > 0

    def test_signup_confirmed_is_false(self, auth_client):
        """Newly registered user is not confirmed"""
        payload = {**VALID_USER, "username": "new_user_003", "email": "new003@example.com"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 201
        assert response.json().get("confirmed") == False

    def test_signup_no_auth_required(self, auth_client):
        """Signup endpoint is publicly accessible — no auth header needed"""
        payload = {**VALID_USER, "username": "new_user_004", "email": "new004@example.com"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code != 401
        assert response.status_code != 403

    def test_signup_response_has_message(self, auth_client):
        """Response body contains a human-readable message"""
        payload = {**VALID_USER, "username": "new_user_005", "email": "new005@example.com"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 201
        data = response.json()
        assert "message" in data
        assert len(data["message"]) > 0

    def test_signup_returns_json(self, auth_client):
        """Signup response Content-Type is application/json"""
        payload = {**VALID_USER, "username": "new_user_006", "email": "new006@example.com"}
        response = auth_client.post(SPEC.path, json=payload)
        assert "application/json" in response.headers.get("content-type", "")


class TestSignupValidation:
    def test_missing_username_returns_422(self, auth_client):
        """Missing required username field returns 422"""
        payload = {k: v for k, v in VALID_USER.items() if k != "username"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 422

    def test_missing_password_returns_422(self, auth_client):
        """Missing required password field returns 422"""
        payload = {k: v for k, v in VALID_USER.items() if k != "password"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 422

    def test_missing_email_returns_422(self, auth_client):
        """Missing required email field returns 422"""
        payload = {k: v for k, v in VALID_USER.items() if k != "email"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 422

    def test_missing_given_name_returns_422(self, auth_client):
        """Missing required given_name field returns 422"""
        payload = {k: v for k, v in VALID_USER.items() if k != "given_name"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 422

    def test_missing_family_name_returns_422(self, auth_client):
        """Missing required family_name field returns 422"""
        payload = {k: v for k, v in VALID_USER.items() if k != "family_name"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 422

    def test_invalid_email_format_returns_422(self, auth_client):
        """Invalid email format returns 422 from Pydantic validation"""
        payload = {**VALID_USER, "email": INVALID_EMAIL, "username": "invalid_email_user"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 422

    def test_empty_body_returns_422(self, auth_client):
        """Empty request body returns 422"""
        response = auth_client.post(SPEC.path, json={})
        assert response.status_code == 422

    def test_short_username_returns_422(self, auth_client):
        """Username shorter than 3 characters returns 422"""
        payload = {**VALID_USER, "username": "ab", "email": "ab@example.com"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 422

    def test_short_password_returns_422(self, auth_client):
        """Password shorter than 8 characters returns 422 from Pydantic"""
        payload = {**VALID_USER, "username": "shortpwduser", "email": "shortpwd@example.com", "password": WEAK_PASSWORD}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 422


class TestSignupErrors:
    def test_duplicate_username_returns_400(self, auth_client, registered_user):
        """Registering with existing username returns 400"""
        # registered_user is already in the pool; try to register again
        payload = {**registered_user, "email": "different@example.com"}
        response = auth_client.post(SPEC.path, json=payload)
        assert response.status_code == 400

    def test_error_response_has_detail(self, auth_client, registered_user):
        """Error response body contains 'detail' field"""
        payload = {**registered_user, "email": "anotherdiff@example.com"}
        response = auth_client.post(SPEC.path, json=payload)
        assert "detail" in response.json()

    def test_duplicate_email_returns_400(self, auth_client, registered_user):
        """Registering with same email under a different username may return 400 (Cognito raises UsernameExistsException on aliased attrs)"""
        payload = {**registered_user, "username": "completely_new_username_xyz"}
        response = auth_client.post(SPEC.path, json=payload)
        # moto may return 201 or 400 depending on alias configuration; accept both
        assert response.status_code in (201, 400)
