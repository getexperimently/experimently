"""
DB-backed tests for BanditScheduler's PostgreSQL stats source.

Seeds an ACTIVE Thompson-sampling experiment with two variants, assignment
rows and conversion events, runs ``update_experiment`` with DynamoDB
unavailable and asserts the persisted BanditState reflects the seeded
conversions.  Every row created here is deleted again in fixture teardown
because the shared test database is not truncated between tests.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.app.core.bandit_scheduler import BanditScheduler
from backend.app.models.assignment import Assignment
from backend.app.models.bandit_state import BanditState
from backend.app.models.event import Event
from backend.app.models.experiment import (
    ExperimentStatus,
    ExperimentType,
    Metric,
    MetricType,
    Variant,
)


@pytest.fixture
def mab_experiment(db_session, make_experiment):
    """ACTIVE thompson_sampling experiment with variants ``arm_a``/``arm_b``."""
    suffix = uuid.uuid4().hex[:8]
    experiment = make_experiment(
        name=f"MAB scheduler {suffix}",
        key=f"mab-scheduler-{suffix}",
        status=ExperimentStatus.ACTIVE,
        experiment_type=ExperimentType.BANDIT,
        optimization_type="thompson_sampling",
    )
    for name, is_control in (("arm_a", True), ("arm_b", False)):
        db_session.add(
            Variant(
                experiment_id=experiment.id,
                name=name,
                is_control=is_control,
                traffic_allocation=50,
                configuration={"arm": name},
            )
        )
    db_session.add(
        Metric(
            experiment_id=experiment.id,
            name="Purchase",
            event_name="purchase",
            metric_type=MetricType.CONVERSION,
            is_primary=True,
        )
    )
    db_session.commit()
    db_session.refresh(experiment)
    yield experiment
    db_session.rollback()
    for model in (BanditState, Event, Assignment):
        db_session.query(model).filter(model.experiment_id == experiment.id).delete(
            synchronize_session=False
        )
    db_session.commit()


def _seed_variant(
    db_session, experiment, variant, n_users, n_converted, event_type="purchase"
):
    """Assign ``n_users`` users to ``variant``; the first ``n_converted`` convert."""
    now_iso = datetime.now(timezone.utc).isoformat()
    prefix = f"{variant.name}-{uuid.uuid4().hex[:6]}"
    rows = []
    for i in range(n_users):
        user_id = f"{prefix}-{i:04d}"
        rows.append(
            Assignment(
                experiment_id=experiment.id, variant_id=variant.id, user_id=user_id
            )
        )
        rows.append(
            Event(
                event_type="experiment_exposure",
                event_name="experiment_exposure",
                user_id=user_id,
                experiment_id=experiment.id,
                variant_id=variant.id,
                value=1.0,
                created_at=now_iso,
            )
        )
        if i < n_converted:
            # Two conversion events for the first user: distinct users must be counted.
            repeats = 2 if i == 0 else 1
            for _ in range(repeats):
                rows.append(
                    Event(
                        event_type=event_type,
                        event_name=event_type,
                        user_id=user_id,
                        experiment_id=experiment.id,
                        variant_id=variant.id,
                        value=1.0,
                        created_at=now_iso,
                    )
                )
    db_session.add_all(rows)
    db_session.commit()


def _variants(experiment):
    by_name = {v.name: v for v in experiment.variants}
    return by_name["arm_a"], by_name["arm_b"]


@pytest.mark.integration
class TestBanditSchedulerLearnsFromPostgres:
    def test_update_experiment_weights_winning_variant(
        self, db_session, mab_experiment
    ):
        arm_a, arm_b = _variants(mab_experiment)
        _seed_variant(db_session, mab_experiment, arm_a, n_users=100, n_converted=5)
        _seed_variant(db_session, mab_experiment, arm_b, n_users=100, n_converted=40)

        scheduler = BanditScheduler(db_session)
        with patch.object(BanditScheduler, "_stats_from_dynamodb", return_value=None):
            assert scheduler.update_experiment(mab_experiment) is True

        state = (
            db_session.query(BanditState)
            .filter(BanditState.experiment_id == mab_experiment.id)
            .one()
        )
        payload = state.variant_weights
        a_stats, b_stats = payload[str(arm_a.id)], payload[str(arm_b.id)]

        assert a_stats["pulls"] == 100 and b_stats["pulls"] == 100
        assert a_stats["successes"] == 5
        assert b_stats["successes"] == 40  # distinct users, not events
        assert a_stats["failures"] == 95 and b_stats["failures"] == 60
        assert state.total_pulls == 200
        assert state.algorithm == "thompson_sampling"
        assert state.last_computed_at

        # Thompson sampling is stochastic; 40/100 vs 5/100 leaves a wide margin.
        assert b_stats["weight"] > 0.6
        assert a_stats["weight"] < 0.4
        assert abs(a_stats["weight"] + b_stats["weight"] - 1.0) < 1e-6
        assert state.regret_reduction_pct is not None and state.regret_reduction_pct > 0

    def test_run_once_picks_up_active_mab_experiment(self, db_session, mab_experiment):
        arm_a, arm_b = _variants(mab_experiment)
        _seed_variant(db_session, mab_experiment, arm_a, n_users=30, n_converted=2)
        _seed_variant(db_session, mab_experiment, arm_b, n_users=30, n_converted=15)

        with patch.object(BanditScheduler, "_stats_from_dynamodb", return_value=None):
            summary = BanditScheduler(db_session).run_once()

        assert summary["errors"] == 0
        assert summary["updated"] >= 1
        state = (
            db_session.query(BanditState)
            .filter(BanditState.experiment_id == mab_experiment.id)
            .one()
        )
        assert state.variant_weights[str(arm_b.id)]["successes"] == 15

    def test_no_metric_rows_counts_any_non_exposure_event(
        self, db_session, mab_experiment
    ):
        """Without a Metric row every non-exposure event type is a conversion."""
        db_session.query(Metric).filter(
            Metric.experiment_id == mab_experiment.id
        ).delete(synchronize_session=False)
        db_session.commit()
        db_session.refresh(mab_experiment)
        assert mab_experiment.metric_definitions == []

        arm_a, arm_b = _variants(mab_experiment)
        _seed_variant(db_session, mab_experiment, arm_a, 20, 0)
        _seed_variant(
            db_session, mab_experiment, arm_b, 20, 6, event_type="add_to_cart"
        )

        scheduler = BanditScheduler(db_session)
        stats = scheduler._stats_from_postgres(
            mab_experiment.id, [str(arm_a.id), str(arm_b.id)], mab_experiment
        )

        assert stats[str(arm_a.id)].pulls == 20
        assert stats[str(arm_a.id)].successes == 0  # exposures are never conversions
        assert stats[str(arm_b.id)].successes == 6
