"""``PUT /experiments/{id}``: required fields cannot be set to null (#541).

``name``, ``status``, ``experiment_type`` and ``sequential_testing_enabled``
are stored in NOT NULL columns. An update that sets one of them to null, or
sets a name longer than the column's 100 characters, used to reach the
database and answer 500. It now answers 422 naming the field, and nothing is
written. Leaving a field out is still allowed: every field of an update is
optional.

Nulls that were accepted before stay accepted: ``description``, ``variants``,
``metrics`` and ``bayesian_enabled`` set to null still answer 200.

The assertions are on the status and the 422 body only, not on the text of
any 500, so they do not depend on how the route words an unexpected error.

Each request is a real one: a DEVELOPER with a local JWT from
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
from backend.app.models.experiment import Experiment
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EXPERIMENTS = "/api/v1/experiments"
PREFIX = "reqnull"

#: The fields an update may not set to null: each is a NOT NULL column.
REQUIRED = ("name", "status", "experiment_type", "sequential_testing_enabled")

#: Fields whose null was accepted before this change and still is.
NULLABLE = ("description", "variants", "metrics", "bayesian_enabled")


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


@pytest.fixture
def developer(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{PREFIX}_developer_{suffix}",
        email=f"{PREFIX}_developer_{suffix}@required.test",
        full_name="Required Fields Developer",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return user


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


@pytest.fixture
def draft(client, developer):
    """Create a DRAFT experiment; return its id."""
    body = {
        "name": f"{PREFIX} {uuid.uuid4().hex[:8]}",
        "description": "Required fields on update",
        "hypothesis": "A null required field is refused",
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
    response = client.post(f"{EXPERIMENTS}/", json=body, headers=_auth(developer))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _stored(fresh, experiment_id) -> dict:
    def work(session):
        row = session.get(Experiment, uuid.UUID(experiment_id))
        return {
            "name": row.name,
            "description": row.description,
            "status": row.status,
            "experiment_type": row.experiment_type,
            "sequential_testing_enabled": row.sequential_testing_enabled,
            "bayesian_enabled": row.bayesian_enabled,
            "updated_at": row.updated_at,
        }

    return fresh(work)


def _only_error(response, field: str) -> dict:
    detail = response.json()["detail"]
    assert isinstance(detail, list) and len(detail) == 1, detail
    error = detail[0]
    assert error["loc"] == ["body", field], error
    return error


@pytest.mark.regression
@pytest.mark.parametrize("field", REQUIRED)
def test_null_required_field_is_refused(client, developer, draft, fresh, field):
    before = _stored(fresh, draft)

    response = client.put(
        f"{EXPERIMENTS}/{draft}", json={field: None}, headers=_auth(developer)
    )

    assert response.status_code == 422, response.text
    error = _only_error(response, field)
    assert error["msg"] == f"{field} cannot be null"
    assert error["type"] == "null_not_allowed"
    assert _stored(fresh, draft) == before


@pytest.mark.regression
def test_name_over_100_characters_is_refused(client, developer, draft, fresh):
    before = _stored(fresh, draft)

    response = client.put(
        f"{EXPERIMENTS}/{draft}", json={"name": "n" * 101}, headers=_auth(developer)
    )

    assert response.status_code == 422, response.text
    error = _only_error(response, "name")
    assert error["type"] == "string_too_long"
    assert error["ctx"] == {"max_length": 100}
    assert _stored(fresh, draft) == before


def test_name_of_100_characters_is_accepted(client, developer, draft, fresh):
    name = "n" * 100

    response = client.put(
        f"{EXPERIMENTS}/{draft}", json={"name": name}, headers=_auth(developer)
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == name
    assert _stored(fresh, draft)["name"] == name


@pytest.mark.parametrize("field", NULLABLE)
def test_null_optional_field_is_still_accepted(client, developer, draft, field):
    response = client.put(
        f"{EXPERIMENTS}/{draft}", json={field: None}, headers=_auth(developer)
    )

    assert response.status_code == 200, response.text


def test_omitting_required_fields_is_still_accepted(client, developer, draft, fresh):
    """Every field of an update is optional: leaving one out keeps it."""
    before = _stored(fresh, draft)

    response = client.put(
        f"{EXPERIMENTS}/{draft}",
        json={"description": "Only the description changes"},
        headers=_auth(developer),
    )

    assert response.status_code == 200, response.text
    after = _stored(fresh, draft)
    assert after["description"] == "Only the description changes"
    for field in REQUIRED:
        assert after[field] == before[field], field
