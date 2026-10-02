"""Local sign-in matches the email address whatever its letter case (#611).

An account stored as ``Bob@acme.com`` -- which is how an administrator's
create stores it: the domain lower-cased, the local part as typed -- signs in
on ``/auth/login`` and the local ``/auth/token`` as ``bob@acme.com``,
``BOB@ACME.COM`` or any other casing.  Every spelling that reaches one
account draws on one failed-attempt budget, shared with ``/users/me/password``.
An address no account can hold (empty, containing NUL, longer than 320
characters) is answered 401 without a database statement and counts toward
nothing.

Real PostgreSQL, real bcrypt, real local JWTs; the only override is
``deps.get_db``.  Accounts are created through ``POST /api/v1/users/`` (the
administrator's create) wherever the stored spelling matters, so the row is
what production writes, not what a fixture assumes.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Iterator, List, Tuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session, sessionmaker

import backend.app.services.local_auth_service as local_auth_module
from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.core.security import create_local_access_token, get_password_hash
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.app.services.local_auth_service import (
    InvalidCredentialsError,
    LocalAuthService,
    LoginAttemptTracker,
    login_attempt_tracker,
)
from backend.tests.integration.email_lower_index import (
    INDEX,
    email_lower_index_survives_the_session,
    expected_indexdef,
    indexdef,
)

pytestmark = pytest.mark.integration

PASSWORD = "Signin-Passw0rd-611"
WRONG = "Wrong-Passw0rd-611"
NEW_PASSWORD = "Changed-Passw0rd-611"
LOGIN = "/api/v1/auth/login"
TOKEN = "/api/v1/auth/token"
ME_PASSWORD = "/api/v1/users/me/password"
SCHEMA = User.__table__.schema


@pytest.fixture(autouse=True)
def _local_provider(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)
    login_attempt_tracker.clear()
    yield
    login_attempt_tracker.clear()


@pytest.fixture
def engine(db_session):
    return db_session.get_bind()


@pytest.fixture
def client(engine) -> Iterator[TestClient]:
    """A fresh session per request.  No ``SET search_path`` statement here:
    the engine's connect hook sets it, so a request that never touches the
    database issues no statement at all."""
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


@pytest.fixture
def statements(engine) -> Iterator[List[Tuple[str, object]]]:
    """Every statement sent to the database, with its parameters."""
    seen: List[Tuple[str, object]] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


@pytest.fixture
def superuser(db_session) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"su611_{suffix}",
        email=f"su611_{suffix}@example.com",
        full_name="Superuser 611",
        hashed_password=get_password_hash(PASSWORD),
        is_active=True,
        is_superuser=True,
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _admin_create(client: TestClient, superuser: User, email: str) -> dict:
    """Create an account the way an administrator does; return the response."""
    resp = client.post(
        "/api/v1/users/",
        json={
            "username": f"u611_{uuid.uuid4().hex[:10]}",
            "email": email,
            "password": PASSWORD,
            "full_name": "Sign-in 611",
            "role": "DEVELOPER",
        },
        headers={"Authorization": f"Bearer {create_local_access_token(superuser)}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


def _token(client: TestClient, username: str, password: str = PASSWORD):
    return client.post(TOKEN, data={"username": username, "password": password})


def _token_raw(client: TestClient, body: bytes):
    return client.post(
        TOKEN,
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def _tag() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_a_mixed_case_address_signs_in_whatever_its_letter_case(client, superuser):
    created = _admin_create(client, superuser, f"Bob.Mixed{_tag()}@Acme.Example")
    stored = created["email"]
    # What the administrator's create stores: the local part as typed.
    assert stored != stored.lower()
    assert stored.split("@")[1] == "acme.example"

    spellings = {
        "exact": stored,
        "lower": stored.lower(),
        "upper": stored.upper(),
        "mixed": stored.swapcase(),
        "padded": f"  {stored.upper()}  ",
    }
    statuses = {}
    for name, spelling in spellings.items():
        for route, send in (("login", _login), ("token", _token)):
            resp = send(client, spelling)
            statuses[(name, route)] = resp.status_code
            if resp.status_code == 200:
                assert resp.json()["user"]["id"] == created["id"]
    assert statuses == dict.fromkeys(statuses, 200), statuses


def test_an_address_typed_with_a_dotted_capital_i_matches_as_the_database_folds_it(
    client, superuser
):
    """PostgreSQL lower-cases U+0130 to a plain ``i``; Python does not."""
    created = _admin_create(client, superuser, f"admin{_tag()}@mail.example")
    typed = created["email"].replace("admin", "admİn", 1)
    assert typed.lower() != created["email"]  # Python's fold differs
    resp = _login(client, typed)
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["id"] == created["id"]


# ---------------------------------------------------------------------------
# One budget per account
# ---------------------------------------------------------------------------


def test_every_ascii_casing_draws_on_one_budget(client, superuser):
    stored = _admin_create(client, superuser, f"Casey.Budget{_tag()}@acme.example")[
        "email"
    ]
    spellings = [stored, stored.lower(), stored.upper(), stored.swapcase()]
    n = login_attempt_tracker.max_attempts

    statuses = [
        _login(client, spellings[i % len(spellings)], WRONG).status_code
        for i in range(n)
    ]
    assert statuses == [401] * n

    # Locked for every spelling, on both routes, even with the right password.
    locked = [_login(client, s).status_code for s in spellings]
    locked += [_token(client, s).status_code for s in spellings]
    assert locked == [423] * (2 * len(spellings))


def _key_queries(statements, value):
    """The ``SELECT lower(:value)`` statements among *statements*."""
    return [
        sql
        for sql, params in statements
        if re.fullmatch(r"SELECT lower\(%\((\w+)\)s\) AS \w+", sql.strip())
        and isinstance(params, dict)
        and list(params.values()) == [value]
    ]


def test_the_counter_key_is_the_database_lower_of_the_typed_address(
    client, superuser, statements
):
    """Pins the key query itself.

    The budget tests alone cannot see a lost SQL ``lower()`` for A-Z: the
    counter folds its keys with Python's ``lower()`` a second time.
    """
    stored = _admin_create(client, superuser, f"Key.Probe{_tag()}@acme.example")[
        "email"
    ]
    typed = stored.swapcase()
    statements.clear()
    signed_in = _login(client, f"  {typed}  ")
    assert signed_in.status_code == 200, signed_in.text
    assert len(_key_queries(statements, typed)) == 1, [s for s, _ in statements]

    statements.clear()
    resp = client.post(
        ME_PASSWORD,
        json={"current_password": WRONG, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {signed_in.json()['access_token']}"},
    )
    assert resp.status_code == 403, resp.text
    assert len(_key_queries(statements, stored)) == 1, [s for s, _ in statements]


def test_spellings_the_database_treats_as_equal_draw_on_one_budget(client, superuser):
    stored = _admin_create(client, superuser, f"admin{_tag()}@mail.institute.example")[
        "email"
    ]
    spellings = [
        stored,
        stored.replace("admin", "admİn", 1),
        stored.upper(),
        stored.upper().replace("I", "İ"),
    ]
    n = login_attempt_tracker.max_attempts

    statuses = []
    for i in range(3 * n):
        status = _login(client, spellings[i % len(spellings)], WRONG).status_code
        statuses.append(status)
        if status == 423:
            break
    assert statuses == [401] * n + [423], statuses


def test_a_password_change_draws_on_the_sign_in_budget_for_any_spelling(
    client, superuser, db_session
):
    """The stored address holds U+0130; sign-in uses the plain ``i`` spelling.

    The two spellings are one key only if both sides are folded by the
    database, so this fails if the password change folds the stored address
    any other way.
    """
    created = _admin_create(client, superuser, f"admİn{_tag()}@mail.example")
    stored = created["email"]
    assert "İ" in stored
    plain = stored.replace("İ", "i")
    signed_in = _login(client, plain)
    assert signed_in.status_code == 200, signed_in.text
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    n = login_attempt_tracker.max_attempts
    assert [_login(client, plain, WRONG).status_code for _ in range(n)] == [401] * n

    resp = client.post(
        ME_PASSWORD,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert resp.status_code == 423, resp.text


def test_different_accounts_do_not_share_a_budget(client, superuser):
    first = _admin_create(client, superuser, f"First{_tag()}@acme.example")["email"]
    second = _admin_create(client, superuser, f"Second{_tag()}@acme.example")["email"]
    n = login_attempt_tracker.max_attempts
    for _ in range(n):
        assert _login(client, first.upper(), WRONG).status_code == 401
    assert _login(client, first).status_code == 423
    assert _login(client, second.upper()).status_code == 200


# ---------------------------------------------------------------------------
# The lookup uses the index
# ---------------------------------------------------------------------------


def test_the_sign_in_lookup_uses_the_lower_email_index(
    client, superuser, statements, engine
):
    stored = _admin_create(client, superuser, f"Index.Probe{_tag()}@acme.example")[
        "email"
    ]
    statements.clear()
    assert _login(client, stored.upper()).status_code == 200

    lookups = [
        (sql, params)
        for sql, params in statements
        if "FROM" in sql and "users" in sql and "LIMIT" in sql
    ]
    assert len(lookups) == 1, [sql for sql, _ in statements]
    sql, params = lookups[0]

    with engine.connect() as conn:
        conn.exec_driver_sql("SET enable_seqscan = off")
        plan = "\n".join(
            row[0] for row in conn.exec_driver_sql("EXPLAIN " + sql, params)
        )
    assert INDEX in plan, plan


# ---------------------------------------------------------------------------
# Addresses no account can hold
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "route,body",
    [
        pytest.param("login", {"email": "\x00", "password": PASSWORD}, id="login-nul"),
        pytest.param(
            "login",
            {"email": "someone\x00@acme.example", "password": PASSWORD},
            id="login-nul-inside",
        ),
        pytest.param("token", b"username=%00&password=x", id="token-nul"),
        pytest.param(
            "token", b"username=someone%00%40acme.example&password=x", id="token-inside"
        ),
    ],
)
def test_an_address_containing_nul_is_401_without_a_database_statement(
    client, statements, route, body
):
    statements.clear()
    if route == "login":
        resp = client.post(LOGIN, json=body)
    else:
        resp = _token_raw(client, body)
    assert resp.status_code == 401, resp.text
    assert resp.json() == {"detail": "Invalid email or password"}
    assert statements == []


def test_a_million_character_username_is_401_without_a_database_statement(
    client, statements
):
    statements.clear()
    resp = _token(client, "a" * 1_000_000 + "@acme.example")
    assert resp.status_code == 401, resp.text
    assert statements == []
    assert all(len(key) <= 320 for key in login_attempt_tracker._failures)


@pytest.mark.regression
def test_addresses_no_account_can_hold_count_toward_nothing(client, db_session):
    """Empty, NUL and overlong addresses are refused without being counted,
    so they lock nothing -- not even an account that has no email address."""
    no_email = User(
        username=f"noemail611_{_tag()}",
        email=None,
        full_name="No Email 611",
        hashed_password=get_password_hash(PASSWORD),
        is_active=True,
        is_superuser=False,
        role=UserRole.VIEWER,
    )
    db_session.add(no_email)
    db_session.commit()
    db_session.refresh(no_email)

    n = login_attempt_tracker.max_attempts
    for _ in range(n):
        assert _token(client, "   ").status_code == 401
        assert _token_raw(client, b"username=%00&password=x").status_code == 401
        assert _token(client, "b" * 1_000_000).status_code == 401
    assert len(login_attempt_tracker) == 0

    resp = client.post(
        ME_PASSWORD,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {create_local_access_token(no_email)}"},
    )
    assert resp.status_code == 204, resp.text


def test_a_password_change_for_an_account_with_no_email_has_its_own_attempt_count(
    client, db_session
):
    user = User(
        username=f"noemail611_{_tag()}",
        email=None,
        full_name="No Email 611",
        hashed_password=get_password_hash(PASSWORD),
        is_active=True,
        is_superuser=False,
        role=UserRole.VIEWER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    n = login_attempt_tracker.max_attempts
    for _ in range(n):
        assert _token(client, f"id:{user.id}", WRONG).status_code == 401

    resp = client.post(
        ME_PASSWORD,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {create_local_access_token(user)}"},
    )
    assert resp.status_code == 204, resp.text


# ---------------------------------------------------------------------------
# Two accounts for one address (only possible without the index)
# ---------------------------------------------------------------------------


def test_an_address_matching_two_accounts_is_refused(engine, monkeypatch, caplog):
    """Without ``ix_users_email_lower`` two rows can differ only in case.

    Sign-in then refuses rather than picking one.  Everything happens in one
    transaction that is rolled back, so the index is never missing for any
    other test.
    """
    tag = _tag()
    typed = f"DUPZQ{tag}@acme.example"
    bcrypt_calls = []
    real_verify = local_auth_module.verify_password

    def recording(password, hashed):
        bcrypt_calls.append(hashed)
        return real_verify(password, hashed)

    monkeypatch.setattr(local_auth_module, "verify_password", recording)
    password_hash = get_password_hash(PASSWORD)
    tracker = LoginAttemptTracker(max_attempts=3, window_seconds=60)
    service = LocalAuthService(tracker)

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(f'DROP INDEX "{SCHEMA}".{INDEX}'))
            session = Session(bind=conn)
            ids = []
            for email in (f"Dupzq{tag}@acme.example", f"dupzq{tag}@acme.example"):
                row = User(
                    id=uuid.uuid4(),
                    username=f"dup611_{uuid.uuid4().hex[:8]}",
                    email=email,
                    hashed_password=password_hash,
                    is_active=True,
                    is_superuser=False,
                    role=UserRole.DEVELOPER,
                )
                session.add(row)
                ids.append(str(row.id))
            session.flush()
            with caplog.at_level(logging.WARNING, logger=local_auth_module.__name__):
                with pytest.raises(InvalidCredentialsError):
                    service.authenticate(session, typed, PASSWORD)
            session.close()
        finally:
            trans.rollback()

    assert bcrypt_calls == [local_auth_module._DUMMY_PASSWORD_HASH]
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.name == local_auth_module.__name__ and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, warnings
    assert all(account_id in warnings[0] for account_id in ids)
    # The typed address appears nowhere in it ("zq" is not a hex digit, so
    # no account id can contain it).
    assert "dupzq" not in warnings[0].lower()
    assert "acme.example" not in warnings[0]
    with engine.connect() as conn:
        assert indexdef(conn, SCHEMA) == expected_indexdef(SCHEMA)
