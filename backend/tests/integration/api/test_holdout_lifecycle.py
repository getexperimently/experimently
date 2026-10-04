"""The global holdout lifecycle on ``POST``/``PUT /api/v1/holdout`` (#445).

What a holdout's measurement depends on, through the HTTP routes and the real
database:

* activation, on POST and PUT alike, stamps ``activated_at`` and deactivates
  the *other* active holdout, stamping its ``deactivated_at`` (A9);
* activating the holdout that is already active changes nothing, legacy salt
  or not (EM condition 4);
* a legacy-salt holdout is never stamped, so it never becomes measurable
  (PE C1);
* the percentage is fixed once the holdout has been active, the same value is
  still accepted, and an ended holdout cannot restart (A10, 422);
* two activations racing each other: the second answers 409;
* a holdout created through the ORM gets its own salt (EM condition 5, PE C3).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from backend.app.models.global_holdout import LEGACY_HOLDOUT_SALT, GlobalHoldout
from backend.app.services import global_holdout_service
from backend.app.services.global_holdout_service import (
    ENDED_DETAIL,
    PERCENTAGE_LOCKED_DETAIL,
    GlobalHoldoutService,
)

pytestmark = [pytest.mark.integration]

UNCHANGED_FIELDS = ("is_active", "activated_at", "deactivated_at", "hash_salt")


@pytest.fixture
def holdout_slot(db_session):
    """Park any active holdout for the test, and delete the ones it creates.

    Parked with a plain UPDATE, so nothing stamps them as ended; restored the
    same way.
    """
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
    created: list[str] = []
    yield created
    db_session.rollback()
    db_session.query(GlobalHoldout).filter(GlobalHoldout.name.in_(created)).delete(
        synchronize_session=False
    )
    db_session.execute(
        update(GlobalHoldout).where(GlobalHoldout.id.in_(parked)).values(is_active=True)
    )
    db_session.commit()


def _name(created: list[str], label: str) -> str:
    name = f"lifecycle-{label}-{uuid.uuid4().hex[:8]}"
    created.append(name)
    return name


def _post(client, created, label, **body):
    body = {"name": _name(created, label), "holdout_percentage": 5, **body}
    resp = client.post("/api/v1/holdout", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _row(db_session, holdout_id) -> GlobalHoldout:
    db_session.expire_all()
    return db_session.get(GlobalHoldout, uuid.UUID(str(holdout_id)))


def _active_ids(db_session) -> list[uuid.UUID]:
    db_session.expire_all()
    return [
        r.id for r in db_session.query(GlobalHoldout).filter(GlobalHoldout.is_active)
    ]


def _orm_holdout(db_session, created, label, *, salt=None, is_active=False):
    """A holdout written straight through the ORM, as an older image or a
    fixture would; ``salt`` set to the legacy salt is a pre-#445 row."""
    holdout = GlobalHoldout(
        name=_name(created, label), holdout_percentage=5, is_active=is_active
    )
    if salt is not None:
        holdout.hash_salt = salt
    db_session.add(holdout)
    db_session.commit()
    return holdout.id


