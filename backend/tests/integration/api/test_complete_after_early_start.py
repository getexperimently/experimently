"""An experiment started before its scheduled start can be completed (#974).

``PUT /api/v1/experiments/{id}/schedule`` gives a draft a ``start_date`` in the
future; ``POST /start`` (the dashboard's Start button) before that date used
to keep the future date, and ``POST /complete`` then wrote ``end_date`` = now,
earlier than the stored ``start_date``. ``check_experiment_dates``
(``end_date > start_date``) refused the row and complete answered 500.

Now:

* a draft started by hand before its scheduled start records the actual start:
  ``start_date`` is the time of the request, and a scheduled ``end_date`` is
  kept, so completing it later works;
* an experiment already in that state, written by an earlier version (ACTIVE or
  PAUSED with a ``start_date`` still ahead), completes with 200: its start is
  moved to one microsecond before the completion time, the latest start the
  row accepts, so the row keeps ``end_date > start_date``.

The start a completion moves is the one that is NOT before the completion time:
a start exactly equal to it moves too (``>=``, not ``>``), or the row would hold
``end_date == start_date`` and the check would refuse it.

Unchanged, and checked here: a start and a complete with no schedule, a resume
from PAUSED, a PAUSED row whose start is still ahead (written by an earlier
version) keeps that start when it is resumed, a draft whose scheduled start has
already passed (started by hand or by the scheduler) keeps that start.

The requests are real: a real ``User`` row, a real local JWT, and no
dependency override except ``deps.get_db``. A state no route can reach any
more is written straight to the row. The scheduler runs against the same
database with its ``SessionLocal`` patched.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

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
        username=f"early974_{suffix}",
        email=f"early974_{suffix}@early.test",
        full_name="Early Start User",
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value):
    """A response's ISO string or a row's naive datetime, as aware UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _create_draft(client, developer) -> str:
    response = client.post(
        f"{BASE}/",
        json={
            "name": f"early974 {uuid.uuid4().hex[:8]}",
            "description": "A draft started before its scheduled start",
            "hypothesis": "Completing it answers 200",
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


def _post(client, developer, experiment_id: str, action: str):
    return client.post(f"{BASE}/{experiment_id}/{action}", headers=_auth(developer))


def _schedule(client, developer, experiment_id: str, body: dict):
    response = client.put(
        f"{BASE}/{experiment_id}/schedule", json=body, headers=_auth(developer)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _write(db_session, experiment_id: str, **values) -> None:
    """Write columns straight to the row (dates as naive UTC, as stored)."""
    stored = {
        key: value.astimezone(timezone.utc).replace(tzinfo=None)
        if isinstance(value, datetime)
        else value
        for key, value in values.items()
    }
    session = _factory(db_session)()
    try:
        session.execute(
            update(Experiment)
            .where(Experiment.id == uuid.UUID(experiment_id))
            .values(**stored)
        )
        session.commit()
    finally:
        session.close()


def _row(db_session, experiment_id: str):
    """Status, start and end date (aware UTC), and the completion audits."""
    session = _factory(db_session)()
    try:
        row = session.get(Experiment, uuid.UUID(experiment_id))
        completes = (
            session.query(AuditLog)
            .filter(AuditLog.entity_id == uuid.UUID(experiment_id))
            .filter(AuditLog.action_type == ActionType.EXPERIMENT_COMPLETE.value)
            .count()
        )
        return row.status, _utc(row.start_date), _utc(row.end_date), completes
    finally:
        session.close()


def _tick(db_session) -> None:
    """One experiment scheduler tick against the test database."""
    from backend.app.core.scheduler import ExperimentScheduler

    scheduler = ExperimentScheduler()
    scheduler._notification_service = MagicMock()
    with patch("backend.app.core.scheduler.SessionLocal", _factory(db_session)):
        asyncio.run(scheduler.process_scheduled_experiments())


# --- the issue's sequence ----------------------------------------------------


@pytest.mark.regression
def test_the_issue_sequence_answers_200_at_each_step(client, db_session, developer):
    """Schedule a future start, start by hand before it, complete: 200 each."""
    experiment_id = _create_draft(client, developer)
    _schedule(
        client,
        developer,
        experiment_id,
        {"start_date": (_now() + timedelta(days=30)).isoformat()},
    )

    started = _post(client, developer, experiment_id, "start")
    assert started.status_code == 200, started.text
    completed = _post(client, developer, experiment_id, "complete")
    assert completed.status_code == 200, completed.text

    assert completed.json()["status"] == "completed"
    status, start_date, end_date, completes = _row(db_session, experiment_id)
    assert status == ExperimentStatus.COMPLETED
    assert start_date < end_date <= _now()
    assert completes == 1


@pytest.mark.regression
def test_a_draft_started_before_its_scheduled_start_records_the_actual_start(
    client, db_session, developer
):
    """The start date is the time of the start; the scheduled end is kept."""
    experiment_id = _create_draft(client, developer)
    scheduled_start = _now() + timedelta(days=1)
    scheduled_end = scheduled_start + timedelta(days=7)
    _schedule(
        client,
        developer,
        experiment_id,
        {
            "start_date": scheduled_start.isoformat(),
            "end_date": scheduled_end.isoformat(),
        },
    )

    before = _now()
    started = _post(client, developer, experiment_id, "start")
    after = _now()

    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "active"
    assert before <= _utc(body["start_date"]) <= after
    assert _utc(body["end_date"]) == scheduled_end
    status, start_date, end_date, _ = _row(db_session, experiment_id)
    assert status == ExperimentStatus.ACTIVE
    assert before <= start_date <= after
    assert end_date == scheduled_end


# --- a row an earlier version left with its start ahead ----------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "status, stored_end",
    [
        pytest.param(ExperimentStatus.ACTIVE, None, id="active"),
        pytest.param(ExperimentStatus.PAUSED, timedelta(days=40), id="paused-with-end"),
    ],
)
def test_an_experiment_whose_start_is_still_ahead_completes(
    client, db_session, developer, status, stored_end
):
    """Started by hand by an earlier version, which kept the scheduled start."""
    experiment_id = _create_draft(client, developer)
    started = _post(client, developer, experiment_id, "start")
    assert started.status_code == 200, started.text
    values = {"status": status, "start_date": _now() + timedelta(days=30)}
    if stored_end is not None:
        values["end_date"] = _now() + stored_end
    _write(db_session, experiment_id, **values)

    before = _now()
    completed = _post(client, developer, experiment_id, "complete")
    after = _now()

    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    status_after, start_date, end_date, completes = _row(db_session, experiment_id)
    assert status_after == ExperimentStatus.COMPLETED
    assert before <= end_date <= after
    assert end_date - start_date == timedelta(microseconds=1)
    assert completes == 1


@pytest.mark.regression
def test_a_start_exactly_at_the_completion_time_is_moved_one_microsecond_back(
    client, db_session, developer, monkeypatch
):
    """``start_date == now`` is moved too: ``end_date`` must be after it.

    The completion time is frozen at the stored start, so the two are equal to
    the microsecond. A comparison of ``>`` instead of ``>=`` leaves the start
    where it is, writes ``end_date == start_date`` and the row is refused (a 500).
    """
    from backend.app.api.v1.endpoints import experiments as experiments_endpoint

    experiment_id = _create_draft(client, developer)
    started = _post(client, developer, experiment_id, "start")
    assert started.status_code == 200, started.text
    moment = _now()
    _write(db_session, experiment_id, start_date=moment)

    real_record_end_date = experiments_endpoint.record_end_date
    monkeypatch.setattr(
        experiments_endpoint,
        "record_end_date",
        lambda experiment, now: real_record_end_date(experiment, moment),
    )
    completed = _post(client, developer, experiment_id, "complete")

    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    status, start_date, end_date, completes = _row(db_session, experiment_id)
    assert status == ExperimentStatus.COMPLETED
    assert end_date == moment
    assert end_date == start_date + timedelta(microseconds=1)
    assert completes == 1


# --- unchanged ------------------------------------------------------------------


def test_a_start_pause_resume_and_complete_with_no_schedule_are_unchanged(
    client, db_session, developer
):
    """The start date is set once, at the first start, and complete keeps it."""
    experiment_id = _create_draft(client, developer)

    before = _now()
    started = _post(client, developer, experiment_id, "start")
    after = _now()
    assert started.status_code == 200, started.text
    first_start = _utc(started.json()["start_date"])
    assert before <= first_start <= after

    assert _post(client, developer, experiment_id, "pause").status_code == 200
    resumed = _post(client, developer, experiment_id, "start")
    assert resumed.status_code == 200, resumed.text
    assert _utc(resumed.json()["start_date"]) == first_start

    before = _now()
    completed = _post(client, developer, experiment_id, "complete")
    after = _now()
    assert completed.status_code == 200, completed.text
    status, start_date, end_date, completes = _row(db_session, experiment_id)
    assert status == ExperimentStatus.COMPLETED
    assert start_date == first_start
    assert before <= end_date <= after
    assert completes == 1


def test_a_paused_row_whose_start_is_ahead_keeps_it_when_resumed(
    client, db_session, developer
):
    """Only a DRAFT's start that is still ahead is replaced by the real start.

    A PAUSED row has already started once, so the date it holds is when it first
    started; a row an earlier version left with a future one keeps it on resume
    (completing it later moves the start, see above).
    """
    experiment_id = _create_draft(client, developer)
    started = _post(client, developer, experiment_id, "start")
    assert started.status_code == 200, started.text
    first_start = _now() + timedelta(days=30)
    _write(
        db_session,
        experiment_id,
        status=ExperimentStatus.PAUSED,
        start_date=first_start,
    )

    resumed = _post(client, developer, experiment_id, "start")

    assert resumed.status_code == 200, resumed.text
    body = resumed.json()
    assert body["status"] == "active"
    assert _utc(body["start_date"]) == first_start
    status, start_date, _, _ = _row(db_session, experiment_id)
    assert status == ExperimentStatus.ACTIVE
    assert start_date == first_start


def test_a_draft_whose_scheduled_start_has_passed_keeps_it_when_started_by_hand(
    client, db_session, developer
):
    experiment_id = _create_draft(client, developer)
    scheduled_start = _now() - timedelta(minutes=1)
    _schedule(
        client, developer, experiment_id, {"start_date": scheduled_start.isoformat()}
    )

    started = _post(client, developer, experiment_id, "start")

    assert started.status_code == 200, started.text
    assert _utc(started.json()["start_date"]) == scheduled_start
    assert _row(db_session, experiment_id)[1] == scheduled_start


def test_a_scheduler_activated_experiment_keeps_its_scheduled_start(
    client, db_session, developer
):
    experiment_id = _create_draft(client, developer)
    scheduled_start = _now() - timedelta(minutes=1)
    scheduled_end = scheduled_start + timedelta(days=7)
    _schedule(
        client,
        developer,
        experiment_id,
        {
            "start_date": scheduled_start.isoformat(),
            "end_date": scheduled_end.isoformat(),
        },
    )

    _tick(db_session)

    status, start_date, end_date, _ = _row(db_session, experiment_id)
    assert status == ExperimentStatus.ACTIVE
    assert start_date == scheduled_start
    assert end_date == scheduled_end

    completed = _post(client, developer, experiment_id, "complete")
    assert completed.status_code == 200, completed.text
    status, start_date, end_date, completes = _row(db_session, experiment_id)
    assert status == ExperimentStatus.COMPLETED
    assert start_date == scheduled_start
    assert start_date < end_date <= _now()
    assert completes == 1
