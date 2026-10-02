"""
POST /api/v1/auth/token when Cognito answers the sign-in with a challenge.

Cognito answers ``InitiateAuth`` with a ``ChallengeName`` and a ``Session``
instead of tokens when the user has a temporary password
(``NEW_PASSWORD_REQUIRED``) or an MFA step to complete. ``/token`` used to
return a token dict of ``None`` values for that, which the response model
rejected with a 500, after logging "Sign-in successful". It now answers 401
with a detail that names the challenge.

moto produces ``NEW_PASSWORD_REQUIRED`` for a user created with
``admin_create_user``; it never issues an MFA challenge, so those are stubbed
at ``initiate_auth`` and the rest of the path (``sign_in``, the endpoint, the
error mapping) is the real one.
"""

import logging
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from backend.app.services.auth_service import CognitoAuthService
from backend.tests.integration.auth.spec_cognito_integration import (
    COGNITO_ENDPOINT_SPECS,
)

SPEC = COGNITO_ENDPOINT_SPECS["token"]

NEW_PASSWORD_DETAIL = (
    "This user must set a new password before signing in; an administrator "
    "sets one with admin-set-user-password --permanent."
)

SESSION_SENTINEL = "b94p2b-session-sentinel-value"

SERVICE_LOGGER = "backend.app.services.auth_service"


def _post_token(auth_client, username: str, password: str):
    return auth_client.post(
        SPEC.path, data={"username": username, "password": password}
    )


@pytest.mark.regression
def test_temporary_password_user_gets_401_naming_the_new_password_step(
    auth_client, cognito_resources, caplog
):
    """A user an administrator created with a temporary password (moto)."""
    boto_client = cognito_resources["boto_client"]
    username = "temp_password_user"
    password = "TempPass123!"
    boto_client.admin_create_user(
        UserPoolId=cognito_resources["user_pool_id"],
        Username=username,
        TemporaryPassword=password,
        MessageAction="SUPPRESS",
        UserAttributes=[
            {"Name": "email", "Value": "temp_password_user@example.com"},
            {"Name": "email_verified", "Value": "true"},
        ],
    )
    user = boto_client.admin_get_user(
        UserPoolId=cognito_resources["user_pool_id"], Username=username
    )
    assert user["UserStatus"] == "FORCE_CHANGE_PASSWORD"

    with caplog.at_level(logging.DEBUG, logger=SERVICE_LOGGER):
        response = _post_token(auth_client, username, password)

    assert response.status_code == 401, response.text
    assert response.json() == {"detail": NEW_PASSWORD_DETAIL}
    assert response.headers.get("www-authenticate") == "Bearer"
    assert "Sign-in successful" not in caplog.text
    assert "Unexpected error" not in caplog.text
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("NEW_PASSWORD_REQUIRED" in r.getMessage() for r in warnings)


@pytest.mark.regression
@pytest.mark.parametrize(
    ("initiate_auth_response", "expected_detail"),
    [
        (
            {
                "ChallengeName": "SOFTWARE_TOKEN_MFA",
                "Session": SESSION_SENTINEL,
                "ChallengeParameters": {},
            },
            "This sign-in needs a step this API does not support (SOFTWARE_TOKEN_MFA).",
        ),
        (
            {
                "ChallengeName": "SMS_MFA",
                "Session": SESSION_SENTINEL,
                "ChallengeParameters": {"CODE_DELIVERY_DESTINATION": "+*******1234"},
            },
            "This sign-in needs a step this API does not support (SMS_MFA).",
        ),
        (
            {"Session": SESSION_SENTINEL, "ChallengeParameters": {}},
            "This sign-in needs a step this API does not support (none).",
        ),
    ],
    ids=["software_token_mfa", "sms_mfa", "neither_challenge_nor_token"],
)
def test_other_challenges_get_401_naming_the_challenge(
    auth_client, initiate_auth_response, expected_detail, caplog
):
    """MFA challenges, and a response with no challenge and no access token."""
    stub = MagicMock()
    stub.initiate_auth.return_value = initiate_auth_response

    with (
        patch.object(
            CognitoAuthService, "client", new_callable=PropertyMock, return_value=stub
        ),
        caplog.at_level(logging.DEBUG, logger=SERVICE_LOGGER),
    ):
        response = _post_token(auth_client, "mfa_user", "Password123!")

    stub.initiate_auth.assert_called_once()
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": expected_detail}
    assert SESSION_SENTINEL not in response.text
    assert SESSION_SENTINEL not in caplog.text
    assert "Sign-in successful" not in caplog.text
    assert "Unexpected error" not in caplog.text
