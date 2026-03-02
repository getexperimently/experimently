"""
Unit tests for CupedService — CUPED Variance Reduction & Advanced Statistical Methods.

Tests cover:
- compute_theta: OLS coefficient
- apply_cuped: Y - theta*(X - E[X])
- apply_winsorization: clip at percentile
- compute_cuped_effect: full CUPED pipeline
- apply_cuped_ratio: delta method for ratio metrics
"""

import math
import pytest
import numpy as np

from backend.app.services.cuped_service import CupedService, CupedEffect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> CupedService:
    return CupedService()


np.random.seed(42)


# ---------------------------------------------------------------------------
# TestComputeTheta — Tests 1–6
# ---------------------------------------------------------------------------


class TestComputeTheta:
    """Tests for compute_theta: OLS coefficient θ = Cov(Y,X) / Var(X)."""

    def test_compute_theta_basic(self):
        """compute_theta returns a finite float for typical inputs."""
        rng = np.random.default_rng(0)
        X = rng.normal(0, 1, 100)
        Y = 2.0 * X + rng.normal(0, 0.1, 100)
        theta = CupedService.compute_theta(Y, X)
        assert isinstance(theta, float)
        assert math.isfinite(theta)

    def test_theta_zero_when_uncorrelated(self):
        """θ ≈ 0 when X and Y are uncorrelated."""
        rng = np.random.default_rng(1)
        X = rng.normal(0, 1, 10000)
        Y = rng.normal(0, 1, 10000)  # independent
        theta = CupedService.compute_theta(Y, X)
        assert abs(theta) < 0.1, f"Expected theta ≈ 0, got {theta}"

    def test_theta_one_when_perfect_covariate(self):
        """θ ≈ 1.0 when X == Y (perfect covariate with same variance)."""
        X = np.linspace(0, 10, 1000)
        Y = X.copy()
        theta = CupedService.compute_theta(Y, X)
        assert abs(theta - 1.0) < 1e-9, f"Expected theta ≈ 1.0, got {theta}"

    def test_theta_scaled(self):
        """θ ≈ 2.0 when Y = 2*X (linear relationship)."""
        rng = np.random.default_rng(2)
        X = rng.normal(0, 1, 5000)
        Y = 2.0 * X  # exactly 2x
        theta = CupedService.compute_theta(Y, X)
        assert abs(theta - 2.0) < 1e-6, f"Expected theta ≈ 2.0, got {theta}"

    def test_theta_zero_variance_returns_zero(self):
        """When X has zero variance, θ should be 0 (no adjustment possible)."""
        X = np.ones(100) * 5.0  # constant — zero variance
        Y = np.random.normal(3, 1, 100)
        theta = CupedService.compute_theta(Y, X)
        assert theta == 0.0, f"Expected theta == 0.0 for zero-variance X, got {theta}"

    def test_theta_numpy_arrays(self):
        """compute_theta works with numpy arrays and returns a Python float."""
        X = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        Y = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
        theta = CupedService.compute_theta(Y, X)
        assert isinstance(theta, float)
        assert abs(theta - 2.0) < 1e-9


# ---------------------------------------------------------------------------
# TestApplyCuped — Tests 7–10
# ---------------------------------------------------------------------------


