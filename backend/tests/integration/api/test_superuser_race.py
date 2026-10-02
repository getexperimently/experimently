"""Two superusers acting on each other cannot leave no active superuser (#652).

``PATCH /admin/users/{id}`` already locked the active superuser rows before
deactivating one. Both PUT routes (demoting or deactivating another
superuser) and both DELETE routes (deleting one) did not, so two superusers
doing that to each other at the same moment could both succeed. All five now
call ``require_still_active_superuser``: it sets a bounded ``lock_timeout``,
locks the rows in id order and refuses a caller who is no longer an active
superuser once it holds them.

* ``TestLockOrder`` records the statements each route sends.
* ``TestCallerChangedJustBefore`` signs in for real (only the database is
  overridden, so the handler and ``get_current_user`` share one session, as
  in production) and commits the caller's demotion, deactivation or deletion
  through a separate connection just before the lock.
* ``TestLockWaitIsBounded`` holds a superuser row from a second connection.

Postgres only: ``SET LOCAL`` and ``FOR UPDATE`` are what is under test.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select, text, update
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints import users as users_endpoints
from backend.app.core.config import settings
from backend.app.core.security import get_password_hash
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.app.services.local_auth_service import login_attempt_tracker
from backend.tests.integration.conftest import make_client_for_user

pytestmark = [pytest.mark.integration]

PASSWORD = "Str0ng-Passw0rd"
ADMIN_URL = "/api/v1/admin/users/{}"
USERS_URL = "/api/v1/users/{}"
USERS = User.__table__


def _account(db_session, *, is_superuser: bool = True) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"su_race_{suffix}",
        email=f"su_race_{suffix}@example.com",
        full_name=f"Superuser Race {suffix}",
        hashed_password=get_password_hash(PASSWORD),
        is_active=True,
        is_superuser=is_superuser,
        role=UserRole.ADMIN if is_superuser else UserRole.VIEWER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _row(db_session, user_id):
    """Every column of the user's row as the database holds it, or None."""
    db_session.expire_all()
    user = db_session.get(User, user_id)
    if user is None:
        return None
    return {c.name: getattr(user, c.name) for c in User.__table__.columns}


def _body(user: User, **changes) -> dict:
    body = {
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
    }
    body.update(changes)
    return body


#: Each route that takes an active superuser out of the set, as
#: (method, url, body for the target). Both PUT changes appear on both URLs.
ROUTES = {
    "patch-admin-deactivate": ("patch", ADMIN_URL, lambda t: {"is_active": False}),
    "put-admin-demote": ("put", ADMIN_URL, lambda t: _body(t, is_superuser=False)),
    "put-admin-deactivate": ("put", ADMIN_URL, lambda t: _body(t, is_active=False)),
    "put-users-demote": ("put", USERS_URL, lambda t: _body(t, is_superuser=False)),
    "put-users-deactivate": ("put", USERS_URL, lambda t: _body(t, is_active=False)),
    "delete-admin": ("delete", ADMIN_URL, None),
    "delete-users": ("delete", USERS_URL, None),
}


def _send(client, route: str, target: User, headers=None):
    method, url, body = ROUTES[route]
    kwargs = {"headers": headers} if headers else {}
    if body is not None:
        kwargs["json"] = body(target)
    return getattr(client, method)(url.format(target.id), **kwargs)


def _first(statements, predicate):
    return next((i for i, s in enumerate(statements) if predicate(s)), None)


def _is_lock_timeout(s: str) -> bool:
    return s.startswith("SET LOCAL lock_timeout")


def _is_superuser_lock(s: str) -> bool:
    return s.startswith("SELECT ") and ".users" in s and s.endswith(" FOR UPDATE")


def _is_users_write(s: str) -> bool:
    return (s.startswith("UPDATE ") and ".users SET " in s) or (
        s.startswith("DELETE FROM ") and ".users " in s
    )


@pytest.mark.regression
class TestLockOrder:
    """A5: the bound, then the lock in id order, then the write."""

    @pytest.mark.parametrize("route", list(ROUTES))
    def test_the_rows_are_locked_with_a_bound_before_the_write(self, db_session, route):
        target = _account(db_session)
        client = make_client_for_user(db_session, _account(db_session))
        engine = db_session.get_bind()
        statements: list = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(" ".join(statement.split()))

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = _send(client, route, target)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert response.status_code in (200, 204), response.text
        bound = _first(statements, _is_lock_timeout)
        lock = _first(statements, _is_superuser_lock)
        write = _first(statements, _is_users_write)
        assert bound is not None, statements
        assert lock is not None, statements
        assert write is not None, statements
        assert bound < lock < write, statements
        assert " ORDER BY " in statements[lock], statements[lock]
        assert statements[bound] == (
            f"SET LOCAL lock_timeout = '{users_endpoints.SUPERUSER_LOCK_TIMEOUT}'"
        )

    @pytest.mark.parametrize(
        "route,make_target,body",
        [
            ("put-admin", True, {"full_name": "Renamed"}),
            ("put-users", True, {"full_name": "Renamed"}),
            ("delete-admin", False, None),
            ("delete-users", False, None),
        ],
    )
    def test_a_write_that_removes_no_superuser_takes_no_lock(
        self, db_session, route, make_target, body
    ):
        """Renaming a superuser, or deleting an account that is not one."""
        target = _account(db_session, is_superuser=make_target)
        client = make_client_for_user(db_session, _account(db_session))
        engine = db_session.get_bind()
        statements: list = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(" ".join(statement.split()))

        url = ADMIN_URL if route.endswith("admin") else USERS_URL
        event.listen(engine, "before_cursor_execute", record)
        try:
            if body is None:
                response = client.delete(url.format(target.id))
            else:
                response = client.put(url.format(target.id), json=_body(target, **body))
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert response.status_code in (200, 204), response.text
        assert _first(statements, _is_superuser_lock) is None, statements
        assert _first(statements, _is_lock_timeout) is None, statements


