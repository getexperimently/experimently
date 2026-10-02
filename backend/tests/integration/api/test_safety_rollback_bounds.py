"""Rollback percentages outside 0-100 are refused; a stored one is clamped (#629).

The API now refuses a ``rollback_percentage`` (safety config) or a
``?percentage=`` (manual rollback) outside 0-100 with 422. The bound sits on
the request schemas and the route parameter only, never on the response, so a
row stored before the bound still reads back (GET config 200) and the safety
monitor clamps it to 0-100 when it uses it, with one warning naming the flag.

Clamping and skipping can look alike: a stored 150 clamped to 100 on a flag at
50 changes nothing, exactly as skipping the flag would. The stored -5 case is
the one that tells them apart: clamped, the unhealthy flag is rolled back to
0%; skipped (or used as is, which the flag's own check constraint refuses), it
stays at 50%.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.core.safety_scheduler import SafetyScheduler
from backend.app.main import app
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.metrics.metric import ErrorLog, MetricType, RawMetric
from backend.app.models.safety import (
    FeatureFlagSafetyConfig,
    SafetyRollbackRecord,
    SafetySettings,
)
from backend.app.schemas.safety import (
    FeatureFlagSafetyConfigCreate,
    FeatureFlagSafetyConfigUpdate,
)

pytestmark = [pytest.mark.integration, pytest.mark.regression]

PREFIX = "c629b-"
SCHEMA = "test_experimentation"
SAFETY = "/api/v1/safety/feature-flags"
CLAMP_MESSAGE = "is outside 0-100"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_factory(db_session):
    # autoflush=False, as backend.app.db.session.SessionLocal is configured.
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)

    def make():
        session = factory()
        session.execute(text(f"SET search_path TO {SCHEMA}"))
        return session

    return make


@pytest.fixture
def automatic_rollbacks(db_session):
    """Global automatic rollbacks on for the test, restored afterwards."""
    row = db_session.query(SafetySettings).first()
    created = row is None
    if created:
        row = SafetySettings(enable_automatic_rollbacks=True, default_metrics=None)
        db_session.add(row)
        previous = None
    else:
        previous = row.enable_automatic_rollbacks
        row.enable_automatic_rollbacks = True
    db_session.commit()
    yield
    db_session.rollback()
    row = db_session.query(SafetySettings).first()
    if created:
        db_session.delete(row)
    else:
        row.enable_automatic_rollbacks = previous
    db_session.commit()


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
        for model in (
            SafetyRollbackRecord,
            FeatureFlagSafetyConfig,
            ErrorLog,
            RawMetric,
        ):
            db_session.query(model).filter(model.feature_flag_id.in_(flag_ids)).delete(
                synchronize_session=False
            )
        db_session.query(FeatureFlag).filter(FeatureFlag.id.in_(flag_ids)).delete(
            synchronize_session=False
        )
    db_session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flag(db_session, rollout_percentage: int = 50) -> FeatureFlag:
    row = FeatureFlag(
        key=f"{PREFIX}{uuid.uuid4().hex[:10]}",
        name="c629 bounds",
        status=FeatureFlagStatus.ACTIVE,
        rollout_percentage=rollout_percentage,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _store_config(db_session, flag, rollback_percentage: int) -> None:
    """Insert the config row directly: the API would refuse this value."""
    db_session.add(
        FeatureFlagSafetyConfig(
            feature_flag_id=flag.id,
            enabled=True,
            metrics={
                "error_rate": {
                    "critical_threshold": 0.05,
                    "comparison_type": "greater_than",
                }
            },
            rollback_percentage=rollback_percentage,
        )
    )
    db_session.commit()


def _make_unhealthy(db_session, flag) -> None:
    """100 evaluations and 20 errors in the window: a 20% error rate."""
    for _ in range(100):
        db_session.add(
            RawMetric(
                feature_flag_id=flag.id, metric_type=MetricType.FLAG_EVALUATION.value
            )
        )
    for i in range(20):
        db_session.add(
            ErrorLog(feature_flag_id=flag.id, error_type="crash", message=f"c629 {i}")
        )
    db_session.commit()


def _tick(session_factory) -> dict:
    scheduler = SafetyScheduler(interval_minutes=1)
    with (
        patch("backend.app.core.safety_scheduler.SessionLocal", session_factory),
        patch.object(scheduler, "_notification_service", MagicMock()),
    ):
        return asyncio.run(scheduler.check_feature_flags_safety())


def _percentage(session_factory, flag) -> int:
    session = session_factory()
    try:
        return (
            session.query(FeatureFlag.rollout_percentage)
            .filter(FeatureFlag.id == flag.id)
            .scalar()
        )
    finally:
        session.close()


def _clamp_warnings(caplog, flag) -> list:
    return [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING
        and CLAMP_MESSAGE in record.getMessage()
        and str(flag.id) in record.getMessage()
    ]


# ---------------------------------------------------------------------------
# A stored value outside 0-100 is clamped where it is used
# ---------------------------------------------------------------------------


def test_stored_negative_rollback_percentage_rolls_the_flag_back_to_zero(
    db_session, session_factory, automatic_rollbacks, caplog
):
    """Clamped, not skipped: -5 becomes 0 and the unhealthy flag goes to 0%."""
    flag = _flag(db_session, rollout_percentage=50)
    _store_config(db_session, flag, rollback_percentage=-5)
    _make_unhealthy(db_session, flag)

    with caplog.at_level(logging.WARNING):
        result = _tick(session_factory)

    assert result["items_failed"] == 0, result
    assert _percentage(session_factory, flag) == 0
    db_session.expire_all()
    stored = db_session.query(FeatureFlag).filter(FeatureFlag.id == flag.id).one()
    assert stored.status == FeatureFlagStatus.INACTIVE  # a rollback to 0 turns it off
    records = (
        db_session.query(SafetyRollbackRecord)
        .filter(SafetyRollbackRecord.feature_flag_id == flag.id)
        .all()
    )
    assert [(r.previous_percentage, r.target_percentage) for r in records] == [(50, 0)]
    assert len(_clamp_warnings(caplog, flag)) == 1


def test_stored_rollback_percentage_above_100_reads_back_and_does_not_fail_the_monitor(
    admin_client, db_session, session_factory, automatic_rollbacks, caplog
):
    flag = _flag(db_session, rollout_percentage=50)
    _store_config(db_session, flag, rollback_percentage=150)
    _make_unhealthy(db_session, flag)

    # A server error answers 500 here rather than raising into the test.
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"{SAFETY}/{flag.id}/config")
    assert response.status_code == 200, response.text
    assert response.json()["rollback_percentage"] == 150

    with caplog.at_level(logging.WARNING):
        result = _tick(session_factory)

    assert result["items_failed"] == 0, result
    # Clamped to 100, which is above the flag's 50%: nothing to roll back.
    assert _percentage(session_factory, flag) == 50
    assert len(_clamp_warnings(caplog, flag)) == 1


# ---------------------------------------------------------------------------
# The API refuses a value outside 0-100
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [150, -1, 101])
def test_config_create_and_update_schemas_refuse_out_of_range(value):
    with pytest.raises(ValidationError):
        FeatureFlagSafetyConfigCreate(rollback_percentage=value)
    with pytest.raises(ValidationError):
        FeatureFlagSafetyConfigUpdate(rollback_percentage=value)


@pytest.mark.parametrize("value", [0, 100])
def test_config_schemas_accept_the_edges(value):
    assert FeatureFlagSafetyConfigCreate(rollback_percentage=value)
    assert FeatureFlagSafetyConfigUpdate(rollback_percentage=value)


@pytest.mark.parametrize("value", [150, -1])
def test_config_route_refuses_out_of_range_when_creating(
    admin_client, db_session, value
):
    """No stored config yet: the POST would create one."""
    flag = _flag(db_session)

    response = admin_client.post(
        f"{SAFETY}/{flag.id}/config",
        json={"enabled": True, "metrics": {}, "rollback_percentage": value},
    )

    assert response.status_code == 422, response.text
    db_session.expire_all()
    assert (
        db_session.query(FeatureFlagSafetyConfig)
        .filter(FeatureFlagSafetyConfig.feature_flag_id == flag.id)
        .count()
        == 0
    )


@pytest.mark.parametrize("value", [150, -1])
def test_config_route_refuses_out_of_range_when_updating(
    admin_client, db_session, value
):
    flag = _flag(db_session)
    _store_config(db_session, flag, rollback_percentage=5)

    response = admin_client.post(
        f"{SAFETY}/{flag.id}/config", json={"rollback_percentage": value}
    )

    assert response.status_code == 422, response.text
    db_session.expire_all()
    stored = (
        db_session.query(FeatureFlagSafetyConfig.rollback_percentage)
        .filter(FeatureFlagSafetyConfig.feature_flag_id == flag.id)
        .scalar()
    )
    assert stored == 5


@pytest.mark.parametrize("value", [150, -1])
def test_rollback_route_refuses_out_of_range_percentage(
    admin_client, db_session, value
):
    flag = _flag(db_session, rollout_percentage=50)

    response = admin_client.post(
        f"{SAFETY}/{flag.id}/rollback", params={"percentage": value}
    )

    assert response.status_code == 422, response.text
    db_session.expire_all()
    assert db_session.get(FeatureFlag, flag.id).rollout_percentage == 50


@pytest.mark.parametrize("value", [0, 100])
def test_rollback_route_accepts_the_edges(admin_client, db_session, value):
    flag = _flag(db_session, rollout_percentage=50)

    response = admin_client.post(
        f"{SAFETY}/{flag.id}/rollback", params={"percentage": value}
    )

    assert response.status_code == 200, response.text
