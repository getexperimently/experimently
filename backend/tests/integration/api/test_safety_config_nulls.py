"""A flag's safety config refuses a null field, and a stored null metrics reads (#954).

``POST /api/v1/safety/feature-flags/{id}/config`` used to accept ``null`` for
``enabled``, ``metrics`` and ``rollback_percentage``. ``metrics: null`` was
stored as a JSON ``null`` (the column is NOT NULL, but a JSON null is a value),
the response then failed its own model (500), and from then on every
``GET .../config`` and ``GET .../check`` for the flag answered 500, for every
role, while the safety monitor logged an error and skipped the flag. A null
``enabled`` or ``rollback_percentage`` reached a NOT NULL column (500).

Now an explicit null answers 422 and nothing is written; a field left out
still keeps its stored value, and on create takes the column default (a
create that leaves ``metrics`` out used to store a JSON null too). A row that
already holds a JSON null ``metrics`` -- written by an earlier version --
reads back with ``metrics: {}`` (no thresholds) and the monitor checks it.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.core.safety_scheduler import SafetyScheduler
from backend.app.main import app
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.safety import FeatureFlagSafetyConfig
from backend.app.services.safety_service import SafetyService

pytestmark = [pytest.mark.integration, pytest.mark.regression]

PREFIX = "c954-"
SCHEMA = "test_experimentation"
SAFETY = "/api/v1/safety/feature-flags"

STORED_METRICS = {
    "error_rate": {
        "warning_threshold": 0.02,
        "critical_threshold": 0.05,
        "comparison_type": "greater_than",
    }
}


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _remove_what_the_test_created(db_session):
    yield
    db_session.rollback()
    flag_ids = [
        row.id
        for row in db_session.query(FeatureFlag.id).filter(
            FeatureFlag.key.like(f"{PREFIX}%")
        )
    ]
    if flag_ids:
        db_session.query(FeatureFlagSafetyConfig).filter(
            FeatureFlagSafetyConfig.feature_flag_id.in_(flag_ids)
        ).delete(synchronize_session=False)
        db_session.query(FeatureFlag).filter(FeatureFlag.id.in_(flag_ids)).delete(
            synchronize_session=False
        )
    db_session.commit()


@pytest.fixture
def session_factory(db_session):
    # autoflush=False, as backend.app.db.session.SessionLocal is configured.
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)

    def make():
        session = factory()
        session.execute(text(f"SET search_path TO {SCHEMA}"))
        return session

    return make


def _no_raise(role_client: TestClient) -> TestClient:
    """A client acting as ``role_client``'s user (the role fixtures install
    their overrides on the app) that answers a server error with 500 instead
    of raising it into the test."""
    assert role_client.app is app
    return TestClient(app, raise_server_exceptions=False)


def _flag(db_session) -> FeatureFlag:
    row = FeatureFlag(
        key=f"{PREFIX}{uuid.uuid4().hex[:10]}",
        name="c954 nulls",
        status=FeatureFlagStatus.ACTIVE,
        rollout_percentage=50,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _store_config(db_session, flag, metrics=STORED_METRICS) -> None:
    db_session.add(
        FeatureFlagSafetyConfig(
            feature_flag_id=flag.id,
            enabled=True,
            metrics=metrics,
            rollback_percentage=5,
        )
    )
    db_session.commit()


def _store_null_metrics(db_session, flag) -> None:
    """The row an earlier version wrote for ``{"metrics": null}``."""
    _store_config(db_session, flag, metrics=None)
    stored = db_session.execute(
        text(
            f"SELECT jsonb_typeof(metrics) FROM {SCHEMA}.feature_flag_safety_configs "
            "WHERE feature_flag_id = :id"
        ),
        {"id": flag.id},
    ).scalar()
    assert stored == "null"  # a JSON null, which the NOT NULL column accepts


def _null_refusal(response) -> tuple:
    (error,) = response.json()["detail"]
    assert error["type"] == "null_not_allowed", error
    return error["loc"], error["msg"]


def _stored(db_session, flag) -> list:
    db_session.expire_all()
    return [
        (row.enabled, row.metrics, row.rollback_percentage)
        for row in db_session.query(FeatureFlagSafetyConfig).filter(
            FeatureFlagSafetyConfig.feature_flag_id == flag.id
        )
    ]


# ---------------------------------------------------------------------------
# The request refuses an explicit null
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["enabled", "metrics", "rollback_percentage"])
def test_null_is_refused_when_creating_and_nothing_is_written(
    admin_client, db_session, field
):
    flag = _flag(db_session)

    response = _no_raise(admin_client).post(
        f"{SAFETY}/{flag.id}/config", json={field: None}
    )

    assert response.status_code == 422, response.text
    assert _null_refusal(response) == (["body", field], f"{field} cannot be null")
    assert _stored(db_session, flag) == []


@pytest.mark.parametrize("field", ["enabled", "rollback_percentage"])
def test_null_is_refused_on_a_create_that_sends_metrics(
    admin_client, db_session, field
):
    """This create used to answer 200, taking the null as the field's default."""
    flag = _flag(db_session)

    response = _no_raise(admin_client).post(
        f"{SAFETY}/{flag.id}/config", json={"metrics": STORED_METRICS, field: None}
    )

    assert response.status_code == 422, response.text
    assert _null_refusal(response) == (["body", field], f"{field} cannot be null")
    assert _stored(db_session, flag) == []


