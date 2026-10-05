"""Holdout and exclusion-group admin operations accept ADMIN only, as documented (#904).

The real routes on Postgres, signed in with local tokens as real users. Each
role is a NON-superuser (a superuser passes every check, so a superuser
fixture would prove nothing about the role); the superuser is one extra cell.

The five operations, and who may perform them:

* ``GET /holdout/all``, ``POST /holdout``, ``PUT /holdout/{id}``,
  ``DELETE /mutual-exclusion-groups/{id}`` (archive), and
  ``PUT /mutual-exclusion-groups/{id}`` with a ``status`` different from the
  stored one (archive or unarchive): ADMIN and superuser only. DEVELOPER,
  ANALYST and VIEWER answer 403.

And what is unchanged: a DEVELOPER may still rename a group, and may send the
group's current ``status`` back (a GET-modify-PUT round trip).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.audit_log import AuditLog
from backend.app.models.global_holdout import GlobalHoldout
from backend.app.models.mutual_exclusion_group import (
    MutualExclusionGroup,
    MutualExclusionGroupStatus,
)
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.regression]

SCHEMA = "test_experimentation"
P = "hr904"
V1 = "/api/v1"

# (role, superuser) -> may perform the admin operations
USERS = {
    "admin": (UserRole.ADMIN, False),
    "developer": (UserRole.DEVELOPER, False),
    "analyst": (UserRole.ANALYST, False),
    "viewer": (UserRole.VIEWER, False),
    "superuser": (UserRole.ADMIN, True),
}
ALLOWED = {"admin", "superuser"}


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


@pytest.fixture
def client(test_db):
    factory = sessionmaker(bind=test_db, autocommit=False, autoflush=False)

    def override_get_db():
        session = factory()
        session.execute(text(f"SET search_path TO {SCHEMA}"))
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


@pytest.fixture(autouse=True)
def _cleanup(db_session):
    """Remove every holdout, group, audit row and user this module created."""
    yield
    s = db_session
    s.rollback()
    users = s.query(User).filter(User.username.like(f"{P}_%")).all()
    for model in (GlobalHoldout, MutualExclusionGroup):
        s.query(model).filter(model.name.like(f"{P}%")).delete(
            synchronize_session=False
        )
    s.query(AuditLog).filter(
        AuditLog.user_email.like(f"{P}%") | AuditLog.entity_name.like(f"{P}%")
    ).delete(synchronize_session=False)
    for user in users:
        s.delete(user)
    s.commit()


def _user(db_session, who: str) -> User:
    from backend.app.api.v1.endpoints.users import get_password_hash

    role, superuser = USERS[who]
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{P}_{who}_{suffix}",
        email=f"{P}_{who}_{suffix}@example.com",
        full_name="Holdout roles user",
        hashed_password=get_password_hash("Hr904-Passw0rd"),
        is_active=True,
        is_superuser=superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


def _holdout(db_session) -> GlobalHoldout:
    """An inactive holdout: changing it activates nothing."""
    holdout = GlobalHoldout(
        name=f"{P} holdout {uuid.uuid4().hex[:8]}",
        holdout_percentage=5,
        is_active=False,
    )
    db_session.add(holdout)
    db_session.commit()
    return holdout


def _group(db_session, status=MutualExclusionGroupStatus.ACTIVE):
    group = MutualExclusionGroup(
        name=f"{P} group {uuid.uuid4().hex[:8]}",
        traffic_allocation=1.0,
        status=status,
    )
    db_session.add(group)
    db_session.commit()
    return group


def _stored_status(db_session, group_id) -> MutualExclusionGroupStatus:
    db_session.expire_all()
    return db_session.get(MutualExclusionGroup, group_id).status


# --- the five operations × every role ----------------------------------------


def _list_all(client, db_session, headers):
    return client.get(f"{V1}/holdout/all", headers=headers)


def _create_holdout(client, db_session, headers):
    return client.post(
        f"{V1}/holdout",
        json={
            "name": f"{P} created {uuid.uuid4().hex[:8]}",
            "holdout_percentage": 5,
            "is_active": False,
        },
        headers=headers,
    )


def _update_holdout(client, db_session, headers):
    holdout = _holdout(db_session)
    return client.put(
        f"{V1}/holdout/{holdout.id}",
        json={"description": "changed"},
        headers=headers,
    )


def _archive_by_delete(client, db_session, headers):
    group = _group(db_session)
    return client.delete(f"{V1}/mutual-exclusion-groups/{group.id}", headers=headers)


def _archive_by_put(client, db_session, headers):
    group = _group(db_session)
    return client.put(
        f"{V1}/mutual-exclusion-groups/{group.id}",
        json={"status": "archived"},
        headers=headers,
    )


OPERATIONS = {
    "GET /holdout/all": (_list_all, 200),
    "POST /holdout": (_create_holdout, 201),
    "PUT /holdout/{id}": (_update_holdout, 200),
    "DELETE /mutual-exclusion-groups/{id}": (_archive_by_delete, 200),
    "PUT /mutual-exclusion-groups/{id} status change": (_archive_by_put, 200),
}


@pytest.mark.parametrize("who", list(USERS))
@pytest.mark.parametrize("operation", list(OPERATIONS))
def test_admin_operation_by_role(client, db_session, operation, who):
    call, success = OPERATIONS[operation]
    user = _user(db_session, who)
    response = call(client, db_session, _auth(user))
    expected = success if who in ALLOWED else 403
    assert response.status_code == expected, (operation, who, response.text)


# --- PUT on a group: what a DEVELOPER keeps, and what it does not -------------


def test_developer_cannot_archive_through_put(client, db_session):
    group = _group(db_session)
    response = client.put(
        f"{V1}/mutual-exclusion-groups/{group.id}",
        json={"status": "archived"},
        headers=_auth(_user(db_session, "developer")),
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Admin permissions required for this action"
    assert _stored_status(db_session, group.id) == MutualExclusionGroupStatus.ACTIVE


def test_developer_cannot_unarchive_through_put(client, db_session):
    group = _group(db_session, status=MutualExclusionGroupStatus.ARCHIVED)
    response = client.put(
        f"{V1}/mutual-exclusion-groups/{group.id}",
        json={"status": "active"},
        headers=_auth(_user(db_session, "developer")),
    )
    assert response.status_code == 403, response.text
    assert _stored_status(db_session, group.id) == MutualExclusionGroupStatus.ARCHIVED


def test_admin_can_unarchive_through_put(client, db_session):
    group = _group(db_session, status=MutualExclusionGroupStatus.ARCHIVED)
    response = client.put(
        f"{V1}/mutual-exclusion-groups/{group.id}",
        json={"status": "active"},
        headers=_auth(_user(db_session, "admin")),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"


@pytest.mark.parametrize(
    "status",
    [MutualExclusionGroupStatus.ACTIVE, MutualExclusionGroupStatus.ARCHIVED],
)
def test_developer_may_send_the_unchanged_status(client, db_session, status):
    """A GET-modify-PUT round trip carries the current status back: accepted."""
    group = _group(db_session, status=status)
    new_name = f"{P} renamed {uuid.uuid4().hex[:8]}"
    response = client.put(
        f"{V1}/mutual-exclusion-groups/{group.id}",
        json={"name": new_name, "status": status.value},
        headers=_auth(_user(db_session, "developer")),
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == new_name
    assert response.json()["status"] == status.value


def test_developer_may_rename_a_group(client, db_session):
    group = _group(db_session)
    new_name = f"{P} renamed {uuid.uuid4().hex[:8]}"
    response = client.put(
        f"{V1}/mutual-exclusion-groups/{group.id}",
        json={"name": new_name, "traffic_allocation": 0.5},
        headers=_auth(_user(db_session, "developer")),
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == new_name
    assert _stored_status(db_session, group.id) == MutualExclusionGroupStatus.ACTIVE


def test_put_on_a_missing_group_is_404_before_the_status_check(client, db_session):
    """The status check needs the stored group, so a missing one is 404 first."""
    response = client.put(
        f"{V1}/mutual-exclusion-groups/{uuid.uuid4()}",
        json={"status": "archived"},
        headers=_auth(_user(db_session, "developer")),
    )
    assert response.status_code == 404, response.text
