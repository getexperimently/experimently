"""``PUT /experiments/{id}``: targeting can change only while DRAFT or PAUSED (#523, PR 1b).

Before, a DEVELOPER or non-superuser ADMIN could change targeting only in
DRAFT, and a superuser could change it in every state, COMPLETED included.
Now, for every role that may update experiments, superuser included:

* DRAFT: ``targeting_rules`` is accepted with any other field.
* PAUSED: accepted only when it is the one field sent.
* ACTIVE, COMPLETED, ARCHIVED: refused (403) whenever the request carries
  ``targeting_rules``, even when the value equals the stored one, with a
  detail naming the state.

A refusal by role and a refusal by state are both 403, so every refusal here
asserts the detail as well as the status: a state refusal answered with the
role message, or the reverse, fails.

Each request is a real one: users of each role with a local JWT from
``create_local_access_token`` and no dependency override except
``deps.get_db`` (see #470 for why ``make_client_for_user`` is not used). What
was stored is read back in a session of the test's own.
"""

from __future__ import annotations

import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
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
from backend.app.core.security import hash_api_key
from backend.app.main import app
from backend.app.models.api_key import APIKey
from backend.app.models.assignment import Assignment
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EXPERIMENTS = "/api/v1/experiments"
ASSIGN = "/api/v1/tracking/assign"
PREFIX = "tgtstate"


def _rules(country: str) -> dict:
    return {
        "logical_operator": "AND",
        "groups": [
            {
                "logical_operator": "AND",
                "conditions": [
                    {"attribute": "country", "operator": "equals", "value": country}
                ],
            }
        ],
    }


STORED = _rules("US")
NEW = _rules("GB")

ROLE_REFUSAL = get_permission_error_message(ResourceType.EXPERIMENT, Action.UPDATE)
OLD_STATE_REFUSAL = "Cannot update experiments in {} status"
PAUSED_ALONE = (
    "While the experiment is paused, targeting can be changed only on its own; "
    "send targeting_rules without other fields."
)


def _state_refusal(state: str) -> str:
    return (
        "Targeting can be changed only while the experiment is draft or paused; "
        f"it is {state}."
    )


#: role name -> (UserRole, is_superuser)
ROLES = {
    "admin": (UserRole.ADMIN, False),
    "developer": (UserRole.DEVELOPER, False),
    "analyst": (UserRole.ANALYST, False),
    "viewer": (UserRole.VIEWER, False),
    "superuser": (UserRole.ADMIN, True),
}
CHANGERS = {"admin", "developer", "superuser"}
STATES = {
    "draft": ExperimentStatus.DRAFT,
    "paused": ExperimentStatus.PAUSED,
    "active": ExperimentStatus.ACTIVE,
    "completed": ExperimentStatus.COMPLETED,
    "archived": ExperimentStatus.ARCHIVED,
}
EDITABLE = {"draft", "paused"}


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
            email=f"{PREFIX}_{role_name}_{suffix}@targeting.test",
            full_name=f"Targeting State {role_name}",
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


def _stored(fresh, experiment_id):
    return fresh(lambda s: s.get(Experiment, uuid.UUID(experiment_id)).targeting_rules)


def _set(fresh, experiment_id, **values):
    def work(session):
        experiment = session.get(Experiment, uuid.UUID(experiment_id))
        for name, value in values.items():
            setattr(experiment, name, value)

    fresh(work)


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
def creator(make_user):
    return make_user("developer")


