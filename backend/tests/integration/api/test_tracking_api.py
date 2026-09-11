"""
Integration tests for the SDK-facing tracking API (/api/v1/tracking/*).

These endpoints resolve experiments by their public ``key`` and persist
assignments and events through AssignmentService / EventService against the
real test database.  Every assertion is scoped to rows created by the test
(unique keys, user ids and experiment ids) because the shared test database is
not truncated between tests.
"""
import json
import uuid

import pytest

from backend.app.models.assignment import Assignment
from backend.app.models.bandit_state import BanditState
from backend.app.models.event import Event
from backend.app.models.experiment import ExperimentStatus, ExperimentType, Variant


def _cleanup_experiment_rows(db_session, experiment) -> None:
    """Remove rows an experiment produced so later tests see a clean slate."""
    db_session.rollback()
    db_session.query(BanditState).filter(
        BanditState.experiment_id == experiment.id
    ).delete()
    db_session.query(Event).filter(Event.experiment_id == experiment.id).delete()
    db_session.query(Assignment).filter(
        Assignment.experiment_id == experiment.id
    ).delete()
    db_session.commit()


@pytest.fixture
def active_experiment(db_session, make_experiment):
    """An ACTIVE experiment with a control and a treatment variant."""
    suffix = uuid.uuid4().hex[:8]
    experiment = make_experiment(
        name=f"Tracking API {suffix}",
        key=f"tracking-api-{suffix}",
        status=ExperimentStatus.ACTIVE,
    )
    for name, is_control in (("control", True), ("treatment", False)):
        db_session.add(
            Variant(
                experiment_id=experiment.id,
                name=name,
                description=f"{name} variant",
                is_control=is_control,
                traffic_allocation=50,
                configuration={"color": name},
            )
        )
    db_session.commit()
    db_session.refresh(experiment)
    yield experiment
    _cleanup_experiment_rows(db_session, experiment)


@pytest.fixture
def bandit_experiment(db_session, make_experiment):
    """An ACTIVE thompson_sampling experiment with variants ``arm_a``/``arm_b``."""
    suffix = uuid.uuid4().hex[:8]
    experiment = make_experiment(
        name=f"Tracking bandit {suffix}",
        key=f"tracking-bandit-{suffix}",
        status=ExperimentStatus.ACTIVE,
        experiment_type=ExperimentType.BANDIT,
        optimization_type="thompson_sampling",
    )
    for name, is_control in (("arm_a", True), ("arm_b", False)):
        db_session.add(
            Variant(
                experiment_id=experiment.id,
                name=name,
                description=f"{name} arm",
                is_control=is_control,
                traffic_allocation=50,
                configuration={"arm": name},
            )
        )
    db_session.commit()
    db_session.refresh(experiment)
    yield experiment
    _cleanup_experiment_rows(db_session, experiment)


def _set_bandit_weights(db_session, experiment, weights: dict) -> None:
    """Upsert the BanditState row for ``experiment`` with ``weights``."""
    state = (
        db_session.query(BanditState)
        .filter(BanditState.experiment_id == experiment.id)
        .first()
    )
    if state is None:
        state = BanditState(
            experiment_id=experiment.id,
            algorithm=experiment.optimization_type or "thompson_sampling",
            variant_weights=weights,
            total_pulls=0,
        )
        db_session.add(state)
    else:
        state.variant_weights = weights
    db_session.commit()


def _variant_by_name(experiment, name):
    return next(v for v in experiment.variants if v.name == name)


def _user() -> str:
    return f"user-{uuid.uuid4().hex[:10]}"


class TestAssign:
    def test_assigns_user_to_a_variant_and_is_sticky(
        self, admin_client, active_experiment
    ):
        user_id = _user()
        body = {"experiment_key": active_experiment.key, "user_id": user_id}

        first = admin_client.post("/api/v1/tracking/assign", json=body)
        assert first.status_code == 200, first.text
        data = first.json()
        assert data["experiment_key"] == active_experiment.key
        assert data["user_id"] == user_id
        assert data["variant_name"] in {"control", "treatment"}
        assert data["configuration"] == {"color": data["variant_name"]}
        assert data["is_control"] == (data["variant_name"] == "control")

        second = admin_client.post("/api/v1/tracking/assign", json=body)
        assert second.status_code == 200, second.text
        assert second.json()["variant_id"] == data["variant_id"]

    def test_unknown_key_returns_404(self, admin_client):
        resp = admin_client.post(
            "/api/v1/tracking/assign",
            json={"experiment_key": f"missing-{uuid.uuid4().hex}", "user_id": _user()},
        )
        assert resp.status_code == 404

    def test_inactive_experiment_returns_404(self, admin_client, make_experiment):
        suffix = uuid.uuid4().hex[:8]
        draft = make_experiment(name=f"Draft {suffix}", key=f"draft-{suffix}")
        resp = admin_client.post(
            "/api/v1/tracking/assign",
            json={"experiment_key": draft.key, "user_id": _user()},
        )
        assert resp.status_code == 404


