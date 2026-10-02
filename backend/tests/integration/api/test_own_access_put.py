"""PUT /api/v1/admin/users/{id} and PUT /api/v1/users/{id}: a superuser cannot
remove their own superuser access or deactivate themselves (#652).

Both routes answered 200 and wrote the row. On an install with one superuser
that left nobody able to open the admin area, and only SQL could undo it. Now
both answer 400 with the same texts as ``PATCH /admin/users/{id}``, and nothing
in the request is written -- a ``full_name`` in the same body included.

A key counts only when it changes the stored value: a client that GETs the
account and PUTs it back (``UserUpdate`` requires ``username`` and ``email``)
still gets 200. Another superuser's access is changed as before.

The cases go through ``make_client_for_user``; ``TestThroughRealSignIn`` uses
a bearer token from ``POST /api/v1/auth/login`` with only the database
overridden, where the handler and ``get_current_user`` share one session.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints import admin as admin_endpoints
from backend.app.api.v1.endpoints import users as users_endpoints
from backend.app.api.v1.endpoints.users import (
    OWN_DEACTIVATION_REFUSED,
    OWN_PASSWORD_DETAIL,
    OWN_SUPERUSER_REFUSED,
)
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
URLS = pytest.mark.parametrize("url", [ADMIN_URL, USERS_URL], ids=["admin", "users"])

#: Each own change that is refused, and the text it is refused with. Both at
#: once answer the superuser text.
OWN_REFUSALS = [
    ({"is_superuser": False}, OWN_SUPERUSER_REFUSED),
    ({"is_active": False}, OWN_DEACTIVATION_REFUSED),
    ({"is_superuser": False, "is_active": False}, OWN_SUPERUSER_REFUSED),
]
OWN_REFUSAL_IDS = ["superuser", "active", "both"]


def _account(db_session, *, is_superuser: bool, role: UserRole) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"own_access_{suffix}",
        email=f"own_access_{suffix}@example.com",
        full_name=f"Own Access {suffix}",
        hashed_password=get_password_hash(PASSWORD),
        is_active=True,
        is_superuser=is_superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _superuser(db_session) -> User:
    return _account(db_session, is_superuser=True, role=UserRole.ADMIN)


def _row(db_session, user_id) -> dict:
    """Every column of the user's row, as the database holds it now."""
    db_session.expire_all()
    user = db_session.get(User, user_id)
    return {c.name: getattr(user, c.name) for c in User.__table__.columns}


def _body(user: User, **changes) -> dict:
    """What a client that read the account sends back, with *changes*."""
    body = {
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
    }
    body.update(changes)
    return body