@pytest.mark.parametrize("field", ["enabled", "metrics", "rollback_percentage"])
def test_null_is_refused_when_updating_and_the_stored_config_is_kept(
    admin_client, db_session, field
):
    flag = _flag(db_session)
    _store_config(db_session, flag)

    response = _no_raise(admin_client).post(
        f"{SAFETY}/{flag.id}/config", json={field: None}
    )

    assert response.status_code == 422, response.text
    assert _null_refusal(response) == (["body", field], f"{field} cannot be null")
    assert _stored(db_session, flag) == [(True, STORED_METRICS, 5)]


def test_a_field_left_out_keeps_its_stored_value(admin_client, db_session):
    flag = _flag(db_session)
    _store_config(db_session, flag)

    response = admin_client.post(f"{SAFETY}/{flag.id}/config", json={"enabled": False})

    assert response.status_code == 200, response.text
    assert response.json()["metrics"] == STORED_METRICS
    assert _stored(db_session, flag) == [(False, STORED_METRICS, 5)]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"enabled": False}, (False, {}, 0)),
        ({"rollback_percentage": 5}, (True, {}, 5)),
    ],
)
def test_a_create_that_leaves_metrics_out_stores_no_thresholds(
    admin_client, db_session, body, expected
):
    """The defaults, ``metrics`` ``{}`` included: not a JSON null that breaks
    every read."""
    flag = _flag(db_session)

    response = _no_raise(admin_client).post(f"{SAFETY}/{flag.id}/config", json=body)

    assert response.status_code == 200, response.text
    enabled, metrics, rollback_percentage = expected
    assert response.json()["enabled"] is enabled
    assert response.json()["metrics"] == metrics
    assert response.json()["rollback_percentage"] == rollback_percentage
    assert _stored(db_session, flag) == [expected]


# ---------------------------------------------------------------------------
# A stored null metrics reads back as no thresholds
# ---------------------------------------------------------------------------


def test_a_stored_null_metrics_reads_back_for_a_viewer(viewer_client, db_session):
    flag = _flag(db_session)
    _store_null_metrics(db_session, flag)
    client = _no_raise(viewer_client)

    config = client.get(f"{SAFETY}/{flag.id}/config")
    assert config.status_code == 200, config.text
    assert config.json()["metrics"] == {}
    assert config.json()["enabled"] is True
    assert config.json()["rollback_percentage"] == 5

    check = client.get(f"{SAFETY}/{flag.id}/check")
    assert check.status_code == 200, check.text
    assert check.json()["is_healthy"] is True
    assert check.json()["metrics"] == []


def test_a_stored_null_metrics_can_be_replaced(admin_client, db_session):
    flag = _flag(db_session)
    _store_null_metrics(db_session, flag)

    response = _no_raise(admin_client).post(
        f"{SAFETY}/{flag.id}/config", json={"metrics": STORED_METRICS}
    )

    assert response.status_code == 200, response.text
    assert _stored(db_session, flag) == [(True, STORED_METRICS, 5)]


def test_the_safety_monitor_checks_a_flag_whose_stored_metrics_are_null(
    db_session, session_factory
):
    """Checked, not skipped: the monitor used to fail reading the config and
    move on to the next flag. The checks it runs are recorded rather than read
    from its log, because other tests reconfigure logging."""
    flag = _flag(db_session)
    _store_null_metrics(db_session, flag)

    checked = {}
    real_check = SafetyService.check_feature_flag_safety

    async def recording_check(self, feature_flag_id):
        checked[feature_flag_id] = await real_check(self, feature_flag_id)
        return checked[feature_flag_id]

    scheduler = SafetyScheduler(interval_minutes=1)
    with (
        patch("backend.app.core.safety_scheduler.SessionLocal", session_factory),
        patch.object(scheduler, "_notification_service", MagicMock()),
        patch.object(SafetyService, "check_feature_flag_safety", recording_check),
    ):
        asyncio.run(scheduler.check_feature_flags_safety())

    assert flag.id in checked
    assert checked[flag.id].is_healthy is True
    assert checked[flag.id].metrics == []