@pytest.fixture
def plain_db_client(db_session):
    """A TestClient whose only override is the database session: real auth."""
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)

    def override_get_db():
        session = factory()
        session.execute(text("SET search_path TO test_experimentation"))
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


@pytest.fixture
def local_sign_in(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    login_attempt_tracker.clear()
    yield
    login_attempt_tracker.clear()


def _sign_in(client, user) -> dict:
    for dependency in (
        deps.get_current_user,
        deps.get_current_active_user,
        deps.get_current_superuser,
    ):
        assert dependency not in app.dependency_overrides, dependency.__name__
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _demote(conn, user_id):
    conn.execute(update(USERS).where(USERS.c.id == user_id).values(is_superuser=False))


def _deactivate(conn, user_id):
    conn.execute(update(USERS).where(USERS.c.id == user_id).values(is_active=False))


def _remove(conn, user_id):
    # Whatever still points at the account without ON DELETE would block the
    # delete; sign-in leaves nothing of the kind today, and the delete below
    # fails the test loudly if that changes.
    conn.execute(delete(USERS).where(USERS.c.id == user_id))


#: What the caller becomes just before the lock, and the answer.
CHANGES = {
    "demoted": (_demote, 403, "Not enough permissions"),
    "deactivated": (_deactivate, 400, "Inactive user"),
    "gone": (_remove, 400, "Inactive user"),
}

#: The routes of A6, one change of the target each: the five route/method
#: pairs, the PUTs once with each kind of change.
RACE_ROUTES = [
    "patch-admin-deactivate",
    "put-admin-demote",
    "put-users-deactivate",
    "delete-admin",
    "delete-users",
]
RACE_CELLS = [
    (route, change) for route in RACE_ROUTES for change in ("demoted", "deactivated")
] + [(route, "gone") for route in ("delete-admin", "delete-users", "put-admin-demote")]


@pytest.mark.regression
@pytest.mark.usefixtures("local_sign_in")
class TestCallerChangedJustBefore:
    """A6: another superuser's change to the caller lands just before the lock."""

    @pytest.mark.parametrize(
        "route,change", RACE_CELLS, ids=[f"{r}-{c}" for r, c in RACE_CELLS]
    )
    def test_the_caller_is_refused_and_the_target_is_unchanged(
        self, db_session, plain_db_client, monkeypatch, route, change
    ):
        target = _account(db_session)
        actor = _account(db_session)
        actor_id = actor.id
        headers = _sign_in(plain_db_client, actor)
        before = _row(db_session, target.id)
        apply_change, status_code, detail = CHANGES[change]
        engine = db_session.get_bind()
        original = users_endpoints.lock_active_superusers
        calls: list = []

        def changed_just_before(db):
            calls.append(route)
            with engine.begin() as conn:
                apply_change(conn, actor_id)
            return original(db)

        monkeypatch.setattr(
            users_endpoints, "lock_active_superusers", changed_just_before
        )

        response = _send(plain_db_client, route, target, headers=headers)

        assert calls == [route], "the route never took the superuser lock"
        assert response.status_code == status_code, response.text
        assert response.json()["detail"] == detail
        assert _row(db_session, target.id) == before


@pytest.mark.regression
@pytest.mark.usefixtures("local_sign_in")
class TestLockWaitIsBounded:
    """EM C3: a request that waits for the superuser rows longer than
    ``SUPERUSER_LOCK_TIMEOUT`` ends with a 500 and writes nothing, instead of
    holding the one worker for as long as the other transaction lasts."""

    #: How long the request may take before the test calls it stuck. Only a
    #: failure detector: nothing is asserted about how long the request took.
    JOIN_BOUND_SECONDS = 20

    def test_a_demotion_waiting_on_a_held_row_gives_up(
        self, db_session, plain_db_client, monkeypatch
    ):
        monkeypatch.setattr(users_endpoints, "SUPERUSER_LOCK_TIMEOUT", "200ms")
        target = _account(db_session)
        held = _account(db_session)
        actor = _account(db_session)
        headers = _sign_in(plain_db_client, actor)
        before = _row(db_session, target.id)
        engine = db_session.get_bind()

        holder = engine.connect()
        transaction = holder.begin()
        holder.execute(
            select(USERS.c.id).where(USERS.c.id == held.id).with_for_update()
        )
        result: dict = {}

        def demote():
            try:
                result["response"] = _send(
                    plain_db_client, "put-admin-demote", target, headers=headers
                )
            except BaseException as exc:  # reported below, not swallowed
                result["error"] = exc

        worker = threading.Thread(target=demote, daemon=True)
        worker.start()
        try:
            worker.join(timeout=self.JOIN_BOUND_SECONDS)
            stuck = worker.is_alive()
        finally:
            transaction.rollback()
            holder.close()
        worker.join(timeout=self.JOIN_BOUND_SECONDS)

        assert not stuck, "the request was still waiting for the held row"
        assert "error" not in result, result.get("error")
        assert result["response"].status_code == 500, result["response"].text
        assert _row(db_session, target.id) == before


def test_the_documented_bound_is_five_seconds():
    """The API reference (endpoints.md) tells clients the wait is at most 5 s."""
    assert users_endpoints.SUPERUSER_LOCK_TIMEOUT == "5s"
