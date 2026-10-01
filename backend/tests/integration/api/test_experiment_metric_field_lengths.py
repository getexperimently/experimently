"""Experiment metrics: a field longer than its column answers 422 (#551).

``aggregation_method`` is stored in a ``String(50)`` column and
``event_value_path`` in a ``String(100)`` one. The schema had no limit on
either, so a longer value reached the database: an update
(``PUT /experiments/{id}``) answered 500 and a create a generic 400. Both now
answer 422 naming the field and the limit, and nothing is written. A value of
exactly the column length is still accepted.

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
from backend.app.models.experiment import Experiment, Metric
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EXPERIMENTS = "/api/v1/experiments"
PREFIX = "metriclen"

#: Metric field -> the length of the column it is stored in.
LIMITS = {"aggregation_method": 50, "event_value_path": 100}


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
        email=f"{PREFIX}_developer_{suffix}@lengths.test",
        full_name="Metric Lengths Developer",
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


def _metric(**extra) -> dict:
    return {
        "name": "Order Value",
        "event_name": "purchase",
        "metric_type": "revenue",
        "is_primary": True,
    } | extra


def _replacement(**extra) -> dict:
    """A metric for an update. Its name differs from the draft's metric:
    replacing a metric with one of the same name is a separate defect."""
    return _metric(name="Order Value (updated)", **extra)


def _create_body(name: str, metric: dict) -> dict:
    return {
        "name": name,
        "description": "Metric field lengths",
        "experiment_type": "a_b",
        "variants": [
            {"name": "Control", "is_control": True, "traffic_allocation": 50},
            {"name": "Treatment", "is_control": False, "traffic_allocation": 50},
        ],
        "metrics": [metric],
    }


@pytest.fixture
def draft(client, developer):
    """Create a DRAFT experiment with one metric; return its id."""
    body = _create_body(f"{PREFIX} {uuid.uuid4().hex[:8]}", _metric())
    response = client.post(f"{EXPERIMENTS}/", json=body, headers=_auth(developer))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _experiments_named(fresh, name: str) -> int:
    return fresh(lambda session: session.query(Experiment).filter_by(name=name).count())


def _stored_metrics(fresh, experiment_id: str) -> list[dict]:
    def work(session):
        rows = (
            session.query(Metric)
            .filter_by(experiment_id=uuid.UUID(experiment_id))
            .order_by(Metric.name)
            .all()
        )
        return [
            {
                "id": row.id,
                "name": row.name,
                "aggregation_method": row.aggregation_method,
                "event_value_path": row.event_value_path,
            }
            for row in rows
        ]

    return fresh(work)


def _only_error(response, field: str, limit: int) -> None:
    detail = response.json()["detail"]
    assert isinstance(detail, list) and len(detail) == 1, detail
    (error,) = detail
    assert error["loc"] == ["body", "metrics", 0, field], error
    assert error["type"] == "string_too_long", error
    assert error["ctx"] == {"max_length": limit}, error


@pytest.mark.regression
@pytest.mark.parametrize("field", sorted(LIMITS))
def test_create_with_an_over_length_metric_field_is_refused(
    client, developer, fresh, field
):
    limit = LIMITS[field]
    name = f"{PREFIX} {uuid.uuid4().hex[:8]}"
    body = _create_body(name, _metric(**{field: "x" * (limit + 1)}))

    response = client.post(f"{EXPERIMENTS}/", json=body, headers=_auth(developer))

    assert response.status_code == 422, response.text
    _only_error(response, field, limit)
    assert _experiments_named(fresh, name) == 0


@pytest.mark.regression
@pytest.mark.parametrize("field", sorted(LIMITS))
def test_create_with_a_metric_field_at_its_length_is_accepted(
    client, developer, fresh, field
):
    value = "x" * LIMITS[field]
    name = f"{PREFIX} {uuid.uuid4().hex[:8]}"
    body = _create_body(name, _metric(**{field: value}))

    response = client.post(f"{EXPERIMENTS}/", json=body, headers=_auth(developer))

    assert response.status_code == 201, response.text
    (stored,) = _stored_metrics(fresh, response.json()["id"])
    assert stored[field] == value


@pytest.mark.regression
@pytest.mark.parametrize("field", sorted(LIMITS))
def test_update_with_an_over_length_metric_field_is_refused(
    client, developer, draft, fresh, field
):
    limit = LIMITS[field]
    before = _stored_metrics(fresh, draft)

    response = client.put(
        f"{EXPERIMENTS}/{draft}",
        json={"metrics": [_replacement(**{field: "x" * (limit + 1)})]},
        headers=_auth(developer),
    )

    assert response.status_code == 422, response.text
    _only_error(response, field, limit)
    assert _stored_metrics(fresh, draft) == before


@pytest.mark.regression
@pytest.mark.parametrize("field", sorted(LIMITS))
def test_update_with_a_metric_field_at_its_length_is_accepted(
    client, developer, draft, fresh, field
):
    value = "x" * LIMITS[field]

    response = client.put(
        f"{EXPERIMENTS}/{draft}",
        json={"metrics": [_replacement(**{field: value})]},
        headers=_auth(developer),
    )

    assert response.status_code == 200, response.text
    (stored,) = _stored_metrics(fresh, draft)
    assert stored[field] == value
