"""Another account's email address in a different letter case answers 409 (#343).

``users.email`` is unique only as an exact string, so ``POST /api/v1/users/``,
``PUT /api/v1/users/{id}`` and ``PUT /api/v1/admin/users/{id}`` accepted
``pat.lee@...`` while another account held ``Pat.Lee@...`` (201/200, and a
second account with the same address). An identical-case duplicate on either
PUT reached the commit and answered 500.

All three routes now look the address up with ``lower(email) = lower(:email)``
in SQL, excluding the row being updated, and answer 409 "Email already
registered". When the commit itself fails with a unique violation (a row
committed between the check and the commit), the transaction is rolled back
and the same query is run again; a hit answers 409. A username collision is
answered 409 "Username already registered", never "Email already registered"
(#610; see ``test_user_username_conflict.py``).

The clients are built with ``raise_server_exceptions=False`` so that a server
error shows up as the 500 a real client sees, not as an exception raised into
the test.
"""

from __future__ import annotations

import uuid
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.app.api.v1.endpoints import admin as admin_endpoints
from backend.app.api.v1.endpoints import users as users_endpoints
from backend.app.core.database_config import get_schema_name
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

pytestmark = [pytest.mark.integration]

EMAIL_TAKEN = "Email already registered"
USERNAME_TAKEN = "Username already registered"
PASSWORD = "Str0ng-Passw0rd"

#: The two PUT routes, as a path template.
PUT_ROUTES = ["/api/v1/users/{id}", "/api/v1/admin/users/{id}"]