class TestApplyCuped:
    """Tests for apply_cuped: Y_cuped = Y - theta * (X - E[X])."""

    def test_apply_cuped_formula(self):
        """apply_cuped implements Y - θ*(X - E[X]) correctly."""
        Y = np.array([1.0, 2.0, 3.0])
        X = np.array([1.0, 2.0, 3.0])
        theta = 1.0
        E_X = 2.0
        result = CupedService.apply_cuped(Y, X, theta, E_X)
        expected = Y - theta * (X - E_X)
        np.testing.assert_allclose(result, expected)

    def test_apply_cuped_mean_preserved(self):
        """CUPED-adjusted mean equals unadjusted mean (bias-free property)."""
        rng = np.random.default_rng(3)
        Y = rng.normal(5.0, 2.0, 1000)
        X = rng.normal(0.0, 1.0, 1000)
        theta = CupedService.compute_theta(Y, X)
        E_X = X.mean()
        Y_adj = CupedService.apply_cuped(Y, X, theta, E_X)
        assert abs(Y_adj.mean() - Y.mean()) < 1e-9, (
            f"Adjusted mean {Y_adj.mean()} != original mean {Y.mean()}"
        )

    def test_apply_cuped_variance_reduced(self):
        """CUPED-adjusted variance is lower when X and Y are correlated."""
        rng = np.random.default_rng(4)
        X = rng.normal(0, 1, 5000)
        noise = rng.normal(0, 0.5, 5000)
        Y = 1.5 * X + noise  # strong correlation
        theta = CupedService.compute_theta(Y, X)
        E_X = X.mean()
        Y_adj = CupedService.apply_cuped(Y, X, theta, E_X)
        assert Y_adj.var() < Y.var(), (
            f"Expected Var(adjusted)={Y_adj.var():.4f} < Var(original)={Y.var():.4f}"
        )

    def test_apply_cuped_numpy_arrays(self):
        """apply_cuped works with numpy arrays and returns a numpy array."""
        Y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        X = np.array([0.5, 1.0, 1.5, 2.0, 2.5])
        theta = 0.5
        E_X = X.mean()
        result = CupedService.apply_cuped(Y, X, theta, E_X)
        assert isinstance(result, np.ndarray)
        assert len(result) == len(Y)


# ---------------------------------------------------------------------------
# TestApplyWinsorization — Tests 11–16
# ---------------------------------------------------------------------------


class TestApplyWinsorization:
    """Tests for apply_winsorization: clip values at the given percentile."""

    def test_winsorization_clips_at_99th(self):
        """Values above the 99th percentile are clipped."""
        values = np.array([1.0] * 99 + [1000.0])
        result = CupedService.apply_winsorization(values, percentile=99.0)
        # The 1000.0 value should be clipped to the 99th percentile
        p99 = np.percentile(values, 99)
        assert result[-1] <= p99

    def test_winsorization_below_percentile_unchanged(self):
        """Values below the percentile are unchanged."""
        values = np.arange(1.0, 101.0)
        result = CupedService.apply_winsorization(values, percentile=99.0)
        p99 = np.percentile(values, 99)
        # Values that were below p99 remain the same
        mask = values < p99
        np.testing.assert_allclose(result[mask], values[mask])

    def test_winsorization_default_percentile_99(self):
        """Default percentile is 99."""
        values = np.array(list(range(100)) + [9999.0])
        result_default = CupedService.apply_winsorization(values)
        result_99 = CupedService.apply_winsorization(values, percentile=99.0)
        np.testing.assert_allclose(result_default, result_99)

    def test_winsorization_percentile_100_no_clipping(self):
        """percentile=100 means no clipping — all values unchanged."""
        values = np.array([1.0, 2.0, 100.0, 1000.0, 99999.0])
        result = CupedService.apply_winsorization(values, percentile=100.0)
        np.testing.assert_allclose(result, values)

    def test_winsorization_percentile_50_clips_at_median(self):
        """percentile=50 clips at the median value."""
        values = np.arange(1.0, 101.0)
        result = CupedService.apply_winsorization(values, percentile=50.0)
        median = np.percentile(values, 50)
        assert result.max() <= median + 1e-9, (
            f"Expected all values <= median ({median}), max is {result.max()}"
        )

    def test_winsorization_returns_numpy_array(self):
        """apply_winsorization returns a numpy array."""
        values = np.array([1.0, 2.0, 3.0])
        result = CupedService.apply_winsorization(values)
        assert isinstance(result, np.ndarray)


# ---------------------------------------------------------------------------
# TestComputeCupedEffect — Tests 17–26
# ---------------------------------------------------------------------------


