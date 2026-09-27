"""Audit log reads follow the role table.

Superusers, ADMIN and ANALYST read every audit entry. DEVELOPER and VIEWER
read only the entries they made, and are refused the per-entity history and
the statistics.

Every reader here is a real, non-superuser user of its role, and nothing
patches the permission rule: the role alone decides the answer. Two users each
write one entry on a real flag, tagged with a marker unique to the test, and
each read path is checked for the other user's entry. Assertions key on those
per-test emails and markers, never on counts, because rows persist across
tests in the shared test database.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from backend.app.models.audit_log import ActionType, EntityType
from backend.app.models.user import User, UserRole
from backend.app.services.audit_service import AuditService
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.regression]


@pytest.fixture
def plain_admin(db_session: Session) -> User:
    """An ADMIN who is NOT a superuser, so the role is what is tested."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"plain_admin_{suffix}",
        email=f"plain_admin_{suffix}@int.test",
        full_name="Plain Admin",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def seeded(db_session, admin_user, developer_user, make_feature_flag):
    """admin_user and developer_user each record one change on one flag."""
    flag = make_feature_flag()
    tag = uuid.uuid4().hex[:8]
    for actor, label in ((admin_user, "admin"), (developer_user, "developer")):
        AuditService._create_audit_log_sync(
            db_session,
            actor.id,
            actor.email,
            ActionType.TOGGLE_DISABLE,
            EntityType.FEATURE_FLAG,
            flag.id,
            flag.name,
            "active",
            "inactive",
            f"{tag}-{label}",
        )
    return flag, tag


def _reads(client, flag, other):
    """Every audit read path, each asked about *other*'s activity."""
    return {
        "list": client.get("/api/v1/audit-logs/?limit=1000"),
        "list?user_id=other": client.get(
            f"/api/v1/audit-logs/?user_id={other.id}&limit=1000"
        ),
        "user/{other}": client.get(f"/api/v1/audit-logs/user/{other.id}"),
        "entity": client.get(f"/api/v1/audit-logs/entity/feature_flag/{flag.id}"),
        "stats": client.get("/api/v1/audit-logs/stats"),
        "stream": client.get("/api/v1/audit-logs/stream?limit=100"),
        "flag-history": client.get(f"/api/v1/feature-flags/{flag.id}/history"),
    }


@pytest.mark.parametrize("role_fixture", ["viewer_user", "developer_user"])
def test_developer_and_viewer_read_only_their_own_entries(
    request, db_session, admin_user, seeded, role_fixture
):
    flag, tag = seeded
    reader = request.getfixturevalue(role_fixture)
    client = make_client_for_user(db_session, reader)

    shown = {
        path: r.status_code
        for path, r in _reads(client, flag, admin_user).items()
        if r.status_code == 200
        and (admin_user.email in r.text or f"{tag}-admin" in r.text)
    }
    # Every path that returned another user's entry, by name.
    assert shown == {}, shown


@pytest.mark.parametrize("role_fixture", ["viewer_user", "developer_user"])
def test_developer_and_viewer_are_refused_entity_history_and_stats(
    request, db_session, seeded, role_fixture
):
    flag, _ = seeded
    client = make_client_for_user(db_session, request.getfixturevalue(role_fixture))
    assert (
        client.get(f"/api/v1/audit-logs/entity/feature_flag/{flag.id}").status_code
        == 403
    )
    assert client.get("/api/v1/audit-logs/stats").status_code == 403


def test_developer_still_reads_own_entries(db_session, developer_user, seeded):
    flag, tag = seeded
    client = make_client_for_user(db_session, developer_user)

    listed = client.get("/api/v1/audit-logs/?limit=1000")
    assert listed.status_code == 200
    assert f"{tag}-developer" in listed.text

    own = client.get(f"/api/v1/audit-logs/user/{developer_user.id}")
    assert own.status_code == 200
    assert f"{tag}-developer" in own.text

    history = client.get(f"/api/v1/feature-flags/{flag.id}/history")
    assert history.status_code == 200
    assert f"{tag}-developer" in history.text
    assert history.json()["total_changes"] == 1

    stream = client.get("/api/v1/audit-logs/stream?limit=100")
    assert stream.status_code == 200
    assert developer_user.email in stream.text


@pytest.mark.parametrize("role_fixture", ["plain_admin", "analyst_user"])
def test_admin_and_analyst_read_every_entry(
    request, db_session, admin_user, seeded, role_fixture
):
    flag, tag = seeded
    reader = request.getfixturevalue(role_fixture)
    assert not reader.is_superuser
    client = make_client_for_user(db_session, reader)

    for path, r in _reads(client, flag, admin_user).items():
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
        if path == "stream":
            # The stream carries no reason field; the email identifies it.
            assert admin_user.email in r.text, path
        elif path != "stats":
            assert f"{tag}-admin" in r.text, path

    history = client.get(f"/api/v1/feature-flags/{flag.id}/history").json()
    assert history["total_changes"] == 2
