"""A clone of an experiment with a long name is shortened to fit (#627), end to end.

``POST /experiments/{id}/clone`` names the clone ``"Copy of <name>"``. The
name column is ``String(100)``, so a source name of 93 to 100 characters made
the insert fail and the clone answered 500. The clone's name is now cut to the
column's limit, by character (Postgres counts characters, not bytes).

Each case reads the stored name back in a fresh session and checks that exactly
one row carries it. The unit tests are in
``backend/tests/unit/services/test_clone_name_fits.py``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.experiment import Experiment
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EXPERIMENTS = "/api/v1/experiments"
PREFIX = "clone627"
LIMIT = 100


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
        full_name="Clone Name",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


def _name_of_length(n: int) -> str:
    """A name unique to this test run, exactly *n* characters long."""
    head = f"{PREFIX} {uuid.uuid4().hex[:8]} "
    return (head + "x" * n)[:n]


def _create(client, headers, name: str) -> str:
    body = {
        "name": name,
        "description": "Clone name fits",
        "hypothesis": "A long name still clones",
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
    return response.json()["id"]


def _clone_and_check(client, headers, fresh, source_id: str, source_name: str):
    expected = ("Copy of " + source_name)[:LIMIT]

    response = client.post(f"{EXPERIMENTS}/{source_id}/clone", headers=headers)

    assert response.status_code == 201, response.text
    assert response.json()["name"] == expected
    clone_id = uuid.UUID(response.json()["id"])

    def read(session):
        stored = session.get(Experiment, clone_id).name
        rows = session.scalar(
            select(func.count())
            .select_from(Experiment)
            .where(Experiment.name == expected)
        )
        return stored, rows

    stored, rows = fresh(read)
    assert stored == expected
    assert len(stored) == min(len("Copy of ") + len(source_name), LIMIT)
    assert rows == 1


# 91 and 92 fitted before the fix and are kept as the boundary controls; 93 to
# 100 answered 500 before it.
@pytest.mark.parametrize(
    "length",
    [91, 92]
    + [pytest.param(n, marks=pytest.mark.regression) for n in range(93, LIMIT + 1)],
)
def test_a_clone_of_a_long_name_is_shortened_to_fit(client, headers, fresh, length):
    name = _name_of_length(length)
    assert len(name) == length
    source_id = _create(client, headers, name)

    _clone_and_check(client, headers, fresh, source_id, name)


@pytest.mark.regression
def test_a_unicode_name_is_cut_by_character_not_by_byte(client, headers, fresh):
    name = "é" * 50 + "\N{GRINNING FACE}" * 50
    assert len(name) == LIMIT
    source_id = _create(client, headers, name)

    _clone_and_check(client, headers, fresh, source_id, name)


@pytest.mark.regression
def test_a_full_length_name_written_to_the_row_still_clones(client, headers, fresh):
    """A name no API path wrote (a direct write at the column's limit)."""
    source_id = _create(client, headers, _name_of_length(20))
    name = "y" * (LIMIT - 12) + uuid.uuid4().hex[:12]

    def write(session):
        session.get(Experiment, uuid.UUID(source_id)).name = name

    fresh(write)

    _clone_and_check(client, headers, fresh, source_id, name)
