"""
DB-backed tests for the bandit audit trail (P0 statistical credibility).

Each ``BanditScheduler.update_experiment`` tick must:

* persist the Thompson-sampling seed / n_samples / engine_version on
  ``bandit_states``;
* write one ``bandit_state_history`` row per variant with the posterior it
  drew from and the weight it produced;
* write one ``analysis_snapshots`` row of kind ``bandit``;
* produce identical weights when re-run on the same day with the same
  counts (the seed is a function of experiment, day and n_samples).

The scheduler runs with DynamoDB patched out so PostgreSQL is the stats
source.  Every row is deleted in fixture teardown.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.app.core.bandit_scheduler import BanditScheduler
from backend.app.core.stats_engine import ENGINE_VERSION, as_of_bucket, derive_seed
from backend.app.models.analysis_snapshot import AnalysisSnapshot
from backend.app.models.assignment import Assignment
from backend.app.models.bandit_state import BanditState, BanditStateHistory
from backend.app.models.event import Event
from backend.app.models.experiment import (
    Experiment,
    ExperimentStatus,
    ExperimentType,
    Metric,
    MetricType,
    Variant,
)
from backend.app.services.bandit_service import ThompsonSampling


@pytest.fixture
def mab_experiment(db_session, make_experiment):
    suffix = uuid.uuid4().hex[:8]
    experiment = make_experiment(
        name=f"MAB history {suffix}",
        key=f"mab-history-{suffix}",
        status=ExperimentStatus.ACTIVE,
        experiment_type=ExperimentType.BANDIT,
        optimization_type="thompson_sampling",
    )
    for name, is_control in (("arm_a", True), ("arm_b", False), ("arm_c", False)):
        db_session.add(
            Variant(
                experiment_id=experiment.id,
                name=name,
                is_control=is_control,
                traffic_allocation=33,
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
    experiment_id = experiment.id
    yield experiment
    db_session.rollback()
    for model in (BanditStateHistory, AnalysisSnapshot, BanditState, Event, Assignment):
        db_session.query(model).filter(model.experiment_id == experiment_id).delete(
            synchronize_session=False
        )
    db_session.commit()


def _seed(db_session, experiment, variant, n_users, n_converted):
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
        if i < n_converted:
            rows.append(
                Event(
                    event_type="purchase",
                    event_name="purchase",
                    user_id=user_id,
                    experiment_id=experiment.id,
                    variant_id=variant.id,
                    value=1.0,
                    created_at=now_iso,
                )
            )
    db_session.add_all(rows)
    db_session.commit()


def _history(db_session, experiment_id):
    return (
        db_session.query(BanditStateHistory)
        .filter(BanditStateHistory.experiment_id == experiment_id)
        .order_by(BanditStateHistory.tick_at, BanditStateHistory.variant_id)
        .all()
    )


def _tick(db_session, experiment):
    with patch.object(BanditScheduler, "_stats_from_dynamodb", return_value=None):
        assert BanditScheduler(db_session).update_experiment(experiment) is True


@pytest.mark.integration
@pytest.mark.requires_db
class TestBanditTickHistory:
    def test_tick_writes_history_row_per_variant_and_bandit_snapshot(
        self, db_session, mab_experiment
    ):
        variants = {v.name: v for v in mab_experiment.variants}
        _seed(db_session, mab_experiment, variants["arm_a"], 100, 5)
        _seed(db_session, mab_experiment, variants["arm_b"], 100, 40)
        _seed(db_session, mab_experiment, variants["arm_c"], 50, 10)

        _tick(db_session, mab_experiment)
        db_session.expire_all()

        state = (
            db_session.query(BanditState)
            .filter(BanditState.experiment_id == mab_experiment.id)
            .one()
        )
        expected_seed = derive_seed(
            mab_experiment.id, as_of_bucket(), ThompsonSampling.N_SAMPLES
        )
        assert state.seed == expected_seed
        assert state.n_samples == ThompsonSampling.N_SAMPLES
        assert state.engine_version == ENGINE_VERSION

        rows = _history(db_session, mab_experiment.id)
        assert len(rows) == 3
        by_variant = {row.variant_id: row for row in rows}
        assert set(by_variant) == {v.id for v in mab_experiment.variants}

        a = by_variant[variants["arm_a"].id]
        b = by_variant[variants["arm_b"].id]
        assert (a.successes, a.failures, a.pulls) == (5, 95, 100)
        assert (a.alpha, a.beta) == (6.0, 96.0)  # Beta(1 + s, 1 + f)
        assert (b.alpha, b.beta) == (41.0, 61.0)
        assert b.weight == state.variant_weights[str(variants["arm_b"].id)]["weight"]
        assert b.weight > a.weight
        assert abs(sum(r.weight for r in rows) - 1.0) < 1e-6
        for row in rows:
            assert row.algorithm == "thompson_sampling"
            assert row.seed == expected_seed
            assert row.n_samples == ThompsonSampling.N_SAMPLES
            assert row.engine_version == ENGINE_VERSION
            assert row.tick_at is not None
            assert row.tick_at.isoformat() == state.last_computed_at

        snaps = (
            db_session.query(AnalysisSnapshot)
            .filter(
                AnalysisSnapshot.experiment_id == mab_experiment.id,
                AnalysisSnapshot.kind == "bandit",
            )
            .all()
        )
        assert len(snaps) == 1
        assert snaps[0].seed == expected_seed
        assert snaps[0].n_samples == ThompsonSampling.N_SAMPLES
        assert snaps[0].payload["algorithm"] == "thompson_sampling"
        assert snaps[0].payload["total_pulls"] == 250
        assert set(snaps[0].payload["variant_weights"]) == {
            str(v.id) for v in mab_experiment.variants
        }

    def test_each_tick_appends_history(self, db_session, mab_experiment):
        variants = {v.name: v for v in mab_experiment.variants}
        _seed(db_session, mab_experiment, variants["arm_a"], 20, 2)
        _seed(db_session, mab_experiment, variants["arm_b"], 20, 8)

        _tick(db_session, mab_experiment)
        _tick(db_session, mab_experiment)
        db_session.expire_all()

        rows = _history(db_session, mab_experiment.id)
        assert len(rows) == 6  # 3 variants x 2 ticks
        ticks = {row.tick_at for row in rows}
        assert len(ticks) == 2

        # Same day + same counts → same seed → identical weights on both ticks.
        first_tick, second_tick = sorted(ticks)
        first = {r.variant_id: r.weight for r in rows if r.tick_at == first_tick}
        second = {r.variant_id: r.weight for r in rows if r.tick_at == second_tick}
        assert first == second

        # Only one current state row, updated in place.
        assert (
            db_session.query(BanditState)
            .filter(BanditState.experiment_id == mab_experiment.id)
            .count()
            == 1
        )

    def test_history_failure_keeps_weight_update(self, db_session, mab_experiment):
        variants = {v.name: v for v in mab_experiment.variants}
        _seed(db_session, mab_experiment, variants["arm_a"], 10, 1)
        _seed(db_session, mab_experiment, variants["arm_b"], 10, 4)

        with patch.object(
            BanditScheduler,
            "build_tick_history",
            side_effect=RuntimeError("audit boom"),
        ):
            _tick(db_session, mab_experiment)
        db_session.expire_all()

        state = (
            db_session.query(BanditState)
            .filter(BanditState.experiment_id == mab_experiment.id)
            .one()
        )
        assert state.total_pulls == 20
        assert state.seed is not None
        assert _history(db_session, mab_experiment.id) == []

    def test_savepoint_rollback_on_bad_history_row_keeps_state(
        self, db_session, mab_experiment
    ):
        """An FK violation in the audit rows rolls back only the savepoint."""
        variants = {v.name: v for v in mab_experiment.variants}
        _seed(db_session, mab_experiment, variants["arm_a"], 10, 1)
        _seed(db_session, mab_experiment, variants["arm_b"], 10, 4)

        original = BanditScheduler.build_tick_history

        def with_orphan_row(*args, **kwargs):
            rows = original(*args, **kwargs)
            rows[0].variant_id = uuid.uuid4()  # no such variant → FK violation
            return rows

        with patch.object(
            BanditScheduler, "build_tick_history", side_effect=with_orphan_row
        ):
            _tick(db_session, mab_experiment)
        db_session.expire_all()

        state = (
            db_session.query(BanditState)
            .filter(BanditState.experiment_id == mab_experiment.id)
            .one()
        )
        assert state.total_pulls == 20
        assert state.variant_weights[str(variants["arm_b"].id)]["successes"] == 4
        assert _history(db_session, mab_experiment.id) == []
        assert (
            db_session.query(AnalysisSnapshot)
            .filter(AnalysisSnapshot.experiment_id == mab_experiment.id)
            .count()
            == 0
        )

        # The session is still usable: a second tick succeeds fully.
        _tick(db_session, mab_experiment)
        db_session.expire_all()
        assert len(_history(db_session, mab_experiment.id)) == 3

    def test_deleting_experiment_cascades_history(self, db_session, mab_experiment):
        variants = {v.name: v for v in mab_experiment.variants}
        _seed(db_session, mab_experiment, variants["arm_a"], 5, 1)
        _tick(db_session, mab_experiment)
        db_session.expire_all()
        assert len(_history(db_session, mab_experiment.id)) == 3

        # Bulk DELETE so the database-level ON DELETE CASCADE is what we test.
        experiment_id = mab_experiment.id
        db_session.query(Experiment).filter(Experiment.id == experiment_id).delete(
            synchronize_session=False
        )
        db_session.commit()

        assert _history(db_session, experiment_id) == []
        assert (
            db_session.query(AnalysisSnapshot)
            .filter(AnalysisSnapshot.experiment_id == experiment_id)
            .count()
            == 0
        )