class TestBanditAssignment:
    """``/tracking/assign`` honours BanditState weights for MAB experiments."""

    def test_new_users_follow_bandit_weights(
        self, admin_client, bandit_experiment, db_session
    ):
        arm_a = _variant_by_name(bandit_experiment, "arm_a")
        arm_b = _variant_by_name(bandit_experiment, "arm_b")
        _set_bandit_weights(
            db_session, bandit_experiment, {str(arm_a.id): 1.0, str(arm_b.id): 0.0}
        )

        for _ in range(20):
            resp = admin_client.post(
                "/api/v1/tracking/assign",
                json={"experiment_key": bandit_experiment.key, "user_id": _user()},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["variant_id"] == str(arm_a.id)
            assert data["variant_name"] == "arm_a"
            assert data["is_control"] is True

    def test_scheduler_payload_shape_is_honoured(
        self, admin_client, bandit_experiment, db_session
    ):
        """The scheduler stores ``{"weight": ..., "pulls": ...}`` per variant."""
        arm_a = _variant_by_name(bandit_experiment, "arm_a")
        arm_b = _variant_by_name(bandit_experiment, "arm_b")
        _set_bandit_weights(
            db_session,
            bandit_experiment,
            {
                str(arm_a.id): {
                    "weight": 0.0,
                    "successes": 1,
                    "failures": 9,
                    "pulls": 10,
                },
                str(arm_b.id): {
                    "weight": 1.0,
                    "successes": 8,
                    "failures": 2,
                    "pulls": 10,
                },
            },
        )

        for _ in range(10):
            resp = admin_client.post(
                "/api/v1/tracking/assign",
                json={"experiment_key": bandit_experiment.key, "user_id": _user()},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["variant_id"] == str(arm_b.id)

    def test_existing_assignment_is_sticky_when_weights_change(
        self, admin_client, bandit_experiment, db_session
    ):
        arm_a = _variant_by_name(bandit_experiment, "arm_a")
        arm_b = _variant_by_name(bandit_experiment, "arm_b")
        _set_bandit_weights(
            db_session, bandit_experiment, {str(arm_a.id): 1.0, str(arm_b.id): 0.0}
        )

        user_id = _user()
        body = {"experiment_key": bandit_experiment.key, "user_id": user_id}
        first = admin_client.post("/api/v1/tracking/assign", json=body)
        assert first.status_code == 200, first.text
        assert first.json()["variant_id"] == str(arm_a.id)

        # The bandit now routes all new traffic to arm_b ...
        _set_bandit_weights(
            db_session, bandit_experiment, {str(arm_a.id): 0.0, str(arm_b.id): 1.0}
        )

        # ... but the already-assigned user keeps arm_a
        again = admin_client.post("/api/v1/tracking/assign", json=body)
        assert again.status_code == 200, again.text
        assert again.json()["variant_id"] == str(arm_a.id)

        stored = (
            db_session.query(Assignment)
            .filter(
                Assignment.experiment_id == bandit_experiment.id,
                Assignment.user_id == user_id,
            )
            .all()
        )
        assert len(stored) == 1 and str(stored[0].variant_id) == str(arm_a.id)

        # while a fresh user follows the new weights
        fresh = admin_client.post(
            "/api/v1/tracking/assign",
            json={"experiment_key": bandit_experiment.key, "user_id": _user()},
        )
        assert fresh.json()["variant_id"] == str(arm_b.id)

    def test_all_zero_weights_fall_back_to_default_hashing(
        self, admin_client, bandit_experiment, db_session
    ):
        arm_a = _variant_by_name(bandit_experiment, "arm_a")
        arm_b = _variant_by_name(bandit_experiment, "arm_b")
        _set_bandit_weights(
            db_session, bandit_experiment, {str(arm_a.id): 0.0, str(arm_b.id): 0.0}
        )

        seen = set()
        for _ in range(40):
            resp = admin_client.post(
                "/api/v1/tracking/assign",
                json={"experiment_key": bandit_experiment.key, "user_id": _user()},
            )
            assert resp.status_code == 200, resp.text
            seen.add(resp.json()["variant_name"])
        # 50/50 traffic allocation: 40 users landing on one arm is ~2^-39 likely
        assert seen == {"arm_a", "arm_b"}

    def test_fixed_allocation_ignores_bandit_state(
        self, admin_client, active_experiment, db_session
    ):
        """A BanditState row on a fixed-allocation experiment changes nothing."""
        control = _variant_by_name(active_experiment, "control")
        treatment = _variant_by_name(active_experiment, "treatment")
        assert (active_experiment.optimization_type or "fixed") == "fixed"
        _set_bandit_weights(
            db_session,
            active_experiment,
            {str(control.id): 0.0, str(treatment.id): 1.0},
        )

        seen = set()
        for _ in range(40):
            resp = admin_client.post(
                "/api/v1/tracking/assign",
                json={"experiment_key": active_experiment.key, "user_id": _user()},
            )
            assert resp.status_code == 200, resp.text
            seen.add(resp.json()["variant_name"])
        # Weights would have sent everyone to treatment; default hashing splits 50/50.
        assert seen == {"control", "treatment"}


class TestTrack:
    def test_tracks_event_with_assigned_variant(
        self, admin_client, active_experiment, db_session
    ):
        user_id = _user()
        assigned = admin_client.post(
            "/api/v1/tracking/assign",
            json={"experiment_key": active_experiment.key, "user_id": user_id},
        ).json()

        resp = admin_client.post(
            "/api/v1/tracking/track",
            json={
                "event_type": "purchase",
                "event_name": "checkout_complete",
                "user_id": user_id,
                "experiment_key": active_experiment.key,
                "value": 49.99,
                "metadata": {"currency": "USD"},
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["event_type"] == "purchase"
        assert data["event_name"] == "checkout_complete"
        assert data["experiment_id"] == str(active_experiment.id)
        assert data["variant_id"] == assigned["variant_id"]
        assert data["value"] == 49.99
        assert data["properties"] == {"currency": "USD"}

        row = db_session.query(Event).filter(Event.id == uuid.UUID(data["id"])).one()
        assert row.user_id == user_id
        assert row.event_metadata == {"currency": "USD"}
        assert str(row.variant_id) == assigned["variant_id"]

    def test_event_name_defaults_to_event_type(self, admin_client, active_experiment):
        resp = admin_client.post(
            "/api/v1/tracking/track",
            json={
                "event_type": "page_view",
                "user_id": _user(),
                "experiment_key": active_experiment.key,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["event_name"] == "page_view"
        assert resp.json()["variant_id"] is None  # no assignment for this user

    def test_unknown_keys_return_404(self, admin_client):
        resp = admin_client.post(
            "/api/v1/tracking/track",
            json={
                "event_type": "click",
                "user_id": _user(),
                "experiment_key": "nope-" + uuid.uuid4().hex,
            },
        )
        assert resp.status_code == 404

    def test_missing_keys_return_422(self, admin_client):
        resp = admin_client.post(
            "/api/v1/tracking/track", json={"event_type": "click", "user_id": _user()}
        )
        assert resp.status_code == 422


class TestBatch:
    def test_reports_success_and_failure_per_event(
        self, admin_client, active_experiment, db_session
    ):
        user_id = _user()
        resp = admin_client.post(
            "/api/v1/tracking/batch",
            json={
                "events": [
                    {
                        "event_type": "page_view",
                        "user_id": user_id,
                        "experiment_key": active_experiment.key,
                    },
                    {
                        "event_type": "click",
                        "user_id": user_id,
                        "experiment_key": "missing-" + uuid.uuid4().hex,
                    },
                    {
                        "event_type": "add_to_cart",
                        "user_id": user_id,
                        "experiment_key": active_experiment.key,
                        "value": 2,
                    },
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success_count"] == 2
        assert data["failure_count"] == 1
        assert data["errors"][0]["index"] == 1
        assert "experiment key" in data["errors"][0]["error"]

        stored = (
            db_session.query(Event)
            .filter(
                Event.experiment_id == active_experiment.id, Event.user_id == user_id
            )
            .all()
        )
        assert sorted(e.event_type for e in stored) == ["add_to_cart", "page_view"]


class TestEventsByIds:
    def test_tracks_event_by_ids_and_parses_json_properties(
        self, admin_client, active_experiment, db_session
    ):
        variant = (
            db_session.query(Variant)
            .filter(Variant.experiment_id == active_experiment.id)
            .first()
        )
        user_id = _user()
        resp = admin_client.post(
            "/api/v1/tracking/events",
            json={
                "event_type": "track",
                "event_name": "signup",
                "user_id": user_id,
                "experiment_id": str(active_experiment.id),
                "variant_id": str(variant.id),
                "value": 1,
                "properties": json.dumps({"plan": "pro"}),
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["experiment_id"] == str(active_experiment.id)
        assert data["variant_id"] == str(variant.id)
        assert data["properties"] == {"plan": "pro"}

        row = db_session.query(Event).filter(Event.id == uuid.UUID(data["id"])).one()
        assert row.event_metadata == {"plan": "pro"}
        assert row.event_type == "track"

    def test_rejects_event_without_experiment_or_flag(self, admin_client):
        resp = admin_client.post(
            "/api/v1/tracking/events",
            json={"event_type": "track", "event_name": "x", "user_id": _user()},
        )
        assert resp.status_code == 422

    def test_rejects_invalid_experiment_id(self, admin_client):
        resp = admin_client.post(
            "/api/v1/tracking/events",
            json={
                "event_type": "track",
                "event_name": "x",
                "user_id": _user(),
                "experiment_id": "not-a-uuid",
            },
        )
        assert resp.status_code == 422


class TestUserAssignments:
    def test_lists_assignments_for_user(self, admin_client, active_experiment):
        user_id = _user()
        admin_client.post(
            "/api/v1/tracking/assign",
            json={"experiment_key": active_experiment.key, "user_id": user_id},
        )
        resp = admin_client.get(f"/api/v1/tracking/assignments/{user_id}")
        assert resp.status_code == 200, resp.text
        assert any(
            a.get("experiment_id") == str(active_experiment.id) for a in resp.json()
        )