@pytest.fixture(autouse=True)
def _clear_auth_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _make_user(
    db_session: Session,
    *,
    email: str | None = None,
    superuser: bool = False,
    role: UserRole = UserRole.VIEWER,
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"case_{suffix}",
        email=email or f"Pat.Lee.{suffix}@example.com",
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


def _holders(db_session: Session, email: str) -> int:
    """How many rows hold ``email`` in any letter case."""
    db_session.rollback()
    return (
        db_session.query(User)
        .filter(func.lower(User.email) == func.lower(email))
        .count()
    )


def _user_count(db_session: Session) -> int:
    db_session.rollback()
    return db_session.query(User).count()


def _put_body(target: User, **changes) -> dict:
    body = {"username": target.username, "email": target.email}
    body.update(changes)
    return body


def _skip_pre_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the routes' pre-check find nothing, as if the row came later.

    Both route modules hold their own reference to the helper.
    """

    def _finds_nothing(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(users_endpoints, "refuse_if_email_held", _finds_nothing)
    monkeypatch.setattr(admin_endpoints, "refuse_if_email_held", _finds_nothing)


class TestCreate:
    """POST /api/v1/users/"""

    @pytest.mark.regression
    def test_a_case_variant_of_another_accounts_address_answers_409(
        self, db_session: Session
    ):
        holder = _make_user(db_session)
        client = _admin_client(db_session)
        before = _user_count(db_session)

        response = client.post(
            "/api/v1/users/",
            json={
                "username": f"new_{uuid.uuid4().hex[:8]}",
                "email": holder.email.lower(),
                "password": PASSWORD,
                "full_name": "New",
            },
        )

        assert response.status_code == 409, response.text
        assert response.json() == {"detail": EMAIL_TAKEN}
        assert _user_count(db_session) == before
        assert _holders(db_session, holder.email) == 1

    def test_an_identical_address_answers_409(self, db_session: Session):
        holder = _make_user(db_session)
        client = _admin_client(db_session)
        before = _user_count(db_session)

        response = client.post(
            "/api/v1/users/",
            json={
                "username": f"new_{uuid.uuid4().hex[:8]}",
                "email": holder.email,
                "password": PASSWORD,
                "full_name": "New",
            },
        )

        assert response.status_code == 409, response.text
        assert response.json() == {"detail": EMAIL_TAKEN}
        assert _user_count(db_session) == before

    def test_a_free_address_is_still_created(self, db_session: Session):
        client = _admin_client(db_session)
        email = f"Free.{uuid.uuid4().hex[:8]}@example.com"

        response = client.post(
            "/api/v1/users/",
            json={
                "username": f"new_{uuid.uuid4().hex[:8]}",
                "email": email,
                "password": PASSWORD,
                "full_name": "New",
            },
        )

        assert response.status_code == 201, response.text
        # The stored address keeps the case it was sent in.
        assert response.json()["email"] == email

    def test_the_race_with_an_identical_address_still_answers_409(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ):
        """The pre-check misses; the exact unique index refuses; the re-query maps it."""
        holder = _make_user(db_session)
        client = _admin_client(db_session)
        before = _user_count(db_session)
        _skip_pre_check(monkeypatch)

        response = client.post(
            "/api/v1/users/",
            json={
                "username": f"new_{uuid.uuid4().hex[:8]}",
                "email": holder.email,
                "password": PASSWORD,
                "full_name": "New",
            },
        )

        assert response.status_code == 409, response.text
        assert response.json() == {"detail": EMAIL_TAKEN}
        assert _user_count(db_session) == before


@pytest.mark.parametrize("route", PUT_ROUTES)
class TestUpdate:
    """PUT /api/v1/users/{id} (superuser) and PUT /api/v1/admin/users/{id}."""

    @pytest.mark.regression
    def test_a_case_variant_of_another_accounts_address_answers_409(
        self, db_session: Session, route: str
    ):
        holder = _make_user(db_session)
        target = _make_user(db_session)
        client = _admin_client(db_session)
        target_before = _row(db_session, target.id)

        response = client.put(
            route.format(id=target.id),
            json=_put_body(target, email=holder.email.upper(), full_name="After"),
        )

        assert response.status_code == 409, response.text
        assert response.json() == {"detail": EMAIL_TAKEN}
        assert _row(db_session, target.id) == target_before
        assert _holders(db_session, holder.email) == 1

    @pytest.mark.regression
    def test_an_identical_address_answers_409(self, db_session: Session, route: str):
        holder = _make_user(db_session)
        target = _make_user(db_session)
        client = _admin_client(db_session)
        target_before = _row(db_session, target.id)

        response = client.put(
            route.format(id=target.id),
            json=_put_body(target, email=holder.email, full_name="After"),
        )

        assert response.status_code == 409, response.text
        assert response.json() == {"detail": EMAIL_TAKEN}
        assert _row(db_session, target.id) == target_before

    def test_the_race_with_an_identical_address_still_answers_409(
        self, db_session: Session, route: str, monkeypatch: pytest.MonkeyPatch
    ):
        """The pre-check misses; the exact unique index refuses; the re-query maps it.

        Without the lower(email) index only an identical-case duplicate trips
        a unique index, so that is the collision this race uses.
        """
        holder = _make_user(db_session)
        target = _make_user(db_session)
        client = _admin_client(db_session)
        target_before = _row(db_session, target.id)
        _skip_pre_check(monkeypatch)

        response = client.put(
            route.format(id=target.id),
            json=_put_body(target, email=holder.email, full_name="After"),
        )

        assert response.status_code == 409, response.text
        assert response.json() == {"detail": EMAIL_TAKEN}
        assert _row(db_session, target.id) == target_before

    def test_re_casing_the_accounts_own_address_succeeds(
        self, db_session: Session, route: str
    ):
        target = _make_user(db_session)
        client = _admin_client(db_session)
        local, domain = target.email.split("@")
        recased = f"{local.upper()}@{domain}"

        response = client.put(
            route.format(id=target.id), json=_put_body(target, email=recased)
        )

        assert response.status_code == 200, response.text
        assert response.json()["email"] == recased
        assert _row(db_session, target.id)[0] == recased

    def test_resending_the_stored_address_is_not_refused_when_a_pair_exists(
        self, db_session: Session, route: str
    ):
        """An account in a pre-existing case pair (made by an administrator,
        SQL or a restore) can still be edited without changing its address."""
        target = _make_user(db_session)
        _make_user(db_session, email=target.email.lower())  # the other half
        client = _admin_client(db_session)

        response = client.put(
            route.format(id=target.id), json=_put_body(target, full_name="After")
        )

        assert response.status_code == 200, response.text
        assert _row(db_session, target.id) == (
            target.email,
            target.username,
            "After",
        )

    @pytest.mark.regression
    def test_resending_a_stored_address_with_a_mixed_case_domain_is_not_refused(
        self, db_session: Session, route: str
    ):
        """The stored row's domain is not lower-case (an administrator, SQL or
        a restore wrote it), and it sits in a case pair. Resending it exactly
        as stored while changing another field answers 200 and keeps the
        row's bytes, although EmailStr lower-cases the domain of the request.
        """
        suffix = uuid.uuid4().hex[:8]
        target = _make_user(db_session, email=f"Bob.{suffix}@Acme.COM")
        # The other half of the pair is exactly what EmailStr makes of the
        # target's address, so writing that back would also collide exactly.
        _make_user(db_session, email=f"Bob.{suffix}@acme.com")
        client = _admin_client(db_session)

        response = client.put(
            route.format(id=target.id),
            json=_put_body(target, full_name="After"),
        )

        assert response.status_code == 200, response.text
        assert _row(db_session, target.id) == (
            f"Bob.{suffix}@Acme.COM",
            target.username,
            "After",
        )

    def test_a_username_collision_is_not_answered_email_already_registered(
        self, db_session: Session, route: str
    ):
        """A duplicate username on a PUT answers 409 "Username already
        registered" (#610), never the email answer."""
        other = _make_user(db_session)
        target = _make_user(db_session)
        client = _admin_client(db_session)
        target_before = _row(db_session, target.id)

        for body in (
            # the stored address resent, the other account's username
            _put_body(target, username=other.username),
            # a free new address, the other account's username
            _put_body(
                target,
                username=other.username,
                email=f"Free.{uuid.uuid4().hex[:8]}@example.com",
            ),
        ):
            response = client.put(route.format(id=target.id), json=body)

            assert response.status_code == 409, response.text
            assert response.json() == {"detail": USERNAME_TAKEN}
            assert _row(db_session, target.id) == target_before


class TestNonDefaultSchema:
    """The suite runs in ``test_experimentation``, not the default schema.

    The exact email index is named after the schema, so its name here is not
    the one a migrated default-schema database has. A mapping keyed on an
    index name rather than on the re-query would miss it; the race tests above
    run in this schema and answer 409.
    """

    def test_the_exact_email_index_is_not_named_as_in_the_default_schema(
        self, db_session: Session
    ):
        schema = get_schema_name()
        names = {
            row[0]
            for row in db_session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema AND tablename = 'users' "
                    "AND indexdef LIKE 'CREATE UNIQUE INDEX%(email)'"
                ),
                {"schema": schema},
            )
        }

        assert schema != "experimentation"
        assert names, "no exact unique index on users.email in this schema"
        assert "ix_experimentation_users_email" not in names
        assert "ix_users_email_lower" not in names
