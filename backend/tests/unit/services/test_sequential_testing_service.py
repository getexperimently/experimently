"""
Unit tests for EP-021 Sequential Testing Service.

Tests cover the SequentialTestingService which implements:
- mSPRT (mixture Sequential Probability Ratio Test)
- Always-valid confidence intervals (confidence sequences)
- Alpha spending functions (O'Brien-Fleming, Pocock)
- Evidence trajectory computation
- Long-running experiment risk detection
- Full sequential analysis integration

All tests are pure math — no mocking needed.
"""

import math
import pytest
import numpy as np

from backend.app.services.sequential_testing_service import (
    SequentialTestingService,
    MSPRTResult,
    ConfidenceSequence,
    AlphaSpendingBoundary,
    EvidencePoint,
    LongRunningRisk,
    SequentialAnalysis,
    SequentialTestingMethod,
    SpendingFunction,
    EvidenceStrength,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> SequentialTestingService:
    """Return a fresh SequentialTestingService instance."""
    return SequentialTestingService()


# ---------------------------------------------------------------------------
# TestMSPRT — 10 tests
# ---------------------------------------------------------------------------


class TestMSPRT:
    """Tests for mSPRT (mixture Sequential Probability Ratio Test)."""

    def test_equal_proportions_lambda_below_boundary(self):
        """When treatment equals control, lambda should not reach the boundary."""
        service = _make_service()
        result = service.compute_msprt(
            control_successes=100, control_total=1000,
            treatment_successes=100, treatment_total=1000,
            tau_squared=0.001,
        )
        # With equal rates, delta=0, so the exponential term is 1.
        # Lambda = sqrt(V_n / (V_n + tau^2)) <= 1, so it must be below boundary.
        assert result.lambda_ratio <= 1.0
        assert not result.can_stop

    def test_large_effect_triggers_stopping(self):
        """Clear treatment win should trigger early stopping."""
        service = _make_service()
        result = service.compute_msprt(
            control_successes=50, control_total=1000,
            treatment_successes=100, treatment_total=1000,
            tau_squared=0.001,
        )
        # boundary = 1/0.05 = 20
        assert result.lambda_ratio > 20
        assert result.can_stop

    def test_boundary_is_reciprocal_of_alpha(self):
        """The stopping boundary should equal 1/alpha."""
        service = _make_service()
        result = service.compute_msprt(
            control_successes=100, control_total=1000,
            treatment_successes=100, treatment_total=1000,
            alpha=0.01,
        )
        assert result.boundary == pytest.approx(100.0, rel=1e-9)

    def test_always_valid_p_value_range(self):
        """The always-valid p-value must lie in (0, 1]."""
        service = _make_service()
        result = service.compute_msprt(
            control_successes=80, control_total=1000,
            treatment_successes=120, treatment_total=1000,
        )
        assert 0.0 < result.always_valid_p_value <= 1.0

    def test_zero_control_samples_returns_default(self):
        """Zero control samples should return lambda_ratio=1, can_stop=False."""
        service = _make_service()
        result = service.compute_msprt(
            control_successes=0, control_total=0,
            treatment_successes=50, treatment_total=500,
        )
        assert result.lambda_ratio == 1.0
        assert not result.can_stop

    def test_zero_treatment_samples_returns_default(self):
        """Zero treatment samples should return lambda_ratio=1, can_stop=False."""
        service = _make_service()
        result = service.compute_msprt(
            control_successes=50, control_total=500,
            treatment_successes=0, treatment_total=0,
        )
        assert result.lambda_ratio == 1.0
        assert not result.can_stop

    def test_identical_rates_evidence_inconclusive(self):
        """Identical conversion rates should yield inconclusive evidence."""
        service = _make_service()
        result = service.compute_msprt(
            control_successes=200, control_total=2000,
            treatment_successes=200, treatment_total=2000,
        )
        assert result.evidence_strength == EvidenceStrength.INCONCLUSIVE

    def test_lambda_increases_with_more_data_and_true_effect(self):
        """Lambda should grow as we collect more data with a real effect."""
        service = _make_service()
        result_small = service.compute_msprt(
            control_successes=10, control_total=100,
            treatment_successes=20, treatment_total=100,
        )
        result_large = service.compute_msprt(
            control_successes=100, control_total=1000,
            treatment_successes=200, treatment_total=1000,
        )
        assert result_large.lambda_ratio > result_small.lambda_ratio

    def test_strong_evidence_for_effect(self):
        """Very strong treatment win should produce strong_for_effect."""
        service = _make_service()
        result = service.compute_msprt(
            control_successes=50, control_total=1000,
            treatment_successes=150, treatment_total=1000,
        )
        assert result.evidence_strength == EvidenceStrength.STRONG_FOR_EFFECT

    def test_custom_tau_squared_changes_result(self):
        """Different tau_squared mixing parameter should change the lambda."""
        service = _make_service()
        r1 = service.compute_msprt(
            control_successes=80, control_total=1000,
            treatment_successes=120, treatment_total=1000,
            tau_squared=0.0001,
        )
        r2 = service.compute_msprt(
            control_successes=80, control_total=1000,
            treatment_successes=120, treatment_total=1000,
            tau_squared=0.01,
        )
        assert r1.lambda_ratio != pytest.approx(r2.lambda_ratio, rel=1e-6)


# ---------------------------------------------------------------------------
# TestAlwaysValidCI — 6 tests
# ---------------------------------------------------------------------------


class TestAlwaysValidCI:
    """Tests for always-valid confidence intervals (confidence sequences)."""

    def test_ci_contains_zero_for_equal_rates(self):
        """When rates are identical the CI should contain zero."""
        service = _make_service()
        cs = service.compute_always_valid_ci(
            control_successes=100, control_total=1000,
            treatment_successes=100, treatment_total=1000,
        )
        assert cs.lower < 0.0 < cs.upper

    def test_ci_width_decreases_with_more_data(self):
        """Width of the CI should shrink as sample size grows."""
        service = _make_service()
        cs_small = service.compute_always_valid_ci(
            control_successes=10, control_total=100,
            treatment_successes=15, treatment_total=100,
        )
        cs_large = service.compute_always_valid_ci(
            control_successes=100, control_total=1000,
            treatment_successes=150, treatment_total=1000,
        )
        assert cs_large.width < cs_small.width

    def test_ci_contains_true_parameter(self):
        """For a known effect (5%), the CI should contain the true value."""
        service = _make_service()
        cs = service.compute_always_valid_ci(
            control_successes=100, control_total=1000,
            treatment_successes=150, treatment_total=1000,
        )
        true_delta = 0.15 - 0.10  # = 0.05
        assert cs.lower <= true_delta <= cs.upper

    def test_ci_is_symmetric_around_point_estimate(self):
        """The CI should be symmetric around delta_hat."""
        service = _make_service()
        cs = service.compute_always_valid_ci(
            control_successes=100, control_total=1000,
            treatment_successes=120, treatment_total=1000,
        )
        delta_hat = 0.12 - 0.10
        lower_dist = delta_hat - cs.lower
        upper_dist = cs.upper - delta_hat
        assert lower_dist == pytest.approx(upper_dist, rel=1e-6)

    def test_ci_width_equals_upper_minus_lower(self):
        """Width field should equal upper - lower."""
        service = _make_service()
        cs = service.compute_always_valid_ci(
            control_successes=50, control_total=500,
            treatment_successes=80, treatment_total=500,
        )
        assert cs.width == pytest.approx(cs.upper - cs.lower, rel=1e-9)

    def test_ci_sample_size_recorded(self):
        """The sample_size field should equal the sum of both groups."""
        service = _make_service()
        cs = service.compute_always_valid_ci(
            control_successes=50, control_total=500,
            treatment_successes=80, treatment_total=800,
        )
        assert cs.sample_size == 1300


# ---------------------------------------------------------------------------
# TestAlphaSpending — 6 tests
# ---------------------------------------------------------------------------


class TestAlphaSpending:
    """Tests for alpha spending functions."""

    def test_obf_boundaries_decrease_over_time(self):
        """O'Brien-Fleming z-boundaries should decrease as looks increase."""
        service = _make_service()
        boundaries = service.compute_alpha_spending(
            current_look=5, planned_looks=5,
            alpha=0.05, spending_function=SpendingFunction.OBRIEN_FLEMING,
        )
        z_values = [b.boundary_z for b in boundaries]
        # OBF: z-boundaries decrease over time
        for i in range(len(z_values) - 1):
            assert z_values[i] > z_values[i + 1]

    def test_pocock_boundaries_are_constant(self):
        """Pocock boundaries should be the same at every look."""
        service = _make_service()
        boundaries = service.compute_alpha_spending(
            current_look=5, planned_looks=5,
            alpha=0.05, spending_function=SpendingFunction.POCOCK,
        )
        z_values = [b.boundary_z for b in boundaries]
        for z in z_values:
            assert z == pytest.approx(z_values[0], rel=1e-6)

    def test_obf_cumulative_alpha_sums_to_alpha(self):
        """The last OBF boundary's cumulative_alpha should be close to alpha."""
        service = _make_service()
        boundaries = service.compute_alpha_spending(
            current_look=5, planned_looks=5,
            alpha=0.05, spending_function=SpendingFunction.OBRIEN_FLEMING,
        )
        # The cumulative alpha at the final look should be the total alpha
        assert boundaries[-1].cumulative_alpha == pytest.approx(0.05, abs=0.01)

    def test_pocock_cumulative_alpha_sums_to_alpha(self):
        """The last Pocock boundary's cumulative_alpha should be close to alpha."""
        service = _make_service()
        boundaries = service.compute_alpha_spending(
            current_look=5, planned_looks=5,
            alpha=0.05, spending_function=SpendingFunction.POCOCK,
        )
        assert boundaries[-1].cumulative_alpha == pytest.approx(0.05, abs=0.01)

    def test_correct_number_of_boundaries(self):
        """Number of boundaries should match current_look."""
        service = _make_service()
        boundaries = service.compute_alpha_spending(
            current_look=3, planned_looks=10,
            alpha=0.05, spending_function=SpendingFunction.OBRIEN_FLEMING,
        )
        assert len(boundaries) == 3

    def test_boundary_p_values_are_valid(self):
        """All boundary p-values should lie in (0, 1)."""
        service = _make_service()
        boundaries = service.compute_alpha_spending(
            current_look=5, planned_looks=5,
            alpha=0.05, spending_function=SpendingFunction.OBRIEN_FLEMING,
        )
        for b in boundaries:
            assert 0.0 < b.boundary_p < 1.0


# ---------------------------------------------------------------------------
# TestEvidenceTrajectory — 5 tests
# ---------------------------------------------------------------------------


class TestEvidenceTrajectory:
    """Tests for evidence trajectory computation."""

    def test_returns_correct_number_of_points(self):
        """Number of trajectory points should match the input lengths."""
        service = _make_service()
        trajectory = service.compute_evidence_trajectory(
            control_successes_over_time=[10, 20, 30],
            control_totals_over_time=[100, 200, 300],
            treatment_successes_over_time=[15, 30, 45],
            treatment_totals_over_time=[100, 200, 300],
        )
        assert len(trajectory) == 3

    def test_sample_sizes_are_cumulative_totals(self):
        """Each point's sample_size should be sum of control + treatment totals."""
        service = _make_service()
        trajectory = service.compute_evidence_trajectory(
            control_successes_over_time=[10, 20],
            control_totals_over_time=[100, 200],
            treatment_successes_over_time=[15, 30],
            treatment_totals_over_time=[100, 200],
        )
        assert trajectory[0].sample_size == 200
        assert trajectory[1].sample_size == 400

    def test_lambda_grows_under_true_effect(self):
        """Under a real effect, lambda should generally increase over time."""
        service = _make_service()
        # Simulate accumulating data with consistent 10% vs 15% conversion
        trajectory = service.compute_evidence_trajectory(
            control_successes_over_time=[10, 50, 100, 200, 500],
            control_totals_over_time=[100, 500, 1000, 2000, 5000],
            treatment_successes_over_time=[15, 75, 150, 300, 750],
            treatment_totals_over_time=[100, 500, 1000, 2000, 5000],
        )
        # The last lambda should be larger than the first
        assert trajectory[-1].lambda_ratio > trajectory[0].lambda_ratio

    def test_p_values_are_valid(self):
        """All always_valid_p_values in trajectory should be in (0, 1]."""
        service = _make_service()
        trajectory = service.compute_evidence_trajectory(
            control_successes_over_time=[10, 20, 30],
            control_totals_over_time=[100, 200, 300],
            treatment_successes_over_time=[12, 25, 40],
            treatment_totals_over_time=[100, 200, 300],
        )
        for point in trajectory:
            assert 0.0 < point.always_valid_p_value <= 1.0

    def test_eventual_stopping_with_large_effect(self):
        """With a big enough effect, trajectory should eventually flag can_stop."""
        service = _make_service()
        trajectory = service.compute_evidence_trajectory(
            control_successes_over_time=[50, 100, 250, 500],
            control_totals_over_time=[500, 1000, 2500, 5000],
            treatment_successes_over_time=[100, 200, 500, 1000],
            treatment_totals_over_time=[500, 1000, 2500, 5000],
        )
        # At least the last point should allow stopping
        assert any(p.can_stop for p in trajectory)


# ---------------------------------------------------------------------------
# TestLongRunningRisk — 4 tests
# ---------------------------------------------------------------------------


class TestLongRunningRisk:
    """Tests for long-running experiment risk detection."""

    def test_no_risk_for_healthy_experiment(self):
        """An on-track experiment should not be flagged at risk."""
        service = _make_service()
        risk = service.estimate_long_running_risk(
            actual_days=7, expected_days=14,
            current_sample_size=5000, required_sample_size=10000,
        )
        assert not risk.is_at_risk

    def test_risk_when_exceeds_duration(self):
        """Experiment running past 1.5x expected duration should be at risk."""
        service = _make_service()
        risk = service.estimate_long_running_risk(
            actual_days=30, expected_days=14,
            current_sample_size=8000, required_sample_size=10000,
        )
        assert risk.is_at_risk
        assert risk.risk_ratio > 1.5

    def test_risk_when_sample_collection_too_slow(self):
        """
        At 50%+ of expected duration with < 50% of required samples, flag risk.
        """
        service = _make_service()
        risk = service.estimate_long_running_risk(
            actual_days=10, expected_days=14,
            current_sample_size=2000, required_sample_size=10000,
        )
        assert risk.is_at_risk

    def test_risk_ratio_calculation(self):
        """Risk ratio should be actual_days / expected_days."""
        service = _make_service()
        risk = service.estimate_long_running_risk(
            actual_days=21, expected_days=14,
            current_sample_size=8000, required_sample_size=10000,
        )
        assert risk.risk_ratio == pytest.approx(21.0 / 14.0, rel=1e-6)


# ---------------------------------------------------------------------------
# TestIntegration — 4 tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration tests: full sequential analysis flow."""

    def test_full_analysis_returns_all_components(self):
        """run_sequential_analysis should return a SequentialAnalysis with all fields."""
        service = _make_service()
        config = {
            "tau_squared": 0.001,
            "alpha": 0.05,
            "spending_function": SpendingFunction.OBRIEN_FLEMING,
            "planned_looks": 5,
            "current_look": 3,
            "actual_days": 10,
            "expected_days": 14,
            "required_sample_size": 10000,
        }
        result = service.run_sequential_analysis(
            control_successes=100, control_total=1000,
            treatment_successes=120, treatment_total=1000,
            config=config,
        )
        assert isinstance(result, SequentialAnalysis)
        assert result.method == SequentialTestingMethod.MSPRT
        assert result.msprt_result is not None
        assert result.confidence_sequence is not None
        assert isinstance(result.alpha_spending, list)
        assert result.long_running_risk is not None

    def test_full_analysis_stop_for_effect(self):
        """When effect is large, recommended_action should be stop_for_effect."""
        service = _make_service()
        config = {
            "tau_squared": 0.001,
            "alpha": 0.05,
            "spending_function": SpendingFunction.OBRIEN_FLEMING,
            "planned_looks": 5,
            "current_look": 3,
            "actual_days": 7,
            "expected_days": 14,
            "required_sample_size": 10000,
        }
        result = service.run_sequential_analysis(
            control_successes=50, control_total=1000,
            treatment_successes=150, treatment_total=1000,
            config=config,
        )
        assert result.recommended_action == "stop_for_effect"

    def test_full_analysis_continue(self):
        """When effect is small and data sparse, action should be continue."""
        service = _make_service()
        config = {
            "tau_squared": 0.001,
            "alpha": 0.05,
            "spending_function": SpendingFunction.OBRIEN_FLEMING,
            "planned_looks": 10,
            "current_look": 2,
            "actual_days": 3,
            "expected_days": 30,
            "required_sample_size": 50000,
        }
        result = service.run_sequential_analysis(
            control_successes=50, control_total=500,
            treatment_successes=55, treatment_total=500,
            config=config,
        )
        assert result.recommended_action == "continue"

    def test_full_analysis_with_pocock_spending(self):
        """Full analysis should work with Pocock spending function too."""
        service = _make_service()
        config = {
            "tau_squared": 0.001,
            "alpha": 0.05,
            "spending_function": SpendingFunction.POCOCK,
            "planned_looks": 4,
            "current_look": 4,
            "actual_days": 14,
            "expected_days": 14,
            "required_sample_size": 10000,
        }
        result = service.run_sequential_analysis(
            control_successes=200, control_total=2000,
            treatment_successes=200, treatment_total=2000,
            config=config,
        )
        assert isinstance(result, SequentialAnalysis)
        assert len(result.alpha_spending) == 4
        # Equal proportions — should continue or declare futility
        assert result.recommended_action in ("continue", "stop_for_futility")
