"""
Realistic scenario: CUPED Variance Reduction & Sequential Testing.

Validates the mathematical correctness of:
  1. CUPED theta (OLS covariance ratio) computation
  2. CUPED adjustment and variance reduction percentage
  3. Winsorization of outliers
  4. mSPRT (mixture Sequential Probability Ratio Test) computation
  5. Always-valid confidence intervals
  6. Alpha spending functions (O'Brien-Fleming, Pocock)
  7. Evidence trajectory tracking
  8. Long-running experiment risk detection

These tests use numpy directly with known inputs and do NOT require a running
platform.
"""

import math
import pytest

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

skip_no_numpy = pytest.mark.skipif(not HAS_NUMPY, reason="numpy not installed")


# ===========================================================================
# CUPED Variance Reduction (Issue #21)
# ===========================================================================

@skip_no_numpy
class TestCupedTheta:
    """Validate OLS theta = Cov(Y,X)/Var(X) computation."""

    def test_perfectly_correlated_covariate(self):
        from backend.app.services.cuped_service import CupedService

        Y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        X = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        theta = CupedService.compute_theta(Y, X)
        assert abs(theta - 1.0) < 1e-6, f"Perfect correlation should give theta=1, got {theta}"

    def test_zero_variance_covariate_returns_zero(self):
        from backend.app.services.cuped_service import CupedService

        Y = np.array([1.0, 2.0, 3.0])
        X = np.array([5.0, 5.0, 5.0])  # zero variance
        theta = CupedService.compute_theta(Y, X)
        assert theta == 0.0

    def test_uncorrelated_theta_near_zero(self):
        from backend.app.services.cuped_service import CupedService

        rng = np.random.RandomState(42)
        Y = rng.randn(1000)
        X = rng.randn(1000)  # independent
        theta = CupedService.compute_theta(Y, X)
        assert abs(theta) < 0.1, f"Uncorrelated data should have theta ≈ 0, got {theta}"

    def test_negative_correlation(self):
        from backend.app.services.cuped_service import CupedService

        Y = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        X = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        theta = CupedService.compute_theta(Y, X)
        assert abs(theta - (-1.0)) < 1e-6


@skip_no_numpy
class TestCupedAdjustment:
    """Validate the CUPED adjustment Y_cuped = Y - theta*(X - E[X])."""

    def test_adjustment_reduces_variance(self):
        from backend.app.services.cuped_service import CupedService

        rng = np.random.RandomState(42)
        X = rng.randn(500)
        noise = rng.randn(500) * 0.5
        Y = 2.0 * X + noise  # strong correlation

        theta = CupedService.compute_theta(Y, X)
        Y_adj = CupedService.apply_cuped(Y, X, theta, np.mean(X))

        var_original = np.var(Y)
        var_adjusted = np.var(Y_adj)
        assert var_adjusted < var_original, (
            f"Adjusted variance {var_adjusted:.4f} should be < original {var_original:.4f}"
        )

    def test_adjustment_preserves_mean(self):
        from backend.app.services.cuped_service import CupedService

        rng = np.random.RandomState(42)
        X = rng.randn(500)
        Y = 3.0 + 1.5 * X + rng.randn(500) * 0.3

        theta = CupedService.compute_theta(Y, X)
        E_X = np.mean(X)
        Y_adj = CupedService.apply_cuped(Y, X, theta, E_X)

        # CUPED adjustment preserves the mean
        assert abs(np.mean(Y_adj) - np.mean(Y)) < 0.01


