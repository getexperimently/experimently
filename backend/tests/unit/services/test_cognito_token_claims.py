"""The claim check on a Cognito access token: it must be an access token from
the configured user pool, issued to the configured app client.

Constructed claims, no AWS. The end-to-end behaviour (moto, two pools, real
Postgres) is in
``backend/tests/integration/api/test_cognito_token_audience.py``; the
``token_use`` case lives here because GetUser accepts only access tokens, so
an ID token never reaches the check end to end.
"""

from unittest.mock import MagicMock

import jwt
import pytest

from backend.app.services.auth_service import (
    CognitoAuthService,
    CognitoTokenRefused,
    expected_issuer,
    validate_access_token_claims,
)

POOL = "us-west-2_AbC123xyZ"
CLIENT = "3n4b5urk1ft4fl3mg5e62d9ado"
ISSUER = "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_AbC123xyZ"

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _claims(**overrides):
    claims = {
        "sub": "c7f1d6a2-0000-4000-8000-000000000001",
        "iss": ISSUER,
        "client_id": CLIENT,
        "token_use": "access",
        "username": "ops",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _reason(claims, pool=POOL, client=CLIENT) -> str:
    with pytest.raises(CognitoTokenRefused) as refused:
        validate_access_token_claims(claims, pool, client)
    return refused.value.reason


class TestExpectedIssuer:
    @pytest.mark.parametrize(
        "pool, region",
        [
            ("us-west-2_AbC123xyZ", "us-west-2"),
            ("eu-central-1_Q9", "eu-central-1"),
            ("ap-southeast-2_x", "ap-southeast-2"),
            ("us-gov-west-1_Abc", "us-gov-west-1"),
        ],
    )
    def test_the_region_comes_from_the_pool_id(self, pool, region):
        assert expected_issuer(pool) == (
            f"https://cognito-idp.{region}.amazonaws.com/{pool}"
        )

    @pytest.mark.parametrize(
        "pool",
        [
            None,
            "",
            "test-pool-id",
            "us-west-2",
            "us-west-2_",
            "_AbC123",
            "us-west-2_AbC/../x",
            "US-WEST-2_AbC",
            "us-west-2_AbC 123",
            "us-west-2_AbC123xyZ\n",
            "us-west-2_" + "a" * 60,
        ],
    )
    def test_a_malformed_pool_id_has_no_issuer(self, pool):
        assert expected_issuer(pool) is None


class TestValidateAccessTokenClaims:
    def test_an_access_token_from_the_pool_and_client_passes(self):
        validate_access_token_claims(_claims(), POOL, CLIENT)

    def test_an_id_token_is_refused(self):
        # An ID token carries `aud` rather than `client_id`; even with both
        # claims present, token_use alone refuses it.
        assert _reason(_claims(token_use="id", aud=CLIENT)) == "wrong_issuer"

    def test_a_missing_token_use_is_refused(self):
        assert _reason(_claims(token_use=None)) == "wrong_issuer"

    @pytest.mark.parametrize(
        "iss",
        [
            "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_Other1",
            "https://cognito-idp.us-east-1.amazonaws.com/us-west-2_AbC123xyZ",
            "http://cognito-idp.us-west-2.amazonaws.com/us-west-2_AbC123xyZ",
            ISSUER + "/",
            "",
            None,
        ],
    )
    def test_a_different_issuer_is_refused(self, iss):
        assert _reason(_claims(iss=iss)) == "wrong_issuer"

    @pytest.mark.parametrize("client_id", ["another-app-client", "", None])
    def test_a_different_app_client_is_refused(self, client_id):
        assert _reason(_claims(client_id=client_id)) == "wrong_issuer"

    def test_a_malformed_pool_id_is_refused(self):
        claims = _claims(iss="https://cognito-idp.us-east-1.amazonaws.com/test-pool-id")
        assert _reason(claims, pool="test-pool-id") == "wrong_issuer"

    @pytest.mark.parametrize("pool, client", [(None, CLIENT), (POOL, None), ("", "")])
    def test_unset_settings_are_refused_as_not_configured(self, pool, client):
        assert _reason(_claims(), pool=pool, client=client) == "not_configured"

    def test_the_refusal_is_not_a_value_error(self):
        # Callers turn ValueError into a 401 carrying the exception's text;
        # a refusal must take the generic-401 path instead.
        assert not issubclass(CognitoTokenRefused, ValueError)


def _service(pool=POOL, client=CLIENT) -> CognitoAuthService:
    service = CognitoAuthService()
    service.user_pool_id = pool
    service.client_id = client
    fake = MagicMock()
    fake.get_user.return_value = {
        "Username": "ops",
        "UserAttributes": [{"Name": "email", "Value": "ops@example.com"}],
    }
    fake.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": "Admins"}]}
    service.client = fake
    return service


def _token(**overrides) -> str:
    return jwt.encode(_claims(**overrides), "unit-test-key", algorithm="HS256")


@pytest.mark.parametrize("method", ["get_user", "get_user_with_groups"])
class TestBothLookupsApplyTheCheck:
    def test_a_matching_token_is_returned_unchanged(self, method):
        result = getattr(_service(), method)(_token())
        assert result["username"] == "ops"
        assert result["attributes"] == {"email": "ops@example.com"}

    def test_a_token_for_a_different_app_client_is_refused(self, method):
        with pytest.raises(CognitoTokenRefused) as refused:
            getattr(_service(), method)(_token(client_id="another-app-client"))
        assert refused.value.reason == "wrong_issuer"

    def test_an_undecodable_token_is_refused(self, method):
        with pytest.raises(CognitoTokenRefused) as refused:
            getattr(_service(), method)("not-a-jwt")
        assert refused.value.reason == "wrong_issuer"

    def test_unset_app_client_is_refused_as_not_configured(self, method):
        with pytest.raises(CognitoTokenRefused) as refused:
            getattr(_service(client=None), method)(_token())
        assert refused.value.reason == "not_configured"

    def test_the_check_runs_only_after_get_user_accepts(self, method):
        service = _service()
        service.client.get_user.side_effect = RuntimeError("GetUser refused")
        with pytest.raises(ValueError):
            getattr(service, method)(_token(client_id="another-app-client"))
