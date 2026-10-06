"""Starting a draft whose end date has passed answers 400, not 500 (#953).

``POST /api/v1/experiments/{id}/start`` stamps a draft's ``start_date`` with
the current time. When the draft carried an ``end_date`` that was already
behind that time, the write broke ``check_experiment_dates`` (``end_date >
start_date``) and the route answered 500 with the generic error body. The
dashboard's Start button sends exactly this request.

Now the start is refused before anything is written: 400 with a sentence that
says the end date has passed and how to change it, the experiment stays a
draft with no start date, and no start is audited.

The end date is written straight to the row. That is what a draft looks like
both when its end date was scheduled in the past and when it was scheduled
ahead and the time has since gone by.

The requests are real: a real ``User`` row, a real local JWT, and no
dependency override except ``deps.get_db``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, update
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.audit_log import ActionType, AuditLog
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration]

BASE = "/api/v1/experiments"

END_DATE_PASSED = (
    "Cannot start experiment: its end date has passed. Set a later end date, "
    "or clear it, with PUT /api/v1/experiments/{id}/schedule, then start it again."
)


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


def _factory(db_session):
    factory = sessionmaker(
        bind=db_session.get_bind(), autocommit=False, autoflush=False
    )

    def session():
        s = factory()
        s.execute(text("SET search_path TO test_experimentation"))
        return s

    return session


@pytest.fixture
def developer(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"end953_{suffix}",
        email=f"end953_{suffix}@end.test",
        full_name="Past End Date User",
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
    session = _factory(db_session)

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


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


def _create_draft(client, developer) -> str:
    response = client.post(
        f"{BASE}/",
        json={
            "name": f"end953 {uuid.uuid4().hex[:8]}",
            "description": "A draft whose end date may have passed",
            "hypothesis": "Starting it answers a clear refusal",
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
        headers=_auth(developer),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _set_end_date(db_session, experiment_id: str, end_date: datetime) -> None:
    """Write the end date straight to the row (stored as naive UTC)."""
    session = _factory(db_session)()
    try:
        session.execute(
            update(Experiment)
            .where(Experiment.id == uuid.UUID(experiment_id))
            .values(end_date=end_date.astimezone(timezone.utc).replace(tzinfo=None))
        )
        session.commit()
    finally:
        session.close()


def _row(db_session, experiment_id: str):
    """The experiment's status, start date and end date, and its start audits."""
    session = _factory(db_session)()
    try:
        row = session.get(Experiment, uuid.UUID(experiment_id))
        starts = (
            session.query(AuditLog)
            .filter(AuditLog.entity_id == uuid.UUID(experiment_id))
            .filter(AuditLog.action_type == ActionType.EXPERIMENT_START.value)
            .count()
        )
        return row.status, row.start_date, row.end_date, starts
    finally:
        session.close()


@pytest.mark.regression
def test_starting_a_draft_whose_end_date_has_passed_answers_400(
    client, db_session, developer
):
    experiment_id = _create_draft(client, developer)
    passed = datetime.now(timezone.utc) - timedelta(days=1)
    _set_end_date(db_session, experiment_id, passed)

    response = client.post(f"{BASE}/{experiment_id}/start", headers=_auth(developer))

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": END_DATE_PASSED}
    status, start_date, end_date, starts = _row(db_session, experiment_id)
    assert status == ExperimentStatus.DRAFT
    assert start_date is None
    assert end_date == passed.replace(tzinfo=None)
    assert starts == 0


@pytest.mark.regression
def test_a_refused_start_can_be_retried_once_the_end_date_is_cleared(
    client, db_session, developer
):
    """The way out the refusal names works: clear the end date, start again."""
    experiment_id = _create_draft(client, developer)
    _set_end_date(
        db_session, experiment_id, datetime.now(timezone.utc) - timedelta(hours=1)
    )
    refused = client.post(f"{BASE}/{experiment_id}/start", headers=_auth(developer))
    assert refused.status_code == 400, refused.text

    cleared = client.put(
        f"{BASE}/{experiment_id}/schedule",
        json={"end_date": None},
        headers=_auth(developer),
    )
    assert cleared.status_code == 200, cleared.text
    started = client.post(f"{BASE}/{experiment_id}/start", headers=_auth(developer))

    assert started.status_code == 200, started.text
    status, start_date, end_date, starts = _row(db_session, experiment_id)
    assert status == ExperimentStatus.ACTIVE
    assert start_date is not None
    assert end_date is None
    assert starts == 1


def test_starting_a_draft_whose_end_date_is_ahead_still_starts(
    client, db_session, developer
):
    """Only an end date that has passed is refused."""
    experiment_id = _create_draft(client, developer)
    ahead = datetime.now(timezone.utc) + timedelta(days=7)
    _set_end_date(db_session, experiment_id, ahead)

    response = client.post(f"{BASE}/{experiment_id}/start", headers=_auth(developer))

    assert response.status_code == 200, response.text
    status, start_date, end_date, starts = _row(db_session, experiment_id)
    assert status == ExperimentStatus.ACTIVE
    assert start_date is not None and start_date < end_date
    assert end_date == ahead.replace(tzinfo=None)
    assert starts == 1
