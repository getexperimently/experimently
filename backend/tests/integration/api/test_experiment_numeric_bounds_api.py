"""Experiment numbers the database cannot hold answer 422 (#559).

* ``minimum_sample_size`` is stored in a 32-bit ``INTEGER`` column. The schema
  had a lower bound only, so 2**31 reached the database: a create answered a
  generic 400 and an update (``PUT /experiments/{id}``) a 500.
* ``bayesian_config`` and ``split_url_config`` are stored as JSONB, which
  cannot hold NaN or an infinity. An infinite Bayesian prior, or a NaN split
  URL allocation (NaN passes the sum-to-100 check), reached the database the
  same way.

Each now answers 422 naming the field, and nothing is written. The largest
value the column holds is still accepted.

Each request is a real one: a DEVELOPER with a local JWT and no dependency
override except ``deps.get_db``. What was stored is read back in a session of
the test's own. Infinity and NaN are sent as the JSON tokens Python's parser
accepts (``Infinity``, ``NaN``).
"""

from __future__ import annotations

import json
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
PREFIX = "numbounds"
INT32_MAX = 2**31 - 1


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
        email=f"{PREFIX}_developer_{suffix}@bounds.test",
        full_name="Numeric Bounds Developer",
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


def _auth(user) -> dict:
    return {
        "Authorization": f"Bearer {create_local_access_token(user)}",
        "Content-Type": "application/json",
    }


def _send(client, method: str, url: str, user, body: dict):
    # json.dumps writes float('inf') / float('nan') as Infinity / NaN.
    return client.request(method, url, content=json.dumps(body), headers=_auth(user))


def _metric(**extra) -> dict:
    return {
        "name": "Conversion",
        "event_name": "purchase",
        "metric_type": "conversion",
        "is_primary": True,
    } | extra


def _create_body(name: str, metric: dict | None = None, **extra) -> dict:
    return {
        "name": name,
        "experiment_type": "a_b",
        "variants": [
            {"name": "Control", "is_control": True, "traffic_allocation": 50},
            {"name": "Treatment", "is_control": False, "traffic_allocation": 50},
        ],
        "metrics": [metric or _metric()],
    } | extra


def _split_url(first_allocation: float) -> dict:
    return {
        "variants": [
            {
                "name": "a",
                "url": "https://a.example.com",
                "traffic_allocation": first_allocation,
            },
            {"name": "b", "url": "https://b.example.com", "traffic_allocation": 50},
        ]
    }


def _name() -> str:
    return f"{PREFIX} {uuid.uuid4().hex[:8]}"


@pytest.fixture
def draft(client, developer):
    """A DRAFT experiment with one metric; returns its id."""
    response = _send(
        client, "POST", f"{EXPERIMENTS}/", developer, _create_body(_name())
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _experiments_named(fresh, name: str) -> int:
    return fresh(lambda s: s.query(Experiment).filter_by(name=name).count())


def _stored(fresh, experiment_id: str) -> dict:
    def work(session):
        experiment = session.get(Experiment, uuid.UUID(experiment_id))
        metrics = (
            session.query(Metric)
            .filter_by(experiment_id=experiment.id)
            .order_by(Metric.name)
            .all()
        )
        return {
            "bayesian_config": experiment.bayesian_config,
            "split_url_config": experiment.split_url_config,
            "metrics": [(m.name, m.minimum_sample_size) for m in metrics],
        }

    return fresh(work)


def _error_at(response, loc: list) -> dict:
    detail = response.json()["detail"]
    assert isinstance(detail, list), detail
    matching = [e for e in detail if e["loc"] == ["body", *loc]]
    assert matching, detail
    return matching[0]


INF, NAN = float("inf"), float("nan")

#: (label, extra body fields, error loc, error type)
REFUSED = [
    (
        "sample-size-2**31",
        {"metrics": [_metric(minimum_sample_size=INT32_MAX + 1)]},
        ["metrics", 0, "minimum_sample_size"],
        "less_than_equal",
    ),
    (
        "bayesian-alpha-inf",
        {"bayesian_enabled": True, "bayesian_config": {"alpha": INF}},
        ["bayesian_config", "alpha"],
        "finite_number",
    ),
    (
        "bayesian-rope-nan",
        {"bayesian_enabled": True, "bayesian_config": {"rope": [0.0, NAN]}},
        ["bayesian_config", "rope", 1],
        "finite_number",
    ),
    (
        "split-url-allocation-nan",
        {"experiment_type": "split_url", "split_url_config": _split_url(NAN)},
        ["split_url_config", "variants", 0, "traffic_allocation"],
        "finite_number",
    ),
]


@pytest.mark.regression
@pytest.mark.parametrize(
    "extra, loc, kind", [r[1:] for r in REFUSED], ids=[r[0] for r in REFUSED]
)
def test_create_with_a_number_the_database_cannot_hold_is_refused(
    client, developer, fresh, extra, loc, kind
):
    name = _name()

    response = _send(
        client, "POST", f"{EXPERIMENTS}/", developer, _create_body(name, **extra)
    )

    assert response.status_code == 422, response.text
    assert _error_at(response, loc)["type"] == kind
    assert _experiments_named(fresh, name) == 0


@pytest.mark.regression
@pytest.mark.parametrize(
    "extra, loc, kind", [r[1:] for r in REFUSED], ids=[r[0] for r in REFUSED]
)
def test_update_with_a_number_the_database_cannot_hold_is_refused(
    client, developer, fresh, draft, extra, loc, kind
):
    before = _stored(fresh, draft)
    body = dict(extra)
    if "metrics" in body:
        # Another name: replacing a metric with one of the same name is a
        # separate defect.
        body["metrics"] = [dict(body["metrics"][0], name="Conversion (updated)")]

    response = _send(client, "PUT", f"{EXPERIMENTS}/{draft}", developer, body)

    assert response.status_code == 422, response.text
    assert _error_at(response, loc)["type"] == kind
    assert _stored(fresh, draft) == before


@pytest.mark.regression
def test_the_largest_sample_size_the_column_holds_is_accepted(
    client, developer, fresh, draft
):
    name = _name()
    created = _send(
        client,
        "POST",
        f"{EXPERIMENTS}/",
        developer,
        _create_body(name, _metric(minimum_sample_size=INT32_MAX)),
    )
    updated = _send(
        client,
        "PUT",
        f"{EXPERIMENTS}/{draft}",
        developer,
        {
            "metrics": [
                _metric(name="Conversion (updated)", minimum_sample_size=INT32_MAX)
            ]
        },
    )

    assert created.status_code == 201, created.text
    assert updated.status_code == 200, updated.text
    assert _stored(fresh, created.json()["id"])["metrics"] == [
        ("Conversion", INT32_MAX)
    ]
    assert _stored(fresh, draft)["metrics"] == [("Conversion (updated)", INT32_MAX)]
