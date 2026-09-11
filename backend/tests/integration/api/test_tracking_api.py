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
from backend.app.models.global_holdout import GlobalHoldout
from backend.app.models.mutual_exclusion_group import (
    MutualExclusionGroup,
    MutualExclusionGroupStatus,
)
from backend.app.services.global_holdout_service import GlobalHoldoutService


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


# ---------------------------------------------------------------------------
# Eligibility on /tracking/assign: global holdout, mutual exclusion, targeting
# ---------------------------------------------------------------------------

HOLDOUT_PERCENTAGE = 20  # the model's CHECK constraint caps holdouts at 20%

NATIVE_US_ONLY_RULES = {
    "version": "1.0",
    "rules": [
        {
            "id": "us_only",
            "name": "US only",
            "rule": {
                "operator": "and",
                "conditions": [
                    {"attribute": "country", "operator": "eq", "value": "US"}
                ],
            },
            "rollout_percentage": 100,
            "priority": 1,
        }
    ],
}

DASHBOARD_US_ONLY_RULES = {
    "logical_operator": "AND",
    "groups": [
        {
            "id": "g1",
            "logical_operator": "AND",
            "conditions": [
                {
                    "id": "c1",
                    "attribute": "user.country",
                    "operator": "equals",
                    "value": "US",
                }
            ],
        }
    ],
}


def _users_by_holdout_membership(count_in: int, count_out: int):
    """Fresh user ids split by the deterministic holdout bucket."""
    inside, outside = [], []
    while len(inside) < count_in or len(outside) < count_out:
        user_id = _user()
        bucket = GlobalHoldoutService._get_holdout_bucket_static(user_id)
        if bucket < HOLDOUT_PERCENTAGE:
            if len(inside) < count_in:
                inside.append(user_id)
        elif len(outside) < count_out:
            outside.append(user_id)
    return inside, outside


def _assignment_rows(db_session, experiment, user_id):
    return (
        db_session.query(Assignment)
        .filter(
            Assignment.experiment_id == experiment.id, Assignment.user_id == user_id
        )
        .all()
    )


def _event_rows(db_session, experiment, user_id):
    return (
        db_session.query(Event)
        .filter(Event.experiment_id == experiment.id, Event.user_id == user_id)
        .all()
    )


def _assert_unassigned(resp, experiment, reason):
    """An ineligible user gets HTTP 200 + the control variant, assigned=False."""
    assert resp.status_code == 200, resp.text
    data = resp.json()
    control = _variant_by_name(experiment, "control")
    assert data["assigned"] is False
    assert data["reason"] == reason
    assert data["variant_id"] == str(control.id)
    assert data["variant_name"] == "control"
    assert data["is_control"] is True
    assert data["configuration"] == {"color": "control"}
    return data


@pytest.fixture
def active_holdout(db_session):
    """An active GlobalHoldout at HOLDOUT_PERCENTAGE; any other active holdout is
    parked for the duration of the test and restored afterwards."""
    parked = (
        db_session.query(GlobalHoldout).filter(GlobalHoldout.is_active == True).all()
    )
    for row in parked:
        row.is_active = False
    holdout = GlobalHoldout(
        name=f"tracking-holdout-{uuid.uuid4().hex[:8]}",
        description="Eligibility test holdout",
        holdout_percentage=HOLDOUT_PERCENTAGE,
        is_active=True,
    )
    db_session.add(holdout)
    db_session.commit()
    db_session.refresh(holdout)
    yield holdout
    db_session.rollback()
    db_session.query(GlobalHoldout).filter(GlobalHoldout.id == holdout.id).delete()
    for row in parked:
        db_session.merge(row).is_active = True
    db_session.commit()


