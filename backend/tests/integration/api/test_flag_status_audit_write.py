"""A flag status change answers 200 and keeps exactly one audit entry (#221).

The four status routes (``/toggle``, ``/enable``, ``/disable``,
``/unarchive``) commit the change first and write the ``audit_logs`` row after
it. These tests drive the real routes on Postgres, as a DEVELOPER who is not a
superuser and signs in with a local token, and read the result back in a
session of their own:

* audit text is normalised before it is stored; each route answers 200,
  applies the change and writes exactly one row;
* an account with no email is recorded under its username;
* when the audit write itself fails (a trigger on ``audit_logs`` that refuses
  every insert), the route still answers 200 with the change committed, and
  the ERROR line it logs carries no values from the row.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps

# The function the local login route signs its tokens with.
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.audit_log import ActionType, AuditLog, EntityType
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.user import User, UserRole
from backend.app.services.audit_service import AuditService

pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.regression]

FLAGS = "/api/v1/feature-flags"
PREFIX = "au221"
SCHEMA = "test_experimentation"

#: Reason text as sent (JSON-escaped) -> as stored.
REASONS = {
    "case-a": (json.dumps("a" + chr(0x0) + "b"), "a\ufffdb"),
    "case-b": (json.dumps("a" + chr(0xD800) + "b"), "a\ufffdb"),
}

#: route -> (status the flag starts in, status it must end in)
STATUS_ROUTES = {
    "toggle": (FeatureFlagStatus.INACTIVE, FeatureFlagStatus.ACTIVE),
    "enable": (FeatureFlagStatus.INACTIVE, FeatureFlagStatus.ACTIVE),
    "disable": (FeatureFlagStatus.ACTIVE, FeatureFlagStatus.INACTIVE),
}


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


def _make_user(db_session, *, email: bool = True) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{PREFIX}_developer_{suffix}",
        email=f"{PREFIX}_{suffix}@audit.test" if email else None,
        full_name="Audit Status User",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def developer(db_session):
    return _make_user(db_session)


@pytest.fixture
def fresh(test_db):
    """A session of the test's own, opened per read, never the request's."""
    factory = sessionmaker(bind=test_db, expire_on_commit=False)

    def open_session():
        session = factory()
        session.execute(text(f"SET search_path TO {SCHEMA}"))
        return session

    return open_session


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
def _remove_flags(db_session):
    """The flag list tests page at 100; leave no flags behind."""
    yield
    db_session.rollback()
    flag_ids = [
        row.id
        for row in db_session.query(FeatureFlag.id).filter(
            FeatureFlag.key.like(f"{PREFIX}-%")
        )
    ]
    if flag_ids:
        db_session.query(AuditLog).filter(AuditLog.entity_id.in_(flag_ids)).delete(
            synchronize_session=False
        )
        db_session.query(FeatureFlag).filter(FeatureFlag.id.in_(flag_ids)).delete(
            synchronize_session=False
        )
    db_session.commit()


@pytest.fixture
def audit_insert_refused(db_session):
    """Every insert into ``audit_logs`` raises while the test runs."""
    db_session.execute(
        text(
            f"CREATE OR REPLACE FUNCTION {SCHEMA}.au221_refuse_audit() "
            "RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RAISE EXCEPTION 'au221 refused'; END $$"
        )
    )
    db_session.execute(
        text(
            f"CREATE TRIGGER au221_refuse_audit BEFORE INSERT ON {SCHEMA}.audit_logs "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.au221_refuse_audit()"
        )
    )
    db_session.commit()
    try:
        yield
    finally:
        db_session.rollback()
        db_session.execute(
            text(f"DROP TRIGGER IF EXISTS au221_refuse_audit ON {SCHEMA}.audit_logs")
        )
        db_session.execute(
            text(f"DROP FUNCTION IF EXISTS {SCHEMA}.au221_refuse_audit()")
        )
        db_session.commit()


# --- helpers ------------------------------------------------------------------


def _auth(user):
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


def _flag(db_session, status, name=None) -> FeatureFlag:
    flag = FeatureFlag(
        key=f"{PREFIX}-{uuid.uuid4().hex[:10]}",
        name=name or f"{PREFIX} flag",
        status=status,
        rollout_percentage=0,
    )
    db_session.add(flag)
    db_session.commit()
    return flag


def _post_raw(client, path, user, raw_body):
    """POST a JSON body exactly as written."""
    headers = {**_auth(user), "Content-Type": "application/json"}
    return client.post(path, content=raw_body.encode("ascii"), headers=headers)


def _state(fresh, flag_id):
    """(status of the flag, its audit rows), read after the request."""
    session = fresh()
    try:
        flag = session.query(FeatureFlag).filter(FeatureFlag.id == flag_id).one()
        rows = session.query(AuditLog).filter(AuditLog.entity_id == flag_id).all()
        return FeatureFlagStatus(flag.status), rows
    finally:
        session.close()


# --- (a) audit text is normalised before it is stored -------------------------


@pytest.mark.parametrize("reason", sorted(REASONS))
@pytest.mark.parametrize("route", sorted(STATUS_ROUTES))
def test_status_route_stores_normalised_reason(
    client, db_session, fresh, developer, route, reason
):
    start, end = STATUS_ROUTES[route]
    sent, stored = REASONS[reason]
    flag = _flag(db_session, start)

    response = _post_raw(
        client, f"{FLAGS}/{flag.id}/{route}", developer, '{"reason": %s}' % sent
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == end.value
    status_after, rows = _state(fresh, flag.id)
    assert status_after == end
    assert len(rows) == 1
    assert rows[0].reason == stored
    assert rows[0].user_email == developer.email
    assert response.json()["audit_log_id"] == str(rows[0].id)


def test_unarchive_answers_200_with_one_row(client, db_session, fresh, developer):
    flag = _flag(db_session, FeatureFlagStatus.ARCHIVED)

    response = client.post(f"{FLAGS}/{flag.id}/unarchive", headers=_auth(developer))

    assert response.status_code == 200, response.text
    status_after, rows = _state(fresh, flag.id)
    assert status_after == FeatureFlagStatus.INACTIVE
    assert len(rows) == 1
    assert rows[0].user_email == developer.email


def _bulk_enable(client, developer, flag, sent):
    return _post_raw(
        client,
        f"{FLAGS}/bulk-toggle",
        developer,
        '{"flag_ids": [%s], "action": "enable", "reason": %s}'
        % (json.dumps(str(flag.id)), sent),
    )


def test_bulk_toggle_stores_normalised_reason(client, db_session, fresh, developer):
    sent, stored = REASONS["case-a"]
    flag = _flag(db_session, FeatureFlagStatus.INACTIVE)

    response = _bulk_enable(client, developer, flag, sent)

    assert response.status_code == 200, response.text
    assert response.json()["succeeded"] == 1, response.text
    status_after, rows = _state(fresh, flag.id)
    assert status_after == FeatureFlagStatus.ACTIVE
    assert len(rows) == 1
    assert rows[0].reason == stored


def test_bulk_toggle_refuses_reason_its_schema_cannot_read(
    client, db_session, fresh, developer
):
    """The bulk request schema answers 422 for this reason; no flag changes."""
    sent, _ = REASONS["case-b"]
    flag = _flag(db_session, FeatureFlagStatus.INACTIVE)

    response = _bulk_enable(client, developer, flag, sent)

    assert response.status_code == 422, response.text
    status_after, rows = _state(fresh, flag.id)
    assert status_after == FeatureFlagStatus.INACTIVE
    assert rows == []


# --- (b) an account with no email ---------------------------------------------


def test_toggle_by_account_without_email_is_recorded_under_username(
    client, db_session, fresh
):
    user = _make_user(db_session, email=False)
    flag = _flag(db_session, FeatureFlagStatus.INACTIVE)

    response = client.post(
        f"{FLAGS}/{flag.id}/toggle", json={"reason": "no email"}, headers=_auth(user)
    )

    assert response.status_code == 200, response.text
    status_after, rows = _state(fresh, flag.id)
    assert status_after == FeatureFlagStatus.ACTIVE
    assert len(rows) == 1
    assert rows[0].user_email == user.username
    assert rows[0].user_id == user.id


# --- (c) the audit write fails ------------------------------------------------


def _assert_no_values_logged(caplog, *values):
    for record in caplog.records:
        message = record.getMessage()
        for value in values:
            assert value not in message, (record.name, message)
        if record.levelno >= logging.ERROR:
            assert record.exc_info is None, (record.name, message)
            assert not record.exc_text, (record.name, message)


def test_toggle_answers_200_when_the_audit_write_fails(
    client, db_session, fresh, developer, audit_insert_refused, caplog
):
    canary = f"au221-canary-{uuid.uuid4().hex}"
    flag = _flag(db_session, FeatureFlagStatus.INACTIVE, name=f"{canary}-name")
    caplog.set_level(logging.INFO)

    response = client.post(
        f"{FLAGS}/{flag.id}/toggle", json={"reason": canary}, headers=_auth(developer)
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == FeatureFlagStatus.ACTIVE.value
    assert response.json()["audit_log_id"] is None
    status_after, rows = _state(fresh, flag.id)
    assert status_after == FeatureFlagStatus.ACTIVE
    assert rows == []

    errors = [
        r
        for r in caplog.records
        if r.levelno >= logging.ERROR and r.name == "backend.app.services.audit_service"
    ]
    assert len(errors) == 1, [r.getMessage() for r in caplog.records]
    _assert_no_values_logged(caplog, canary, "au221 refused", developer.email)

    # The client saw the change succeed, so it has no reason to send it again;
    # one more toggle, asked for, flips the flag once more and no further.
    again = client.post(
        f"{FLAGS}/{flag.id}/toggle", json={"reason": canary}, headers=_auth(developer)
    )
    assert again.status_code == 200, again.text
    assert _state(fresh, flag.id)[0] == FeatureFlagStatus.INACTIVE


def test_bulk_toggle_error_lines_carry_no_values(
    client, db_session, developer, audit_insert_refused, caplog
):
    canary = f"au221-canary-{uuid.uuid4().hex}"
    flag = _flag(db_session, FeatureFlagStatus.INACTIVE, name=f"{canary}-name")
    caplog.set_level(logging.INFO)

    response = client.post(
        f"{FLAGS}/bulk-toggle",
        json={"flag_ids": [str(flag.id)], "action": "enable", "reason": canary},
        headers=_auth(developer),
    )

    assert response.status_code == 200, response.text
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    _assert_no_values_logged(caplog, canary, "au221 refused", developer.email)


# --- the writers' ERROR lines, with a NOT NULL violation ----------------------


@pytest.mark.asyncio
async def test_log_action_error_line_carries_no_values(db_session, caplog):
    canary = f"au221-canary-{uuid.uuid4().hex}"
    caplog.set_level(logging.INFO)

    result = await AuditService.log_action(
        db=db_session,
        user_id=None,
        user_email=f"{canary}@audit.test",
        action_type=ActionType.TOGGLE_ENABLE,
        entity_type=EntityType.FEATURE_FLAG,
        entity_id=uuid.uuid4(),
        entity_name=None,  # NOT NULL column
        old_value=f"{canary}-old",
        new_value=f"{canary}-new",
        reason=canary,
    )

    assert result is None
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    _assert_no_values_logged(caplog, canary)
    # The failed insert was rolled back: the session is usable again.
    assert db_session.execute(text("SELECT 1")).scalar() == 1


@pytest.mark.asyncio
async def test_log_toggle_operation_error_line_carries_no_values(db_session, caplog):
    canary = f"au221-canary-{uuid.uuid4().hex}"
    caplog.set_level(logging.INFO)

    with pytest.raises(Exception):
        await AuditService.log_toggle_operation(
            db=db_session,
            user_id=None,
            user_email=f"{canary}@audit.test",
            action_type=ActionType.TOGGLE_ENABLE.value,
            entity_id=uuid.uuid4(),
            entity_name=None,  # NOT NULL column
            old_value=f"{canary}-old",
            new_value=f"{canary}-new",
            reason=canary,
        )

    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    _assert_no_values_logged(caplog, canary)
    assert db_session.execute(text("SELECT 1")).scalar() == 1
