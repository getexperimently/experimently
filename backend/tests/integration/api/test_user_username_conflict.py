"""A duplicate username on either user PUT answers 409, as on create (#610).

``PUT /api/v1/users/{id}`` and ``PUT /api/v1/admin/users/{id}`` did not check
whether the new ``username`` belonged to another account, so the unique
constraint's error reached the client as a 500. Both now answer 409
"Username already registered", the answer ``POST /api/v1/users/`` gives, and
never "Email already registered". When the commit itself fails (a row
committed between the check and the commit) the same answer is given.

The clients are built with ``raise_server_exceptions=False`` so that a server
error shows up as the 500 a real client sees.
"""

from __future__ import annotations

import uuid
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.api.v1.endpoints import admin as admin_endpoints
from backend.app.api.v1.endpoints import users as users_endpoints
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

pytestmark = [pytest.mark.integration]

USERNAME_TAKEN = "Username already registered"

#: The two PUT routes, as a path template.
PUT_ROUTES = ["/api/v1/users/{id}", "/api/v1/admin/users/{id}"]


@pytest.fixture(autouse=True)
def _clear_auth_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _make_user(
    db_session: Session, *, superuser: bool = False, role: UserRole = UserRole.VIEWER
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"uname_{suffix}",
        email=f"uname.{suffix}@example.com",
        full_name="Before",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _admin_client(db_session: Session) -> TestClient:
    admin = _make_user(db_session, superuser=True, role=UserRole.ADMIN)
    make_client_for_user(db_session, admin)
    return TestClient(app, raise_server_exceptions=False)


def _row(db_session: Session, user_id) -> tuple:
    """(email, username, first_name) as the database holds them now."""
    db_session.rollback()
    return tuple(
        db_session.query(User.email, User.username, User.first_name)
        .filter(User.id == user_id)
        .one()
    )


@pytest.mark.parametrize("route", PUT_ROUTES)
class TestUpdateUsername:
    """PUT /api/v1/users/{id} (superuser) and PUT /api/v1/admin/users/{id}."""

    @pytest.mark.regression
    def test_another_accounts_username_answers_409(
        self, db_session: Session, route: str
    ):
        other = _make_user(db_session)
        target = _make_user(db_session)
        client = _admin_client(db_session)
        target_before = _row(db_session, target.id)

        response = client.put(
            route.format(id=target.id),
            json={
                "username": other.username,
                "email": target.email,
                "full_name": "After",
            },
        )

        assert response.status_code == 409, response.text
        assert response.json() == {"detail": USERNAME_TAKEN}
        assert _row(db_session, target.id) == target_before

    @pytest.mark.regression
    def test_the_race_with_another_accounts_username_answers_409(
        self, db_session: Session, route: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The pre-check misses; the unique constraint refuses; the re-query maps it."""

        def _finds_nothing(*args, **kwargs) -> None:
            return None

        monkeypatch.setattr(users_endpoints, "refuse_if_username_held", _finds_nothing)
        monkeypatch.setattr(admin_endpoints, "refuse_if_username_held", _finds_nothing)

        other = _make_user(db_session)
        target = _make_user(db_session)
        client = _admin_client(db_session)
        target_before = _row(db_session, target.id)

        response = client.put(
            route.format(id=target.id),
            json={"username": other.username, "email": target.email},
        )

        assert response.status_code == 409, response.text
        assert response.json() == {"detail": USERNAME_TAKEN}
        assert _row(db_session, target.id) == target_before

    def test_keeping_the_accounts_own_username_succeeds(
        self, db_session: Session, route: str
    ):
        target = _make_user(db_session)
        client = _admin_client(db_session)

        response = client.put(
            route.format(id=target.id),
            json={
                "username": target.username,
                "email": target.email,
                "full_name": "After",
            },
        )

        assert response.status_code == 200, response.text
        assert _row(db_session, target.id)[1] == target.username

    def test_a_free_username_is_saved(self, db_session: Session, route: str):
        target = _make_user(db_session)
        client = _admin_client(db_session)
        new_name = f"free_{uuid.uuid4().hex[:8]}"

        response = client.put(
            route.format(id=target.id),
            json={"username": new_name, "email": target.email},
        )

        assert response.status_code == 200, response.text
        assert response.json()["username"] == new_name
        assert _row(db_session, target.id)[1] == new_name
