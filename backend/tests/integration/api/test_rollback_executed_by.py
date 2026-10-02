"""The rollback record names the administrator who ran a manual rollback (#629).

``SafetyRollbackRecord.executed_by_user_id`` is filled from the caller of
``POST /safety/feature-flags/{id}/rollback``. The safety monitor's automatic
rollback has no caller, so its record leaves the column NULL -- even when the
flag has an owner, who did not run it.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.metrics.metric import ErrorLog, MetricType, RawMetric
from backend.app.models.safety import (
    FeatureFlagSafetyConfig,
    SafetyRollbackRecord,
    SafetySettings,
)
from backend.tests.integration.conftest import make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.regression]

PREFIX = "r629-"
SCHEMA = "test_experimentation"


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


def _flag(db_session, owner_id=None) -> FeatureFlag:
    row = FeatureFlag(
        key=f"{PREFIX}{uuid.uuid4().hex[:10]}",
        name="r629",
        status=FeatureFlagStatus.ACTIVE,
        rollout_percentage=50,
        owner_id=owner_id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _records(db_session, flag):
    db_session.expire_all()
    return (
        db_session.query(SafetyRollbackRecord)
        .filter(SafetyRollbackRecord.feature_flag_id == flag.id)
        .all()
    )


def test_a_manual_rollback_records_the_administrator_who_ran_it(db_session, admin_user):
    assert admin_user.is_superuser
    flag = _flag(db_session)
    client = make_client_for_user(db_session, admin_user)

    resp = client.post(
        f"/api/v1/safety/feature-flags/{flag.id}/rollback",
        params={"percentage": 5, "reason": "r629"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True, resp.text

    (record,) = _records(db_session, flag)
    assert record.trigger_type == "manual"
    assert record.executed_by_user_id == admin_user.id


@pytest.mark.usefixtures("automatic_rollbacks")
def test_an_automatic_rollback_records_no_administrator(
    db_session, session_factory, admin_user
):
    from backend.app.core.safety_scheduler import SafetyScheduler

    # The flag has an owner; the monitor's rollback is still not theirs.
    flag = _flag(db_session, owner_id=admin_user.id)
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
            rollback_percentage=5,
        )
    )
    # 100 evaluations and 20 errors in the window: a 20% error rate.
    for _ in range(100):
        db_session.add(
            RawMetric(
                feature_flag_id=flag.id, metric_type=MetricType.FLAG_EVALUATION.value
            )
        )
    for i in range(20):
        db_session.add(
            ErrorLog(feature_flag_id=flag.id, error_type="crash", message=f"r629 {i}")
        )
    db_session.commit()

    scheduler = SafetyScheduler(interval_minutes=1)
    with (
        patch("backend.app.core.safety_scheduler.SessionLocal", session_factory),
        patch.object(scheduler, "_notification_service", MagicMock()),
    ):
        asyncio.run(scheduler.check_feature_flags_safety())

    records = _records(db_session, flag)
    assert len(records) == 1, "the monitor did not roll the flag back"
    (record,) = records
    assert record.trigger_type == "automatic"
    assert record.executed_by_user_id is None
