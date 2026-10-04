"""Each experiment stores its correction method and confidence level (#580), end to end.

Through the API against a real database:

* **A4** a new experiment stores Benjamini-Hochberg at 0.95, as the plain
  strings ``benjamini_hochberg`` and 0.95 (read back with SQL, not through the
  ORM); a creator's own choice is stored and returned; a draft that grows from
  two variants to three keeps its stored method; a clone of an ACTIVE
  experiment is a DRAFT with the source's ``none`` at 0.90.
* **A5** values outside the contract are refused with 422 on create and on
  update, null included, and the database's check constraints refuse them too.
* **The lock** once an experiment leaves draft nobody changes either setting,
  a superuser included, and re-sending the stored value is refused too; a
  draft is changed freely.
* ``/results/{id}/sample-size`` plans with the stored settings unless the
  request names its own.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.regression]

EXPERIMENTS = "/api/v1/experiments"
PREFIX = "corr580"
SCHEMA = "test_experimentation"


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
            session.execute(text(f"SET search_path TO {SCHEMA}"))
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
        session.execute(text(f"SET search_path TO {SCHEMA}"))
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


def _user(db_session, *, superuser: bool) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{PREFIX}_{'su' if superuser else 'dev'}_{suffix}",
        email=f"{PREFIX}_{suffix}@corr.test",
        full_name="Correction Settings",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=superuser,
        role=UserRole.ADMIN if superuser else UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def developer(db_session):
    return {
        "Authorization": f"Bearer {create_local_access_token(_user(db_session, superuser=False))}"
    }


@pytest.fixture
def superuser(db_session):
    return {
        "Authorization": f"Bearer {create_local_access_token(_user(db_session, superuser=True))}"
    }


def _variants(count: int) -> list:
    share = 100 // count
    return [
        {
            "name": "Control" if i == 0 else f"Treatment {i}",
            "is_control": i == 0,
            "traffic_allocation": share + (100 - share * count if i == 0 else 0),
        }
        for i in range(count)
    ]


def _body(variants: int = 2, **extra) -> dict:
    return {
        "name": f"{PREFIX} {uuid.uuid4().hex[:8]}",
        "description": "Stored correction settings",
        "hypothesis": "Results are judged as the experiment says",
        "experiment_type": "a_b",
        "variants": _variants(variants),
        "metrics": [
            {
                "name": "Conversion Rate",
                "event_name": "purchase",
                "metric_type": "conversion",
                "is_primary": True,
            }
        ],
        **extra,
    }


def _create(client, headers, **extra) -> dict:
    response = client.post(f"{EXPERIMENTS}/", json=_body(**extra), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _raw(test_db, experiment_id: str) -> tuple:
    """The two columns as the database holds them, read with SQL."""
    with test_db.connect() as conn:
        row = conn.execute(
            text(
                f"SELECT correction_method, confidence_level FROM {SCHEMA}.experiments "
                "WHERE id = :id"
            ),
            {"id": experiment_id},
        ).one()
    return tuple(row)


def _set_status(fresh, experiment_id: str, status: ExperimentStatus) -> None:
    def work(session):
        session.get(Experiment, uuid.UUID(experiment_id)).status = status

    fresh(work)


# ---------------------------------------------------------------------------
# A4: defaults, a creator's choice, the draft change, the clone
# ---------------------------------------------------------------------------
def test_a_new_experiment_stores_benjamini_hochberg_at_095(client, developer, test_db):
    created = _create(client, developer)
    assert (created["correction_method"], created["confidence_level"]) == (
        "benjamini_hochberg",
        0.95,
    )
    assert _raw(test_db, created["id"]) == ("benjamini_hochberg", 0.95)

    fetched = client.get(f"{EXPERIMENTS}/{created['id']}", headers=developer)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["correction_method"] == "benjamini_hochberg"
    assert fetched.json()["confidence_level"] == 0.95


def test_a_creators_choice_is_stored_and_returned(client, developer, test_db):
    created = _create(
        client, developer, correction_method="none", confidence_level=0.90
    )
    assert (created["correction_method"], created["confidence_level"]) == ("none", 0.9)
    assert _raw(test_db, created["id"]) == ("none", 0.9)


def test_a_draft_that_grows_to_three_variants_keeps_its_stored_method(
    client, developer, test_db
):
    created = _create(client, developer)
    response = client.put(
        f"{EXPERIMENTS}/{created['id']}",
        json={"variants": _variants(3)},
        headers=developer,
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["variants"]) == 3
    assert response.json()["correction_method"] == "benjamini_hochberg"
    assert _raw(test_db, created["id"]) == ("benjamini_hochberg", 0.95)


def test_a_draft_is_changed_freely(client, developer, test_db):
    created = _create(client, developer)
    response = client.put(
        f"{EXPERIMENTS}/{created['id']}",
        json={"correction_method": "bonferroni", "confidence_level": 0.9},
        headers=developer,
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["correction_method"],
        response.json()["confidence_level"],
    ) == (
        "bonferroni",
        0.9,
    )
    assert _raw(test_db, created["id"]) == ("bonferroni", 0.9)


def test_a_clone_of_an_active_experiment_is_a_draft_with_the_sources_settings(
    client, superuser, fresh, test_db
):
    source = _create(client, superuser, correction_method="none", confidence_level=0.90)
    _set_status(fresh, source["id"], ExperimentStatus.ACTIVE)

    response = client.post(f"{EXPERIMENTS}/{source['id']}/clone", headers=superuser)
    assert response.status_code == 201, response.text
    clone = response.json()
    assert clone["status"] == "draft"
    assert (clone["correction_method"], clone["confidence_level"]) == ("none", 0.9)
    assert _raw(test_db, clone["id"]) == ("none", 0.9)


# ---------------------------------------------------------------------------
# A5: refusals
# ---------------------------------------------------------------------------
REFUSED = [
    {"confidence_level": 0.79},
    {"confidence_level": 0.995},
    {"confidence_level": None},
    {"correction_method": "holm"},
    {"correction_method": "benjamini-hochberg"},
    {"correction_method": None},
]


@pytest.mark.parametrize("values", REFUSED, ids=[str(v) for v in REFUSED])
def test_create_refuses_a_value_outside_the_contract(client, developer, values):
    response = client.post(f"{EXPERIMENTS}/", json=_body(**values), headers=developer)
    assert response.status_code == 422, response.text
    (field,) = values
    assert any(field in error["loc"] for error in response.json()["detail"])


@pytest.mark.parametrize("values", REFUSED, ids=[str(v) for v in REFUSED])
def test_update_refuses_a_value_outside_the_contract(
    client, developer, test_db, values
):
    created = _create(client, developer)
    response = client.put(
        f"{EXPERIMENTS}/{created['id']}", json=values, headers=developer
    )
    assert response.status_code == 422, response.text
    assert _raw(test_db, created["id"]) == ("benjamini_hochberg", 0.95)


@pytest.mark.parametrize(
    "assignment, check",
    [
        ("correction_method = 'holm'", "ck_experiments_correction_method"),
        ("confidence_level = 0.5", "ck_experiments_confidence_level"),
        ("confidence_level = 0.995", "ck_experiments_confidence_level"),
    ],
)
def test_the_database_refuses_a_value_outside_the_contract(
    client, developer, test_db, assignment, check
):
    created = _create(client, developer)
    with pytest.raises(IntegrityError, match=check):
        with test_db.begin() as conn:
            conn.execute(
                text(f"UPDATE {SCHEMA}.experiments SET {assignment} WHERE id = :id"),
                {"id": created["id"]},
            )


# ---------------------------------------------------------------------------
# The lock: every role, once the experiment leaves draft
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", [ExperimentStatus.ACTIVE, ExperimentStatus.PAUSED])
@pytest.mark.parametrize(
    "values",
    [
        {"correction_method": "none"},
        {"confidence_level": 0.9},
        # Re-sending the stored value is refused too: the lock is on presence.
        {"correction_method": "benjamini_hochberg"},
    ],
    ids=["method", "level", "same-value"],
)
def test_a_superuser_cannot_change_the_settings_once_out_of_draft(
    client, superuser, fresh, test_db, status, values
):
    created = _create(client, superuser)
    _set_status(fresh, created["id"], status)

    response = client.put(
        f"{EXPERIMENTS}/{created['id']}", json=values, headers=superuser
    )

    assert response.status_code == 400, response.text
    (field,) = values
    assert response.json()["detail"] == (
        f"Cannot update {field} for experiments in {status.value} status"
    )
    assert _raw(test_db, created["id"]) == ("benjamini_hochberg", 0.95)


def test_a_developer_cannot_change_them_on_an_active_experiment_either(
    client, developer, fresh, test_db
):
    created = _create(client, developer)
    _set_status(fresh, created["id"], ExperimentStatus.ACTIVE)

    response = client.put(
        f"{EXPERIMENTS}/{created['id']}",
        json={"correction_method": "none"},
        headers=developer,
    )

    assert response.status_code == 400, response.text
    assert _raw(test_db, created["id"]) == ("benjamini_hochberg", 0.95)


def test_a_superuser_can_still_change_other_fields_of_an_active_experiment(
    client, superuser, fresh, test_db
):
    """The lock is on these two fields, not a new refusal of every update."""
    created = _create(client, superuser)
    _set_status(fresh, created["id"], ExperimentStatus.ACTIVE)

    response = client.put(
        f"{EXPERIMENTS}/{created['id']}",
        json={"description": "edited while running"},
        headers=superuser,
    )

    assert response.status_code == 200, response.text
    assert response.json()["correction_method"] == "benjamini_hochberg"


# ---------------------------------------------------------------------------
# The sample-size plan follows the stored settings
# ---------------------------------------------------------------------------
def test_the_sample_size_plan_uses_the_stored_settings(client, developer, fresh):
    created = _create(
        client,
        developer,
        variants=3,
        correction_method="bonferroni",
        confidence_level=0.90,
    )
    path = f"/api/v1/results/{created['id']}/sample-size"

    stored = client.get(
        path, params={"baseline_conversion_rate": 0.1}, headers=developer
    )
    assert stored.status_code == 200, stored.text
    body = stored.json()
    assert (body["correction_method"], body["confidence_level"]) == ("bonferroni", 0.9)
    assert body["comparisons"] == 2
    assert body["alpha"] == pytest.approx(0.1 / 2)

    named = client.get(
        path,
        params={"baseline_conversion_rate": 0.1, "correction_method": "none"},
        headers=developer,
    )
    assert named.status_code == 200, named.text
    assert named.json()["correction_method"] == "none"
    assert named.json()["alpha"] == pytest.approx(0.1)
