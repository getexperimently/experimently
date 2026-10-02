"""Each experiment's partial rollout admits its own users (#533), end to end.

A dashboard rule with a ``rollout_percentage`` below 100 admits a user when
``md5("<user_id>:<rule id>") % 100`` is below it, and a rule with no id used
the shared id ``"dashboard"``. Now:

* a first start (``POST /start`` or the scheduler, DRAFT -> ACTIVE) gives such
  a rule the experiment's id, and ``/tracking/assign`` admits exactly the users
  that id selects;
* 533b: an experiment started before the change keeps ``"dashboard"``: a pause
  and resume writes nothing, everyone already assigned keeps their variant
  with no new row and nobody shown another variant, and new users are still admitted on
  ``"dashboard"`` (C7, through the route and the scheduler);
* a PAUSED edit that adds a rollout below 100 to a rule with no id stamps the
  id then, and nobody already assigned moves;
* a ``PUT`` whose rule has no id keeps the stored one; an id the caller chose
  is never replaced.

Every request is a real one: users with a local JWT, and no dependency
override except ``deps.get_db`` (#470). What was stored is read back in a
session of the test's own. The scheduler runs against the same database with
its ``SessionLocal`` patched, as ``test_scheduler_pause_semantics.py`` does.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.core.security import hash_api_key
from backend.app.main import app
from backend.app.models.api_key import APIKey
from backend.app.models.assignment import Assignment
from backend.app.models.event import Event
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.user import User, UserRole
from backend.app.services.assignment_service import AssignmentService
from backend.app.services.rules_evaluation_service import RulesEvaluationService

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EXPERIMENTS = "/api/v1/experiments"
ASSIGN = "/api/v1/tracking/assign"
PREFIX = "rollid533"


def _rules(country: str = "US", rollout: int | None = 50, **extra) -> dict:
    rules = {
        "logical_operator": "AND",
        "groups": [
            {
                "logical_operator": "AND",
                "conditions": [
                    {"attribute": "country", "operator": "equals", "value": country}
                ],
            }
        ],
        **extra,
    }
    if rollout is not None:
        rules["rollout_percentage"] = rollout
    return rules


def _md5_admits(user_id: str, salt: str, percentage: int = 50) -> bool:
    digest = hashlib.md5(f"{user_id}:{salt}".encode(), usedforsecurity=False)
    return int(digest.hexdigest(), 16) % 100 < percentage


def _users(n: int, tag: str) -> list[str]:
    run = uuid.uuid4().hex[:8]
    return [f"{PREFIX}-{tag}-{run}-{i}" for i in range(n)]


# --- fixtures (as test_experiment_targeting_by_state.py) ------------------------


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


@pytest.fixture
def session_factory(test_db):
    return sessionmaker(bind=test_db, expire_on_commit=False)


@pytest.fixture
def fresh(session_factory):
    """Run ``work(session)`` in a session of the test's own and commit."""

    def run(work):
        session = session_factory()
        try:
            session.execute(text("SET search_path TO test_experimentation"))
            result = work(session)
            session.commit()
            return result
        finally:
            session.close()

    return run


def _scheduler_session(test_db):
    factory = sessionmaker(bind=test_db)

    def session():
        s = factory()
        s.execute(text("SET search_path TO test_experimentation"))
        return s

    return session


def _stored(fresh, experiment_id):
    return fresh(lambda s: s.get(Experiment, uuid.UUID(experiment_id)).targeting_rules)


def _set(fresh, experiment_id, **values):
    def work(session):
        experiment = session.get(Experiment, uuid.UUID(experiment_id))
        for name, value in values.items():
            setattr(experiment, name, value)

    fresh(work)


