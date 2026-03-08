"""
Realistic scenario: Statistical Edge Cases.

Validates that the platform handles statistically pathological situations
correctly rather than silently returning wrong answers:

  - Zero-variance metric (all users convert or none do)
  - Outlier contamination (a handful of whale users skewing the mean)
  - Simpson's paradox (aggregate shows lift; subgroup shows reversal)
  - Multi-assignment bug (same user in both variants)
  - Metric drift (baseline shifts mid-experiment)
  - Extremely small samples (underpowered test)
  - Perfect separation (100% vs 0% CVR)

These tests do NOT require a running platform — they validate the data
generation engine itself and the statistical properties of the output.
"""

import pytest
from datetime import timedelta

from backend.tests.realistic.data_generator import DataScenario, make_edge_case_scenario


class TestZeroVarianceMetric:
    """All users convert or none convert — variance = 0."""

    def test_all_users_convert(self):
        scenario = DataScenario(
            name="all_convert",
            users=200,
            control_cvr=1.0,
            treatment_cvr=1.0,
            seed=1,
        )
        result = scenario.generate()
        events = len(result.events)
        users = len(result.users)
        # Should produce one event per user (approximately)
        assert events >= users * 0.95, f"Expected ~{users} events, got {events}"

    def test_no_users_convert(self):
        scenario = DataScenario(
            name="none_convert",
            users=500,
            control_cvr=0.0,
            treatment_cvr=0.0,
            seed=2,
        )
        result = scenario.generate()
        # Edge cases may add a few events — base simulation should have zero
        base_events = [e for e in result.events if not e.properties.get("injected")]
        assert len(base_events) == 0, f"Expected 0 events, got {len(base_events)}"

    def test_zero_cvr_scenario_not_significant(self):
        scenario = DataScenario(
            name="zero_cvr",
            users=1000,
            control_cvr=0.0,
            treatment_cvr=0.0,
            seed=3,
        )
        result = scenario.generate()
        assert not result.expected_significant


class TestOutlierContamination:
    """High outlier rate should produce high-value events."""

    def test_outlier_events_have_elevated_values(self):
        scenario = DataScenario(
            name="outliers",
            users=2000,
            control_cvr=0.05,
            treatment_cvr=0.06,
            outlier_rate=0.20,  # aggressive outlier rate for testability
            seed=5,
        )
        result = scenario.generate()
        outlier_events = [e for e in result.events if e.properties.get("outlier")]
        assert len(outlier_events) > 0, "Expected some outlier events"
        avg_outlier_value = sum(e.value for e in outlier_events) / len(outlier_events)
        non_outlier_events = [e for e in result.events if not e.properties.get("outlier")]
        avg_normal_value = (
            sum(e.value for e in non_outlier_events) / len(non_outlier_events)
            if non_outlier_events
            else 1.0
        )
        assert avg_outlier_value > avg_normal_value, (
            f"Outlier avg value {avg_outlier_value:.2f} should exceed normal {avg_normal_value:.2f}"
        )

    def test_outlier_rate_is_approximate(self):
        scenario = DataScenario(
            name="outlier_rate_check",
            users=5000,
            control_cvr=0.50,
            treatment_cvr=0.50,
            outlier_rate=0.10,
            seed=6,
        )
        result = scenario.generate()
        outlier_events = [e for e in result.events if e.properties.get("outlier")]
        total_events = len(result.events)
        if total_events > 0:
            actual_rate = len(outlier_events) / total_events
            # Allow ±50% relative tolerance (stochastic)
            assert 0.05 <= actual_rate <= 0.20, (
                f"Outlier rate {actual_rate:.3f} out of expected range [0.05, 0.20]"
            )


