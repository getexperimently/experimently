"""An account with no email address no longer makes the user endpoints answer 500 (#342).

``users.email`` is nullable, and the Cognito sign-in creates an account with
``email = None`` when the token carries no email attribute. ``UserResponse``
declared ``email: str``, so every operation that returned such an account
answered 500 -- a list answered 500 for every account in it.

``UserResponse.email`` is now ``Optional[str]`` with no default: the key is
still always present, and is ``null`` for such an account.

The clients here are built with ``raise_server_exceptions=False`` so that the
old behaviour shows up as the 500 a real client saw, not as an exception
raised into the test.
"""

from __future__ import annotations

import uuid
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.regression]


@pytest.fixture(autouse=True)
def _clear_auth_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _make_user(
    db_session: Session,
    role: UserRole,
    *,
    email: str | None,
    superuser: bool = False,
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"noemail_{suffix}",
        email=email,
        full_name=f"No Email {suffix}",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _client_as(db_session: Session, user: User) -> TestClient:
    """Sign in as ``user``; a server error comes back as a 500 response."""
    make_client_for_user(db_session, user)
    return TestClient(app, raise_server_exceptions=False)


def _admin(db_session: Session) -> User:
    suffix = uuid.uuid4().hex[:8]
    return _make_user(
        db_session,
        UserRole.ADMIN,
        email=f"admin_{suffix}@int.test",
        superuser=True,
    )


class TestUserListWithNullEmail:
    """GET /api/v1/users/"""

    def test_superuser_list_includes_the_account_with_null_email(
        self, db_session: Session
    ):
        no_email = _make_user(db_session, UserRole.VIEWER, email=None)
        total_rows = db_session.query(User).count()
        client = _client_as(db_session, _admin(db_session))

        response = client.get("/api/v1/users/", params={"limit": 100})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == total_rows + 1  # every row, plus the admin
        listed = {item["id"]: item for item in body["items"]}
        assert str(no_email.id) in listed
        item = listed[str(no_email.id)]
        assert "email" in item and item["email"] is None
        assert item["username"] == no_email.username

    def test_non_superuser_with_null_email_lists_itself(self, db_session: Session):
        """A non-superuser's list is its own account (the route's RBAC)."""
        no_email = _make_user(db_session, UserRole.VIEWER, email=None)
        client = _client_as(db_session, no_email)

        response = client.get("/api/v1/users/")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert [item["id"] for item in body["items"]] == [str(no_email.id)]
        assert body["items"][0]["email"] is None


class TestAdminUserListWithNullEmail:
    """GET /api/v1/admin/users (superuser only)."""

    def test_list_includes_the_account_with_null_email(self, db_session: Session):
        no_email = _make_user(db_session, UserRole.ANALYST, email=None)
        total_rows = db_session.query(User).count()
        client = _client_as(db_session, _admin(db_session))

        response = client.get("/api/v1/admin/users", params={"limit": 100})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == total_rows + 1  # every row, plus the admin
        listed = {item["id"]: item for item in body["items"]}
        assert str(no_email.id) in listed
        item = listed[str(no_email.id)]
        assert "email" in item and item["email"] is None
        assert item["role"] == "ANALYST"

    def test_a_non_superuser_is_still_refused(self, db_session: Session):
        no_email = _make_user(db_session, UserRole.DEVELOPER, email=None)
        client = _client_as(db_session, no_email)

        assert client.get("/api/v1/admin/users").status_code == 403


class TestGetUserWithNullEmail:
    """GET /api/v1/users/{user_id}"""

    def test_non_superuser_reads_its_own_account(self, db_session: Session):
        no_email = _make_user(db_session, UserRole.DEVELOPER, email=None)
        client = _client_as(db_session, no_email)

        response = client.get(f"/api/v1/users/{no_email.id}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == str(no_email.id)
        assert "email" in body and body["email"] is None

    def test_superuser_reads_another_account(self, db_session: Session):
        no_email = _make_user(db_session, UserRole.VIEWER, email=None)
        client = _client_as(db_session, _admin(db_session))

        response = client.get(f"/api/v1/users/{no_email.id}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == str(no_email.id)
        assert "email" in body and body["email"] is None

    def test_a_non_superuser_is_still_refused_another_account(
        self, db_session: Session
    ):
        other = _make_user(db_session, UserRole.VIEWER, email=None)
        no_email = _make_user(db_session, UserRole.DEVELOPER, email=None)
        client = _client_as(db_session, no_email)

        assert client.get(f"/api/v1/users/{other.id}").status_code == 403
