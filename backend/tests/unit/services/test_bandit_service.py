"""
Test cases for BanditService and MAB algorithm implementations.

Tests the core multi-armed bandit algorithms:
- Thompson Sampling (Bayesian Beta-Bernoulli)
- UCB1 (Upper Confidence Bound)
- Epsilon-Greedy

Following TDD: tests written first, then implementation.
"""

import math
from typing import Dict, List

import pytest

from backend.app.services.bandit_service import (
    UCB1,
    BanditService,
    EpsilonGreedy,
    ThompsonSampling,
    VariantStats,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_stats(
    variant_id: str,
    successes: int,
    failures: int,
    pulls: int = None,
    total_reward: float = None,
) -> VariantStats:
    """Create a VariantStats instance with sensible defaults."""
    if pulls is None:
        pulls = successes + failures
    if total_reward is None:
        total_reward = float(successes)
    return VariantStats(
        variant_id=variant_id,
        successes=successes,
        failures=failures,
        pulls=pulls,
        total_reward=total_reward,
    )


# ===========================================================================
# TestThompsonSampling
# ===========================================================================


class TestThompsonSampling:
    """Tests for Thompson Sampling algorithm."""

    def test_sample_returns_list_of_floats_with_correct_length(self):
        """sample() returns a list of floats with length == num_variants."""
        alpha = [10.0, 10.0, 10.0]
        beta = [10.0, 10.0, 10.0]
        result = ThompsonSampling.sample(alpha, beta, n_samples=1000)
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(v, float) for v in result)

    def test_dominant_arm_wins_nearly_always(self):
        """Arm 0 with high alpha & low beta wins most samples."""
        # alpha=[100,1], beta=[1,100] → arm 0 has Beta(100,1) ≈ 1.0
        # arm 1 has Beta(1,100) ≈ 0.0 — arm 0 should win ≥ 99% of the time
        alpha = [100.0, 1.0]
        beta = [1.0, 100.0]
        result = ThompsonSampling.sample(alpha, beta, n_samples=5000)
        assert result[0] > 0.99, (
            f"Expected arm 0 to win > 99% of the time, got {result[0]:.4f}"
        )

    def test_uniform_prior_roughly_equal_selection(self):
        """With identical Beta(1,1) priors, all arms selected roughly equally."""
        n = 4
        alpha = [1.0] * n
        beta_vals = [1.0] * n
        result = ThompsonSampling.sample(alpha, beta_vals, n_samples=10000)
        for i, p in enumerate(result):
            assert abs(p - 1 / n) < 0.05, (
                f"Arm {i} probability {p:.4f} deviates too far from {1 / n:.4f}"
            )

    def test_sample_probabilities_sum_to_one(self):
        """Selection probabilities returned by sample() sum to 1.0."""
        alpha = [5.0, 15.0, 10.0]
        beta_vals = [15.0, 5.0, 10.0]
        result = ThompsonSampling.sample(alpha, beta_vals, n_samples=5000)
        assert abs(sum(result) - 1.0) < 1e-9

    def test_compute_weights_returns_dict_per_variant(self):
        """compute_weights() returns a dict mapping variant_id → weight."""
        stats = [
            make_stats("v0", successes=50, failures=50),
            make_stats("v1", successes=80, failures=20),
        ]
        weights = ThompsonSampling.compute_weights(stats)
        assert isinstance(weights, dict)
        assert set(weights.keys()) == {"v0", "v1"}

    def test_compute_weights_sum_to_one(self):
        """Weights from compute_weights() sum to 1.0."""
        stats = [
            make_stats("v0", successes=30, failures=70),
            make_stats("v1", successes=70, failures=30),
        ]
        weights = ThompsonSampling.compute_weights(stats)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_compute_weights_higher_success_gets_higher_weight(self):
        """Variant with more successes receives a higher allocation weight."""
        stats = [
            make_stats("v0", successes=10, failures=90),
            make_stats("v1", successes=90, failures=10),
        ]
        weights = ThompsonSampling.compute_weights(stats)
        assert weights["v1"] > weights["v0"], (
            f"v1 should outweigh v0 but got v0={weights['v0']:.4f}, v1={weights['v1']:.4f}"
        )

    def test_compute_weights_handles_zero_successes(self):
        """Handles variants with zero observations (uses uninformative prior)."""
        stats = [
            make_stats("v0", successes=0, failures=0, pulls=0, total_reward=0.0),
            make_stats("v1", successes=0, failures=0, pulls=0, total_reward=0.0),
        ]
        weights = ThompsonSampling.compute_weights(stats)
        assert abs(sum(weights.values()) - 1.0) < 1e-9
        # Both should get roughly equal weight from uniform priors
        for w in weights.values():
            assert w > 0.0

    def test_compute_weights_single_variant(self):
        """With a single variant it must receive weight 1.0."""
        stats = [make_stats("only", successes=10, failures=10)]
        weights = ThompsonSampling.compute_weights(stats)
        assert abs(weights["only"] - 1.0) < 1e-9

    def test_compute_weights_ten_variants(self):
        """Works correctly with 10 variants; weights still sum to 1."""
        stats = [
            make_stats(f"v{i}", successes=i * 5, failures=(10 - i) * 5)
            for i in range(10)
        ]
        weights = ThompsonSampling.compute_weights(stats)
        assert len(weights) == 10
        assert abs(sum(weights.values()) - 1.0) < 1e-9


