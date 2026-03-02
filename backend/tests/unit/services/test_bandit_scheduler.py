"""
Unit tests for BanditScheduler (Issue #22 Batch B).

Coverage:
- BanditScheduler.run_once()                    (scheduler logic with mocked DB)
- BanditScheduler.update_experiment()
- BanditScheduler.get_variant_stats_from_counters()
- BanditScheduler.estimate_regret_reduction()
- BanditScheduler.get_recommendation()
- Pure-logic integration tests (no DB)
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from backend.app.services.bandit_service import (
    BanditService,
    EpsilonGreedy,
    ThompsonSampling,
    UCB1,
    VariantStats,
)
from backend.app.core.bandit_scheduler import BanditScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_variant(variant_id: str, name: str = None):
    """Create a mock Variant with a UUID id."""
    v = MagicMock()
    v.id = uuid.UUID(variant_id) if "-" in variant_id else uuid.uuid4()
    v.name = name or f"variant_{variant_id}"
    return v


def _make_experiment(
    exp_id: str,
    optimization_type: str = "thompson_sampling",
    variant_ids: Optional[List[str]] = None,
    status=None,
):
    """Create a mock Experiment object."""
    from backend.app.models.experiment import ExperimentStatus

    exp = MagicMock()
    exp.id = uuid.UUID(exp_id) if len(exp_id) == 36 else uuid.uuid4()
    exp.optimization_type = optimization_type
    exp.status = status or ExperimentStatus.ACTIVE

    if variant_ids is None:
        variant_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    exp.variants = [_make_variant(vid) for vid in variant_ids]
    return exp


def _make_scheduler(db=None):
    """Create a BanditScheduler with a mocked DB session."""
    if db is None:
        db = MagicMock()
    return BanditScheduler(db=db)


# ===========================================================================
# TestBanditScheduler — scheduler logic with mocked DB
# ===========================================================================

class TestBanditScheduler:
    """Tests for BanditScheduler using mocked DB and service dependencies."""

    # -----------------------------------------------------------------------
    # 1. run_once finds active MAB experiments
    # -----------------------------------------------------------------------
    def test_run_once_finds_active_mab_experiments(self):
        """run_once queries for ACTIVE experiments with non-fixed optimization_type."""
        from backend.app.models.experiment import ExperimentStatus

        db = MagicMock()
        exp_id = str(uuid.uuid4())
        mock_exp = _make_experiment(exp_id, optimization_type="thompson_sampling")

        # DB query chain returns a list with one experiment
        db.query.return_value.filter.return_value.all.return_value = [mock_exp]

        scheduler = BanditScheduler(db=db)

        with patch.object(scheduler, "update_experiment", return_value=True):
            result = scheduler.run_once()

        assert result["updated"] == 1
        assert result["errors"] == 0

    # -----------------------------------------------------------------------
    # 2. run_once skips fixed experiments
    # -----------------------------------------------------------------------
    def test_run_once_skips_fixed_optimization_experiments(self):
        """run_once must NOT include fixed-type experiments in the query."""
        db = MagicMock()

        # DB returns empty list (fixed experiments excluded by WHERE clause)
        db.query.return_value.filter.return_value.all.return_value = []

        scheduler = BanditScheduler(db=db)
        result = scheduler.run_once()

        assert result["updated"] == 0
        assert result["skipped"] == 0

    # -----------------------------------------------------------------------
    # 3. update_experiment calls BanditService.compute_weights with correct algorithm
    # -----------------------------------------------------------------------
    def test_update_experiment_calls_correct_algorithm(self):
        """update_experiment uses the experiment's optimization_type."""
        db = MagicMock()
        exp_id = str(uuid.uuid4())
        mock_exp = _make_experiment(exp_id, optimization_type="ucb1")

        scheduler = BanditScheduler(db=db)

        mock_stats = {
            str(v.id): VariantStats(
                variant_id=str(v.id), successes=10, failures=5, pulls=15
            )
            for v in mock_exp.variants
        }

        with patch.object(
            scheduler, "get_variant_stats_from_counters", return_value=mock_stats
        ):
            with patch.object(
                BanditService, "compute_weights", return_value={str(v.id): 0.5 for v in mock_exp.variants}
            ) as mock_compute:
                db.query.return_value.filter.return_value.first.return_value = None
                scheduler.update_experiment(mock_exp)

        mock_compute.assert_called_once()
        call_kwargs = mock_compute.call_args
        assert call_kwargs[1]["algorithm"] == "ucb1" or call_kwargs[0][0] == "ucb1"

    # -----------------------------------------------------------------------
    # 4. update_experiment updates variant_weights in DB
    # -----------------------------------------------------------------------
    def test_update_experiment_updates_bandit_state_in_db(self):
        """update_experiment commits a BanditState to the DB."""
        db = MagicMock()
        exp_id = str(uuid.uuid4())
        mock_exp = _make_experiment(exp_id, optimization_type="thompson_sampling")

        # Pretend no BanditState exists yet
        db.query.return_value.filter.return_value.first.return_value = None

        scheduler = BanditScheduler(db=db)

        vid = str(mock_exp.variants[0].id)
        vid2 = str(mock_exp.variants[1].id)
        mock_stats = {
            vid: VariantStats(variant_id=vid, successes=20, failures=10, pulls=30),
            vid2: VariantStats(variant_id=vid2, successes=5, failures=15, pulls=20),
        }
        weights = {vid: 0.7, vid2: 0.3}

        with patch.object(scheduler, "get_variant_stats_from_counters", return_value=mock_stats):
            with patch.object(BanditService, "compute_weights", return_value=weights):
                result = scheduler.update_experiment(mock_exp)

        assert result is True
        db.add.assert_called_once()
        db.commit.assert_called_once()

    # -----------------------------------------------------------------------
    # 5. Creates BanditState record if it doesn't exist
    # -----------------------------------------------------------------------
    def test_update_experiment_creates_bandit_state_when_missing(self):
        """A new BanditState is added when none exists for the experiment."""
        from backend.app.models.bandit_state import BanditState

        db = MagicMock()
        exp_id = str(uuid.uuid4())
        mock_exp = _make_experiment(exp_id)
        db.query.return_value.filter.return_value.first.return_value = None

        scheduler = BanditScheduler(db=db)
        vid = str(mock_exp.variants[0].id)
        vid2 = str(mock_exp.variants[1].id)
        mock_stats = {
            vid: VariantStats(variant_id=vid),
            vid2: VariantStats(variant_id=vid2),
        }

        with patch.object(scheduler, "get_variant_stats_from_counters", return_value=mock_stats):
            with patch.object(BanditService, "compute_weights", return_value={vid: 0.5, vid2: 0.5}):
                scheduler.update_experiment(mock_exp)

        # db.add must have been called with a BanditState instance
        added_obj = db.add.call_args[0][0]
        assert isinstance(added_obj, BanditState)
        assert str(added_obj.experiment_id) == str(mock_exp.id)

    # -----------------------------------------------------------------------
    # 6. Updates existing BanditState rather than creating a new one
    # -----------------------------------------------------------------------
    def test_update_experiment_updates_existing_bandit_state(self):
        """When a BanditState already exists, it is updated in place."""
        from backend.app.models.bandit_state import BanditState

        db = MagicMock()
        exp_id = str(uuid.uuid4())
        mock_exp = _make_experiment(exp_id)

        existing_state = MagicMock(spec=BanditState)
        db.query.return_value.filter.return_value.first.return_value = existing_state

        scheduler = BanditScheduler(db=db)
        vid = str(mock_exp.variants[0].id)
        vid2 = str(mock_exp.variants[1].id)
        mock_stats = {
            vid: VariantStats(variant_id=vid, successes=30, pulls=50),
            vid2: VariantStats(variant_id=vid2, successes=10, pulls=50),
        }

        with patch.object(scheduler, "get_variant_stats_from_counters", return_value=mock_stats):
            with patch.object(BanditService, "compute_weights", return_value={vid: 0.65, vid2: 0.35}):
                scheduler.update_experiment(mock_exp)

        # db.add should NOT be called (existing record updated in place)
        db.add.assert_not_called()
        db.commit.assert_called_once()
        # The variant_weights attribute on the existing state should be set
        assert existing_state.variant_weights is not None

    # -----------------------------------------------------------------------
    # 7. Handles empty active experiments gracefully
    # -----------------------------------------------------------------------
    def test_run_once_handles_no_active_experiments(self):
        """run_once returns zero counts when no active MAB experiments exist."""
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        scheduler = BanditScheduler(db=db)
        result = scheduler.run_once()

        assert result == {"updated": 0, "skipped": 0, "errors": 0}

    # -----------------------------------------------------------------------
    # 8. Handles experiment with no variant data (uses priors)
    # -----------------------------------------------------------------------
    def test_update_experiment_handles_all_zero_counts(self):
        """Experiment with zero pulls uses equal weights (uninformative priors)."""
        db = MagicMock()
        exp_id = str(uuid.uuid4())
        mock_exp = _make_experiment(exp_id, optimization_type="thompson_sampling")
        db.query.return_value.filter.return_value.first.return_value = None

        scheduler = BanditScheduler(db=db)
        vid = str(mock_exp.variants[0].id)
        vid2 = str(mock_exp.variants[1].id)
        mock_stats = {
            vid: VariantStats(variant_id=vid),  # 0 pulls
            vid2: VariantStats(variant_id=vid2),  # 0 pulls
        }

        with patch.object(scheduler, "get_variant_stats_from_counters", return_value=mock_stats):
            result = scheduler.update_experiment(mock_exp)

        assert result is True
        db.commit.assert_called_once()

    # -----------------------------------------------------------------------
    # 9. get_variant_stats_from_counters — mocked DynamoDB fetch
    # -----------------------------------------------------------------------
    def test_get_variant_stats_from_counters_uses_dynamodb(self):
        """get_variant_stats_from_counters calls DynamoDB counter service."""
        db = MagicMock()
        scheduler = BanditScheduler(db=db)

        exp_id = uuid.uuid4()
        vid1, vid2 = str(uuid.uuid4()), str(uuid.uuid4())

        mock_counters = {
            vid1: {"assignments": 100, "conversions": 40},
            vid2: {"assignments": 100, "conversions": 20},
        }

        mock_counter_service = MagicMock()
        mock_counter_service.get_counters.return_value = mock_counters

        # DynamoDBCounterService is imported inside the function body, so we
        # patch the class at its definition site (the service module).
        with patch(
            "backend.app.services.dynamodb_counter_service.DynamoDBCounterService",
            return_value=mock_counter_service,
        ):
            # Also patch the import reference the scheduler uses at call time
            import backend.app.services.dynamodb_counter_service as _dcs
            original_cls = _dcs.DynamoDBCounterService
            _dcs.DynamoDBCounterService = lambda: mock_counter_service
            try:
                stats = scheduler.get_variant_stats_from_counters(exp_id, [vid1, vid2])
            finally:
                _dcs.DynamoDBCounterService = original_cls

        assert vid1 in stats
        assert vid2 in stats
        # conversions → successes
        assert stats[vid1].successes == 40
        assert stats[vid2].successes == 20

    # -----------------------------------------------------------------------
    # 10. estimate_regret_reduction > 0 when best variant dominates
    # -----------------------------------------------------------------------
    def test_estimate_regret_reduction_positive_when_best_dominates(self):
        """Regret reduction > 0 when bandit has concentrated weight on best variant."""
        db = MagicMock()
        scheduler = BanditScheduler(db=db)

        vid1, vid2 = "v1", "v2"
        # v1 has 80% weight and 70% conversion; v2 has 20% and 10% conversion
        weights = {vid1: 0.8, vid2: 0.2}
        variant_stats = {
            vid1: VariantStats(variant_id=vid1, successes=70, pulls=100),
            vid2: VariantStats(variant_id=vid2, successes=10, pulls=100),
        }

        reduction = scheduler.estimate_regret_reduction(weights, variant_stats)
        assert reduction > 0.0


