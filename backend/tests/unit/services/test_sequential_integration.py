"""
Integration tests for EP-021 Sequential Testing Service (Batch 5).

Tests the end-to-end orchestration of SequentialTestingService.run_sequential_analysis()
including correct sub-method wiring, result structure completeness, edge cases,
recommended_action logic, alpha spending monotonicity, evidence trajectory ordering,
and confidence sequence narrowing.

All tests are pure computation -- no database or mocking required.
"""

import math

import pytest

from backend.app.services.sequential_testing_service import (
    AlphaSpendingBoundary,
    ConfidenceSequence,
    EvidencePoint,
    EvidenceStrength,
    LongRunningRisk,
    MSPRTResult,
    SequentialAnalysis,
    SequentialTestingMethod,
    SequentialTestingService,
    SpendingFunction,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Return a fresh SequentialTestingService instance."""
    return SequentialTestingService()


@pytest.fixture
def default_config():
    """Standard config for run_sequential_analysis."""
    return {
        "tau_squared": 0.001,
        "alpha": 0.05,
        "spending_function": SpendingFunction.OBRIEN_FLEMING,
        "planned_looks": 5,
        "current_look": 3,
        "actual_days": 7,
        "expected_days": 14,
        "required_sample_size": 10000,
    }


# ---------------------------------------------------------------------------
# 1. Orchestration: run_sequential_analysis wires all sub-methods correctly
# ---------------------------------------------------------------------------


class TestRunSequentialAnalysisOrchestration:
    """Verify that run_sequential_analysis orchestrates every sub-method."""

    def test_all_fields_populated(self, service, default_config):
        """Every field in the returned SequentialAnalysis must be non-None."""
        result = service.run_sequential_analysis(
            control_successes=100,
            control_total=1000,
            treatment_successes=130,
            treatment_total=1000,
            config=default_config,
        )
        assert isinstance(result, SequentialAnalysis)
        assert result.method == SequentialTestingMethod.MSPRT
        assert result.msprt_result is not None
        assert isinstance(result.msprt_result, MSPRTResult)
        assert result.confidence_sequence is not None
        assert isinstance(result.confidence_sequence, ConfidenceSequence)
        assert isinstance(result.evidence_trajectory, list)
        assert len(result.evidence_trajectory) >= 1
        assert isinstance(result.evidence_trajectory[0], EvidencePoint)
        assert isinstance(result.alpha_spending, list)
        assert len(result.alpha_spending) == default_config["current_look"]
        assert all(isinstance(b, AlphaSpendingBoundary) for b in result.alpha_spending)
        assert result.long_running_risk is not None
        assert isinstance(result.long_running_risk, LongRunningRisk)
        assert result.recommended_action in (
            "stop_for_effect",
            "stop_for_futility",
            "continue",
        )

    def test_msprt_result_matches_direct_call(self, service, default_config):
        """mSPRT result from run_sequential_analysis should match a direct call."""
        control_s, control_t = 100, 1000
        treatment_s, treatment_t = 130, 1000

        full_result = service.run_sequential_analysis(
            control_successes=control_s,
            control_total=control_t,
            treatment_successes=treatment_s,
            treatment_total=treatment_t,
            config=default_config,
        )
        direct_msprt = service.compute_msprt(
            control_successes=control_s,
            control_total=control_t,
            treatment_successes=treatment_s,
            treatment_total=treatment_t,
            tau_squared=default_config["tau_squared"],
            alpha=default_config["alpha"],
        )
        assert full_result.msprt_result.lambda_ratio == pytest.approx(
            direct_msprt.lambda_ratio, rel=1e-9
        )
        assert full_result.msprt_result.always_valid_p_value == pytest.approx(
            direct_msprt.always_valid_p_value, rel=1e-9
        )
        assert full_result.msprt_result.can_stop == direct_msprt.can_stop
        assert (
            full_result.msprt_result.evidence_strength == direct_msprt.evidence_strength
        )

    def test_confidence_sequence_matches_direct_call(self, service, default_config):
        """Confidence sequence from orchestrator should match direct computation."""
        control_s, control_t = 80, 1000
        treatment_s, treatment_t = 120, 1000

        full_result = service.run_sequential_analysis(
            control_successes=control_s,
            control_total=control_t,
            treatment_successes=treatment_s,
            treatment_total=treatment_t,
            config=default_config,
        )
        direct_cs = service.compute_always_valid_ci(
            control_successes=control_s,
            control_total=control_t,
            treatment_successes=treatment_s,
            treatment_total=treatment_t,
            alpha=default_config["alpha"],
            tau_squared=default_config["tau_squared"],
        )
        assert full_result.confidence_sequence.lower == pytest.approx(
            direct_cs.lower, rel=1e-9
        )
        assert full_result.confidence_sequence.upper == pytest.approx(
            direct_cs.upper, rel=1e-9
        )
        assert full_result.confidence_sequence.width == pytest.approx(
            direct_cs.width, rel=1e-9
        )

    def test_evidence_trajectory_has_single_point_from_orchestrator(
        self, service, default_config
    ):
        """run_sequential_analysis should produce a single-point evidence trajectory
        built from the current data snapshot."""
        result = service.run_sequential_analysis(
            control_successes=100,
            control_total=1000,
            treatment_successes=130,
            treatment_total=1000,
            config=default_config,
        )
        assert len(result.evidence_trajectory) == 1
        point = result.evidence_trajectory[0]
        assert point.sample_size == 2000
        assert point.lambda_ratio == result.msprt_result.lambda_ratio
        assert point.always_valid_p_value == result.msprt_result.always_valid_p_value
        assert point.can_stop == result.msprt_result.can_stop


# ---------------------------------------------------------------------------
# 2. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: tiny samples, zero conversions, degenerate inputs."""

    def test_very_small_sample_sizes(self, service):
        """With only a handful of observations, the analysis should not crash
        and should recommend 'continue'."""
        # Use a config where the experiment is very early in its lifecycle
        # so the long-running risk check does not trigger futility.
        early_config = {
            "tau_squared": 0.001,
            "alpha": 0.05,
            "spending_function": SpendingFunction.OBRIEN_FLEMING,
            "planned_looks": 10,
            "current_look": 1,
            "actual_days": 1,
            "expected_days": 30,
            "required_sample_size": 10000,
        }
        result = service.run_sequential_analysis(
            control_successes=1,
            control_total=5,
            treatment_successes=2,
            treatment_total=5,
            config=early_config,
        )
        assert isinstance(result, SequentialAnalysis)
        # Tiny samples yield near-zero information; should not stop
        assert result.recommended_action == "continue"
        assert not result.msprt_result.can_stop

    def test_zero_conversions_both_groups(self, service, default_config):
        """When neither group has any conversions, V_n = 0 so the degenerate
        branch should fire and return inconclusive."""
        result = service.run_sequential_analysis(
            control_successes=0,
            control_total=500,
            treatment_successes=0,
            treatment_total=500,
            config=default_config,
        )
        assert result.msprt_result.lambda_ratio == 1.0
        assert result.msprt_result.evidence_strength == EvidenceStrength.INCONCLUSIVE
        assert not result.msprt_result.can_stop

    def test_equal_conversion_rates_large_sample(self, service, default_config):
        """Equal conversion rates with large samples: lambda should stay below
        boundary and CI should straddle zero."""
        result = service.run_sequential_analysis(
            control_successes=500,
            control_total=5000,
            treatment_successes=500,
            treatment_total=5000,
            config=default_config,
        )
        assert result.msprt_result.lambda_ratio < result.msprt_result.boundary
        assert not result.msprt_result.can_stop
        # CI should contain 0
        assert result.confidence_sequence.lower < 0.0 < result.confidence_sequence.upper

    def test_very_large_lambda_ratio(self, service, default_config):
        """An extreme difference should produce a very large lambda ratio
        and trigger stop_for_effect."""
        result = service.run_sequential_analysis(
            control_successes=10,
            control_total=5000,
            treatment_successes=500,
            treatment_total=5000,
            config=default_config,
        )
        assert result.msprt_result.lambda_ratio > 1000.0
        assert result.msprt_result.can_stop
        assert result.recommended_action == "stop_for_effect"


# ---------------------------------------------------------------------------
# 3. always_valid method handling
# ---------------------------------------------------------------------------


class TestAlwaysValidMethod:
    """Test that the service works when the config implies an always-valid approach
    (larger tau_squared, single look)."""

    def test_single_look_always_valid_style(self, service):
        """With planned_looks=1 and current_look=1 (always-valid style),
        the analysis should still produce valid results."""
        config = {
            "tau_squared": 0.01,
            "alpha": 0.05,
            "spending_function": SpendingFunction.OBRIEN_FLEMING,
            "planned_looks": 1,
            "current_look": 1,
            "actual_days": 14,
            "expected_days": 14,
            "required_sample_size": 10000,
        }
        result = service.run_sequential_analysis(
            control_successes=100,
            control_total=1000,
            treatment_successes=150,
            treatment_total=1000,
            config=config,
        )
        assert isinstance(result, SequentialAnalysis)
        # Single look should produce exactly 1 alpha spending boundary
        assert len(result.alpha_spending) == 1
        # With a single look, the OBF boundary z = z_{alpha/2}/sqrt(1) = z_{alpha/2}
        # so the boundary_p should approximate alpha
        assert result.alpha_spending[0].boundary_p == pytest.approx(0.05, abs=0.001)


# ---------------------------------------------------------------------------
# 4. Recommended action logic
# ---------------------------------------------------------------------------


class TestRecommendedAction:
    """Validate the _determine_action decision tree."""

    def test_stop_for_effect_when_can_stop_true(self, service):
        """When mSPRT can_stop is True, action should be stop_for_effect."""
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
            control_successes=50,
            control_total=2000,
            treatment_successes=200,
            treatment_total=2000,
            config=config,
        )
        assert result.msprt_result.can_stop is True
        assert result.recommended_action == "stop_for_effect"

    def test_continue_when_inconclusive_and_on_track(self, service):
        """When evidence is weak and experiment is on schedule, continue."""
        config = {
            "tau_squared": 0.001,
            "alpha": 0.05,
            "spending_function": SpendingFunction.OBRIEN_FLEMING,
            "planned_looks": 10,
            "current_look": 1,
            "actual_days": 2,
            "expected_days": 30,
            "required_sample_size": 50000,
        }
        result = service.run_sequential_analysis(
            control_successes=50,
            control_total=500,
            treatment_successes=52,
            treatment_total=500,
            config=config,
        )
        assert result.msprt_result.can_stop is False
        assert result.long_running_risk.is_at_risk is False
        assert result.recommended_action == "continue"

    def test_stop_for_futility_when_at_risk_and_weak_evidence(self, service):
        """When experiment is at risk and evidence is inconclusive/null,
        recommended action should be stop_for_futility."""
        config = {
            "tau_squared": 0.001,
            "alpha": 0.05,
            "spending_function": SpendingFunction.OBRIEN_FLEMING,
            "planned_looks": 5,
            "current_look": 5,
            # Duration greatly exceeds expectation -> at risk
            "actual_days": 45,
            "expected_days": 14,
            "required_sample_size": 50000,
        }
        result = service.run_sequential_analysis(
            # Equal rates -> inconclusive evidence
            control_successes=200,
            control_total=2000,
            treatment_successes=200,
            treatment_total=2000,
            config=config,
        )
        assert result.long_running_risk.is_at_risk is True
        assert result.msprt_result.can_stop is False
        assert result.recommended_action == "stop_for_futility"


