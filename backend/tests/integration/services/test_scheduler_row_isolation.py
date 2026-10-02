"""One experiment the database refuses no longer undoes the rest of the tick (#489).

``ExperimentScheduler.process_scheduled_experiments`` used to stage every
activation of a tick and commit them with one ``db.commit()``, and the same
for completions. A single row that failed at flush time -- here, one that
breaks ``ck_experiments_resume_only_when_paused`` -- rolled back the whole
batch, so every other experiment due in that tick silently missed its start
(or its end), and the error named none of them.

Now each row is flushed inside its own savepoint. The tests below put three
experiments due in one tick, make the database refuse exactly one of them, and
check that the other two transition, the refused one is unchanged, and the
error is logged with its id and a traceback.

The refusal is a real constraint error from PostgreSQL: a ``before_update``
listener, scoped to the test and to one experiment id, puts a ``resume_at`` on
the row as its status leaves PAUSED -- the shape of a writer that sidesteps
the status listener, which is the risk the issue describes.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text, update
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.user import User, UserRole
from backend.app.services.notification_service import NotificationService

pytestmark = [pytest.mark.integration, pytest.mark.regression]

BASE = "/api/v1/experiments"
CONSTRAINT = "ck_experiments_resume_only_when_paused"


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


def _factory(db_session, **kwargs):
    factory = sessionmaker(bind=db_session.get_bind(), **kwargs)

    def session():
        s = factory()
        s.execute(text("SET search_path TO test_experimentation"))
        return s

    return session


@pytest.fixture
def developer(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"rows489_{suffix}",
        email=f"rows489_{suffix}@rows.test",
        full_name="Row Isolation User",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def client(db_session):
    session = _factory(db_session, autocommit=False, autoflush=False)

    def override_get_db():
        s = session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


def _now():
    return datetime.now(timezone.utc)


def _create(client, developer) -> str:
    response = client.post(
        f"{BASE}/",
        json={
            "name": f"rows489 {uuid.uuid4().hex[:8]}",
            "description": "One refused row must not undo the others",
            "hypothesis": "Each row commits on its own",
            "experiment_type": "a_b",
            "variants": [
                {"name": "Control", "is_control": True, "traffic_allocation": 50},
                {"name": "Treatment", "is_control": False, "traffic_allocation": 50},
            ],
            "metrics": [
                {
                    "name": "Conversion Rate",
                    "event_name": "purchase",
                    "metric_type": "conversion",
                    "is_primary": True,
                }
            ],
        },
        headers={"Authorization": f"Bearer {create_local_access_token(developer)}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _set(db_session, experiment_id, **values):
    """Write columns straight to the row (the starting state of the test)."""
    session = _factory(db_session)()
    try:
        session.execute(
            update(Experiment)
            .where(Experiment.id == uuid.UUID(experiment_id))
            .values(**values)
        )
        session.commit()
    finally:
        session.close()


def _status(db_session, experiment_id):
    session = _factory(db_session)()
    try:
        row = session.get(Experiment, uuid.UUID(experiment_id))
        return row.status, row.resume_at
    finally:
        session.close()


@contextmanager
def _refuse(experiment_id):
    """Make the database refuse the UPDATE of this one experiment."""
    target_id = uuid.UUID(experiment_id)

    def before_update(mapper, connection, target):
        if target.id == target_id:
            target.resume_at = datetime.now(timezone.utc) + timedelta(days=1)

    event.listen(Experiment, "before_update", before_update)
    try:
        yield
    finally:
        event.remove(Experiment, "before_update", before_update)


def _tick(db_session):
    """One scheduler tick against the test database. Returns the tick's
    result and the experiment ids it sent a notification for."""
    from backend.app.core.scheduler import ExperimentScheduler

    sent = set()
    notifications = NotificationService()
    notifications._slack = MagicMock()
    notifications._email = MagicMock()

    def capture(event_):
        sent.add(event_.experiment_id)
        return True

    notifications._send = capture

    scheduler = ExperimentScheduler()
    scheduler._notification_service = notifications
    with patch("backend.app.core.scheduler.SessionLocal", _factory(db_session)):
        result = asyncio.run(scheduler.process_scheduled_experiments())
    return result, sent


def _logged(caplog, verb, experiment_id):
    return [
        r
        for r in caplog.records
        if r.levelno >= logging.ERROR
        and r.getMessage() == f"Error {verb} experiment {experiment_id}"
        and r.exc_info
        and CONSTRAINT in str(r.exc_info[1])
    ]


def test_one_refused_activation_leaves_the_others_activated(
    client, db_session, developer, caplog
):
    """Three experiments due to start in one tick, the middle one refused."""
    due = (_now() - timedelta(minutes=5)).replace(tzinfo=None)
    ids = [_create(client, developer) for _ in range(3)]
    for experiment_id in ids:
        _set(db_session, experiment_id, start_date=due)
    first, refused, last = ids

    caplog.set_level(logging.INFO)
    with _refuse(refused):
        result, sent = _tick(db_session)

    assert _status(db_session, first) == (ExperimentStatus.ACTIVE, None)
    assert _status(db_session, last) == (ExperimentStatus.ACTIVE, None)
    assert _status(db_session, refused) == (ExperimentStatus.DRAFT, None)
    assert {first, last} <= sent
    assert refused not in sent
    assert result["items_failed"] >= 1
    assert _logged(caplog, "activating", refused), [
        r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
    ]


def test_one_refused_completion_leaves_the_others_completed(
    client, db_session, developer, caplog
):
    """Three ACTIVE experiments due to end in one tick, the middle one refused."""
    started = (_now() - timedelta(hours=2)).replace(tzinfo=None)
    ended = (_now() - timedelta(hours=1)).replace(tzinfo=None)
    ids = [_create(client, developer) for _ in range(3)]
    for experiment_id in ids:
        _set(
            db_session,
            experiment_id,
            status=ExperimentStatus.ACTIVE,
            start_date=started,
            end_date=ended,
        )
    first, refused, last = ids

    caplog.set_level(logging.INFO)
    with _refuse(refused):
        result, sent = _tick(db_session)

    assert _status(db_session, first) == (ExperimentStatus.COMPLETED, None)
    assert _status(db_session, last) == (ExperimentStatus.COMPLETED, None)
    assert _status(db_session, refused) == (ExperimentStatus.ACTIVE, None)
    assert {first, last} <= sent
    assert refused not in sent
    assert result["items_failed"] >= 1
    assert _logged(caplog, "completing", refused), [
        r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
    ]
