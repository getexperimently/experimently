"""An experiment's status changes only through the lifecycle endpoints (#542).

Before, ``PUT /experiments/{id}`` set ``status`` directly: a DRAFT became
ACTIVE with no ``start_date`` and without ``/start``'s checks (two variants, a
control, a metric), and a superuser could move any status to any other,
COMPLETED back to ACTIVE included. ``POST /experiments`` kept a client-sent
status, so an experiment could be created ACTIVE.

Now, for every role including the superuser:

* PUT: a ``status`` equal to the current one is accepted and changes nothing
  (a GET-then-PUT round trip works); any other value is 422 with
  ``loc ["body", "status"]`` and a fixed message naming the lifecycle
  endpoints. Nothing is written.
* POST: any ``status`` other than ``draft`` is 422 and nothing is created;
  ``status`` left out, or ``"draft"``, creates a DRAFT.

Each request is a real one: users with a local JWT from
``create_local_access_token`` and no dependency override except
``deps.get_db``. What was stored is read back in a session of the test's own.
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
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EXPERIMENTS = "/api/v1/experiments"
PREFIX = "statuslc"

THROUGH_LIFECYCLE = (
    "status changes through POST /api/v1/experiments/{id}/start, /pause, "
    "/complete or /archive; it cannot be set by an update."
)
ON_CREATE = (
    "a new experiment is created as draft; status changes through "
    "POST /api/v1/experiments/{id}/start, /pause, /complete or /archive."
)

#: role name -> (UserRole, is_superuser). Both may update a DRAFT.
ROLES = {
    "developer": (UserRole.DEVELOPER, False),
    "superuser": (UserRole.ADMIN, True),
}
STATUSES = {s.value: s for s in ExperimentStatus}
RULES = {
    "logical_operator": "AND",
    "groups": [
        {
            "logical_operator": "AND",
            "conditions": [
                {"attribute": "country", "operator": "equals", "value": "GB"}
            ],
        }
    ],
}


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


@pytest.fixture
def make_user(db_session):
    def make(role_name: str) -> User:
        role, is_superuser = ROLES[role_name]
        suffix = uuid.uuid4().hex[:8]
        user = User(
            username=f"{PREFIX}_{role_name}_{suffix}",
            email=f"{PREFIX}_{role_name}_{suffix}@status.test",
            full_name=f"Status Lifecycle {role_name}",
            hashed_password="unused: this user signs in by token only",
            is_active=True,
            is_superuser=is_superuser,
            role=role,
        )
        db_session.add(user)
        db_session.commit()
        return user

    return make


@pytest.fixture
def fresh(test_db):
    """Run ``work(session)`` in a session of the test's own and commit."""
    factory = sessionmaker(bind=test_db, expire_on_commit=False)

    def run(work):
        session = factory()
        try:
            session.execute(text("SET search_path TO test_experimentation"))
            result = work(session)
            session.commit()
            return result
        finally:
            session.close()

    return run


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


def _auth(user):
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


def _body(name: str, **extra) -> dict:
    body = {
        "name": name,
        "description": "Status through the lifecycle",
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
    }
    body.update(extra)
    return body


@pytest.fixture
def new_draft(client, make_user):
    creator = make_user("developer")

    def create() -> str:
        response = client.post(
            f"{EXPERIMENTS}/",
            json=_body(f"{PREFIX} {uuid.uuid4().hex[:8]}"),
            headers=_auth(creator),
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    return create


def _row(fresh, experiment_id):
    """(status value, start_date, end_date) as stored, or None if absent."""

    def work(session):
        experiment = session.get(Experiment, uuid.UUID(experiment_id))
        if experiment is None:
            return None
        return experiment.status.value, experiment.start_date, experiment.end_date

    return fresh(work)


def _set_status(fresh, experiment_id, status: ExperimentStatus):
    def work(session):
        session.get(Experiment, uuid.UUID(experiment_id)).status = status

    fresh(work)


def _assert_status_refused(response, message: str):
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert [(d["loc"], d["msg"]) for d in detail] == [(["body", "status"], message)]


# --- PUT ----------------------------------------------------------------------


@pytest.mark.regression
def test_draft_put_active_is_refused_and_the_row_stays_draft(
    client, make_user, new_draft, fresh
):
    experiment_id = new_draft()
    user = make_user("developer")

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}", json={"status": "active"}, headers=_auth(user)
    )

    _assert_status_refused(response, THROUGH_LIFECYCLE)
    assert _row(fresh, experiment_id) == ("draft", None, None)


@pytest.mark.regression
@pytest.mark.parametrize("target", ["active", "paused", "completed", "archived"])
@pytest.mark.parametrize("role_name", list(ROLES))
def test_put_a_different_status_is_refused_for_every_role(
    client, make_user, new_draft, fresh, role_name, target
):
    experiment_id = new_draft()
    user = make_user(role_name)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"status": target, "description": "changed with the status"},
        headers=_auth(user),
    )

    _assert_status_refused(response, THROUGH_LIFECYCLE)
    assert _row(fresh, experiment_id) == ("draft", None, None)

    def description(session):
        return session.get(Experiment, uuid.UUID(experiment_id)).description

    # Refused as a whole: the other field sent with it was not written either.
    assert fresh(description) == "Status through the lifecycle"