# ===========================================================================
# TestUCB1
# ===========================================================================


class TestUCB1:
    """Tests for UCB1 (Upper Confidence Bound) algorithm."""

    def test_compute_scores_returns_correct_length(self):
        """compute_scores() returns a list of the same length as counts."""
        counts = [10, 20, 15]
        rewards = [5.0, 8.0, 7.0]
        total_pulls = sum(counts)
        scores = UCB1.compute_scores(counts, rewards, total_pulls)
        assert len(scores) == 3

    def test_unplayed_arm_gets_infinite_score(self):
        """An arm with count=0 receives infinity so it is tried first."""
        counts = [10, 0, 10]
        rewards = [5.0, 0.0, 5.0]
        total_pulls = 20
        scores = UCB1.compute_scores(counts, rewards, total_pulls)
        assert scores[1] == math.inf

    def test_higher_reward_rate_gives_higher_score(self):
        """Arm with higher mean reward gets a higher UCB1 score."""
        counts = [100, 100]
        # arm 1 has higher mean reward: 80/100 = 0.8 vs 20/100 = 0.2
        rewards = [20.0, 80.0]
        total_pulls = 200
        scores = UCB1.compute_scores(counts, rewards, total_pulls)
        assert scores[1] > scores[0]

    def test_exploration_bonus_decreases_with_more_pulls(self):
        """Exploration bonus sqrt(2*ln(N)/n) decreases as an arm gets pulled more."""
        # Compare two arms with same reward rate but different pull counts
        counts_few = [10, 100]
        counts_many = [100, 100]
        rewards_few = [5.0, 50.0]
        rewards_many = [50.0, 50.0]
        total_few = 110
        total_many = 200

        scores_few = UCB1.compute_scores(counts_few, rewards_few, total_few)
        scores_many = UCB1.compute_scores(counts_many, rewards_many, total_many)

        # Arm 0 has the same mean reward (0.5) but fewer pulls in the first case
        # so its exploration bonus should be larger
        assert scores_few[0] > scores_many[0]

    def test_compute_weights_sums_to_one(self):
        """compute_weights() normalises UCB1 scores so weights sum to 1."""
        stats = [
            make_stats("v0", successes=30, failures=70),
            make_stats("v1", successes=70, failures=30),
        ]
        weights = UCB1.compute_weights(stats)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_compute_weights_all_arms_played(self):
        """When all arms have been played weights reflect reward + bonus."""
        stats = [
            make_stats("v0", successes=20, failures=80),
            make_stats("v1", successes=80, failures=20),
        ]
        weights = UCB1.compute_weights(stats)
        # Higher-success variant should get a higher weight
        assert weights["v1"] > weights["v0"]

    def test_compute_weights_single_variant(self):
        """Single variant gets weight 1.0."""
        stats = [make_stats("only", successes=10, failures=10)]
        weights = UCB1.compute_weights(stats)
        assert abs(weights["only"] - 1.0) < 1e-9

    def test_total_pulls_equals_sum_of_counts(self):
        """total_pulls used internally equals sum of individual counts."""
        stats = [
            make_stats("v0", successes=40, failures=60),  # 100 pulls
            make_stats("v1", successes=60, failures=40),  # 100 pulls
        ]
        # The implementation should not raise or produce wrong results
        weights = UCB1.compute_weights(stats)
        assert abs(sum(weights.values()) - 1.0) < 1e-9


# ===========================================================================
# TestEpsilonGreedy
# ===========================================================================