class TestOwnAccessRefused:
    @pytest.mark.regression
    @URLS
    @pytest.mark.parametrize("change,detail", OWN_REFUSALS, ids=OWN_REFUSAL_IDS)
    def test_removing_your_own_access_is_refused_and_nothing_is_written(
        self, db_session, url, change, detail
    ):
        """On main: 200 and the row changed, on both routes."""
        actor = _superuser(db_session)
        before = _row(db_session, actor.id)
        client = make_client_for_user(db_session, actor)

        response = client.put(
            url.format(actor.id), json=_body(actor, full_name="Renamed", **change)
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == detail
        assert _row(db_session, actor.id) == before

    @pytest.mark.regression
    @URLS
    def test_only_the_changed_key_is_sent(self, db_session, url):
        """A partial body (only the flag) is refused the same way."""
        actor = _superuser(db_session)
        before = _row(db_session, actor.id)
        client = make_client_for_user(db_session, actor)

        response = client.put(
            url.format(actor.id),
            json={
                "username": actor.username,
                "email": actor.email,
                "is_superuser": False,
            },
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == OWN_SUPERUSER_REFUSED
        assert _row(db_session, actor.id) == before

    @URLS
    def test_your_own_password_is_refused_first(self, db_session, url):
        """The own-password 403 keeps its place ahead of the new 400."""
        actor = _superuser(db_session)
        before = _row(db_session, actor.id)
        client = make_client_for_user(db_session, actor)

        response = client.put(
            url.format(actor.id),
            json=_body(actor, password="An0ther-Passw0rd", is_superuser=False),
        )

        assert response.status_code == 403, response.text
        assert response.json()["detail"] == OWN_PASSWORD_DETAIL
        assert _row(db_session, actor.id) == before


class TestStillAllowed:
    @URLS
    def test_resending_your_stored_values_with_an_edit_is_saved(self, db_session, url):
        """``is_superuser: true, is_active: true`` on yourself changes nothing,
        so it is not refused: the ``full_name`` beside it is saved."""
        actor = _superuser(db_session)
        before = _row(db_session, actor.id)
        client = make_client_for_user(db_session, actor)

        response = client.put(
            url.format(actor.id), json=_body(actor, full_name="Renamed Self")
        )

        assert response.status_code == 200, response.text
        after = _row(db_session, actor.id)
        # ``full_name`` is stored as first_name / last_name.
        assert (after["first_name"], after["last_name"]) == ("Renamed", "Self")
        assert after["is_superuser"] is True and after["is_active"] is True
        untouched = set(before) - {"first_name", "last_name", "updated_at"}
        assert {c: after[c] for c in untouched} == {c: before[c] for c in untouched}

    @URLS
    @pytest.mark.parametrize(
        "change",
        [{"is_superuser": False}, {"is_active": False}],
        ids=["demote", "deactivate"],
    )
    def test_another_superuser_can_be_demoted_or_deactivated(
        self, db_session, url, change
    ):
        target = _superuser(db_session)
        actor = _superuser(db_session)
        client = make_client_for_user(db_session, actor)

        response = client.put(url.format(target.id), json=_body(target, **change))

        assert response.status_code == 200, response.text
        after = _row(db_session, target.id)
        for column, value in change.items():
            assert after[column] is value, column
        assert _row(db_session, actor.id)["is_superuser"] is True


class TestTexts:
    def test_the_texts_are_shared_with_patch(self):
        """One definition: PATCH and both PUTs answer the same strings."""
        assert admin_endpoints.OWN_DEACTIVATION_REFUSED is OWN_DEACTIVATION_REFUSED
        assert admin_endpoints.OWN_ROLE_REFUSED is users_endpoints.OWN_ROLE_REFUSED
        assert OWN_SUPERUSER_REFUSED == (
            "You can't remove your own superuser access. "
            "Ask another administrator to do it."
        )
        assert OWN_DEACTIVATION_REFUSED == "You can't deactivate your own account."


class TestDeleteAnswersAsDocumented:
    """The DELETE answers ``docs/api/endpoints.md`` states beside the PUT
    rule. Unchanged behaviour, pinned because the page now states it."""

    @pytest.mark.parametrize(
        "url,detail",
        [
            (ADMIN_URL, "Cannot delete your own user account"),
            (USERS_URL, "Superusers cannot delete themselves"),
        ],
        ids=["admin", "users"],
    )
    def test_a_superuser_cannot_delete_their_own_account(self, db_session, url, detail):
        actor = _superuser(db_session)
        before = _row(db_session, actor.id)
        client = make_client_for_user(db_session, actor)

        response = client.delete(url.format(actor.id))

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == detail
        assert _row(db_session, actor.id) == before

    def test_anyone_else_deletes_only_their_own_account(self, db_session):
        other = _account(db_session, is_superuser=False, role=UserRole.VIEWER)
        actor = _account(db_session, is_superuser=False, role=UserRole.ADMIN)
        actor_id, other_id = actor.id, other.id
        client = make_client_for_user(db_session, actor)

        refused = client.delete(USERS_URL.format(other_id))
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"] == "Not enough permissions"

        deleted = client.delete(USERS_URL.format(actor_id))
        assert deleted.status_code == 204, deleted.text
        db_session.expunge(actor)
        remaining = {
            row.id
            for row in db_session.query(User.id).filter(
                User.id.in_([actor_id, other_id])
            )
        }
        assert remaining == {other_id}


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


class TestThroughRealSignIn:
    """A real token and the real dependencies: the route reads the caller's
    row through the same session it then compares against."""

    @pytest.fixture(autouse=True)
    def _local_provider(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
        monkeypatch.setattr(settings, "ENVIRONMENT", "test")
        login_attempt_tracker.clear()
        yield
        login_attempt_tracker.clear()

    @pytest.mark.regression
    @URLS
    @pytest.mark.parametrize("change,detail", OWN_REFUSALS, ids=OWN_REFUSAL_IDS)
    def test_a_signed_in_superuser_keeps_their_access(
        self, db_session, plain_db_client, url, change, detail
    ):
        for dependency in (
            deps.get_current_user,
            deps.get_current_active_user,
            deps.get_current_superuser,
        ):
            assert dependency not in app.dependency_overrides, dependency.__name__
        actor = _superuser(db_session)
        before = _row(db_session, actor.id)
        login = plain_db_client.post(
            "/api/v1/auth/login", json={"email": actor.email, "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        refused = plain_db_client.put(
            url.format(actor.id), json=_body(actor, **change), headers=headers
        )

        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"] == detail
        assert _row(db_session, actor.id) == before
        # Still signed in, and still a superuser: the admin area opens.
        listed = plain_db_client.get("/api/v1/admin/users", headers=headers)
        assert listed.status_code == 200, listed.text