@pytest.mark.parametrize("role_name", list(ROLES))
def test_put_the_current_status_is_a_no_op(
    client, make_user, new_draft, fresh, role_name
):
    experiment_id = new_draft()
    user = make_user(role_name)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"status": "draft", "description": "renamed"},
        headers=_auth(user),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "draft"
    assert _row(fresh, experiment_id) == ("draft", None, None)


def test_get_then_put_round_trip_still_works(client, make_user, new_draft):
    experiment_id = new_draft()
    user = make_user("developer")
    fetched = client.get(f"{EXPERIMENTS}/{experiment_id}", headers=_auth(user))
    assert fetched.status_code == 200, fetched.text

    body = {
        field: fetched.json()[field]
        for field in ("name", "description", "status", "experiment_type")
    }
    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}", json=body, headers=_auth(user)
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "draft"


@pytest.mark.regression
@pytest.mark.parametrize("stored", ["completed", "archived", "paused", "active"])
def test_superuser_cannot_move_a_non_draft_status_through_put(
    client, make_user, new_draft, fresh, stored
):
    experiment_id = new_draft()
    _set_status(fresh, experiment_id, STATUSES[stored])
    before = _row(fresh, experiment_id)
    user = make_user("superuser")
    target = "draft" if stored == "active" else "active"

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}", json={"status": target}, headers=_auth(user)
    )

    _assert_status_refused(response, THROUGH_LIFECYCLE)
    assert _row(fresh, experiment_id) == before


@pytest.mark.parametrize("stored", ["completed", "archived", "paused", "active"])
def test_superuser_put_of_the_current_non_draft_status_is_accepted(
    client, make_user, new_draft, fresh, stored
):
    experiment_id = new_draft()
    _set_status(fresh, experiment_id, STATUSES[stored])
    user = make_user("superuser")

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}", json={"status": stored}, headers=_auth(user)
    )

    assert response.status_code == 200, response.text
    assert _row(fresh, experiment_id)[0] == stored


def test_developer_on_a_non_draft_keeps_the_state_refusal(
    client, make_user, new_draft, fresh
):
    """A request the state rule refuses keeps its 403: the status check runs
    after it."""
    experiment_id = new_draft()
    _set_status(fresh, experiment_id, ExperimentStatus.ACTIVE)
    user = make_user("developer")

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}", json={"status": "paused"}, headers=_auth(user)
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Cannot update experiments in active status"
    assert _row(fresh, experiment_id)[0] == "active"


@pytest.mark.parametrize("role_name", list(ROLES))
def test_paused_targeting_sent_with_the_current_status_is_still_refused(
    client, make_user, new_draft, fresh, role_name
):
    """On a PAUSED experiment targeting must be sent on its own (#523); an
    equal status still counts as another field."""
    experiment_id = new_draft()
    _set_status(fresh, experiment_id, ExperimentStatus.PAUSED)
    user = make_user(role_name)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": RULES, "status": "paused"},
        headers=_auth(user),
    )

    assert response.status_code == 403, response.text
    assert _row(fresh, experiment_id)[0] == "paused"


# --- POST ---------------------------------------------------------------------


def _count(fresh, name: str) -> int:
    return fresh(lambda s: s.query(Experiment).filter(Experiment.name == name).count())


@pytest.mark.regression
@pytest.mark.parametrize("sent", ["active", "paused", "completed", "archived"])
@pytest.mark.parametrize("role_name", list(ROLES))
def test_create_with_a_status_other_than_draft_is_refused(
    client, make_user, fresh, role_name, sent
):
    user = make_user(role_name)
    name = f"{PREFIX} create {uuid.uuid4().hex[:8]}"

    response = client.post(
        f"{EXPERIMENTS}/", json=_body(name, status=sent), headers=_auth(user)
    )

    _assert_status_refused(response, ON_CREATE)
    assert _count(fresh, name) == 0


@pytest.mark.parametrize("sent", [None, "draft"])
def test_create_without_status_or_with_draft_creates_a_draft(
    client, make_user, fresh, sent
):
    user = make_user("developer")
    name = f"{PREFIX} create {uuid.uuid4().hex[:8]}"
    extra = {} if sent is None else {"status": sent}

    response = client.post(
        f"{EXPERIMENTS}/", json=_body(name, **extra), headers=_auth(user)
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "draft"
    assert _row(fresh, response.json()["id"]) == ("draft", None, None)


# --- the lifecycle endpoints still move the status ----------------------------


def test_the_lifecycle_endpoints_still_move_the_status(
    client, make_user, new_draft, fresh
):
    experiment_id = new_draft()
    headers = _auth(make_user("developer"))

    for action, expected in (
        ("start", "active"),
        ("pause", "paused"),
        ("start", "active"),
        ("complete", "completed"),
        ("archive", "archived"),
    ):
        response = client.post(
            f"{EXPERIMENTS}/{experiment_id}/{action}", headers=headers
        )
        assert response.status_code == 200, (action, response.text)
        assert _row(fresh, experiment_id)[0] == expected, action

    status_value, start_date, end_date = _row(fresh, experiment_id)
    assert start_date is not None and end_date is not None