class TestEpsilonGreedy:
    """Tests for Epsilon-Greedy algorithm."""

    def test_compute_weights_returns_dict_per_variant(self):
        """compute_weights() returns a dict mapping variant_id → weight."""
        stats = [
            make_stats("v0", successes=40, failures=60),
            make_stats("v1", successes=70, failures=30),
        ]
        weights = EpsilonGreedy.compute_weights(stats, epsilon=0.1)
        assert set(weights.keys()) == {"v0", "v1"}

    def test_best_variant_gets_largest_weight(self):
        """Best variant receives weight = (1 - epsilon) + epsilon/n."""
        stats = [
            make_stats("v0", successes=20, failures=80),  # mean 0.2
            make_stats("v1", successes=80, failures=20),  # mean 0.8  ← best
        ]
        epsilon = 0.1
        n = 2
        weights = EpsilonGreedy.compute_weights(stats, epsilon=epsilon)
        expected_best = (1 - epsilon) + epsilon / n
        assert abs(weights["v1"] - expected_best) < 1e-9

    def test_non_best_variants_get_epsilon_over_n(self):
        """Non-best variants each receive weight = epsilon/n."""
        stats = [
            make_stats("v0", successes=20, failures=80),
            make_stats("v1", successes=80, failures=20),
        ]
        epsilon = 0.1
        n = 2
        weights = EpsilonGreedy.compute_weights(stats, epsilon=epsilon)
        assert abs(weights["v0"] - epsilon / n) < 1e-9

    def test_weights_sum_to_one(self):
        """All weights sum to exactly 1.0."""
        stats = [
            make_stats("v0", successes=30, failures=70),
            make_stats("v1", successes=50, failures=50),
            make_stats("v2", successes=80, failures=20),
        ]
        weights = EpsilonGreedy.compute_weights(stats, epsilon=0.15)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_epsilon_zero_winner_takes_all(self):
        """With epsilon=0 the best arm gets weight 1.0, all others 0.0."""
        stats = [
            make_stats("v0", successes=10, failures=90),
            make_stats("v1", successes=90, failures=10),
        ]
        weights = EpsilonGreedy.compute_weights(stats, epsilon=0.0)
        assert abs(weights["v1"] - 1.0) < 1e-9
        assert abs(weights["v0"] - 0.0) < 1e-9

    def test_epsilon_one_pure_exploration_uniform(self):
        """With epsilon=1 all arms get equal weight (pure exploration)."""
        stats = [
            make_stats("v0", successes=10, failures=90),
            make_stats("v1", successes=90, failures=10),
            make_stats("v2", successes=50, failures=50),
        ]
        weights = EpsilonGreedy.compute_weights(stats, epsilon=1.0)
        n = 3
        for v_id, w in weights.items():
            assert abs(w - 1 / n) < 1e-9, (
                f"Variant {v_id}: expected {1 / n:.4f}, got {w:.4f}"
            )

    def test_tie_broken_by_first_variant(self):
        """When multiple arms share the best mean the first one in list wins."""
        stats = [
            make_stats("v0", successes=50, failures=50),  # mean=0.5
            make_stats("v1", successes=50, failures=50),  # mean=0.5
        ]
        epsilon = 0.1
        n = 2
        weights = EpsilonGreedy.compute_weights(stats, epsilon=epsilon)
        expected_best = (1 - epsilon) + epsilon / n
        # v0 comes first; it should win the tie
        assert abs(weights["v0"] - expected_best) < 1e-9
        assert abs(weights["v1"] - epsilon / n) < 1e-9


# ===========================================================================
# TestBanditService
# ===========================================================================