@pytest.fixture
def new_experiment(client, creator):
    """Create a DRAFT experiment with ``STORED`` rules; return (id, key)."""

    def create():
        body = {
            "name": f"{PREFIX} {uuid.uuid4().hex[:8]}",
            "description": "Targeting by state",
            "hypothesis": "Targeting changes only while draft or paused",
            "experiment_type": "a_b",
            "targeting_rules": STORED,
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
        return response.json()["id"], response.json()["key"]

    return create


def _expected(role_name: str, state: str) -> tuple[int, str | None]:
    if role_name not in CHANGERS:
        return 403, ROLE_REFUSAL
    if state not in EDITABLE:
        return 403, _state_refusal(state)
    return 200, None


# --- the matrix ----------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("state", list(STATES))
@pytest.mark.parametrize("role_name", list(ROLES))
def test_targeting_change_by_state_and_role(
    client, make_user, new_experiment, fresh, role_name, state
):
    experiment_id, _ = new_experiment()
    _set(fresh, experiment_id, status=STATES[state])
    user = make_user(role_name)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": NEW},
        headers=_auth(user),
    )

    code, detail = _expected(role_name, state)
    assert (role_name, state, response.status_code) == (role_name, state, code), (
        response.text
    )
    if detail is not None:
        assert response.json()["detail"] == detail, (role_name, state, response.text)
    assert _stored(fresh, experiment_id) == (NEW if code == 200 else STORED)


@pytest.mark.regression
@pytest.mark.parametrize("role_name", list(ROLES))
def test_paused_targeting_with_another_field_is_refused(
    client, make_user, new_experiment, fresh, role_name
):
    experiment_id, _ = new_experiment()
    _set(fresh, experiment_id, status=ExperimentStatus.PAUSED)
    user = make_user(role_name)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": NEW, "description": "changed too"},
        headers=_auth(user),
    )

    assert response.status_code == 403, response.text
    expected = {
        "admin": OLD_STATE_REFUSAL.format("paused"),
        "developer": OLD_STATE_REFUSAL.format("paused"),
        "analyst": ROLE_REFUSAL,
        "viewer": ROLE_REFUSAL,
        "superuser": PAUSED_ALONE,
    }[role_name]
    assert response.json()["detail"] == expected, response.text
    assert _stored(fresh, experiment_id) == STORED

    def description(session):
        return session.get(Experiment, uuid.UUID(experiment_id)).description

    assert fresh(description) == "Targeting by state"


@pytest.mark.parametrize(
    "extra",
    [{"status": "paused"}, {"description": None}, {"hypothesis": None}],
    ids=["same status", "null description", "null hypothesis"],
)
def test_paused_targeting_is_judged_on_the_fields_sent(
    client, make_user, new_experiment, fresh, extra
):
    """A second field counts however the route later processes it: a status
    equal to the current one, or a null that a filtered dict would drop."""
    experiment_id, _ = new_experiment()
    _set(fresh, experiment_id, status=ExperimentStatus.PAUSED)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": NEW, **extra},
        headers=_auth(make_user("developer")),
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == OLD_STATE_REFUSAL.format("paused")
    assert _stored(fresh, experiment_id) == STORED


@pytest.mark.parametrize("field", ["status", "name"])
def test_paused_targeting_with_a_null_required_field_changes_nothing(
    client, make_user, new_experiment, fresh, field
):
    """``status`` and ``name`` cannot be null (#541): the request is refused at
    parsing (422), before the route, so it cannot become a targeting-only
    change either."""
    experiment_id, _ = new_experiment()
    _set(fresh, experiment_id, status=ExperimentStatus.PAUSED)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": NEW, field: None},
        headers=_auth(make_user("developer")),
    )

    assert response.status_code == 422, response.text
    assert [e["msg"] for e in response.json()["detail"]] == [f"{field} cannot be null"]
    assert _stored(fresh, experiment_id) == STORED


def test_paused_targeting_with_an_unknown_status_changes_nothing(
    client, make_user, new_experiment, fresh
):
    """``status`` is typed, so an unknown value is refused at parsing (422)
    before the route runs; the unknown-status branch there is unreachable
    over HTTP. Pinned so that loosening the type cannot turn this request
    into a targeting-only change."""
    experiment_id, _ = new_experiment()
    _set(fresh, experiment_id, status=ExperimentStatus.PAUSED)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": NEW, "status": "bogus"},
        headers=_auth(make_user("developer")),
    )

    assert response.status_code in (403, 422), response.text
    assert _stored(fresh, experiment_id) == STORED

    def status_of(session):
        return session.get(Experiment, uuid.UUID(experiment_id)).status

    assert fresh(status_of) == ExperimentStatus.PAUSED