def _make_active_experiment(db_session, make_experiment, label, **kwargs):
    suffix = uuid.uuid4().hex[:8]
    experiment = make_experiment(
        name=f"Tracking {label} {suffix}",
        key=f"tracking-{label}-{suffix}",
        status=ExperimentStatus.ACTIVE,
        **kwargs,
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
    return experiment


@pytest.fixture
def meg_experiments(db_session, make_experiment):
    """Two ACTIVE experiments sharing one ACTIVE mutual exclusion group (traffic 1.0)."""
    group = MutualExclusionGroup(
        name=f"tracking-meg-{uuid.uuid4().hex[:8]}",
        description="Eligibility test group",
        traffic_allocation=1.0,
        status=MutualExclusionGroupStatus.ACTIVE,
    )
    db_session.add(group)
    db_session.commit()
    db_session.refresh(group)

    experiments = [
        _make_active_experiment(
            db_session, make_experiment, f"meg{i}", mutual_exclusion_group_id=group.id
        )
        for i in (1, 2)
    ]
    yield group, experiments
    for experiment in experiments:
        _cleanup_experiment_rows(db_session, experiment)
        experiment.mutual_exclusion_group_id = None
    db_session.commit()
    db_session.query(MutualExclusionGroup).filter(
        MutualExclusionGroup.id == group.id
    ).delete()
    db_session.commit()


@pytest.fixture
def targeted_experiment(db_session, make_experiment):
    """ACTIVE experiment whose native targeting rules admit ``country == "US"`` only."""
    experiment = _make_active_experiment(
        db_session, make_experiment, "targeting", targeting_rules=NATIVE_US_ONLY_RULES
    )
    yield experiment
    _cleanup_experiment_rows(db_session, experiment)


@pytest.fixture
def dashboard_targeted_experiment(db_session, make_experiment):
    """Same as ``targeted_experiment`` but rules in the dashboard editor shape."""
    experiment = _make_active_experiment(
        db_session,
        make_experiment,
        "dash-targeting",
        targeting_rules=DASHBOARD_US_ONLY_RULES,
    )
    yield experiment
    _cleanup_experiment_rows(db_session, experiment)


class TestAssignEligibility:
    """``/tracking/assign`` honours the global holdout, mutual exclusion groups
    and experiment targeting rules for *new* users; sticky users bypass all."""

    def test_holdout_users_get_control_and_are_not_recorded(
        self, admin_client, active_experiment, active_holdout, db_session
    ):
        inside, outside = _users_by_holdout_membership(10, 10)

        for user_id in inside:
            resp = admin_client.post(
                "/api/v1/tracking/assign",
                json={"experiment_key": active_experiment.key, "user_id": user_id},
            )
            data = _assert_unassigned(resp, active_experiment, "holdout")
            assert data["experiment_key"] == active_experiment.key
            assert data["user_id"] == user_id
            assert _assignment_rows(db_session, active_experiment, user_id) == []
            assert _event_rows(db_session, active_experiment, user_id) == []

            # Still no row after a second call: the response is not sticky.
            again = admin_client.post(
                "/api/v1/tracking/assign",
                json={"experiment_key": active_experiment.key, "user_id": user_id},
            )
            assert again.json()["assigned"] is False
            assert _assignment_rows(db_session, active_experiment, user_id) == []

        for user_id in outside:
            resp = admin_client.post(
                "/api/v1/tracking/assign",
                json={"experiment_key": active_experiment.key, "user_id": user_id},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["assigned"] is True
            assert data["reason"] == "assigned"
            assert len(_assignment_rows(db_session, active_experiment, user_id)) == 1

    def test_every_holdout_bucket_user_is_unassigned(
        self, admin_client, active_experiment, active_holdout
    ):
        """Every user the holdout hashes inside the holdout is refused (not a sample)."""
        inside, _ = _users_by_holdout_membership(40, 0)
        reasons = {
            admin_client.post(
                "/api/v1/tracking/assign",
                json={"experiment_key": active_experiment.key, "user_id": user_id},
            ).json()["reason"]
            for user_id in inside
        }
        assert reasons == {"holdout"}

    def test_mutual_exclusion_assigns_each_user_to_exactly_one_experiment(
        self, admin_client, meg_experiments, db_session
    ):
        group, (exp_a, exp_b) = meg_experiments
        assigned_counts = {exp_a.key: 0, exp_b.key: 0}

        for _ in range(200):
            user_id = _user()
            results = {}
            for experiment in (exp_a, exp_b):
                resp = admin_client.post(
                    "/api/v1/tracking/assign",
                    json={"experiment_key": experiment.key, "user_id": user_id},
                )
                assert resp.status_code == 200, resp.text
                results[experiment.key] = resp.json()

            assigned = [k for k, v in results.items() if v["assigned"]]
            excluded = [k for k, v in results.items() if not v["assigned"]]
            assert len(assigned) == 1 and len(excluded) == 1, results
            assigned_counts[assigned[0]] += 1

            assert results[assigned[0]]["reason"] == "assigned"
            assert results[excluded[0]]["reason"] == "mutual_exclusion"
            excluded_exp = exp_a if excluded[0] == exp_a.key else exp_b
            _assert_unassigned(
                admin_client.post(
                    "/api/v1/tracking/assign",
                    json={"experiment_key": excluded_exp.key, "user_id": user_id},
                ),
                excluded_exp,
                "mutual_exclusion",
            )
            assert _assignment_rows(db_session, excluded_exp, user_id) == []
            assert _event_rows(db_session, excluded_exp, user_id) == []

        # traffic_allocation 1.0 split between two experiments: both get users
        assert assigned_counts[exp_a.key] > 0 and assigned_counts[exp_b.key] > 0
        total_rows = (
            db_session.query(Assignment)
            .filter(Assignment.experiment_id.in_([exp_a.id, exp_b.id]))
            .count()
        )
        assert total_rows == 200

    def test_native_targeting_rules_gate_new_users(
        self, admin_client, targeted_experiment, db_session
    ):
        us_user, de_user, blank_user = _user(), _user(), _user()

        resp = admin_client.post(
            "/api/v1/tracking/assign",
            json={
                "experiment_key": targeted_experiment.key,
                "user_id": us_user,
                "context": {"country": "US"},
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["assigned"] is True
        assert resp.json()["reason"] == "assigned"
        assert len(_assignment_rows(db_session, targeted_experiment, us_user)) == 1
        # exposure recorded with the request context
        events = _event_rows(db_session, targeted_experiment, us_user)
        assert len(events) == 1 and events[0].event_metadata == {"country": "US"}

        resp = admin_client.post(
            "/api/v1/tracking/assign",
            json={
                "experiment_key": targeted_experiment.key,
                "user_id": de_user,
                "context": {"country": "DE"},
            },
        )
        _assert_unassigned(resp, targeted_experiment, "targeting")
        assert _assignment_rows(db_session, targeted_experiment, de_user) == []
        assert _event_rows(db_session, targeted_experiment, de_user) == []

        resp = admin_client.post(
            "/api/v1/tracking/assign",
            json={"experiment_key": targeted_experiment.key, "user_id": blank_user},
        )
        _assert_unassigned(resp, targeted_experiment, "targeting")
        assert _assignment_rows(db_session, targeted_experiment, blank_user) == []

    def test_targeting_accepts_dotted_aliases_for_top_level_context(
        self, admin_client, targeted_experiment, db_session
    ):
        """A rule on ``country`` also matches a nested ``{"user": {"country"}}``
        context, and the dotted lookup works the other way round too."""
        user_id = _user()
        resp = admin_client.post(
            "/api/v1/tracking/assign",
            json={
                "experiment_key": targeted_experiment.key,
                "user_id": user_id,
                "context": {"user": {"country": "US"}, "country": "US"},
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["assigned"] is True

    def test_dashboard_shaped_targeting_rules_gate_new_users(
        self, admin_client, dashboard_targeted_experiment, db_session
    ):
        """Rules saved by the dashboard editor (``user.country equals US``) are
        normalised through ``backend.app.core.targeting_adapter``."""
        us_user, de_user, blank_user = _user(), _user(), _user()

        resp = admin_client.post(
            "/api/v1/tracking/assign",
            json={
                "experiment_key": dashboard_targeted_experiment.key,
                "user_id": us_user,
                "context": {"country": "US"},  # answers ``user.country`` via alias
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["assigned"] is True
        assert (
            len(_assignment_rows(db_session, dashboard_targeted_experiment, us_user))
            == 1
        )

        resp = admin_client.post(
            "/api/v1/tracking/assign",
            json={
                "experiment_key": dashboard_targeted_experiment.key,
                "user_id": de_user,
                "context": {"country": "DE"},
            },
        )
        _assert_unassigned(resp, dashboard_targeted_experiment, "targeting")
        assert (
            _assignment_rows(db_session, dashboard_targeted_experiment, de_user) == []
        )

        resp = admin_client.post(
            "/api/v1/tracking/assign",
            json={
                "experiment_key": dashboard_targeted_experiment.key,
                "user_id": blank_user,
            },
        )
        _assert_unassigned(resp, dashboard_targeted_experiment, "targeting")

    def test_sticky_assignment_bypasses_all_eligibility_checks(
        self,
        admin_client,
        targeted_experiment,
        active_holdout,
        meg_experiments,
        make_assignment,
        db_session,
    ):
        """A stored Assignment row wins even if the user is now in the holdout,
        excluded by the group and fails targeting."""
        group, (exp_a, exp_b) = meg_experiments
        (user_id,), _ = _users_by_holdout_membership(1, 0)

        # Put the targeted experiment into the group as well so all three
        # gates apply to it; the link is removed in ``finally`` before the
        # meg_experiments fixture deletes the group.
        targeted_experiment.mutual_exclusion_group_id = group.id
        db_session.commit()
        try:
            treatment = _variant_by_name(targeted_experiment, "treatment")
            make_assignment(
                experiment=targeted_experiment, variant=treatment, user_id=user_id
            )

            # Sanity: a *new* user with the same profile is refused (holdout wins).
            (fresh,), _ = _users_by_holdout_membership(1, 0)
            _assert_unassigned(
                admin_client.post(
                    "/api/v1/tracking/assign",
                    json={
                        "experiment_key": targeted_experiment.key,
                        "user_id": fresh,
                        "context": {"country": "DE"},
                    },
                ),
                targeted_experiment,
                "holdout",
            )

            resp = admin_client.post(
                "/api/v1/tracking/assign",
                json={
                    "experiment_key": targeted_experiment.key,
                    "user_id": user_id,
                    "context": {"country": "DE"},
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["assigned"] is True
            assert data["reason"] == "assigned"
            assert data["variant_id"] == str(treatment.id)
            assert data["variant_name"] == "treatment"
            assert data["is_control"] is False
            assert len(_assignment_rows(db_session, targeted_experiment, user_id)) == 1
        finally:
            db_session.rollback()
            targeted_experiment.mutual_exclusion_group_id = None
            db_session.commit()

    def test_reason_order_is_holdout_then_mutual_exclusion_then_targeting(
        self, admin_client, meg_experiments, active_holdout, db_session
    ):
        group, (exp_a, exp_b) = meg_experiments
        exp_a.targeting_rules = NATIVE_US_ONLY_RULES
        db_session.commit()
        try:
            # In the holdout: reason is holdout regardless of group/targeting.
            (held,), _ = _users_by_holdout_membership(1, 0)
            _assert_unassigned(
                admin_client.post(
                    "/api/v1/tracking/assign",
                    json={
                        "experiment_key": exp_a.key,
                        "user_id": held,
                        "context": {"country": "DE"},
                    },
                ),
                exp_a,
                "holdout",
            )

            # Outside the holdout, with a DE context (fails targeting on exp_a):
            # users routed to exp_b by the group report mutual_exclusion on
            # exp_a, users routed to exp_a report targeting.
            _, outside = _users_by_holdout_membership(0, 40)
            seen = set()
            for user_id in outside:
                resp = admin_client.post(
                    "/api/v1/tracking/assign",
                    json={
                        "experiment_key": exp_a.key,
                        "user_id": user_id,
                        "context": {"country": "DE"},
                    },
                )
                assert resp.status_code == 200, resp.text
                reason = resp.json()["reason"]
                assert reason in {"mutual_exclusion", "targeting"}, resp.text
                _assert_unassigned(resp, exp_a, reason)
                seen.add(reason)
            # 40 users routed by the group hash: both outcomes show up (~2^-39 otherwise)
            assert seen == {"mutual_exclusion", "targeting"}
        finally:
            db_session.rollback()
            exp_a.targeting_rules = None
            db_session.commit()
