"""SDK routes answer 422 for a NUL in a path parameter (#547).

A path parameter holding U+0000 used to reach a database query, which
PostgreSQL refuses, and the route answered a plain-text 500. Each such
parameter is now checked where it is declared: 422, the fixed message naming
the parameter, and the value absent from the body.

Only the NUL is exercised over HTTP: a percent-encoded lone surrogate
(``%ED%A0%80``) is not valid UTF-8, so the path decoder turns it into U+FFFD
before the route sees it. The check itself refuses both, which
``backend/tests/unit/schemas/test_storable_text.py`` covers.

Every other answer on these routes is unchanged, which the last two tests pin.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.core.security import hash_api_key
from backend.app.main import app
from backend.app.models.api_key import APIKey
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.metrics.metric import RawMetric
from backend.tests.integration.conftest import make_client_for_user
from backend.tests.integration.helpers import unique_flag_key

pytestmark = [pytest.mark.integration, pytest.mark.regression]

#: Marks the refused path segment so a test can tell whether the body repeats it.
MARK = "zq547mark"

#: The refused path segment, percent-encoded as a client sends it.
REFUSED_SEGMENT = f"{MARK}%00"

#: Path segment with ordinary non-ASCII text, still accepted.
VALID_SEGMENT = "%C3%A9t%C3%A9-u547"

#: (id, method, url with ``{seg}`` for the path parameter, parameter name)
ROUTES = [
    (
        "tracking-assignments-user_id",
        "GET",
        "/api/v1/tracking/assignments/{seg}",
        "user_id",
    ),
    (
        "flag-evaluate-get-flag_key",
        "GET",
        "/api/v1/feature-flags/evaluate/{seg}?user_id=u547",
        "flag_key",
    ),
    (
        "flag-evaluate-post-flag_key",
        "POST",
        "/api/v1/feature-flags/evaluate/{seg}",
        "flag_key",
    ),
    (
        "flag-user-user_id",
        "GET",
        "/api/v1/feature-flags/user/{seg}",
        "user_id",
    ),
]


def _send(client: TestClient, method: str, url: str):
    if method == "POST":
        return client.post(url, json={"user_id": "u547"})
    return client.get(url)


@pytest.fixture
def flag(db_session, make_feature_flag):
    """An active flag, so the user-flags route evaluates at least one."""
    created = make_feature_flag(
        key=unique_flag_key("pathref"),
        name="Path text refused flag",
        status=FeatureFlagStatus.ACTIVE,
        rollout_percentage=25,
    )
    yield created
    db_session.rollback()
    db_session.query(RawMetric).filter(RawMetric.feature_flag_id == created.id).delete()
    db_session.query(FeatureFlag).filter(FeatureFlag.id == created.id).delete()
    db_session.commit()


@pytest.fixture
def sdk_client(db_session, admin_user):
    """A client whose real API key row is checked; it shows a 500 as a response.

    ``make_client_for_user`` points the routes at the test database and also
    replaces the API-key check; that replacement is removed again, so the key
    is looked up as in production and a request without it answers 401.
    """
    raw = f"tr547-{uuid.uuid4().hex}"
    key = APIKey(
        key=hash_api_key(raw),
        name=f"path-text-{uuid.uuid4().hex[:6]}",
        is_active=True,
        scopes="sdk:ruleset",
        user_id=admin_user.id,
    )
    db_session.add(key)
    db_session.commit()
    make_client_for_user(db_session, admin_user)
    app.dependency_overrides.pop(deps.get_api_key)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            c.headers.update({"X-API-Key": raw})
            yield c
    finally:
        app.dependency_overrides.clear()
        db_session.rollback()
        db_session.query(APIKey).filter(APIKey.id == key.id).delete()
        db_session.commit()


@pytest.mark.parametrize(
    "method,url,param",
    [r[1:] for r in ROUTES],
    ids=[r[0] for r in ROUTES],
)
def test_nul_in_path_answers_422_with_the_fixed_message(
    sdk_client, flag, method, url, param
):
    response = _send(sdk_client, method, url.format(seg=REFUSED_SEGMENT))

    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/json")
    (error,) = response.json()["detail"]
    assert error["loc"] == ["path", param]
    assert error["msg"].endswith(
        f"{param} must not contain NUL or unpaired surrogate characters"
    )
    assert "input" not in error
    assert MARK not in response.text


@pytest.mark.parametrize(
    "method,url,expected",
    [
        ("GET", ROUTES[0][2], 200),
        ("GET", ROUTES[1][2], 404),
        ("POST", ROUTES[2][2], 404),
        ("GET", ROUTES[3][2], 200),
    ],
    ids=[r[0] for r in ROUTES],
)
def test_non_ascii_path_answers_as_before(sdk_client, flag, method, url, expected):
    response = _send(sdk_client, method, url.format(seg=VALID_SEGMENT))
    assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    "method,url",
    [r[1:3] for r in ROUTES],
    ids=[r[0] for r in ROUTES],
)
def test_nul_in_path_without_an_api_key_still_answers_401(sdk_client, method, url):
    """The key is checked first, as before: the refusal does not reorder it."""
    del sdk_client.headers["X-API-Key"]
    response = _send(sdk_client, method, url.format(seg=REFUSED_SEGMENT))
    assert response.status_code == 401, response.text