class TestComputeCupedEffect:
    """Tests for compute_cuped_effect: full CUPED pipeline."""

    def _make_correlated_data(self, n=500, effect=0.1, rho=0.8, seed=42):
        """Generate control/treatment data with a correlated covariate."""
        rng = np.random.default_rng(seed)
        X_control = rng.normal(5.0, 1.0, n)
        noise_c = rng.normal(0, math.sqrt(1 - rho ** 2), n)
        Y_control = rho * (X_control - 5.0) + noise_c + 5.0

        X_treatment = rng.normal(5.0, 1.0, n)
        noise_t = rng.normal(0, math.sqrt(1 - rho ** 2), n)
        Y_treatment = rho * (X_treatment - 5.0) + noise_t + 5.0 + effect
        return X_control, Y_control, X_treatment, Y_treatment

    def test_compute_cuped_effect_returns_cuped_effect(self):
        """compute_cuped_effect returns a CupedEffect dataclass."""
        X_c, Y_c, X_t, Y_t = self._make_correlated_data()
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert isinstance(effect, CupedEffect)

    def test_cuped_effect_has_all_fields(self):
        """CupedEffect has all required fields."""
        X_c, Y_c, X_t, Y_t = self._make_correlated_data()
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert hasattr(effect, "adjusted_control_mean")
        assert hasattr(effect, "adjusted_treatment_mean")
        assert hasattr(effect, "adjusted_effect")
        assert hasattr(effect, "adjusted_se")
        assert hasattr(effect, "adjusted_p_value")
        assert hasattr(effect, "adjusted_ci")
        assert hasattr(effect, "variance_reduction_pct")
        assert hasattr(effect, "theta")

    def test_variance_reduction_pct_formula(self):
        """variance_reduction_pct = 1 - Var(adjusted) / Var(original) for control."""
        rng = np.random.default_rng(5)
        X_c = rng.normal(5, 1, 1000)
        Y_c = 0.9 * X_c + rng.normal(0, 0.5, 1000)
        X_t = rng.normal(5, 1, 1000)
        Y_t = 0.9 * X_t + rng.normal(0, 0.5, 1000) + 0.1
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        # Compute expected reduction manually
        theta = CupedService.compute_theta(Y_c, X_c)
        E_X = np.concatenate([X_c, X_t]).mean()
        Y_c_adj = CupedService.apply_cuped(Y_c, X_c, theta, E_X)
        expected_reduction = 1.0 - Y_c_adj.var() / Y_c.var()
        assert abs(effect.variance_reduction_pct - expected_reduction * 100) < 1.0

    def test_adjusted_effect_equals_diff_of_adjusted_means(self):
        """adjusted_effect = adjusted_treatment_mean - adjusted_control_mean."""
        X_c, Y_c, X_t, Y_t = self._make_correlated_data()
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        diff = effect.adjusted_treatment_mean - effect.adjusted_control_mean
        assert abs(effect.adjusted_effect - diff) < 1e-9

    def test_adjusted_se_positive(self):
        """adjusted_se is a positive finite number."""
        X_c, Y_c, X_t, Y_t = self._make_correlated_data()
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert effect.adjusted_se > 0
        assert math.isfinite(effect.adjusted_se)

    def test_adjusted_p_value_in_range(self):
        """adjusted_p_value is in [0, 1]."""
        X_c, Y_c, X_t, Y_t = self._make_correlated_data()
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert 0.0 <= effect.adjusted_p_value <= 1.0

    def test_adjusted_ci_is_tuple(self):
        """adjusted_ci is a tuple of (lower, upper) with lower < upper."""
        X_c, Y_c, X_t, Y_t = self._make_correlated_data()
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        lower, upper = effect.adjusted_ci
        assert lower < upper

    def test_zero_variance_covariate_no_adjustment(self):
        """When covariate has zero variance, theta=0 and no adjustment occurs."""
        rng = np.random.default_rng(6)
        Y_c = rng.normal(5.0, 1.0, 200)
        X_c = np.ones(200) * 3.0  # constant covariate
        Y_t = rng.normal(5.1, 1.0, 200)
        X_t = np.ones(200) * 3.0
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        # theta should be 0 → adjusted means ≈ original means
        assert effect.theta == 0.0
        assert abs(effect.adjusted_control_mean - Y_c.mean()) < 1e-9

    def test_cuped_reduces_variance_with_correlated_covariate(self):
        """With a highly correlated covariate, variance reduction pct > 0."""
        X_c, Y_c, X_t, Y_t = self._make_correlated_data(n=1000, rho=0.9)
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert effect.variance_reduction_pct > 0

    def test_small_sample_works(self):
        """compute_cuped_effect works on small samples (n=10)."""
        rng = np.random.default_rng(7)
        Y_c = rng.normal(5, 1, 10)
        X_c = rng.normal(5, 1, 10)
        Y_t = rng.normal(5.2, 1, 10)
        X_t = rng.normal(5, 1, 10)
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert isinstance(effect, CupedEffect)
        assert math.isfinite(effect.adjusted_effect)

    def test_large_sample_works(self):
        """compute_cuped_effect works on large samples (n=10000)."""
        rng = np.random.default_rng(8)
        n = 10000
        X_c = rng.normal(5, 1, n)
        Y_c = 0.8 * X_c + rng.normal(0, 0.5, n)
        X_t = rng.normal(5, 1, n)
        Y_t = 0.8 * X_t + rng.normal(0, 0.5, n) + 0.1
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert isinstance(effect, CupedEffect)
        # With large n and a real effect, p-value should be small
        assert effect.adjusted_p_value < 0.05


