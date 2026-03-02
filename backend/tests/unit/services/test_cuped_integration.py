"""
Integration tests for CUPED variance reduction — Issue #21.

Tests exercise the full pipeline end-to-end using simulated experiment data
with known statistical properties, verifying:
1. Variance is genuinely reduced when using a correlated covariate
2. Treatment effects are preserved (unbiased estimator)
3. Winsorization + CUPED combination works
4. Ratio metrics (CUPED++)
5. Edge cases (zero-variance covariate, small samples, large samples)
6. Consistency between individual primitives and the full pipeline
"""

import math

import numpy as np
import pytest

from backend.app.services.cuped_service import CupedEffect, CupedService


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------


def _simulate_experiment(
    n_control: int = 500,
    n_treatment: int = 500,
    true_effect: float = 0.1,
    covariate_correlation: float = 0.8,
    noise_sd: float = 0.5,
    seed: int = 42,
):
    """Generate simulated experiment data with known covariate correlation.

    Returns:
        (X_c, Y_c, X_t, Y_t) — covariate and outcome arrays for each group.
    """
    rng = np.random.default_rng(seed)

    # Pre-experiment covariate (same distribution for both groups)
    X_c = rng.normal(5.0, 1.0, n_control)
    X_t = rng.normal(5.0, 1.0, n_treatment)

    # Outcome = rho * X + sqrt(1 - rho^2) * noise + mean + effect
    rho = covariate_correlation
    sigma_noise = math.sqrt(max(0, 1.0 - rho ** 2)) * noise_sd

    Y_c = rho * (X_c - 5.0) + rng.normal(0, sigma_noise, n_control) + 5.0
    Y_t = rho * (X_t - 5.0) + rng.normal(0, sigma_noise, n_treatment) + 5.0 + true_effect

    return X_c, Y_c, X_t, Y_t


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestCupedIntegration:
    """Full-pipeline integration tests for CUPED variance reduction."""

    def test_full_pipeline_correlated_covariate(self):
        """Full pipeline with correlated covariate runs without error."""
        X_c, Y_c, X_t, Y_t = _simulate_experiment(n_control=1000, n_treatment=1000)
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert isinstance(effect, CupedEffect)
        assert math.isfinite(effect.adjusted_effect)

    def test_variance_is_reduced_after_cuped(self):
        """With a correlated covariate, variance_reduction_pct > 0."""
        X_c, Y_c, X_t, Y_t = _simulate_experiment(
            n_control=2000, n_treatment=2000, covariate_correlation=0.85
        )
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert effect.variance_reduction_pct > 0, (
            f"Expected positive variance reduction, got {effect.variance_reduction_pct:.2f}%"
        )

    def test_effect_estimate_is_preserved(self):
        """Adjusted effect ≈ true_effect (unbiased estimator property)."""
        true_effect = 0.2
        X_c, Y_c, X_t, Y_t = _simulate_experiment(
            n_control=5000,
            n_treatment=5000,
            true_effect=true_effect,
            covariate_correlation=0.7,
        )
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        # With n=5000, adjusted estimate should be within ±0.05 of true effect
        assert abs(effect.adjusted_effect - true_effect) < 0.05, (
            f"Adjusted effect {effect.adjusted_effect:.4f} far from "
            f"true effect {true_effect:.4f}"
        )

    def test_winsorization_then_cuped_pipeline(self):
        """Winsorization followed by CUPED works end-to-end."""
        rng = np.random.default_rng(10)
        n = 1000
        # Introduce outliers
        X_c = np.concatenate([rng.normal(5, 1, n - 5), [100.0] * 5])
        Y_c = np.concatenate([rng.normal(5, 1, n - 5), [500.0] * 5])
        X_t = np.concatenate([rng.normal(5, 1, n - 5), [100.0] * 5])
        Y_t = np.concatenate([rng.normal(5.1, 1, n - 5), [500.0] * 5])

        # Apply Winsorization first
        Y_c_w = CupedService.apply_winsorization(Y_c, percentile=99.0)
        Y_t_w = CupedService.apply_winsorization(Y_t, percentile=99.0)

        effect = CupedService.compute_cuped_effect(Y_c_w, X_c, Y_t_w, X_t)
        assert isinstance(effect, CupedEffect)
        # Outliers removed, so variance should be manageable
        assert effect.adjusted_se < 1.0, (
            f"SE={effect.adjusted_se:.4f} unexpectedly large after Winsorization"
        )

    def test_ratio_metrics_cuped_plus(self):
        """CUPED++ ratio metric adjustment returns a finite float."""
        rng = np.random.default_rng(11)
        n = 500
        Y_num = rng.lognormal(2.0, 0.5, n)
        Y_den = rng.lognormal(1.0, 0.3, n)
        X_num = rng.lognormal(2.0, 0.5, n)
        X_den = rng.lognormal(1.0, 0.3, n)

        ratio = CupedService.apply_cuped_ratio(Y_num, Y_den, X_num, X_den)
        assert math.isfinite(ratio)
        # Ratio should be positive (both numerator and denominator are log-normal)
        assert ratio > 0

    def test_zero_variance_covariate_no_adjustment(self):
        """With a constant covariate, theta=0 and no CUPED adjustment is applied."""
        rng = np.random.default_rng(12)
        Y_c = rng.normal(5.0, 1.0, 300)
        X_c = np.ones(300) * 3.0  # constant — zero variance
        Y_t = rng.normal(5.2, 1.0, 300)
        X_t = np.ones(300) * 3.0

        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert effect.theta == 0.0, f"Expected theta=0, got {effect.theta}"
        # Adjusted means should equal raw means
        assert abs(effect.adjusted_control_mean - Y_c.mean()) < 1e-9

    def test_small_sample_no_crash(self):
        """Very small sample (n=5) does not crash."""
        rng = np.random.default_rng(13)
        Y_c = rng.normal(5, 1, 5)
        X_c = rng.normal(5, 1, 5)
        Y_t = rng.normal(5.5, 1, 5)
        X_t = rng.normal(5, 1, 5)
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert isinstance(effect, CupedEffect)
        assert math.isfinite(effect.adjusted_effect)
        assert 0.0 <= effect.adjusted_p_value <= 1.0

    def test_high_correlation_large_variance_reduction(self):
        """High correlation (rho=0.95) leads to variance reduction > 30%."""
        X_c, Y_c, X_t, Y_t = _simulate_experiment(
            n_control=3000,
            n_treatment=3000,
            covariate_correlation=0.95,
            noise_sd=1.0,
        )
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert effect.variance_reduction_pct > 30.0, (
            f"Expected >30% variance reduction with rho=0.95, "
            f"got {effect.variance_reduction_pct:.1f}%"
        )

    def test_zero_correlation_minimal_variance_reduction(self):
        """Zero correlation (rho=0) leads to minimal variance reduction (~0%)."""
        rng = np.random.default_rng(14)
        n = 5000
        X_c = rng.normal(5, 1, n)
        Y_c = rng.normal(5, 1, n)  # independent of X
        X_t = rng.normal(5, 1, n)
        Y_t = rng.normal(5.1, 1, n)

        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        # With zero correlation, reduction should be near 0 (allow ±5% due to noise)
        assert abs(effect.variance_reduction_pct) < 5.0, (
            f"Expected ~0% variance reduction with zero correlation, "
            f"got {effect.variance_reduction_pct:.2f}%"
        )

    def test_all_cuped_effect_fields_are_finite(self):
        """All CupedEffect numeric fields are finite (no NaN or Inf)."""
        X_c, Y_c, X_t, Y_t = _simulate_experiment(n_control=500, n_treatment=500)
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)

        assert math.isfinite(effect.adjusted_control_mean), "adjusted_control_mean is not finite"
        assert math.isfinite(effect.adjusted_treatment_mean), "adjusted_treatment_mean is not finite"
        assert math.isfinite(effect.adjusted_effect), "adjusted_effect is not finite"
        assert math.isfinite(effect.adjusted_se), "adjusted_se is not finite"
        assert math.isfinite(effect.adjusted_p_value), "adjusted_p_value is not finite"
        assert math.isfinite(effect.adjusted_ci[0]), "adjusted_ci lower is not finite"
        assert math.isfinite(effect.adjusted_ci[1]), "adjusted_ci upper is not finite"
        assert math.isfinite(effect.variance_reduction_pct), "variance_reduction_pct is not finite"
        assert math.isfinite(effect.theta), "theta is not finite"

    def test_pipeline_output_matches_direct_primitives(self):
        """compute_cuped_effect matches direct compute_theta + apply_cuped calls."""
        rng = np.random.default_rng(15)
        n = 1000
        X_c = rng.normal(5, 1, n)
        Y_c = 0.8 * X_c + rng.normal(0, 0.5, n)
        X_t = rng.normal(5, 1, n)
        Y_t = 0.8 * X_t + rng.normal(0, 0.5, n) + 0.15

        # Full pipeline
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)

        # Direct computation
        theta = CupedService.compute_theta(Y_c, X_c)
        E_X = np.concatenate([X_c, X_t]).mean()
        Y_c_adj = CupedService.apply_cuped(Y_c, X_c, theta, E_X)
        Y_t_adj = CupedService.apply_cuped(Y_t, X_t, theta, E_X)

        assert abs(effect.theta - theta) < 1e-9
        assert abs(effect.adjusted_control_mean - float(Y_c_adj.mean())) < 1e-9
        assert abs(effect.adjusted_treatment_mean - float(Y_t_adj.mean())) < 1e-9

    def test_large_sample_p_value_detects_effect(self):
        """With n=10000 and a true effect, adjusted p-value < 0.05."""
        X_c, Y_c, X_t, Y_t = _simulate_experiment(
            n_control=10000,
            n_treatment=10000,
            true_effect=0.1,
            covariate_correlation=0.7,
        )
        effect = CupedService.compute_cuped_effect(Y_c, X_c, Y_t, X_t)
        assert effect.adjusted_p_value < 0.05, (
            f"Expected p < 0.05 with n=10000 and true effect=0.1, "
            f"got p={effect.adjusted_p_value:.4f}"
        )
