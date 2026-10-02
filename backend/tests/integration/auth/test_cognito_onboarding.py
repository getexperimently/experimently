"""The documented Cognito onboarding works: the user can sign in (T94).

With self sign-up off by default, ``docs/cognito_integration.md`` "Adding a
user" is how a Cognito user gets in.  This runs the page's own commands --
read from the page and turned into boto3 calls -- against a moto pool shaped
like the reference one, then signs the user in with ``POST /api/v1/auth/token``.
Run without ``--permanent`` (step 6 of the page), the sign-in gets the 401
the page quotes.

The ``/users/me`` leg, which needs PostgreSQL, is
``backend/tests/integration/api/test_cognito_onboarding_users_me.py``.

Not marked ``slow``: the path-filtered Cognito workflow runs ``-m "not slow"``.
"""

import boto3
import pytest

from backend.tests.integration.cognito_reference_pool import (
    REGION,
    create_reference_like_pool,
    run_documented_onboarding,
)

pytestmark = [pytest.mark.integration, pytest.mark.regression]

#: Spelled out, not imported; docs/cognito_integration.md step 6 quotes it.
NEW_PASSWORD_DETAIL = (
    "This user must set a new password before signing in; an administrator "
    "sets one with admin-set-user-password --permanent."
)

TOKEN_KEYS = {"access_token", "id_token", "refresh_token", "expires_in", "token_type"}


@pytest.fixture
def reference_pool(cognito_mock, auth_client, monkeypatch):
    """A fresh reference-shaped pool that this deployment is configured for."""
    idp = boto3.client("cognito-idp", region_name=REGION)
    pool_id, client_id = create_reference_like_pool(idp)
    monkeypatch.setenv("COGNITO_USER_POOL_ID", pool_id)
    monkeypatch.setenv("COGNITO_CLIENT_ID", client_id)
    return idp, pool_id


def test_a_user_added_as_documented_signs_in(reference_pool, auth_client):
    idp, pool_id = reference_pool

    step = run_documented_onboarding(idp, pool_id)
    response = auth_client.post(
        "/api/v1/auth/token",
        data={"username": step["Username"], "password": step["Password"]},
    )

    # The sign-in first: a procedure that leaves a temporary password then
    # fails here with the refusal's own text in the message.
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == TOKEN_KEYS
    assert body["access_token"]
    user = idp.admin_get_user(UserPoolId=pool_id, Username=step["Username"])
    assert user["UserStatus"] == "CONFIRMED"
    groups = idp.admin_list_groups_for_user(
        UserPoolId=pool_id, Username=step["Username"]
    )
    assert [g["GroupName"] for g in groups["Groups"]] == ["Developers"]


def _drop_permanent(calls) -> None:
    """Step 3 run without ``--permanent``: the user keeps a temporary password."""
    (step,) = [p for op, p in calls if op == "admin_set_user_password"]
    del step["Permanent"]


def test_a_user_left_with_a_temporary_password_gets_the_documented_401(
    reference_pool, auth_client
):
    """Step 6 of the page: the exact 401 a temporary password gets."""
    idp, pool_id = reference_pool

    step = run_documented_onboarding(idp, pool_id, edit=_drop_permanent)

    user = idp.admin_get_user(UserPoolId=pool_id, Username=step["Username"])
    assert user["UserStatus"] == "FORCE_CHANGE_PASSWORD"
    response = auth_client.post(
        "/api/v1/auth/token",
        data={"username": step["Username"], "password": step["Password"]},
    )
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": NEW_PASSWORD_DETAIL}