# ===========================================================================
# TestBanditSchedulerIntegration — pure logic, no DB
# ===========================================================================

class TestBanditSchedulerIntegration:
    """Integration tests that exercise the pure MAB algorithm logic."""

    # -----------------------------------------------------------------------
    # 11. Thompson Sampling weights update when successes increase
    # -----------------------------------------------------------------------
    def test_thompson_weights_shift_toward_better_variant(self):
        """Thompson Sampling allocates more traffic to the higher-converting variant."""
        variant_data = {
            "ctrl": {"successes": 5, "failures": 95, "pulls": 100, "total_reward": 5.0},
            "trtm": {"successes": 50, "failures": 50, "pulls": 100, "total_reward": 50.0},
        }
        weights = BanditService.compute_weights("thompson_sampling", variant_data)
        assert weights["trtm"] > weights["ctrl"]

    # -----------------------------------------------------------------------
    # 12. UCB1 weights shift toward better variant over rounds
    # -----------------------------------------------------------------------
    def test_ucb1_weights_shift_toward_better_variant(self):
        """UCB1 allocates more weight to the variant with higher observed reward."""
        variant_data = {
            "ctrl": {"successes": 10, "failures": 90, "pulls": 100, "total_reward": 10.0},
            "trtm": {"successes": 80, "failures": 20, "pulls": 100, "total_reward": 80.0},
        }
        weights = BanditService.compute_weights("ucb1", variant_data)
        assert weights["trtm"] > weights["ctrl"]

    # -----------------------------------------------------------------------
    # 13. Epsilon-Greedy converges to best variant with epsilon=0.05
    # -----------------------------------------------------------------------
    def test_epsilon_greedy_converges_to_best_variant(self):
        """EpsilonGreedy assigns most traffic (1-ε) to the best variant."""
        stats = [
            VariantStats(variant_id="ctrl", successes=10, pulls=100),
            VariantStats(variant_id="trtm", successes=70, pulls=100),
        ]
        weights = EpsilonGreedy.compute_weights(stats, epsilon=0.05)
        # trtm should get (1 - 0.05) + 0.05/2 = 0.975 weight
        assert weights["trtm"] > 0.9
        assert weights["ctrl"] < 0.1

    # -----------------------------------------------------------------------
    # 14. estimate_regret_reduction > 0 vs uniform
    # -----------------------------------------------------------------------
    def test_estimate_regret_reduction_vs_uniform(self):
        """Bandit with concentrated weights beats uniform allocation."""
        db = MagicMock()
        scheduler = BanditScheduler(db=db)

        vid_a, vid_b = "a", "b"
        weights = {vid_a: 0.85, vid_b: 0.15}
        variant_stats = {
            vid_a: VariantStats(variant_id=vid_a, successes=60, pulls=100),
            vid_b: VariantStats(variant_id=vid_b, successes=10, pulls=100),
        }

        reduction = scheduler.estimate_regret_reduction(weights, variant_stats)
        assert reduction > 0.0

    # -----------------------------------------------------------------------
    # 15. estimate_regret_reduction == 0 for uniform weights
    # -----------------------------------------------------------------------
    def test_estimate_regret_reduction_zero_for_uniform_weights(self):
        """Uniform allocation produces 0% regret reduction vs itself."""
        db = MagicMock()
        scheduler = BanditScheduler(db=db)

        vid_a, vid_b = "a", "b"
        weights = {vid_a: 0.5, vid_b: 0.5}
        variant_stats = {
            vid_a: VariantStats(variant_id=vid_a, successes=30, pulls=100),
            vid_b: VariantStats(variant_id=vid_b, successes=70, pulls=100),
        }

        reduction = scheduler.estimate_regret_reduction(weights, variant_stats)
        # Uniform weights → no improvement over baseline
        assert reduction == 0.0

    # -----------------------------------------------------------------------
    # 16. All-zero counts returns equal weights
    # -----------------------------------------------------------------------
    def test_all_zero_counts_returns_equal_weights(self):
        """With no observations, non-epsilon algorithms fall back to equal weights.

        Note: EpsilonGreedy with 0 pulls assigns the exploit weight to the
        *first* arm (arbitrary tie-break on conversion_rate == 0), so only
        Thompson Sampling and UCB1 are checked for equal splits here.
        """
        variant_data = {
            "a": {"successes": 0, "failures": 0, "pulls": 0, "total_reward": 0.0},
            "b": {"successes": 0, "failures": 0, "pulls": 0, "total_reward": 0.0},
        }
        # Thompson Sampling and UCB1 produce near-equal weights with no data
        for algo in ("thompson_sampling", "ucb1"):
            weights = BanditService.compute_weights(algo, variant_data)
            assert abs(weights["a"] - weights["b"]) < 0.3, (
                f"{algo} weights not near equal: {weights}"
            )

        # EpsilonGreedy still sums to 1.0 even if not equal
        eg_weights = BanditService.compute_weights("epsilon_greedy", variant_data)
        assert abs(sum(eg_weights.values()) - 1.0) < 1e-6

    # -----------------------------------------------------------------------
    # 17. Single variant → weight = 1.0
    # -----------------------------------------------------------------------
    def test_single_variant_gets_full_weight(self):
        """With a single variant every algorithm assigns weight=1.0."""
        variant_data = {"only": {"successes": 5, "failures": 5, "pulls": 10, "total_reward": 5.0}}
        for algo in ("thompson_sampling", "ucb1", "epsilon_greedy"):
            weights = BanditService.compute_weights(algo, variant_data)
            assert weights["only"] == pytest.approx(1.0), f"{algo}: expected 1.0, got {weights}"

    # -----------------------------------------------------------------------
    # 18. get_recommendation strings
    # -----------------------------------------------------------------------
    def test_get_recommendation_deploying_when_weight_above_0_8(self):
        """Returns DEPLOYING_<name> when max weight >= 0.8."""
        db = MagicMock()
        scheduler = BanditScheduler(db=db)
        weights = {"v1": 0.85, "v2": 0.15}
        names = {"v1": "VariantA", "v2": "VariantB"}
        rec = scheduler.get_recommendation(weights, names)
        assert rec == "DEPLOYING_VariantA"

    def test_get_recommendation_converging_when_weight_0_5_to_0_8(self):
        """Returns CONVERGING when max weight is between 0.5 and 0.8."""
        db = MagicMock()
        scheduler = BanditScheduler(db=db)
        weights = {"v1": 0.6, "v2": 0.4}
        names = {"v1": "VariantA", "v2": "VariantB"}
        rec = scheduler.get_recommendation(weights, names)
        assert rec == "CONVERGING"

    def test_get_recommendation_exploring_when_weight_below_0_5(self):
        """Returns EXPLORING when no variant dominates (max weight < 0.5)."""
        db = MagicMock()
        scheduler = BanditScheduler(db=db)
        weights = {"v1": 0.45, "v2": 0.35, "v3": 0.20}
        names = {"v1": "A", "v2": "B", "v3": "C"}
        rec = scheduler.get_recommendation(weights, names)
        assert rec == "EXPLORING"
