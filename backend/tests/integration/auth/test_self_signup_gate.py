"""Self sign-up under Cognito makes no Cognito call unless it is turned on (T94).

Against moto, with every botocore operation the request makes recorded
(``BaseClient._make_api_call``) and the pool's users counted exactly:

* M1 (regression) with ``COGNITO_SELF_SIGNUP_ENABLED`` at its default,
  ``/signup`` answers 404, makes no Cognito call, and the pool stays empty;
* M2 likewise ``/confirm``: 404, no call, the unconfirmed user stays so;
* M3 with the setting on, ``/signup`` makes exactly ``SignUp`` and adds one
  user, and ``/confirm`` makes exactly ``ConfirmSignUp``.

Each test gets a fresh pool, so the counts are exact.  Not marked ``slow``.
"""

from typing import List

import boto3
import pytest
from botocore.client import BaseClient

from backend.app.core.config import settings
from backend.tests.integration.cognito_reference_pool import REGION

pytestmark = [pytest.mark.integration, pytest.mark.regression]

SELF_SIGNUP_OFF = (
    "Endpoint not available: self sign-up is turned off "
    "(COGNITO_SELF_SIGNUP_ENABLED is not true). "
    "An administrator creates users in the Cognito user pool."
)

USER = {
    "username": "gate_user",
    "password": "GatePass123!",
    "email": "gate.user@example.com",
    "given_name": "Gate",
    "family_name": "User",
}


@pytest.fixture
def pool(cognito_mock, auth_client, monkeypatch):
    """A fresh pool and app client that this deployment is configured for."""
    idp = boto3.client("cognito-idp", region_name=REGION)
    pool_id = idp.create_user_pool(PoolName="gate")["UserPool"]["Id"]
    client_id = idp.create_user_pool_client(
        UserPoolId=pool_id, ClientName="gate", GenerateSecret=False
    )["UserPoolClient"]["ClientId"]
    monkeypatch.setenv("COGNITO_USER_POOL_ID", pool_id)
    monkeypatch.setenv("COGNITO_CLIENT_ID", client_id)
    return idp, pool_id, client_id


@pytest.fixture
def recorded(monkeypatch) -> List[str]:
    """The botocore operation names called while the list is being recorded."""
    ops: List[str] = []
    real = BaseClient._make_api_call

    def record(self, operation_name, api_params):
        ops.append(operation_name)
        return real(self, operation_name, api_params)

    monkeypatch.setattr(BaseClient, "_make_api_call", record)
    return ops


def _users(idp, pool_id) -> List[str]:
    return [u["Username"] for u in idp.list_users(UserPoolId=pool_id)["Users"]]


def test_signup_refused_by_default_makes_no_cognito_call(pool, auth_client, recorded):
    """M1: the setting is left at its default (not set by the test)."""
    idp, pool_id, _ = pool

    response = auth_client.post("/api/v1/auth/signup", json=USER)
    ops = list(recorded)

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": SELF_SIGNUP_OFF}
    assert ops == []
    assert len(_users(idp, pool_id)) == 0


def test_confirm_refused_by_default_makes_no_cognito_call(pool, auth_client, recorded):
    """M2: an unconfirmed user (signed up directly in the pool) stays so."""
    idp, pool_id, client_id = pool
    idp.sign_up(
        ClientId=client_id,
        Username=USER["username"],
        Password=USER["password"],
        UserAttributes=[{"Name": "email", "Value": USER["email"]}],
    )
    recorded.clear()

    response = auth_client.post(
        "/api/v1/auth/confirm",
        json={"username": USER["username"], "confirmation_code": "123456"},
    )
    ops = list(recorded)

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": SELF_SIGNUP_OFF}
    assert ops == []
    status = idp.admin_get_user(UserPoolId=pool_id, Username=USER["username"])
    assert status["UserStatus"] == "UNCONFIRMED"


def test_signup_and_confirm_reach_cognito_when_turned_on(
    pool, auth_client, recorded, monkeypatch
):
    """M3."""
    idp, pool_id, _ = pool
    monkeypatch.setattr(settings, "COGNITO_SELF_SIGNUP_ENABLED", True)

    signup = auth_client.post("/api/v1/auth/signup", json=USER)
    signup_ops = list(recorded)
    assert signup.status_code == 201, signup.text
    assert signup_ops == ["SignUp"]
    assert _users(idp, pool_id) == [USER["username"]]

    recorded.clear()
    confirm = auth_client.post(
        "/api/v1/auth/confirm",
        json={"username": USER["username"], "confirmation_code": "123456"},
    )
    confirm_ops = list(recorded)
    assert confirm.status_code == 200, confirm.text
    assert confirm_ops == ["ConfirmSignUp"]
    status = idp.admin_get_user(UserPoolId=pool_id, Username=USER["username"])
    assert status["UserStatus"] == "CONFIRMED"
