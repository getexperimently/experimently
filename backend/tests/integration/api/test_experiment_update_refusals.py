"""``PUT /experiments/{id}``: what it refuses, with which status (#602, #595).

#602: the four refusals because of the experiment's state answer 400, not 403,
with the detail unchanged. 403 is left for the role: a caller whose role may
not update experiments gets it before any state is looked at, so it learns
nothing about the state. The order is 404, 403 (role), 501, the four 400s,
then the 422s.

#595: ``schedule`` was accepted and silently ignored. Any body that contains
the key, whatever its value, is now refused with one fixed 422 that points at
``PUT /api/v1/experiments/{experiment_id}/schedule`` and repeats nothing from
the value.

Every request is a real one (users of each role with a local JWT, no
dependency override except ``deps.get_db``), and what was stored is read back
in a session of the test's own.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.core.permissions import (
    Action,
    ResourceType,
    get_permission_error_message,
)
from backend.app.main import app
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.user import User, UserRole
from backend.app.schemas.experiment import ExperimentUpdate

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EXPERIMENTS = "/api/v1/experiments"
PREFIX = "updrefuse"

ROLE_REFUSAL = get_permission_error_message(ResourceType.EXPERIMENT, Action.UPDATE)
TARGETING_STATE = (
    "Targeting can be changed only while the experiment is draft or paused; it is {}."
)
NOT_DRAFT = "Cannot update experiments in {} status"
PAUSED_ALONE = (
    "While the experiment is paused, targeting can be changed only on its own; "
    "send targeting_rules without other fields."
)
RESTRICTED = "Cannot update {} for experiments in {} status"

SCHEDULE_MESSAGE = (
    "schedule is not applied by this endpoint; use "
    "PUT /api/v1/experiments/{experiment_id}/schedule"
)
SCHEDULE_DETAIL = [
    {"type": "value_error", "loc": ["body", "schedule"], "msg": SCHEDULE_MESSAGE}
]
SENTINEL = "PlantedSentinel7f3a"

NEW_RULES = {
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
NEW_VARIANTS = [
    {"name": "Control", "is_control": True, "traffic_allocation": 30},
    {"name": "Treatment", "is_control": False, "traffic_allocation": 70},
]

#: role name -> (UserRole, is_superuser)
ROLES = {
    "developer": (UserRole.DEVELOPER, False),
    "analyst": (UserRole.ANALYST, False),
    "viewer": (UserRole.VIEWER, False),
    "superuser": (UserRole.ADMIN, True),
}


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


@pytest.fixture
def make_user(fresh):
    def make(role_name: str) -> User:
        role, is_superuser = ROLES[role_name]
        suffix = uuid.uuid4().hex[:8]

        def work(session):
            user = User(
                username=f"{PREFIX}_{role_name}_{suffix}",
                email=f"{PREFIX}_{role_name}_{suffix}@refusals.test",
                full_name=f"Update Refusals {role_name}",
                hashed_password="unused: this user signs in by token only",
                is_active=True,
                is_superuser=is_superuser,
                role=role,
            )
            session.add(user)
            return user

        return fresh(work)

    return make


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


@pytest.fixture
def experiment(client, make_user, fresh):
    """Create an experiment through the API, then put it in ``status``."""
    creator = make_user("developer")

    def create(status: ExperimentStatus = ExperimentStatus.DRAFT) -> str:
        body = {
            "name": f"{PREFIX} {uuid.uuid4().hex[:8]}",
            "description": "Update refusals",
            "hypothesis": "A refusal changes nothing",
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
        response = client.post(f"{EXPERIMENTS}/", json=body, headers=_auth(creator))
        assert response.status_code == 201, response.text
        experiment_id = response.json()["id"]

        def work(session):
            session.get(Experiment, uuid.UUID(experiment_id)).status = status

        fresh(work)
        return experiment_id

    return create


def _snapshot(fresh, experiment_id):
    """Everything a refused update could have changed."""

    def work(session):
        row = session.get(Experiment, uuid.UUID(experiment_id))
        return (
            row.name,
            row.description,
            row.status,
            row.targeting_rules,
            row.start_date,
            row.end_date,
            row.updated_at,
            sorted((v.name, v.traffic_allocation) for v in row.variants),
        )

    return fresh(work)


def _put(client, experiment_id, body, user):
    return client.put(f"{EXPERIMENTS}/{experiment_id}", json=body, headers=_auth(user))


# --- #602: the four state refusals answer 400 ---------------------------------

#: site -> (role, state, body, detail). One case per refusal in the route, in
#: the route's order. The superuser passes the non-draft guard, so the last two
#: sites are reached only by it.
STATE_SITES = {
    "targeting_not_draft_or_paused": (
        "developer",
        ExperimentStatus.ACTIVE,
        {"targeting_rules": NEW_RULES},
        TARGETING_STATE.format("active"),
    ),
    "not_draft": (
        "developer",
        ExperimentStatus.ACTIVE,
        {"name": "renamed while active"},
        NOT_DRAFT.format("active"),
    ),
    "paused_targeting_with_other_fields": (
        "superuser",
        ExperimentStatus.PAUSED,
        {"targeting_rules": NEW_RULES, "name": "renamed while paused"},
        PAUSED_ALONE,
    ),
    "restricted_field_not_draft": (
        "superuser",
        ExperimentStatus.ACTIVE,
        {"variants": NEW_VARIANTS},
        RESTRICTED.format("variants", "active"),
    ),
}


@pytest.mark.regression
@pytest.mark.parametrize("site", list(STATE_SITES))
def test_a_state_refusal_answers_400_with_its_detail(
    client, make_user, experiment, fresh, site
):
    role_name, state, body, detail = STATE_SITES[site]
    experiment_id = experiment(state)
    before = _snapshot(fresh, experiment_id)

    response = _put(client, experiment_id, body, make_user(role_name))

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == detail
    assert _snapshot(fresh, experiment_id) == before


@pytest.mark.regression
@pytest.mark.parametrize("site", list(STATE_SITES))
@pytest.mark.parametrize("role_name", ["analyst", "viewer"])
def test_a_role_without_update_gets_403_before_any_state_check(
    client, make_user, experiment, fresh, site, role_name
):
    """The same bodies, from a role that may not update: the role refusal,
    never the state's 400, so the answer says nothing about the state."""
    _, state, body, _ = STATE_SITES[site]
    experiment_id = experiment(state)
    before = _snapshot(fresh, experiment_id)

    response = _put(client, experiment_id, body, make_user(role_name))

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == ROLE_REFUSAL
    assert _snapshot(fresh, experiment_id) == before


