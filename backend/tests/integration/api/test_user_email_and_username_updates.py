"""PUT /api/v1/users/{id}: only a superuser changes an email address or username.

``UserUpdate`` requires both fields, so every request from a non-superuser
-- whatever their role, ADMIN included -- resends them. It is accepted only
when the email address is the stored one as the request's own parser
(EmailStr) reads it, and the username is exactly the stored one; the two
values are then dropped, so the row keeps its bytes. Anything else answers
403, including a change of case in the local part and a look-alike
character. Administrators change those fields through
``/api/v1/admin/users/{id}``, which is untouched.

The role matrix goes through ``make_client_for_user``; the sign-in test at the
bottom uses real bearer tokens from ``POST /api/v1/auth/login``, with nothing
but the database overridden.
"""

from __future__ import annotations

import uuid
from typing import Iterator

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api import deps
from backend.app.db.session import get_db as _session_get_db
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import make_client_for_user

pytestmark = [pytest.mark.integration]

PASSWORD = "Str0ng-Passw0rd"
ADMIN_ONLY_IDENTITY_DETAIL = (
    "Only an administrator can change an account's email address or username."
)
#: U+212A KELVIN SIGN, which lower-cases to an ASCII "k".
KELVIN = "\u212a"
ROLES = [UserRole.VIEWER, UserRole.ANALYST, UserRole.DEVELOPER, UserRole.ADMIN]