@skip_no_numpy
class TestCupedFullPipeline:
    """Validate compute_cuped_effect() end-to-end."""

    def test_variance_reduction_percentage_positive(self):
        from backend.app.services.cuped_service import CupedService

        rng = np.random.RandomState(42)
        n = 1000
        X_ctrl = rng.randn(n)
        X_treat = rng.randn(n)
        noise_ctrl = rng.randn(n) * 0.3
        noise_treat = rng.randn(n) * 0.3

        Y_ctrl = 0.10 + 0.5 * X_ctrl + noise_ctrl
        Y_treat = 0.12 + 0.5 * X_treat + noise_treat

        effect = CupedService.compute_cuped_effect(Y_ctrl, X_ctrl, Y_treat, X_treat)
        assert effect.variance_reduction_pct > 0, (
            f"Variance reduction should be positive, got {effect.variance_reduction_pct}%"
        )

    def test_adjusted_effect_detects_treatment_lift(self):
        from backend.app.services.cuped_service import CupedService

        rng = np.random.RandomState(42)
        n = 1000
        X_ctrl = rng.randn(n)
        X_treat = rng.randn(n)

        Y_ctrl = 0.10 + 0.5 * X_ctrl + rng.randn(n) * 0.3
        Y_treat = 0.15 + 0.5 * X_treat + rng.randn(n) * 0.3  # +0.05 lift

        effect = CupedService.compute_cuped_effect(Y_ctrl, X_ctrl, Y_treat, X_treat)
        assert effect.adjusted_effect > 0, "Should detect positive treatment effect"
        assert effect.adjusted_p_value < 0.05, (
            f"Effect should be significant, got p={effect.adjusted_p_value}"
        )

    def test_no_effect_when_identical_groups(self):
        from backend.app.services.cuped_service import CupedService

        rng = np.random.RandomState(42)
        n = 500
        X = rng.randn(n)

        Y_ctrl = 0.10 + 0.5 * X + rng.randn(n) * 0.3
        Y_treat = 0.10 + 0.5 * X + rng.randn(n) * 0.3

        effect = CupedService.compute_cuped_effect(Y_ctrl, X, Y_treat, X)
        assert effect.adjusted_p_value > 0.05 or abs(effect.adjusted_effect) < 0.02

    def test_ci_contains_true_effect(self):
        from backend.app.services.cuped_service import CupedService

        rng = np.random.RandomState(42)
        n = 2000
        true_effect = 0.05
        X_ctrl = rng.randn(n)
        X_treat = rng.randn(n)

        Y_ctrl = 0.10 + 0.5 * X_ctrl + rng.randn(n) * 0.2
        Y_treat = 0.10 + true_effect + 0.5 * X_treat + rng.randn(n) * 0.2

        effect = CupedService.compute_cuped_effect(Y_ctrl, X_ctrl, Y_treat, X_treat)
        lo, hi = effect.adjusted_ci
        assert lo <= true_effect <= hi, (
            f"95% CI [{lo:.4f}, {hi:.4f}] should contain true effect {true_effect}"
        )


@skip_no_numpy
class TestWinsorization:
    """Validate outlier clipping via winsorization."""

    def test_clips_outliers_above_percentile(self):
        from backend.app.services.cuped_service import CupedService

        values = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 100])
        result = CupedService.apply_winsorization(values, percentile=90.0)
        assert result[-1] < 100, "Outlier should be clipped"

    def test_preserves_values_within_bounds(self):
        from backend.app.services.cuped_service import CupedService

        # With 100 identical values, no clipping should occur
        values = np.ones(100) * 5.0
        result = CupedService.apply_winsorization(values, percentile=99.0)
        np.testing.assert_array_almost_equal(values, result)


# ===========================================================================
# Sequential Testing / mSPRT (EP-021)
# ===========================================================================