def test_an_unknown_experiment_is_404_before_the_role(client, make_user):
    response = _put(client, uuid.uuid4(), {"name": "x"}, make_user("viewer"))

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Experiment not found"


def test_the_route_documents_the_400():
    operation = app.openapi()["paths"]["/api/v1/experiments/{experiment_id}"]["put"]

    assert operation["responses"]["400"]["description"] == (
        "The experiment's state does not allow this change"
    )


# --- #595: schedule is refused on presence ------------------------------------


def _valid_schedule():
    start = datetime.now(timezone.utc) + timedelta(days=1)
    return {
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=7)).isoformat(),
        "time_zone": "UTC",
        # Not a ScheduleConfig field, so the schedule is still valid; it is
        # there to show that nothing from the value comes back.
        "note": SENTINEL,
    }


SCHEDULES = {
    "valid": _valid_schedule,
    "unknown_zone": lambda: {"time_zone": f"Planted/{SENTINEL}"},
    "empty": dict,
    "null": lambda: None,
}


@pytest.mark.regression
@pytest.mark.parametrize("case", list(SCHEDULES))
def test_a_schedule_is_refused_whatever_its_value(
    client, make_user, experiment, fresh, case
):
    experiment_id = experiment()
    before = _snapshot(fresh, experiment_id)

    response = _put(
        client,
        experiment_id,
        {"name": "renamed with a schedule", "schedule": SCHEDULES[case]()},
        make_user("developer"),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == SCHEDULE_DETAIL
    assert SENTINEL not in response.text
    assert _snapshot(fresh, experiment_id) == before


@pytest.mark.regression
def test_an_update_without_schedule_is_applied(client, make_user, experiment, fresh):
    experiment_id = experiment()

    response = _put(client, experiment_id, {"name": "renamed"}, make_user("developer"))

    assert response.status_code == 200, response.text
    assert "schedule" not in response.json()
    assert _snapshot(fresh, experiment_id)[0] == "renamed"


@pytest.mark.regression
def test_an_experiment_read_with_get_can_be_sent_back(
    client, make_user, experiment, fresh
):
    """The response has no ``schedule``, so a GET-then-PUT round trip never
    sends one and is not refused."""
    user = make_user("developer")
    experiment_id = experiment()
    fetched = client.get(f"{EXPERIMENTS}/{experiment_id}", headers=_auth(user))
    assert fetched.status_code == 200, fetched.text
    assert "schedule" not in fetched.json()

    response = _put(client, experiment_id, fetched.json(), user)

    assert response.status_code == 200, response.text


@pytest.mark.regression
@pytest.mark.parametrize("case", list(SCHEDULES))
def test_the_schema_refuses_schedule_before_validating_it(case):
    with pytest.raises(ValidationError) as caught:
        ExperimentUpdate.model_validate({"schedule": SCHEDULES[case]()})

    errors = caught.value.errors()
    assert [(e["loc"], e["type"], e["msg"]) for e in errors] == [
        (("schedule",), "value_error", SCHEDULE_MESSAGE)
    ]


def test_the_schedule_field_stays_declared_and_deprecated():
    """Removing it would let ``extra="ignore"`` drop the key and answer 200."""
    schema = ExperimentUpdate.model_json_schema()["properties"]["schedule"]

    assert schema["deprecated"] is True
    assert "refused with 422" in schema["description"]
