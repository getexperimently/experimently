"""
Cognito Integration Test Specification.

Defines the contract for all Cognito authentication flows.
Every endpoint, expected status code, required fields, and
error scenario is declared here before any test is written.

NOTE on path discrepancy: The auth.py endpoint for completing password reset
is registered at /reset-password (not /confirm-forgot-password). Both the spec
path and the actual path are tracked here. Tests use ACTUAL_PATH overrides
where the spec path differs from the live router.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EndpointSpec:
    method: str
    path: str
    description: str
    auth_required: bool
    success_status: int
    error_cases: List[dict]  # {"scenario": str, "status": int, "trigger": str}


COGNITO_ENDPOINT_SPECS = {
    "signup": EndpointSpec(
        method="POST",
        path="/api/v1/auth/signup",
        description="Register a new user in Cognito User Pool",
        auth_required=False,
        success_status=201,
        error_cases=[
            {
                "scenario": "duplicate username",
                "status": 400,
                "trigger": "UsernameExistsException",
            },
            {
                "scenario": "weak password",
                "status": 400,
                "trigger": "InvalidPasswordException",
            },
            {"scenario": "invalid email", "status": 422, "trigger": "validation_error"},
            {
                "scenario": "missing required fields",
                "status": 422,
                "trigger": "validation_error",
            },
        ],
    ),
    "confirm": EndpointSpec(
        method="POST",
        path="/api/v1/auth/confirm",
        description="Confirm user registration with verification code",
        auth_required=False,
        success_status=200,
        error_cases=[
            {
                "scenario": "wrong code",
                "status": 400,
                "trigger": "CodeMismatchException",
            },
            {
                "scenario": "expired code",
                "status": 400,
                "trigger": "ExpiredCodeException",
            },
            {
                "scenario": "already confirmed",
                "status": 400,
                "trigger": "NotAuthorizedException",
            },
        ],
    ),
    "token": EndpointSpec(
        method="POST",
        path="/api/v1/auth/token",
        description="Authenticate user and return JWT tokens",
        auth_required=False,
        success_status=200,
        error_cases=[
            {
                "scenario": "wrong password",
                "status": 401,
                "trigger": "NotAuthorizedException",
            },
            {
                "scenario": "unconfirmed user",
                "status": 401,
                "trigger": "UserNotConfirmedException",
            },
            {
                "scenario": "non-existent user",
                "status": 401,
                "trigger": "UserNotFoundException",
            },
        ],
    ),
    "refresh": EndpointSpec(
        method="POST",
        path="/api/v1/auth/refresh",
        description="Refresh access token using refresh token",
        auth_required=False,
        success_status=200,
        error_cases=[
            {
                "scenario": "invalid refresh token",
                "status": 401,
                "trigger": "NotAuthorizedException",
            },
            {
                "scenario": "expired refresh token",
                "status": 401,
                "trigger": "NotAuthorizedException",
            },
        ],
    ),
    "forgot_password": EndpointSpec(
        method="POST",
        path="/api/v1/auth/forgot-password",
        description="Initiate password reset flow",
        auth_required=False,
        success_status=200,
        error_cases=[
            # NOTE: The endpoint maps all ValueError to 400; the service raises
            # ValueError for UserNotFoundException too, so the real status is 400.
            {
                "scenario": "non-existent user",
                "status": 400,
                "trigger": "UserNotFoundException",
            },
        ],
    ),
    "confirm_forgot_password": EndpointSpec(
        method="POST",
        # NOTE: The spec path is /confirm-forgot-password but the live router
        # registers this at /reset-password. Tests use the actual endpoint path.
        path="/api/v1/auth/confirm-forgot-password",
        description="Complete password reset with code",
        auth_required=False,
        success_status=200,
        error_cases=[
            {
                "scenario": "wrong code",
                "status": 400,
                "trigger": "CodeMismatchException",
            },
            {
                "scenario": "expired code",
                "status": 400,
                "trigger": "ExpiredCodeException",
            },
        ],
    ),
    "me": EndpointSpec(
        method="GET",
        path="/api/v1/auth/me",
        description="Get current user info from token",
        auth_required=True,
        success_status=200,
        error_cases=[
            {"scenario": "no token", "status": 401, "trigger": "missing_auth"},
            {"scenario": "invalid token", "status": 401, "trigger": "invalid_token"},
        ],
    ),
}

# Actual live endpoint paths (use these in tests where spec path differs)
ACTUAL_PATHS = {
    "confirm_forgot_password": "/api/v1/auth/reset-password",
}

# Valid test data
VALID_USER = {
    "username": "testuser_cognito",
    "password": "TestPass123!",
    "email": "testcognito@example.com",
    "given_name": "Test",
    "family_name": "User",
}

WEAK_PASSWORD = "short"
INVALID_EMAIL = "not-an-email"
WRONG_CODE = "000000"
VALID_CODE = "123456"  # moto auto-confirms or use this