class TestBanditService:
    """Tests for the high-level BanditService dispatcher."""

    def _make_variant_data(self, specs: List[Dict]) -> Dict[str, Dict]:
        """Build variant_data dict from a list of spec dicts."""
        return {
            spec["id"]: {
                "successes": spec.get("successes", 0),
                "failures": spec.get("failures", 0),
                "pulls": spec.get(
                    "pulls", spec.get("successes", 0) + spec.get("failures", 0)
                ),
                "total_reward": spec.get(
                    "total_reward", float(spec.get("successes", 0))
                ),
            }
            for spec in specs
        }

    def test_compute_weights_dispatches_correctly(self):
        """compute_weights() returns a dict keyed by variant_id."""
        variant_data = self._make_variant_data(
            [
                {"id": "v0", "successes": 30, "failures": 70},
                {"id": "v1", "successes": 70, "failures": 30},
            ]
        )
        weights = BanditService.compute_weights("thompson_sampling", variant_data)
        assert isinstance(weights, dict)
        assert set(weights.keys()) == {"v0", "v1"}

    def test_thompson_sampling_dispatch(self):
        """algorithm='thompson_sampling' invokes Thompson Sampling path."""
        variant_data = self._make_variant_data(
            [
                {"id": "a", "successes": 10, "failures": 90},
                {"id": "b", "successes": 90, "failures": 10},
            ]
        )
        weights = BanditService.compute_weights("thompson_sampling", variant_data)
        # b should dominate substantially
        assert weights["b"] > weights["a"]

    def test_ucb1_dispatch(self):
        """algorithm='ucb1' invokes UCB1 path."""
        variant_data = self._make_variant_data(
            [
                {"id": "a", "successes": 20, "failures": 80},
                {"id": "b", "successes": 80, "failures": 20},
            ]
        )
        weights = BanditService.compute_weights("ucb1", variant_data)
        assert weights["b"] > weights["a"]

    def test_epsilon_greedy_dispatch(self):
        """algorithm='epsilon_greedy' invokes EpsilonGreedy path."""
        variant_data = self._make_variant_data(
            [
                {"id": "a", "successes": 20, "failures": 80},
                {"id": "b", "successes": 80, "failures": 20},
            ]
        )
        weights = BanditService.compute_weights("epsilon_greedy", variant_data)
        assert weights["b"] > weights["a"]

    def test_fixed_algorithm_returns_equal_weights(self):
        """algorithm='fixed' returns equal weights for all variants."""
        variant_data = self._make_variant_data(
            [
                {"id": "a", "successes": 80, "failures": 20},
                {"id": "b", "successes": 10, "failures": 90},
                {"id": "c", "successes": 50, "failures": 50},
            ]
        )
        weights = BanditService.compute_weights("fixed", variant_data)
        expected = 1 / 3
        for v_id, w in weights.items():
            assert abs(w - expected) < 1e-9, (
                f"{v_id}: expected {expected:.4f}, got {w:.4f}"
            )

    def test_variant_data_structure_is_dict_of_dicts(self):
        """variant_data format: {variant_id: {successes, failures, pulls, total_reward}}."""
        variant_data = {
            "v0": {"successes": 50, "failures": 50, "pulls": 100, "total_reward": 50.0},
            "v1": {"successes": 70, "failures": 30, "pulls": 100, "total_reward": 70.0},
        }
        weights = BanditService.compute_weights("ucb1", variant_data)
        assert set(weights.keys()) == {"v0", "v1"}

    def test_weights_sum_to_approximately_one(self):
        """All returned weights sum to approximately 1.0."""
        variant_data = self._make_variant_data(
            [
                {"id": "x", "successes": 40, "failures": 60},
                {"id": "y", "successes": 60, "failures": 40},
            ]
        )
        for algo in ["thompson_sampling", "ucb1", "epsilon_greedy", "fixed"]:
            weights = BanditService.compute_weights(algo, variant_data)
            total = sum(weights.values())
            assert abs(total - 1.0) < 1e-6, (
                f"Algorithm {algo}: weights sum to {total:.6f}"
            )

    def test_ucb1_deterministic_for_same_data(self):
        """UCB1 is deterministic: same data always yields same weights."""
        variant_data = self._make_variant_data(
            [
                {"id": "v0", "successes": 50, "failures": 50},
                {"id": "v1", "successes": 70, "failures": 30},
            ]
        )
        w1 = BanditService.compute_weights("ucb1", variant_data)
        w2 = BanditService.compute_weights("ucb1", variant_data)
        assert w1 == w2

    def test_epsilon_greedy_deterministic_for_same_data(self):
        """Epsilon-greedy is deterministic: same data yields same weights."""
        variant_data = self._make_variant_data(
            [
                {"id": "v0", "successes": 50, "failures": 50},
                {"id": "v1", "successes": 70, "failures": 30},
            ]
        )
        w1 = BanditService.compute_weights("epsilon_greedy", variant_data)
        w2 = BanditService.compute_weights("epsilon_greedy", variant_data)
        assert w1 == w2

    def test_two_variants(self):
        """Works correctly with exactly 2 variants."""
        variant_data = self._make_variant_data(
            [
                {"id": "control", "successes": 40, "failures": 60},
                {"id": "treatment", "successes": 60, "failures": 40},
            ]
        )
        weights = BanditService.compute_weights("ucb1", variant_data)
        assert len(weights) == 2
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_five_variants(self):
        """Works correctly with 5 variants."""
        variant_data = self._make_variant_data(
            [
                {"id": f"v{i}", "successes": i * 10, "failures": (5 - i) * 10}
                for i in range(5)
            ]
        )
        for algo in ["thompson_sampling", "ucb1", "epsilon_greedy", "fixed"]:
            weights = BanditService.compute_weights(algo, variant_data)
            assert len(weights) == 5
            assert abs(sum(weights.values()) - 1.0) < 1e-6
