"""A user field longer than its column answers 422 naming the field (#709).

``full_name`` (stored split into ``first_name`` and ``last_name``, 100
characters each) had no maximum, and ``email`` allowed the 254 characters of
an address where the column holds 100, so the insert or update failed in the
database and the request answered 500. The limits are read from the model.

The clients are built with ``raise_server_exceptions=False`` so that a server
error shows up as the 500 a real client sees.
"""

from __future__ import annotations

import uuid
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.app.schemas.user import EMAIL_MAX, FULL_NAME_MAX
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

pytestmark = [pytest.mark.integration]

PASSWORD = "Strong-pass1"

#: The two PUT routes, as a path template.
PUT_ROUTES = ["/api/v1/users/{id}", "/api/v1/admin/users/{id}"]


@pytest.fixture(autouse=True)
def _clear_auth_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_the_limits_are_the_columns():
    columns = User.__table__.c
    assert EMAIL_MAX == columns.email.type.length == 100
    assert FULL_NAME_MAX == columns.first_name.type.length == 100
    assert columns.last_name.type.length == 100


def _email(length: int) -> str:
    """A valid, unique address of exactly ``length`` characters."""
    local = f"u{uuid.uuid4().hex[:12]}"
    tail = ".example.com"
    filler = length - len(local) - 1 - len(tail)
    labels = []
    while filler > 0:
        size = min(filler, 63)
        if 0 < filler - size < 2:  # leave room for ".x"
            size -= 2
        labels.append("d" * size)
        filler -= size + 1
    address = f"{local}@{'.'.join(labels)}{tail}"
    assert len(address) == length, (len(address), address)
    return address


def _make_user(
    db_session: Session, *, superuser: bool = False, role: UserRole = UserRole.VIEWER
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"flen_{suffix}",
        email=f"flen.{suffix}@example.com",
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


def _client_for(db_session: Session, user: User) -> TestClient:
    make_client_for_user(db_session, user)
    return TestClient(app, raise_server_exceptions=False)


def _admin_client(db_session: Session) -> TestClient:
    return _client_for(
        db_session, _make_user(db_session, superuser=True, role=UserRole.ADMIN)
    )


def _row(db_session: Session, user_id) -> tuple:
    """(email, username, first_name, last_name) as the database holds them."""
    db_session.rollback()
    return tuple(
        db_session.query(User.email, User.username, User.first_name, User.last_name)
        .filter(User.id == user_id)
        .one()
    )


def _assert_422_naming(response, field: str) -> None:
    assert response.status_code == 422, response.text
    body = response.text
    assert field in body, body
    errors = response.json().get("detail")
    if isinstance(errors, list):
        assert any(
            isinstance(e, dict) and e.get("loc", [None])[-1] == field for e in errors
        ), errors


@pytest.mark.parametrize("route", PUT_ROUTES)
class TestUpdate:
    """PUT /api/v1/users/{id} (superuser) and PUT /api/v1/admin/users/{id}."""

    @pytest.mark.regression
    def test_a_full_name_one_over_the_column_answers_422(
        self, db_session: Session, route: str
    ):
        target = _make_user(db_session)
        client = _admin_client(db_session)
        before = _row(db_session, target.id)

        response = client.put(
            route.format(id=target.id),
            json={
                "username": target.username,
                "email": target.email,
                "full_name": "n" * (FULL_NAME_MAX + 1),
            },
        )

        _assert_422_naming(response, "full_name")
        assert _row(db_session, target.id) == before

    @pytest.mark.regression
    def test_an_email_one_over_the_column_answers_422(
        self, db_session: Session, route: str
    ):
        target = _make_user(db_session)
        client = _admin_client(db_session)
        before = _row(db_session, target.id)

        response = client.put(
            route.format(id=target.id),
            json={"username": target.username, "email": _email(EMAIL_MAX + 1)},
        )

        _assert_422_naming(response, "email")
        assert _row(db_session, target.id) == before

    @pytest.mark.parametrize(
        "full_name",
        ["n" * FULL_NAME_MAX, "a " + "b" * (FULL_NAME_MAX - 2)],
        ids=["one_word", "two_words"],
    )
    def test_values_exactly_the_column_length_are_stored(
        self, db_session: Session, route: str, full_name: str
    ):
        target = _make_user(db_session)
        client = _admin_client(db_session)
        email = _email(EMAIL_MAX)

        response = client.put(
            route.format(id=target.id),
            json={"username": target.username, "email": email, "full_name": full_name},
        )

        assert response.status_code == 200, response.text
        assert response.json()["full_name"] == full_name
        stored = _row(db_session, target.id)
        assert stored[0] == email
        assert " ".join(p for p in stored[2:] if p) == full_name


@pytest.mark.regression
def test_a_signed_in_user_updating_their_own_full_name_one_over_gets_422(
    db_session: Session,
):
    user = _make_user(db_session)
    client = _client_for(db_session, user)
    before = _row(db_session, user.id)

    response = client.put(
        f"/api/v1/users/{user.id}",
        json={
            "username": user.username,
            "email": user.email,
            "full_name": "n" * (FULL_NAME_MAX + 1),
        },
    )

    _assert_422_naming(response, "full_name")
    assert _row(db_session, user.id) == before


class TestCreate:
    """POST /api/v1/users/ (superuser)."""

    def _body(self, **overrides) -> dict:
        body = {
            "username": f"flen_new_{uuid.uuid4().hex[:8]}",
            "email": f"flen.new.{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "New User",
            "password": PASSWORD,
        }
        body.update(overrides)
        return body

    def _count(self, db_session: Session) -> int:
        db_session.rollback()
        return db_session.query(User).count()

    @pytest.mark.regression
    def test_a_full_name_one_over_the_column_answers_422(self, db_session: Session):
        client = _admin_client(db_session)
        count = self._count(db_session)

        response = client.post(
            "/api/v1/users/", json=self._body(full_name="n" * (FULL_NAME_MAX + 1))
        )

        _assert_422_naming(response, "full_name")
        assert self._count(db_session) == count

    @pytest.mark.regression
    @pytest.mark.parametrize("length", [EMAIL_MAX + 1, 254], ids=["101", "254"])
    def test_an_email_over_the_column_answers_422(
        self, db_session: Session, length: int
    ):
        client = _admin_client(db_session)
        count = self._count(db_session)

        response = client.post("/api/v1/users/", json=self._body(email=_email(length)))

        _assert_422_naming(response, "email")
        assert self._count(db_session) == count

    def test_values_exactly_the_column_length_are_created(self, db_session: Session):
        client = _admin_client(db_session)
        email = _email(EMAIL_MAX)
        full_name = "n" * FULL_NAME_MAX

        response = client.post(
            "/api/v1/users/", json=self._body(email=email, full_name=full_name)
        )

        assert response.status_code == 201, response.text
        db_session.rollback()
        row = db_session.query(User).filter(User.email == email).one()
        assert row.first_name == full_name