def test_superuser_still_changes_other_fields_when_not_draft(
    client, make_user, new_experiment, fresh
):
    """Only targeting moved; a superuser's other changes on an ACTIVE
    experiment are accepted as before."""
    experiment_id, _ = new_experiment()
    _set(fresh, experiment_id, status=ExperimentStatus.ACTIVE)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"description": "superuser edit"},
        headers=_auth(make_user("superuser")),
    )

    assert response.status_code == 200, response.text
    assert response.json()["description"] == "superuser edit"


# --- presence, not difference --------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("role_name", ["developer", "superuser"])
def test_resending_the_stored_rules_on_an_active_experiment_is_refused(
    client, make_user, new_experiment, fresh, role_name
):
    experiment_id, _ = new_experiment()
    _set(fresh, experiment_id, status=ExperimentStatus.ACTIVE)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": STORED},
        headers=_auth(make_user(role_name)),
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == _state_refusal("active")
    assert _stored(fresh, experiment_id) == STORED


@pytest.mark.parametrize("state", ["draft", "paused"])
def test_resending_invalid_stored_rules_is_validated(
    client, make_user, new_experiment, fresh, state
):
    """Rules stored before validation existed are validated like any new
    value when sent again."""
    flat = {"country": ["US"]}
    experiment_id, _ = new_experiment()
    _set(fresh, experiment_id, status=STATES[state], targeting_rules=flat)

    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": flat},
        headers=_auth(make_user("developer")),
    )

    assert response.status_code == 422, response.text
    assert [e["loc"][-1] for e in response.json()["detail"]] == ["targeting_rules"]
    assert _stored(fresh, experiment_id) == flat


# --- the journey: edit while paused, resume -------------------------------------


@pytest.fixture
def api_key(fresh, creator):
    raw = f"tgtstate_{secrets.token_hex(16)}"

    def add(session):
        session.add(
            APIKey(
                key=hash_api_key(raw),
                name=f"{PREFIX} {uuid.uuid4().hex[:6]}",
                is_active=True,
                user_id=creator.id,
            )
        )

    fresh(add)
    return {"X-API-Key": raw}


def _assign(client, api_key, key, user_id, country):
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
    return response.json()


@pytest.mark.regression
def test_a_paused_edit_applies_to_new_people_only(
    client, creator, new_experiment, fresh, api_key
):
    experiment_id, key = new_experiment()
    headers = _auth(creator)
    started = client.post(f"{EXPERIMENTS}/{experiment_id}/start", headers=headers)
    assert started.status_code == 200, started.text

    stays = f"{PREFIX}-us-{uuid.uuid4().hex[:8]}"
    turned_away = f"{PREFIX}-gb-{uuid.uuid4().hex[:8]}"
    first = _assign(client, api_key, key, stays, "US")
    assert first["assigned"] is True, first
    refused = _assign(client, api_key, key, turned_away, "GB")
    assert (refused["assigned"], refused["reason"]) == (False, "targeting"), refused

    paused = client.post(f"{EXPERIMENTS}/{experiment_id}/pause", headers=headers)
    assert paused.status_code == 200, paused.text
    edited = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": NEW},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    resumed = client.post(f"{EXPERIMENTS}/{experiment_id}/start", headers=headers)
    assert resumed.status_code == 200, resumed.text

    now_in = _assign(client, api_key, key, turned_away, "GB")
    assert now_in["assigned"] is True, now_in

    again = _assign(client, api_key, key, stays, "US")
    assert (again["assigned"], again["variant_name"]) == (
        True,
        first["variant_name"],
    ), again

    def rows(session):
        return (
            session.query(Assignment)
            .filter(
                Assignment.experiment_id == uuid.UUID(experiment_id),
                Assignment.user_id == stays,
            )
            .count()
        )

    assert fresh(rows) == 1
