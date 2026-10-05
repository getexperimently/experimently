"""A details-only update leaves a draft's variants and metrics alone (#442).

The dashboard's "Edit details" sends ``PUT /experiments/{id}`` with only the
changed subset of ``name``, ``description`` and ``hypothesis``. The update
route replaces variants and metrics wholesale when a request carries them
(``ExperimentService.update_experiment``), so the dashboard never sends them;
this pins the server half: a request without them keeps every variant and
metric row, with its id and every field the dashboard does not carry
(a variant's ``configuration``, a metric's ``minimum_sample_size``,
``expected_effect``, ``event_value_path`` and ``lower_is_better``).

Who may send it, and in which status, is pinned route by route in
``test_experiment_access_by_role.py`` (rows ``update`` and ``update_active``).
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
PREFIX = "details442"


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
            return work(session)
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
        email=f"{PREFIX}_dev_{suffix}@details.test",
        full_name="Details Edit",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


def _rows(fresh, experiment_id):
    def work(session):
        experiment = session.get(Experiment, uuid.UUID(experiment_id))
        variants = sorted(
            (
                str(v.id),
                v.name,
                v.description,
                v.is_control,
                v.traffic_allocation,
                v.configuration,
            )
            for v in experiment.variants
        )
        metrics = sorted(
            (
                str(m.id),
                m.name,
                m.description,
                m.event_name,
                m.is_primary,
                m.aggregation_method,
                m.minimum_sample_size,
                m.expected_effect,
                m.event_value_path,
                m.lower_is_better,
            )
            for m in experiment.metric_definitions
        )
        return variants, metrics

    return fresh(work)


@pytest.mark.regression
def test_a_details_edit_keeps_every_variant_and_metric_row(client, headers, fresh):
    suffix = uuid.uuid4().hex[:8]
    created = client.post(
        f"{EXPERIMENTS}/",
        headers=headers,
        json={
            "name": f"{PREFIX} {suffix}",
            "description": "before",
            "hypothesis": "before",
            "variants": [
                {"name": "control", "is_control": True, "traffic_allocation": 50},
                {
                    "name": "treatment",
                    "description": "green",
                    "is_control": False,
                    "traffic_allocation": 50,
                    "configuration": {"color": "green", "layout": {"columns": 2}},
                },
            ],
            "metrics": [
                {
                    "name": "Revenue",
                    "description": "order value",
                    "event_name": "purchase",
                    "metric_type": "revenue",
                    "is_primary": True,
                    "minimum_sample_size": 1234,
                    "expected_effect": 0.07,
                    "event_value_path": "amount",
                    "lower_is_better": True,
                }
            ],
        },
    )
    assert created.status_code in (200, 201), created.text
    experiment_id = created.json()["id"]
    before = _rows(fresh, experiment_id)
    assert len(before[0]) == 2 and len(before[1]) == 1

    body = {
        "name": f"{PREFIX} renamed {suffix}",
        "description": None,
        "hypothesis": "after",
    }
    response = client.put(f"{EXPERIMENTS}/{experiment_id}", headers=headers, json=body)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert (answer["name"], answer["description"], answer["hypothesis"]) == (
        body["name"],
        None,
        "after",
    )

    assert _rows(fresh, experiment_id) == before
