"""The StreamPulse seed's holdout step, for every state of its holdout (#445).

``seed_global_holdout`` goes through ``GlobalHoldoutService``, never changes the
percentage of a holdout that has been active, never restarts an ended one, and
writes no ``holdout_population`` row (membership comes only from real
``/tracking/assign`` calls).  Each case returns normally, so the seed carries on
and exits 0.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update

from backend.app.models.global_holdout import LEGACY_HOLDOUT_SALT, GlobalHoldout
from backend.app.models.holdout_population import HoldoutPopulation
from backend.scripts import seed_streampulse

pytestmark = [pytest.mark.integration]


@pytest.fixture
def seed_name(db_session, monkeypatch):
    """A unique holdout name for the seed, with every active holdout parked."""
    name = f"streampulse-holdout-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(seed_streampulse, "HOLDOUT_NAME", name)
    parked = [
        row.id
        for row in db_session.query(GlobalHoldout).filter(GlobalHoldout.is_active)
    ]
    db_session.execute(
        update(GlobalHoldout)
        .where(GlobalHoldout.id.in_(parked))
        .values(is_active=False)
    )
    db_session.commit()
    yield name
    db_session.rollback()
    db_session.query(GlobalHoldout).filter(GlobalHoldout.name == name).delete()
    db_session.execute(
        update(GlobalHoldout).where(GlobalHoldout.id.in_(parked)).values(is_active=True)
    )
    db_session.commit()


def _row(db_session, name) -> GlobalHoldout:
    db_session.expire_all()
    return db_session.query(GlobalHoldout).filter(GlobalHoldout.name == name).one()


def _population_rows(db_session, holdout_id) -> int:
    return (
        db_session.query(HoldoutPopulation)
        .filter(HoldoutPopulation.holdout_id == holdout_id)
        .count()
    )


@pytest.mark.regression
def test_twice_from_absent_creates_once_and_changes_nothing_after(
    db_session, admin_user, seed_name, capsys
):
    first = seed_streampulse.seed_global_holdout(db_session, admin_user)
    created = _row(db_session, seed_name)
    assert first.id == created.id
    assert created.is_active is True
    assert created.is_measurable
    assert created.hash_salt == seed_streampulse.DEMO_HOLDOUT_SALT
    assert created.holdout_percentage == seed_streampulse.HOLDOUT_PERCENTAGE
    stamped = created.activated_at

    seed_streampulse.seed_global_holdout(db_session, admin_user)

    again = _row(db_session, seed_name)
    assert again.activated_at == stamped
    assert again.holdout_percentage == seed_streampulse.HOLDOUT_PERCENTAGE
    assert again.deactivated_at is None
    assert _population_rows(db_session, again.id) == 0
    assert "already active" in capsys.readouterr().out


def test_a_legacy_active_holdout_is_reused_with_a_note(
    db_session, admin_user, seed_name, capsys
):
    db_session.add(
        GlobalHoldout(
            name=seed_name,
            holdout_percentage=5,
            is_active=True,
            hash_salt=LEGACY_HOLDOUT_SALT,
        )
    )
    db_session.commit()

    seed_streampulse.seed_global_holdout(db_session, admin_user)

    row = _row(db_session, seed_name)
    assert row.is_active is True
    assert row.activated_at is None
    assert row.holdout_percentage == 5
    out = capsys.readouterr().out
    assert "cannot be measured" in out and "--reset" in out


def test_an_ended_holdout_is_not_restarted(db_session, admin_user, seed_name, capsys):
    seed_streampulse.seed_global_holdout(db_session, admin_user)
    row = _row(db_session, seed_name)
    row.is_active = False
    row.deactivated_at = row.activated_at
    db_session.commit()

    returned = seed_streampulse.seed_global_holdout(db_session, admin_user)

    assert returned.id == row.id
    after = _row(db_session, seed_name)
    assert after.is_active is False
    assert "has ended and cannot restart" in capsys.readouterr().out


def test_the_demo_salt_keeps_the_documented_ids_where_the_demo_says():
    """``sp-holdout-15`` is held out and no preset device is (README step 8,
    ``devices.ts``), under the salt the seed gives its holdout."""
    import re
    from pathlib import Path

    from backend.app.services.global_holdout_service import holdout_bucket

    salt = seed_streampulse.DEMO_HOLDOUT_SALT
    pct = seed_streampulse.HOLDOUT_PERCENTAGE
    root = Path(__file__).resolve().parents[4]
    presets = re.findall(
        r"device_id: '([^']+)'",
        (root / "demo/streampulse/src/lib/devices.ts").read_text(encoding="utf-8"),
    )
    assert len(presets) >= 5, presets
    assert [p for p in presets if holdout_bucket(p, salt) < pct] == []
    assert holdout_bucket("sp-holdout-15", salt) < pct
    readme = (root / "demo/streampulse/README.md").read_text(encoding="utf-8")
    assert "`sp-holdout-15`" in readme