# ---------------------------------------------------------------------------
# 5. Alpha spending monotonicity
# ---------------------------------------------------------------------------


class TestAlphaSpendingMonotonicity:
    """Cumulative alpha must be monotonically non-decreasing across looks."""

    def test_obf_cumulative_alpha_monotonically_increasing(self, service):
        """O'Brien-Fleming cumulative alpha must increase at each look."""
        boundaries = service.compute_alpha_spending(
            current_look=5,
            planned_looks=5,
            alpha=0.05,
            spending_function=SpendingFunction.OBRIEN_FLEMING,
        )
        cumulative_alphas = [b.cumulative_alpha for b in boundaries]
        for i in range(len(cumulative_alphas) - 1):
            assert cumulative_alphas[i + 1] >= cumulative_alphas[i], (
                f"Cumulative alpha decreased from look {i + 1} ({cumulative_alphas[i]}) "
                f"to look {i + 2} ({cumulative_alphas[i + 1]})"
            )

    def test_pocock_cumulative_alpha_monotonically_increasing(self, service):
        """Pocock cumulative alpha must increase at each look."""
        boundaries = service.compute_alpha_spending(
            current_look=10,
            planned_looks=10,
            alpha=0.05,
            spending_function=SpendingFunction.POCOCK,
        )
        cumulative_alphas = [b.cumulative_alpha for b in boundaries]
        for i in range(len(cumulative_alphas) - 1):
            assert cumulative_alphas[i + 1] > cumulative_alphas[i], (
                f"Cumulative alpha did not increase from look {i + 1} to look {i + 2}"
            )


