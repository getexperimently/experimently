"""A cloned experiment keeps its analysis settings (#255), end to end.

An experiment is created through ``POST /experiments/`` with every analysis
setting the API accepts, ``sequential_testing_method`` is written to its row
(no route writes that column), and ``POST /experiments/{id}/clone`` must return
-- and store -- the same settings. The unit tests are in
``backend/tests/unit/services/test_clone_keeps_analysis_settings.py``.
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
from backend.app.services.experiment_service import CLONED_ANALYSIS_FIELDS

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EXPERIMENTS = "/api/v1/experiments"
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
def headers(db_session):
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