def get_password_hash(password: str) -> str:
    """A bcrypt hash the password sign-in verifies (cheap rounds for tests)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode()


def _make_user(
    db_session: Session,
    *,
    role: UserRole = UserRole.VIEWER,
    superuser: bool = False,
    email: str | None = None,
    hashed_password: str | None = None,
) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"Kim_{suffix}",
        # A mixed-case local part, starting with "K", so the case-only and
        # Kelvin-sign variants below are both different strings.
        email=email or f"Kate.Doe.{suffix}@example.com",
        full_name="Before",
        hashed_password=hashed_password or get_password_hash(PASSWORD),
        is_active=True,
        is_superuser=superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _row(db_session: Session, user_id) -> tuple:
    """(email, username, full_name) as the database holds them now.

    A column query, not the entity: the entity would come back from the
    session's identity map as the very object the test compares against.
    ``full_name`` is a property over ``first_name``/``last_name``; the names
    used here are one word, so ``first_name`` holds all of it.
    """
    return tuple(
        db_session.query(User.email, User.username, User.first_name)
        .filter(User.id == user_id)
        .one()
    )


def _as_created(user: User) -> tuple:
    return (user.email, user.username, "Before")


@pytest.fixture(params=ROLES, ids=lambda r: r.value)
def member(request, db_session: Session) -> Iterator[tuple[User, TestClient]]:
    """A non-superuser of each role, and a client signed in as them."""
    user = _make_user(db_session, role=request.param)
    assert user.is_superuser is False
    client = make_client_for_user(db_session, user)
    yield user, client
    app.dependency_overrides.clear()


def _refused(resp, db_session: Session, user_id, before: tuple) -> None:
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == ADMIN_ONLY_IDENTITY_DETAIL
    # Nothing in the request was applied, full_name included.
    assert _row(db_session, user_id) == before


# ---------------------------------------------------------------------------
# A non-superuser of every role
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_a_user_cannot_change_their_own_email(member, db_session):
    user, client = member
    before = _as_created(user)
    resp = client.put(
        f"/api/v1/users/{user.id}",
        json={
            "username": user.username,
            "email": f"someone.else.{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "After",
        },
    )
    _refused(resp, db_session, user.id, before)


@pytest.mark.regression
def test_a_change_of_case_in_the_email_is_a_change(member, db_session):
    user, client = member
    before = _as_created(user)
    for variant in (user.email.lower(), user.email.upper()):
        resp = client.put(
            f"/api/v1/users/{user.id}",
            json={"username": user.username, "email": variant, "full_name": "After"},
        )
        _refused(resp, db_session, user.id, before)


@pytest.mark.regression
def test_a_look_alike_character_in_the_email_is_a_change(member, db_session):
    """The Kelvin sign (U+212A) lower-cases to "k", so a lowered comparison
    calls it the same address as ``kate.doe@``. EmailStr normalises it to an
    ASCII capital "K": a different address from the stored one."""
    user, client = member
    user.email = user.email.lower()
    db_session.commit()
    before = _as_created(user)
    variant = KELVIN + user.email[1:]
    assert variant != user.email
    assert variant.lower() == user.email  # why the comparison is exact
    resp = client.put(
        f"/api/v1/users/{user.id}",
        json={"username": user.username, "email": variant, "full_name": "After"},
    )
    _refused(resp, db_session, user.id, before)


@pytest.mark.regression
def test_a_user_cannot_change_their_own_username(member, db_session):
    user, client = member
    before = _as_created(user)
    for variant in (f"renamed_{uuid.uuid4().hex[:8]}", user.username.lower()):
        resp = client.put(
            f"/api/v1/users/{user.id}",
            json={"username": variant, "email": user.email, "full_name": "After"},
        )
        _refused(resp, db_session, user.id, before)


def test_resending_the_stored_email_and_username_is_accepted(member, db_session):
    user, client = member
    email, username = user.email, user.username
    resp = client.put(
        f"/api/v1/users/{user.id}",
        json={"username": username, "email": email, "full_name": "After"},
    )
    assert resp.status_code == 200, resp.text
    assert _row(db_session, user.id) == (email, username, "After")


# ---------------------------------------------------------------------------
# Rows whose stored address is not in EmailStr's form
#
# Accounts created from an identity provider's attributes, by SQL, a seed or a
# restore are stored as written; the API never writes such a row, so these
# fixtures write it directly.
# ---------------------------------------------------------------------------


@pytest.fixture(params=ROLES, ids=lambda r: r.value)
def member_as_written(request, db_session: Session):
    """A non-superuser whose stored address has an upper-case domain."""
    suffix = uuid.uuid4().hex[:8]
    user = _make_user(db_session, role=request.param, email=f"Bob.{suffix}@Corp.COM")
    client = make_client_for_user(db_session, user)
    yield user, client
    app.dependency_overrides.clear()


def _put(client: TestClient, user: User, email: str):
    return client.put(
        f"/api/v1/users/{user.id}",
        json={"username": user.username, "email": email, "full_name": "After"},
    )


@pytest.mark.regression
def test_resending_an_address_stored_with_an_upper_case_domain_is_accepted(
    member_as_written, db_session
):
    """EmailStr lower-cases the domain of what is sent; the stored address is
    read the same way before the comparison, and is not rewritten."""
    user, client = member_as_written
    email, username = user.email, user.username
    assert email.endswith("@Corp.COM")
    resp = _put(client, user, email)
    assert resp.status_code == 200, resp.text
    # Byte for byte, the domain's case included.
    assert _row(db_session, user.id) == (email, username, "After")


@pytest.mark.regression
def test_the_parsers_spelling_of_the_stored_address_is_accepted_and_not_written(
    member_as_written, db_session
):
    user, client = member_as_written
    email, username = user.email, user.username
    local, domain = email.split("@")
    resp = _put(client, user, f"{local}@{domain.lower()}")
    assert resp.status_code == 200, resp.text
    assert _row(db_session, user.id) == (email, username, "After")


@pytest.mark.regression
def test_a_change_of_case_in_the_local_part_is_refused_for_a_row_as_written(
    member_as_written, db_session
):
    user, client = member_as_written
    before = _as_created(user)
    local, domain = user.email.split("@")
    resp = _put(client, user, f"{local.lower()}@{domain}")
    _refused(resp, db_session, user.id, before)


@pytest.mark.regression
def test_a_look_alike_character_is_refused_for_a_row_as_written(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = _make_user(db_session, email=f"kate.{suffix}@Corp.COM")
    client = make_client_for_user(db_session, user)
    try:
        before = _as_created(user)
        variant = KELVIN + user.email[1:]
        assert variant.lower() == user.email.lower()
        _refused(_put(client, user, variant), db_session, user.id, before)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("stored", [None, "localhost"])
def test_a_stored_address_that_is_missing_or_unparseable_never_matches(
    db_session, stored
):
    """Nothing the request can send equals it, so the request is refused.

    (EmailStr refuses an address at ``localhost`` itself, so resending one is
    a 422 before this check.) The row is removed afterwards: other tests list
    every user, and a user without an email address cannot be listed."""
    user = _make_user(db_session)
    if stored is not None:
        stored = f"dev-{uuid.uuid4().hex[:8]}@{stored}"
    user.email = stored
    db_session.commit()
    client = make_client_for_user(db_session, user)
    try:
        resp = _put(client, user, f"someone.{uuid.uuid4().hex[:8]}@example.com")
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == ADMIN_ONLY_IDENTITY_DETAIL
        assert _row(db_session, user.id) == (stored, user.username, "Before")
    finally:
        app.dependency_overrides.clear()
        db_session.delete(user)
        db_session.commit()


# ---------------------------------------------------------------------------
# A superuser
# ---------------------------------------------------------------------------


def test_a_superuser_can_change_a_users_email_and_username(admin_client, db_session):
    target = _make_user(db_session)
    new_email = f"renamed.{uuid.uuid4().hex[:8]}@example.com"
    new_username = f"renamed_{uuid.uuid4().hex[:8]}"
    resp = admin_client.put(
        f"/api/v1/users/{target.id}",
        json={"username": new_username, "email": new_email},
    )
    assert resp.status_code == 200, resp.text
    assert _row(db_session, target.id)[:2] == (new_email, new_username)


def test_a_superuser_can_change_their_own_email_and_username(
    admin_client, admin_user, db_session
):
    new_email = f"self.{uuid.uuid4().hex[:8]}@example.com"
    new_username = f"self_{uuid.uuid4().hex[:8]}"
    resp = admin_client.put(
        f"/api/v1/users/{admin_user.id}",
        json={"username": new_username, "email": new_email},
    )
    assert resp.status_code == 200, resp.text
    assert _row(db_session, admin_user.id)[:2] == (new_email, new_username)


# ---------------------------------------------------------------------------
# Password sign-in, with real tokens
# ---------------------------------------------------------------------------


@pytest.fixture
def anonymous(db_session: Session) -> Iterator[TestClient]:
    """A client with only the database overridden: authentication is real."""
    factory = sessionmaker(
        bind=db_session.get_bind(), autocommit=False, autoflush=False
    )

    def override_get_db():
        session = factory()
        session.execute(text("SET search_path TO test_experimentation"))
        try:
            yield session
        finally:
            session.close()

    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[_session_get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def _login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


@pytest.mark.regression
def test_another_users_password_sign_in_is_unaffected_by_a_refused_email_change(
    anonymous, db_session
):
    """A mixed-case address and its lower-case copy cannot both be stored.

    Password sign-in looks the lower-cased address up first, so a second row
    holding the lower-case copy would answer for the first one's address.
    The self-service change that would create that row is refused, and the
    first account signs in as before.
    """
    other = _make_user(
        db_session,
        email=f"Sam.Lee.{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=get_password_hash("0ther-Passw0rd"),
    )
    assert other.email != other.email.lower()
    before = _login(anonymous, other.email, "0ther-Passw0rd")
    assert before.status_code == 200, before.text

    member = _make_user(db_session)
    member_before = _as_created(member)
    signed_in = _login(anonymous, member.email)
    assert signed_in.status_code == 200, signed_in.text
    token = signed_in.json()["access_token"]

    resp = anonymous.put(
        f"/api/v1/users/{member.id}",
        json={"username": member.username, "email": other.email.lower()},
        headers={"Authorization": f"Bearer {token}"},
    )

    after = _login(anonymous, other.email, "0ther-Passw0rd")
    assert after.status_code == 200, after.text
    assert after.json()["user"]["id"] == str(other.id)
    assert _row(db_session, member.id) == member_before
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == ADMIN_ONLY_IDENTITY_DETAIL