# ---------------------------------------------------------------------------
# 6. Evidence trajectory ordering
# ---------------------------------------------------------------------------


class TestEvidenceTrajectoryOrdering:
    """Evidence trajectory points must be ordered by sample_size."""

    def test_trajectory_ordered_by_sample_size(self, service):
        """Trajectory points should have strictly increasing sample sizes
        when the underlying data grows."""
        trajectory = service.compute_evidence_trajectory(
            control_successes_over_time=[10, 30, 60, 100, 200],
            control_totals_over_time=[100, 300, 600, 1000, 2000],
            treatment_successes_over_time=[12, 36, 72, 120, 240],
            treatment_totals_over_time=[100, 300, 600, 1000, 2000],
        )
        sample_sizes = [p.sample_size for p in trajectory]
        for i in range(len(sample_sizes) - 1):
            assert sample_sizes[i + 1] > sample_sizes[i], (
                f"Sample sizes not increasing: {sample_sizes[i]} >= {sample_sizes[i + 1]}"
            )


# ---------------------------------------------------------------------------
# 7. Confidence sequences narrow with larger samples
# ---------------------------------------------------------------------------


class TestConfidenceSequenceNarrowing:
    """Confidence sequences should get narrower as sample size grows."""

    def test_ci_narrows_with_more_data(self, service):
        """Width of the always-valid CI should decrease as we collect
        more observations (holding the true rate constant)."""
        widths = []
        for n in [100, 500, 1000, 5000, 10000]:
            # Keep conversion rate fixed at 10% control, 12% treatment
            cs = service.compute_always_valid_ci(
                control_successes=int(0.10 * n),
                control_total=n,
                treatment_successes=int(0.12 * n),
                treatment_total=n,
                alpha=0.05,
                tau_squared=0.001,
            )
            widths.append(cs.width)
        # Each subsequent width should be smaller
        for i in range(len(widths) - 1):
            assert widths[i + 1] < widths[i], (
                f"CI width did not decrease from n={[100, 500, 1000, 5000, 10000][i]} "
                f"({widths[i]:.6f}) to n={[100, 500, 1000, 5000, 10000][i + 1]} ({widths[i + 1]:.6f})"
            )
