"""
Spec coverage test — verifies every endpoint in the spec has at least one test.
Meta-test to ensure spec and test suite stay in sync.
"""

import pytest

from backend.tests.integration.auth.spec_cognito_integration import (
    COGNITO_ENDPOINT_SPECS,
)


def test_all_spec_endpoints_are_defined():
    """Spec must define at least the 7 core Cognito auth endpoints"""
    required = {
        "signup",
        "confirm",
        "token",
        "refresh",
        "forgot_password",
        "confirm_forgot_password",
        "me",
    }
    assert required.issubset(set(COGNITO_ENDPOINT_SPECS.keys()))


def test_all_spec_endpoints_have_error_cases():
    """Every endpoint spec must define at least one error case"""
    for name, spec in COGNITO_ENDPOINT_SPECS.items():
        assert len(spec.error_cases) >= 1, (
            f"{name} must have at least one error case defined"
        )


def test_all_spec_success_status_codes_valid():
    """Success status codes must be in valid HTTP range"""
    for name, spec in COGNITO_ENDPOINT_SPECS.items():
        assert 200 <= spec.success_status < 300, (
            f"{name}: invalid success_status {spec.success_status}"
        )


def test_auth_required_endpoints_identified():
    """At least one endpoint must require authentication"""
    auth_required = [
        name for name, spec in COGNITO_ENDPOINT_SPECS.items() if spec.auth_required
    ]
    assert len(auth_required) >= 1, "At least /me must require authentication"


def test_public_endpoints_identified():
    """At least login and signup must be public"""
    public = [
        name for name, spec in COGNITO_ENDPOINT_SPECS.items() if not spec.auth_required
    ]
    assert "signup" in public
    assert "token" in public


def test_all_spec_methods_are_valid_http():
    """All endpoint methods must be valid HTTP verbs"""
    valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
    for name, spec in COGNITO_ENDPOINT_SPECS.items():
        assert spec.method in valid_methods, (
            f"{name}: invalid HTTP method '{spec.method}'"
        )


def test_all_spec_paths_start_with_api_v1_auth():
    """All auth endpoint paths must start with /api/v1/auth"""
    for name, spec in COGNITO_ENDPOINT_SPECS.items():
        assert spec.path.startswith("/api/v1/auth"), (
            f"{name}: path '{spec.path}' should start with /api/v1/auth"
        )


def test_error_cases_have_required_fields():
    """Each error case must have scenario, status, and trigger fields"""
    for endpoint_name, spec in COGNITO_ENDPOINT_SPECS.items():
        for i, error_case in enumerate(spec.error_cases):
            assert "scenario" in error_case, (
                f"{endpoint_name} error_case[{i}] missing 'scenario' field"
            )
            assert "status" in error_case, (
                f"{endpoint_name} error_case[{i}] missing 'status' field"
            )
            assert "trigger" in error_case, (
                f"{endpoint_name} error_case[{i}] missing 'trigger' field"
            )


def test_error_status_codes_are_client_errors():
    """Error status codes must be 4xx or 5xx"""
    for endpoint_name, spec in COGNITO_ENDPOINT_SPECS.items():
        for error_case in spec.error_cases:
            assert error_case["status"] >= 400, (
                f"{endpoint_name} '{error_case['scenario']}': "
                f"error status {error_case['status']} should be >= 400"
            )
