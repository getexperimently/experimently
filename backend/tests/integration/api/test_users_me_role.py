"""``GET /api/v1/users/me`` returns the caller's role (#644).

The handler built its response without ``role``, and because ``role`` is
optional on ``UserResponse`` every caller got ``"role": null``. The Cognito
docs tell operators to check an account's role with this call, and the
dashboard needs it to decide what to offer.

Two providers, both against real Postgres:

* local: real rows and real local JWTs; for every role, a row whose role is
  NULL and a superuser, ``/users/me`` and ``/auth/me`` agree on the role
  (NULL reads as VIEWER on both).
* cognito: the real ``CognitoAuthService`` through moto (the ``pool``
  harness from ``test_cognito_sign_in_linking``; nothing stubs
  ``get_user_with_groups``). ``/auth/me`` has no role under Cognito, so the
  reference is the role the pool groups map to, and the row the sign-in wrote.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.security import create_local_access_token
from backend.app.models.user import User, UserRole
from backend.tests.integration.api.test_cognito_sign_in_linking import (
    _pool_sign_in,
    _pool_user,
    _restore_overrides,
    _route_db_to,
    pool,
)
from backend.tests.integration.conftest import HASHED_PASSWORD

pytestmark = [pytest.mark.integration, pytest.mark.regression]

USERS_ME = "/api/v1/users/me"
AUTH_ME = "/api/v1/auth/me"

# --------------------------------------------------------------------------
# Local provider: /users/me agrees with /auth/me
# --------------------------------------------------------------------------

LOCAL_CASES = {
    "viewer": (UserRole.VIEWER, False, "VIEWER"),
    "analyst": (UserRole.ANALYST, False, "ANALYST"),
    "developer": (UserRole.DEVELOPER, False, "DEVELOPER"),
    "admin": (UserRole.ADMIN, False, "ADMIN"),
    "null_role": (None, False, "VIEWER"),
    "superuser": (UserRole.ADMIN, True, "ADMIN"),
}


@pytest.fixture
def local_client(db_session: Session, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app.main import app

    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    saved = _route_db_to(db_session)
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        _restore_overrides(saved)


@pytest.mark.parametrize("case", list(LOCAL_CASES), ids=list(LOCAL_CASES))
def test_users_me_role_matches_auth_me_under_local(
    case: str, local_client, db_session: Session
):
    role, is_superuser, expected = LOCAL_CASES[case]
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f"me644_{suffix}",
        email=f"me644_{suffix}@example.com",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=is_superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    if role is None:
        # The column has a VIEWER default; make the row really NULL.
        db_session.execute(
            text("UPDATE users SET role = NULL WHERE id = :id"), {"id": user.id}
        )
        db_session.commit()
        db_session.expire_all()
        assert (
            db_session.execute(
                text("SELECT role FROM users WHERE id = :id"), {"id": user.id}
            ).scalar()
            is None
        )
    headers = {"Authorization": f"Bearer {create_local_access_token(user)}"}

    users_me = local_client.get(USERS_ME, headers=headers)
    auth_me = local_client.get(AUTH_ME, headers=headers)

    assert users_me.status_code == 200, users_me.text
    assert auth_me.status_code == 200, auth_me.text
    assert users_me.json()["id"] == auth_me.json()["id"] == str(user.id)
    assert users_me.json()["role"] == auth_me.json()["role"] == expected


# --------------------------------------------------------------------------
# Cognito provider: /users/me is the role the pool groups map to
# --------------------------------------------------------------------------

COGNITO_CASES = {
    "admins": (["Admins"], "ADMIN"),
    "developers": (["Developers"], "DEVELOPER"),
    "analysts": (["Analysts"], "ANALYST"),
    "viewers": (["Viewers"], "VIEWER"),
    "no_group": ([], "VIEWER"),
}


@pytest.mark.parametrize("case", list(COGNITO_CASES), ids=list(COGNITO_CASES))
def test_users_me_role_is_the_group_mapped_role_under_cognito(
    case: str, pool, monkeypatch
):
    groups, expected = COGNITO_CASES[case]
    monkeypatch.setattr(settings, "SYNC_ROLES_ON_LOGIN", True)
    for group in groups:
        if group != "Admins":  # the harness creates Admins
            pool.idp.create_group(GroupName=group, UserPoolId=pool.pool_id)
    username = _pool_user(pool, groups)

    response = _pool_sign_in(pool, username)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == expected
    assert pool.rows.column(body["id"], "role") == expected