# ---------------------------------------------------------------------------
# TestApplyCupedRatio — Tests 27–29
# ---------------------------------------------------------------------------


class TestApplyCupedRatio:
    """Tests for apply_cuped_ratio: delta method adjustment for ratio metrics."""

    def test_apply_cuped_ratio_returns_float(self):
        """apply_cuped_ratio returns a finite float ratio estimate."""
        rng = np.random.default_rng(9)
        n = 500
        Y_num = rng.normal(10, 1, n)
        Y_den = rng.normal(5, 0.5, n)
        X_num = rng.normal(10, 1, n)
        X_den = rng.normal(5, 0.5, n)
        result = CupedService.apply_cuped_ratio(Y_num, Y_den, X_num, X_den)
        assert isinstance(result, float)
        assert math.isfinite(result)

    def test_apply_cuped_ratio_delta_method(self):
        """Effect equals mean(Y_num)/mean(Y_den) as base ratio estimate."""
        rng = np.random.default_rng(10)
        n = 1000
        Y_num_c = rng.normal(10, 1, n)
        Y_den_c = rng.normal(5, 0.5, n)
        X_num_c = rng.normal(10, 1, n)
        X_den_c = rng.normal(5, 0.5, n)
        result = CupedService.apply_cuped_ratio(Y_num_c, Y_den_c, X_num_c, X_den_c)
        # Result should be a reasonable ratio (around 2.0 here)
        base_ratio = Y_num_c.mean() / Y_den_c.mean()
        assert abs(result - base_ratio) < 1.0  # within plausible range

    def test_apply_cuped_ratio_finite_with_noise(self):
        """apply_cuped_ratio handles noisy ratio data without crashing."""
        rng = np.random.default_rng(11)
        n = 200
        Y_num = rng.lognormal(0, 1, n)
        Y_den = rng.lognormal(0, 0.5, n)
        X_num = rng.lognormal(0, 1, n)
        X_den = rng.lognormal(0, 0.5, n)
        result = CupedService.apply_cuped_ratio(Y_num, Y_den, X_num, X_den)
        assert math.isfinite(result)