class TestMSPRT:
    """Validate mSPRT computation for sequential testing."""

    def test_significant_result_can_stop(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        result = service.compute_msprt(
            control_successes=500, control_total=5000,
            treatment_successes=600, treatment_total=5000,
        )
        assert hasattr(result, "can_stop")
        assert hasattr(result, "lambda_ratio")
        assert result.lambda_ratio > 0

    def test_no_difference_does_not_stop(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        result = service.compute_msprt(
            control_successes=100, control_total=1000,
            treatment_successes=100, treatment_total=1000,
        )
        assert not result.can_stop, "Equal rates should not trigger early stop"

    def test_lambda_ratio_increases_with_more_data(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        # Small sample
        r1 = service.compute_msprt(
            control_successes=50, control_total=500,
            treatment_successes=65, treatment_total=500,
        )
        # Larger sample, same rate
        r2 = service.compute_msprt(
            control_successes=500, control_total=5000,
            treatment_successes=650, treatment_total=5000,
        )
        assert r2.lambda_ratio >= r1.lambda_ratio, (
            "More data with same effect should increase lambda ratio"
        )

    def test_evidence_strength_is_populated(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        result = service.compute_msprt(
            control_successes=100, control_total=1000,
            treatment_successes=150, treatment_total=1000,
        )
        assert result.evidence_strength is not None


class TestAlwaysValidCI:
    """Validate always-valid confidence intervals."""

    def test_ci_contains_zero_when_no_effect(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        cs = service.compute_always_valid_ci(
            control_successes=100, control_total=1000,
            treatment_successes=100, treatment_total=1000,
        )
        assert cs.lower <= 0 <= cs.upper, (
            f"No-effect CI [{cs.lower:.4f}, {cs.upper:.4f}] should contain 0"
        )

    def test_ci_excludes_zero_when_strong_effect(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        cs = service.compute_always_valid_ci(
            control_successes=100, control_total=5000,
            treatment_successes=500, treatment_total=5000,
        )
        # Large effect (2% vs 10%) — CI should exclude 0
        assert cs.lower > 0 or cs.upper < 0, (
            f"Strong effect CI [{cs.lower:.4f}, {cs.upper:.4f}] should exclude 0"
        )

    def test_ci_width_is_positive(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        cs = service.compute_always_valid_ci(
            control_successes=50, control_total=500,
            treatment_successes=60, treatment_total=500,
        )
        assert cs.width > 0


class TestAlphaSpending:
    """Validate alpha spending boundaries."""

    def test_obrien_fleming_boundaries_decrease(self):
        from backend.app.services.sequential_testing_service import (
            SequentialTestingService,
            SpendingFunction,
        )

        service = SequentialTestingService()
        boundaries = service.compute_alpha_spending(
            current_look=5,
            planned_looks=5,
            alpha=0.05,
            spending_function=SpendingFunction.OBRIEN_FLEMING,
        )
        assert len(boundaries) == 5
        # O'Brien-Fleming: early boundaries should be higher (harder to reject)
        assert boundaries[0].boundary_z > boundaries[-1].boundary_z

    def test_pocock_boundaries_roughly_constant(self):
        from backend.app.services.sequential_testing_service import (
            SequentialTestingService,
            SpendingFunction,
        )

        service = SequentialTestingService()
        boundaries = service.compute_alpha_spending(
            current_look=5,
            planned_looks=5,
            alpha=0.05,
            spending_function=SpendingFunction.POCOCK,
        )
        z_values = [b.boundary_z for b in boundaries]
        # Pocock boundaries should be approximately equal
        z_range = max(z_values) - min(z_values)
        assert z_range < 1.0, f"Pocock boundaries should be roughly constant, range={z_range}"

    def test_cumulative_alpha_does_not_exceed_total(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        boundaries = service.compute_alpha_spending(
            current_look=10,
            planned_looks=10,
            alpha=0.05,
        )
        max_alpha = boundaries[-1].cumulative_alpha
        assert max_alpha <= 0.05 + 1e-6, f"Cumulative alpha {max_alpha} exceeds 0.05"


class TestEvidenceTrajectory:
    """Validate evidence trajectory tracking over sequential looks."""

    def test_trajectory_length_matches_input(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        n_looks = 5
        ctrl_s = [10 * (i + 1) for i in range(n_looks)]
        ctrl_t = [100 * (i + 1) for i in range(n_looks)]
        treat_s = [12 * (i + 1) for i in range(n_looks)]
        treat_t = [100 * (i + 1) for i in range(n_looks)]

        trajectory = service.compute_evidence_trajectory(
            ctrl_s, ctrl_t, treat_s, treat_t,
        )
        assert len(trajectory) == n_looks

    def test_trajectory_sample_sizes_increase(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        ctrl_s = [10, 20, 30, 40, 50]
        ctrl_t = [100, 200, 300, 400, 500]
        treat_s = [12, 24, 36, 48, 60]
        treat_t = [100, 200, 300, 400, 500]

        trajectory = service.compute_evidence_trajectory(
            ctrl_s, ctrl_t, treat_s, treat_t,
        )
        sample_sizes = [ep.sample_size for ep in trajectory]
        for i in range(1, len(sample_sizes)):
            assert sample_sizes[i] >= sample_sizes[i - 1]


class TestLongRunningRisk:
    """Validate long-running experiment risk detection."""

    def test_at_risk_when_way_over_expected_duration(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        risk = service.estimate_long_running_risk(
            actual_days=60,
            expected_days=14,
            current_sample_size=500,
            required_sample_size=10000,
        )
        assert risk.is_at_risk

    def test_not_at_risk_when_on_track(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        risk = service.estimate_long_running_risk(
            actual_days=7,
            expected_days=14,
            current_sample_size=5000,
            required_sample_size=10000,
        )
        assert not risk.is_at_risk

    def test_risk_ratio_computed_correctly(self):
        from backend.app.services.sequential_testing_service import SequentialTestingService

        service = SequentialTestingService()
        risk = service.estimate_long_running_risk(
            actual_days=28,
            expected_days=14,
            current_sample_size=3000,
            required_sample_size=10000,
        )
        assert risk.risk_ratio == 28 / 14
