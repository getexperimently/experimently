"""A cloned experiment keeps its analysis settings (#255), end to end.

An experiment is created through ``POST /experiments/`` with every analysis
setting the API accepts, ``sequential_testing_method`` is written to its row
(no route writes that column), and ``POST /experiments/{id}/clone`` must return
-- and store -- the same settings. The unit tests are in
``backend/tests/unit/services/test_clone_keeps_analysis_settings.py``.

A clone also gets a generated key of its own, with the same bounded retry as
create, so the tracking API can find it (#609).
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
from backend.app.core.security import hash_api_key
from backend.app.main import app
from backend.app.models.api_key import APIKey
from backend.app.models.experiment import Experiment
from backend.app.models.user import User, UserRole
from backend.app.services.experiment_service import (
    CLONED_ANALYSIS_FIELDS,
    ExperimentService,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EXPERIMENTS = "/api/v1/experiments"
ASSIGN = "/api/v1/tracking/assign"
PREFIX = "clone255"


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


@pytest.fixture
def fresh(test_db):
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


@pytest.fixture
def user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{PREFIX}_dev_{suffix}",
        email=f"{PREFIX}_dev_{suffix}@clone.test",
        full_name="Clone Settings",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def headers(user):
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


def _stored(fresh, experiment_id):
    def work(session):
        experiment = session.get(Experiment, uuid.UUID(experiment_id))
        return {name: getattr(experiment, name) for name in CLONED_ANALYSIS_FIELDS}

    return fresh(work)


@pytest.mark.regression
def test_a_clone_through_the_api_keeps_every_analysis_setting(client, headers, fresh):
    body = {
        "name": f"{PREFIX} {uuid.uuid4().hex[:8]}",
        "description": "Clone keeps analysis settings",
        "hypothesis": "A clone is analysed like its source",
        "experiment_type": "a_b",
        "optimization_type": "thompson_sampling",
        "sequential_testing_enabled": True,
        "sequential_testing_config": {"method": "always_valid", "alpha": 0.1},
        "variance_reduction_config": {
            "method": "winsorization",
            "winsorization_percentile": 95.0,
        },
        "bayesian_enabled": True,
        "bayesian_config": {"alpha": 2.0, "beta": 3.0, "rope": [-0.01, 0.01]},
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
    source_id = response.json()["id"]

    def set_method(session):
        experiment = session.get(Experiment, uuid.UUID(source_id))
        experiment.sequential_testing_method = "always_valid"

    fresh(set_method)
    source = _stored(fresh, source_id)
    assert source["bayesian_enabled"] is True
    assert source["sequential_testing_method"] == "always_valid"
    assert source["variance_reduction_config"]["method"] == "winsorization"

    response = client.post(f"{EXPERIMENTS}/{source_id}/clone", headers=headers)
    assert response.status_code == 201, response.text
    clone_id = response.json()["id"]

    assert _stored(fresh, clone_id) == source
    assert {name: response.json()[name] for name in CLONED_ANALYSIS_FIELDS} == source
    assert _stored(fresh, source_id) == source


# --- the clone's key (#609) -----------------------------------------------------


@pytest.fixture
def api_key(fresh, user):
    raw = f"{PREFIX}_{secrets.token_hex(16)}"

    def add(session):
        session.add(
            APIKey(
                key=hash_api_key(raw),
                name=f"{PREFIX} {uuid.uuid4().hex[:6]}",
                is_active=True,
                user_id=user.id,
            )
        )

    fresh(add)
    return {"X-API-Key": raw}


def _create(client, headers) -> dict:
    body = {
        "name": f"{PREFIX} key {uuid.uuid4().hex[:8]}",
        "description": "Clone gets a key",
        "hypothesis": "A clone can be assigned",
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
    response = client.post(f"{EXPERIMENTS}/", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _stored_key(fresh, experiment_id):
    return fresh(lambda session: session.get(Experiment, uuid.UUID(experiment_id)).key)


@pytest.mark.regression
def test_a_clone_gets_its_own_key_and_can_be_assigned(client, headers, fresh, api_key):
    source = _create(client, headers)
    assert source["key"]

    response = client.post(f"{EXPERIMENTS}/{source['id']}/clone", headers=headers)
    assert response.status_code == 201, response.text
    clone = response.json()

    assert clone["key"], clone
    assert clone["key"] != source["key"]
    assert _stored_key(fresh, clone["id"]) == clone["key"]

    started = client.post(f"{EXPERIMENTS}/{clone['id']}/start", headers=headers)
    assert started.status_code == 200, started.text

    assigned = client.post(
        ASSIGN,
        json={
            "experiment_key": clone["key"],
            "user_id": f"{PREFIX}-user-{uuid.uuid4().hex[:8]}",
        },
        headers=api_key,
    )
    assert assigned.status_code == 200, assigned.text
    body = assigned.json()
    assert body["assigned"] is True, body
    assert body["variant_name"] in {"Control", "Treatment"}, body


@pytest.mark.regression
def test_a_clone_whose_first_generated_key_is_taken_still_gets_one(
    client, headers, fresh, monkeypatch
):
    source = _create(client, headers)
    taken = source["key"]

    real = ExperimentService.generate_key
    calls: list[str] = []

    def taken_once(name: str) -> str:
        key = taken if not calls else real(name)
        calls.append(key)
        return key

    monkeypatch.setattr(ExperimentService, "generate_key", staticmethod(taken_once))
    response = client.post(f"{EXPERIMENTS}/{source['id']}/clone", headers=headers)

    assert response.status_code == 201, response.text
    assert len(calls) == 2
    assert response.json()["key"] == calls[1] != taken
    assert _stored_key(fresh, response.json()["id"]) == calls[1]
