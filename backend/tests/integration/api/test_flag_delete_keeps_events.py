"""#855: deleting a feature flag keeps its events.

``FeatureFlag.events`` carried ``cascade="all, delete-orphan"``, so
``db.delete(flag)`` made the ORM load every event tagged with the flag and
DELETE it before the database's own rule was reached. The
``events.feature_flag_id`` foreign key has always been ``ON DELETE SET NULL``
(in the model and in every migration that creates the table), so the intent
was to keep the events and untag them. The relationship now uses
``passive_deletes=True`` and leaves that to Postgres.

The FK action is Postgres behaviour, so this runs against the real database.
The flag is created through the API by a non-superuser DEVELOPER (D11), and
deleted through the API.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.app.main import app
from backend.app.models.event import Event
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.feature_flag import FeatureFlag
from backend.tests.integration.conftest import make_client_for_user

BASE = "/api/v1/feature-flags"
PREFIX = "ff855-"


@pytest.fixture(autouse=True)
def _clean_up(db_session):
    """Remove what the test created, and the overrides it installed."""
    yield
    app.dependency_overrides.clear()
    db_session.rollback()
    db_session.query(Event).filter(Event.user_id.like(f"{PREFIX}%")).delete(
        synchronize_session=False
    )
    db_session.query(Experiment).filter(Experiment.name.like(f"{PREFIX}%")).delete(
        synchronize_session=False
    )
    db_session.query(FeatureFlag).filter(FeatureFlag.key.like(f"{PREFIX}%")).delete(
        synchronize_session=False
    )
    db_session.commit()


def _snapshot(event: Event) -> dict:
    return {
        "experiment_id": event.experiment_id,
        "variant_id": event.variant_id,
        "event_type": event.event_type,
        "event_name": event.event_name,
        "user_id": event.user_id,
        "value": event.value,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


@pytest.mark.integration
@pytest.mark.requires_db
def test_events_flag_foreign_key_is_set_null(db_session):
    """The fix leaves the untagging to this rule; with CASCADE events would vanish."""
    action = db_session.execute(
        text(
            "SELECT c.confdeltype FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY (c.conkey) "
            "WHERE c.contype = 'f' AND t.relname = 'events' "
            "AND n.nspname = current_schema() AND a.attname = 'feature_flag_id'"
        )
    ).scalar_one()
    assert action == "n", (
        f"events.feature_flag_id must be ON DELETE SET NULL, got {action!r}"
    )


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.regression
def test_deleting_a_flag_keeps_its_events_untagged(db_session, developer_user):
    client = make_client_for_user(db_session, developer_user)
    key = f"{PREFIX}{uuid.uuid4().hex[:8]}"

    created = client.post(
        f"{BASE}/", json={"key": key, "name": "ff855", "is_active": False}
    )
    assert created.status_code == 201, created.text
    flag_id = uuid.UUID(created.json()["id"])

    experiment = Experiment(
        name=f"{PREFIX}experiment",
        status=ExperimentStatus.DRAFT,
        owner_id=developer_user.id,
    )
    db_session.add(experiment)
    db_session.commit()

    now = datetime.now(timezone.utc).isoformat()
    tagged = Event(
        event_type="purchase",
        event_name="purchase",
        user_id=f"{PREFIX}tagged",
        value=9.5,
        feature_flag_id=flag_id,
        created_at=now,
    )
    # Tagged with both an experiment and the flag: the experiment tag must stay.
    both = Event(
        event_type="conversion",
        event_name="signup",
        user_id=f"{PREFIX}both",
        value=1.0,
        feature_flag_id=flag_id,
        experiment_id=experiment.id,
        created_at=now,
    )
    untagged = Event(
        event_type="purchase",
        event_name="purchase",
        user_id=f"{PREFIX}untagged",
        value=3.0,
        created_at=now,
    )
    db_session.add_all([tagged, both, untagged])
    db_session.commit()
    ids = [tagged.id, both.id, untagged.id]
    before = {
        e.id: _snapshot(e)
        for e in db_session.query(Event).filter(Event.id.in_(ids)).all()
    }
    assert len(before) == 3

    deleted = client.delete(f"{BASE}/{flag_id}")
    assert deleted.status_code == 204, deleted.text

    db_session.expire_all()
    assert db_session.get(FeatureFlag, flag_id) is None, "the flag must be removed"

    after = {e.id: e for e in db_session.query(Event).filter(Event.id.in_(ids)).all()}
    assert set(after) == set(ids), (
        f"deleting the flag removed {3 - len(after)} of its events; "
        "all three must remain"
    )
    for event_id in ids:
        assert after[event_id].feature_flag_id is None
        assert _snapshot(after[event_id]) == before[event_id], (
            "only feature_flag_id may change on a kept event"
        )
    assert after[both.id].experiment_id == experiment.id