def _counts(fresh, experiment_id):
    """(assignment rows, the distinct (user, variant) pairs of its events).

    ``/tracking/assign`` records a variant-shown event on every call, for a returning
    user too (unchanged here), so the event count grows with each call; what
    must not change is which variant anyone has been shown.
    """

    def work(session):
        eid = uuid.UUID(experiment_id)
        rows = session.query(Assignment).filter(Assignment.experiment_id == eid).count()
        pairs = {
            (user_id, str(variant_id))
            for user_id, variant_id in session.query(Event.user_id, Event.variant_id)
            .filter(Event.experiment_id == eid)
            .distinct()
        }
        return rows, pairs

    return fresh(work)


@pytest.fixture
def client(test_db):
    factory = sessionmaker(bind=test_db, autocommit=False, autoflush=False)

    def override_get_db():
        session = factory()
        session.execute(text("SET search_path TO test_experimentation"))
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


@pytest.fixture
def developer(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{PREFIX}_dev_{suffix}",
        email=f"{PREFIX}_dev_{suffix}@rollout.test",
        full_name="Rollout Rule Id",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def headers(developer):
    return {"Authorization": f"Bearer {create_local_access_token(developer)}"}


@pytest.fixture
def api_key(fresh, developer):
    raw = f"{PREFIX}_{secrets.token_hex(16)}"

    def add(session):
        session.add(
            APIKey(
                key=hash_api_key(raw),
                name=f"{PREFIX} {uuid.uuid4().hex[:6]}",
                is_active=True,
                user_id=developer.id,
            )
        )

    fresh(add)
    return {"X-API-Key": raw}


@pytest.fixture
def create(client, headers):
    """Create a DRAFT experiment with ``rules``; return (id, key)."""

    def make(rules):
        body = {
            "name": f"{PREFIX} {uuid.uuid4().hex[:8]}",
            "description": "Partial rollout rule id",
            "hypothesis": "Each experiment admits its own users",
            "experiment_type": "a_b",
            "targeting_rules": rules,
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
        }
        response = client.post(f"{EXPERIMENTS}/", json=body, headers=headers)
        assert response.status_code == 201, response.text
        return response.json()["id"], response.json()["key"]

    return make


def _post(client, headers, experiment_id, action):
    response = client.post(f"{EXPERIMENTS}/{experiment_id}/{action}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _put_rules(client, headers, experiment_id, rules):
    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": rules},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assign_all(client, api_key, key, users, country="US"):
    """{user_id: (assigned, variant_name)} from ``/tracking/assign``."""
    seen = {}
    for user_id in users:
        response = client.post(
            ASSIGN,
            json={
                "experiment_key": key,
                "user_id": user_id,
                "context": {"country": country},
            },
            headers=api_key,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        seen[user_id] = (body["assigned"], body["variant_name"])
    return seen


def _admitted(seen):
    return {user_id for user_id, (assigned, _) in seen.items() if assigned}


def _tick(test_db):
    from backend.app.core.scheduler import ExperimentScheduler

    scheduler = ExperimentScheduler()
    scheduler._notification_service = MagicMock()
    with patch("backend.app.core.scheduler.SessionLocal", _scheduler_session(test_db)):
        asyncio.run(scheduler.process_scheduled_experiments())


# --- a first start stamps ---------------------------------------------------------


@pytest.mark.regression
def test_first_start_stamps_and_admits_by_the_experiments_id(
    client, headers, create, fresh, api_key
):
    experiment_id, key = create(_rules())

    started = _post(client, headers, experiment_id, "start")

    expected = {**_rules(), "id": experiment_id}
    assert started["targeting_rules"] == expected
    assert _stored(fresh, experiment_id) == expected

    users = _users(300, "first")
    seen = _assign_all(client, api_key, key, users)
    assert _admitted(seen) == {u for u in users if _md5_admits(u, experiment_id)}


@pytest.mark.regression
def test_scheduled_first_start_stamps(client, create, fresh, test_db):
    experiment_id, _ = create(_rules())
    _set(
        fresh,
        experiment_id,
        start_date=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    _tick(test_db)

    def status_of(session):
        return session.get(Experiment, uuid.UUID(experiment_id)).status

    assert fresh(status_of) == ExperimentStatus.ACTIVE
    assert _stored(fresh, experiment_id) == {**_rules(), "id": experiment_id}


# --- 533b / C7: an experiment already running keeps "dashboard" -------------------


def test_a_running_experiment_keeps_its_users_and_its_bucketing(
    client, headers, create, fresh, api_key
):
    experiment_id, key = create(_rules())
    # Started before the change: ACTIVE with the id-less rule as stored.
    _set(fresh, experiment_id, status=ExperimentStatus.ACTIVE)

    users = _users(1000, "running")
    before = _assign_all(client, api_key, key, users)
    admitted = _admitted(before)
    assert admitted == {u for u in users if _md5_admits(u, "dashboard")}
    assert 400 <= len(admitted) <= 600, len(admitted)
    rows_before = _counts(fresh, experiment_id)
    # One row and one exposed variant per admitted user: not vacuous.
    assert rows_before[0] == len(rows_before[1]) == len(_admitted(before))

    # Pause and resume through the routes: a resume is not a first start.
    _post(client, headers, experiment_id, "pause")
    resumed = _post(client, headers, experiment_id, "start")
    assert resumed["targeting_rules"] == _rules()
    assert _stored(fresh, experiment_id) == _rules()

    # Everyone admitted, and a sample of those turned away.
    again = sorted(admitted) + sorted(set(users) - admitted)[:100]
    after = _assign_all(client, api_key, key, again)
    assert after == {u: before[u] for u in again}
    assert _counts(fresh, experiment_id) == rows_before

    newcomers = _users(200, "running-new")
    seen = _assign_all(client, api_key, key, newcomers)
    assert _admitted(seen) == {u for u in newcomers if _md5_admits(u, "dashboard")}


def test_a_scheduled_resume_writes_nothing(create, fresh, test_db):
    experiment_id, _ = create(_rules())
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    # Started before the change, then paused with a resume due.
    _set(
        fresh,
        experiment_id,
        status=ExperimentStatus.PAUSED,
        start_date=past - timedelta(days=1),
    )
    _set(fresh, experiment_id, resume_at=past)

    _tick(test_db)

    def status_of(session):
        return session.get(Experiment, uuid.UUID(experiment_id)).status

    assert fresh(status_of) == ExperimentStatus.ACTIVE
    assert _stored(fresh, experiment_id) == _rules()


def test_a_paused_edit_of_a_running_partial_rollout_keeps_dashboard(
    client, headers, create, fresh
):
    """The stored rule already admitted part of the users on ``"dashboard"``:
    an edit while paused does not change which new users that is."""
    experiment_id, _ = create(_rules())
    _set(fresh, experiment_id, status=ExperimentStatus.PAUSED)

    body = _put_rules(client, headers, experiment_id, _rules(country="GB"))

    assert body["targeting_rules"] == _rules(country="GB")
    assert _stored(fresh, experiment_id) == _rules(country="GB")


# --- a PAUSED edit that adds a partial rollout -------------------------------------


@pytest.mark.regression
def test_a_paused_edit_adding_a_partial_rollout_stamps_and_moves_nobody(
    client, headers, create, fresh, api_key
):
    experiment_id, key = create(_rules(rollout=None))
    _post(client, headers, experiment_id, "start")
    # Everyone it matches is admitted, so nothing was stamped.
    assert _stored(fresh, experiment_id) == _rules(rollout=None)

    users = _users(200, "paused-add")
    before = _assign_all(client, api_key, key, users)
    assert _admitted(before) == set(users)
    rows_before = _counts(fresh, experiment_id)
    # One row and one exposed variant per admitted user: not vacuous.
    assert rows_before[0] == len(rows_before[1]) == len(_admitted(before))

    _post(client, headers, experiment_id, "pause")
    edited = _put_rules(client, headers, experiment_id, _rules())
    expected = {**_rules(), "id": experiment_id}
    assert edited["targeting_rules"] == expected
    assert _stored(fresh, experiment_id) == expected

    resumed = _post(client, headers, experiment_id, "start")
    assert resumed["targeting_rules"] == expected

    # Sticky: everyone already assigned keeps their variant, no new rows.
    assert _assign_all(client, api_key, key, users) == before
    assert _counts(fresh, experiment_id) == rows_before

    newcomers = _users(300, "paused-add-new")
    seen = _assign_all(client, api_key, key, newcomers)
    assert _admitted(seen) == {u for u in newcomers if _md5_admits(u, experiment_id)}


# --- a PUT keeps the stored id -------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "sent",
    [_rules(country="GB"), _rules(country="GB", rollout=None)],
    ids=["partial rollout", "the dashboard's payload (no rollout)"],
)
def test_a_put_without_an_id_keeps_the_stored_one(client, headers, create, fresh, sent):
    experiment_id, _ = create(_rules())
    _post(client, headers, experiment_id, "start")
    _post(client, headers, experiment_id, "pause")

    body = _put_rules(client, headers, experiment_id, sent)

    assert body["targeting_rules"] == {**sent, "id": experiment_id}
    assert _stored(fresh, experiment_id) == {**sent, "id": experiment_id}


@pytest.mark.regression
def test_an_id_the_caller_chose_is_kept(client, headers, create, fresh):
    experiment_id, _ = create(_rules(id="checkout-half"))
    _post(client, headers, experiment_id, "start")
    assert _stored(fresh, experiment_id) == _rules(id="checkout-half")

    _post(client, headers, experiment_id, "pause")
    _put_rules(client, headers, experiment_id, _rules(country="GB"))
    assert _stored(fresh, experiment_id) == _rules(country="GB", id="checkout-half")


def test_a_draft_put_does_not_stamp(client, headers, create, fresh):
    """The id is given when the experiment first starts, not before."""
    experiment_id, _ = create(_rules(rollout=None))

    _put_rules(client, headers, experiment_id, _rules())

    assert _stored(fresh, experiment_id) == _rules()


# --- a clone gets its own id ----------------------------------------------------------


def _admitted_by_targeting(fresh, experiment_id, users):
    """The users the assignment path's targeting admits, read from the stored
    experiment. Ten thousand ``/tracking/assign`` calls would take minutes;
    this is the same eligibility check those calls make for a new user."""
    experiment = fresh(lambda s: s.get(Experiment, uuid.UUID(experiment_id)))
    service = AssignmentService.__new__(AssignmentService)
    service.rules_evaluation_service = RulesEvaluationService()
    admitted = set()
    for user_id in users:
        context = AssignmentService._build_targeting_context(user_id, {"country": "US"})
        if service._evaluate_experiment_targeting(experiment, context)["eligible"]:
            admitted.add(user_id)
    return admitted


@pytest.mark.regression
def test_a_clone_of_a_started_experiment_admits_its_own_users(
    client, headers, create, fresh
):
    source_id, _ = create(_rules())
    _post(client, headers, source_id, "start")
    assert _stored(fresh, source_id) == {**_rules(), "id": source_id}

    response = client.post(f"{EXPERIMENTS}/{source_id}/clone", headers=headers)
    assert response.status_code == 201, response.text
    clone_id = response.json()["id"]
    assert response.json()["targeting_rules"] == _rules()

    _post(client, headers, clone_id, "start")
    assert _stored(fresh, clone_id) == {**_rules(), "id": clone_id}
    assert _stored(fresh, source_id) == {**_rules(), "id": source_id}

    users = [f"{PREFIX}-clone-{i}" for i in range(10_000)]
    a = _admitted_by_targeting(fresh, source_id, users)
    b = _admitted_by_targeting(fresh, clone_id, users)
    assert a == {u for u in users if _md5_admits(u, source_id)}
    assert b == {u for u in users if _md5_admits(u, clone_id)}
    # The 533a bounds: 2,500 +- 5 sd overlap, 5,000 +- 5 sd each.
    assert 2_283 <= len(a & b) <= 2_717, (len(a), len(b), len(a & b))
    assert 4_750 <= len(b) <= 5_250, len(b)