# ---------------------------------------------------------------------------
# A9: activation timestamps on every path, POST included
# ---------------------------------------------------------------------------
class TestActivation:
    @pytest.mark.regression
    def test_post_active_stamps_it_and_ends_the_one_that_was_active(
        self, admin_client, db_session, holdout_slot
    ):
        first = _post(admin_client, holdout_slot, "first", is_active=True)
        assert first["is_active"] is True
        assert first["activated_at"] is not None
        assert first["deactivated_at"] is None

        second = _post(admin_client, holdout_slot, "second", is_active=True)

        assert second["activated_at"] is not None
        old = _row(db_session, first["id"])
        assert old.is_active is False
        assert old.deactivated_at is not None
        assert old.deactivated_at.isoformat() == second["activated_at"]
        assert _active_ids(db_session) == [uuid.UUID(second["id"])]

    def test_put_active_stamps_activated_at(
        self, admin_client, db_session, holdout_slot
    ):
        created = _post(admin_client, holdout_slot, "put")
        assert created["activated_at"] is None

        resp = admin_client.put(
            f"/api/v1/holdout/{created['id']}", json={"is_active": True}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["activated_at"] is not None
        assert _row(db_session, created["id"]).is_measurable

    def test_deactivating_stamps_deactivated_at(
        self, admin_client, db_session, holdout_slot
    ):
        created = _post(admin_client, holdout_slot, "off", is_active=True)

        resp = admin_client.put(
            f"/api/v1/holdout/{created['id']}", json={"is_active": False}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["deactivated_at"] is not None
        assert resp.json()["activated_at"] == created["activated_at"]


# ---------------------------------------------------------------------------
# EM condition 4 and PE C1: re-activating, and legacy-salt rows
# ---------------------------------------------------------------------------
class TestReactivation:
    @pytest.mark.regression
    def test_reactivating_the_active_holdout_changes_nothing(
        self, admin_client, db_session, holdout_slot
    ):
        created = _post(admin_client, holdout_slot, "again", is_active=True)
        before = _row(db_session, created["id"])
        snapshot = {f: getattr(before, f) for f in UNCHANGED_FIELDS}

        resp = admin_client.put(
            f"/api/v1/holdout/{created['id']}",
            json={"name": created["name"], "is_active": True},
        )

        assert resp.status_code == 200, resp.text
        after = _row(db_session, created["id"])
        assert {f: getattr(after, f) for f in UNCHANGED_FIELDS} == snapshot
        assert after.is_active is True

    @pytest.mark.regression
    def test_reactivating_the_legacy_active_row_leaves_it_unmeasurable(
        self, admin_client, db_session, holdout_slot
    ):
        """The row active at the upgrade: legacy salt, no activated_at (C1)."""
        holdout_id = _orm_holdout(
            db_session,
            holdout_slot,
            "legacy-on",
            salt=LEGACY_HOLDOUT_SALT,
            is_active=True,
        )
        name = _row(db_session, holdout_id).name

        resp = admin_client.put(
            f"/api/v1/holdout/{holdout_id}", json={"name": name, "is_active": True}
        )

        assert resp.status_code == 200, resp.text
        row = _row(db_session, holdout_id)
        assert row.is_active is True
        assert row.activated_at is None
        assert row.deactivated_at is None
        assert row.hash_salt == LEGACY_HOLDOUT_SALT
        assert not row.is_measurable

    @pytest.mark.regression
    def test_activating_a_legacy_inactive_row_does_not_make_it_measurable(
        self, admin_client, db_session, holdout_slot
    ):
        holdout_id = _orm_holdout(
            db_session, holdout_slot, "legacy-off", salt=LEGACY_HOLDOUT_SALT
        )

        resp = admin_client.put(
            f"/api/v1/holdout/{holdout_id}", json={"is_active": True}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["activated_at"] is None
        row = _row(db_session, holdout_id)
        assert row.is_active is True
        assert not row.is_measurable


# ---------------------------------------------------------------------------
# A10: the percentage lock, and the restart refusal
# ---------------------------------------------------------------------------
class TestRefusals:
    def test_a_never_active_holdout_can_change_its_percentage(
        self, admin_client, holdout_slot
    ):
        created = _post(admin_client, holdout_slot, "pct-free")

        resp = admin_client.put(
            f"/api/v1/holdout/{created['id']}", json={"holdout_percentage": 7}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["holdout_percentage"] == 7

    @pytest.mark.regression
    def test_the_percentage_is_fixed_once_active(
        self, admin_client, db_session, holdout_slot
    ):
        created = _post(admin_client, holdout_slot, "pct-lock", is_active=True)
        url = f"/api/v1/holdout/{created['id']}"

        changed = admin_client.put(url, json={"holdout_percentage": 6})
        assert changed.status_code == 422, changed.text
        assert changed.json()["detail"] == PERCENTAGE_LOCKED_DETAIL
        assert _row(db_session, created["id"]).holdout_percentage == 5

        # A form that sends every field, the same percentage included, works.
        same = admin_client.put(
            url,
            json={
                "name": created["name"],
                "description": "edited",
                "holdout_percentage": 5,
                "is_active": True,
            },
        )
        assert same.status_code == 200, same.text
        assert same.json()["description"] == "edited"

        # Still fixed after it has ended.
        assert admin_client.put(url, json={"is_active": False}).status_code == 200
        ended = admin_client.put(url, json={"holdout_percentage": 6})
        assert ended.status_code == 422, ended.text

    @pytest.mark.regression
    def test_an_ended_holdout_cannot_restart(
        self, admin_client, db_session, holdout_slot
    ):
        created = _post(admin_client, holdout_slot, "restart", is_active=True)
        url = f"/api/v1/holdout/{created['id']}"
        assert admin_client.put(url, json={"is_active": False}).status_code == 200

        resp = admin_client.put(url, json={"name": "renamed", "is_active": True})

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == ENDED_DETAIL
        row = _row(db_session, created["id"])
        assert row.is_active is False
        assert row.name == created["name"]  # nothing changed


# ---------------------------------------------------------------------------
# Concurrent activation: the one-active index answers 409
# ---------------------------------------------------------------------------
@pytest.mark.regression
def test_an_activation_racing_another_answers_409(
    admin_client, db_session, holdout_slot, monkeypatch
):
    """B reads "nothing else is active", then A commits its activation, then B
    turns active: the index refuses B, and the route answers 409, not 500."""
    winner = _post(admin_client, holdout_slot, "winner")
    loser = _post(admin_client, holdout_slot, "loser")
    engine = db_session.get_bind()
    real_flush = GlobalHoldoutService._flush
    calls = {"n": 0}

    def flush_after_the_winner_commits(self):
        calls["n"] += 1
        if calls["n"] == 1:
            # After B found no other active holdout: A commits its activation.
            with engine.begin() as conn:
                conn.execute(text("SET search_path TO test_experimentation"))
                conn.execute(
                    update(GlobalHoldout)
                    .where(GlobalHoldout.id == uuid.UUID(winner["id"]))
                    .values(is_active=True)
                )
        return real_flush(self)

    monkeypatch.setattr(GlobalHoldoutService, "_flush", flush_after_the_winner_commits)

    resp = admin_client.put(f"/api/v1/holdout/{loser['id']}", json={"is_active": True})

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == global_holdout_service.ACTIVATION_CONFLICT_DETAIL
    assert _active_ids(db_session) == [uuid.UUID(winner["id"])]
    assert _row(db_session, loser["id"]).activated_at is None


# ---------------------------------------------------------------------------
# EM condition 5 / PE C3: every ORM-created holdout gets its own salt
# ---------------------------------------------------------------------------
@pytest.mark.regression
def test_holdouts_added_and_flushed_together_get_distinct_own_salts(
    db_session: Session, holdout_slot
):
    first = GlobalHoldout(name=_name(holdout_slot, "salt-a"), holdout_percentage=5)
    second = GlobalHoldout(name=_name(holdout_slot, "salt-b"), holdout_percentage=5)
    db_session.add_all([first, second])
    db_session.flush()

    salts = {first.hash_salt, second.hash_salt}
    db_session.commit()
    assert len(salts) == 2, salts
    assert LEGACY_HOLDOUT_SALT not in salts
    assert all(s.startswith("holdout:") for s in salts), salts