class TestSimpsonsParadox:
    """Subgroup reversal: aggregate shows lift, mobile subgroup does not."""

    def test_mobile_subgroup_has_lower_treatment_cvr(self):
        scenario = DataScenario(
            name="simpsons_paradox",
            users=3000,
            control_cvr=0.07,
            treatment_cvr=0.09,
            inject_edge_cases=["simpsons_paradox"],
            seed=8,
        )
        result = scenario.generate()

        mobile_treatment_ids = {
            u.user_id for u in result.users
            if u.variant_name == "treatment" and u.properties.get("device") == "mobile"
        }
        mobile_control_ids = {
            u.user_id for u in result.users
            if u.variant_name == "control" and u.properties.get("device") == "mobile"
        }

        mobile_t_events = [e for e in result.events if e.user_id in mobile_treatment_ids]
        mobile_c_events = [e for e in result.events if e.user_id in mobile_control_ids]

        if mobile_treatment_ids and mobile_control_ids:
            t_cvr = len(mobile_t_events) / len(mobile_treatment_ids)
            c_cvr = len(mobile_c_events) / len(mobile_control_ids)
            assert t_cvr < c_cvr, (
                f"Simpson's paradox injection failed: mobile treatment CVR {t_cvr:.3f} "
                f"should be < control {c_cvr:.3f}"
            )


class TestMultiAssignment:
    """A user assigned to both variants is an integrity violation."""

    def test_multi_assignment_injects_duplicate(self):
        scenario = DataScenario(
            name="multi_assign",
            users=500,
            control_cvr=0.10,
            treatment_cvr=0.12,
            inject_edge_cases=["multi_assignment"],
            seed=9,
        )
        result = scenario.generate()

        # Find users appearing in both variants
        control_ids = {u.user_id for u in result.users if u.variant_name == "control"}
        treatment_ids = {u.user_id for u in result.users if u.variant_name == "treatment"}
        duplicates = control_ids & treatment_ids

        assert len(duplicates) >= 1, (
            "Expected at least one user in both variants after multi_assignment injection"
        )


class TestMetricDrift:
    """Gradual baseline shift should produce more events in the second half."""

    def test_late_control_events_elevated(self):
        scenario = DataScenario(
            name="metric_drift",
            users=2000,
            control_cvr=0.05,
            treatment_cvr=0.06,
            inject_edge_cases=["metric_drift"],
            experiment_duration_days=14,
            seed=10,
        )
        result = scenario.generate()

        # Check that drift-injected events are present
        drift_events = [
            e for e in result.events if e.properties.get("injected") == "metric_drift"
        ]
        assert len(drift_events) > 0, "Expected metric drift events to be injected"

        # Drift events should only be in control
        for event in drift_events:
            assert event.variant_name == "control", (
                f"Drift event for {event.user_id} should be in control, got {event.variant_name}"
            )


class TestUnderpoweredExperiment:
    """Small sample sizes should not produce false positives consistently."""

    def test_very_small_sample_not_significant(self):
        scenario = DataScenario(
            name="underpowered",
            users=20,
            control_cvr=0.05,
            treatment_cvr=0.06,
            seed=11,
        )
        result = scenario.generate()
        # With only 20 users, a 20% relative lift is not detectable
        assert not result.expected_significant, (
            f"Underpowered test (n=20) should not be significant, z={result.metadata['z_score']}"
        )


class TestFullEdgeCaseScenario:
    """Integration: all edge cases in a single scenario."""

    def test_edge_case_scenario_generates_cleanly(self):
        scenario = make_edge_case_scenario(seed=13)
        result = scenario.generate()

        assert len(result.users) > 0
        assert len(result.events) >= 0
        assert len(result.edge_cases_injected) == 4
        assert set(result.edge_cases_injected) == {
            "zero_events_user",
            "multi_assignment",
            "metric_drift",
            "simpsons_paradox",
        }

    def test_edge_case_scenario_summary_is_printable(self, capsys):
        scenario = make_edge_case_scenario(seed=13)
        result = scenario.generate()
        print(result.summary())
        captured = capsys.readouterr()
        assert "Scenario: statistical_edge_cases" in captured.out
        assert "Edge cases:" in captured.out
