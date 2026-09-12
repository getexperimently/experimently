"""
Unit tests for AIDesignService.

Tests cover:
- ExperimentDesignAssistant: suggest_experiment_design, suggest_metrics_for_experiment
- ResultsInterpreter: interpret_results, generate_plain_english_summary
- SampleSizeAdvisor: estimate_sample_size
- GracefulDegradation: fallback behaviour when AI is unavailable

Claude API is always mocked — no real API calls are made.
"""

import os
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from backend.app.services.ai_design_service import (
    AIDesignService,
    ExperimentDesignSuggestion,
    ResultsInterpretation,
    SampleSizeEstimate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_anthropic_client(response_text: str = "AI response text"):
    """Return a mock anthropic.Anthropic() client with a preconfigured response."""
    mock_content = MagicMock()
    mock_content.text = response_text

    mock_message = MagicMock()
    mock_message.content = [mock_content]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


# ---------------------------------------------------------------------------
# TestExperimentDesignAssistant (8 tests)
# ---------------------------------------------------------------------------


class TestExperimentDesignAssistant:
    """Tests for suggest_experiment_design and suggest_metrics_for_experiment."""

    def test_suggest_experiment_design_returns_suggestion(self):
        """suggest_experiment_design returns an ExperimentDesignSuggestion object."""
        result = AIDesignService.suggest_experiment_design(
            description="Test button colour to improve signup",
            experiment_type="default",
        )
        assert isinstance(result, ExperimentDesignSuggestion)

    def test_suggestion_has_required_fields(self):
        """Suggestion includes all required fields with non-empty values."""
        result = AIDesignService.suggest_experiment_design(
            description="Optimise the checkout page flow"
        )
        assert result.hypothesis
        assert result.primary_metric
        assert isinstance(result.guardrail_metrics, list)
        assert result.recommended_sample_size > 0
        assert result.recommended_duration_days > 0
        assert isinstance(result.variant_descriptions, list)
        assert len(result.variant_descriptions) >= 2

    @patch(
        "backend.app.services.ai_design_service.AIDesignService.is_ai_available",
        return_value=True,
    )
    @patch("backend.app.services.ai_design_service.AIDesignService._ai_suggest")
    def test_ai_suggest_called_when_key_available(
        self, mock_ai_suggest, mock_available
    ):
        """When ANTHROPIC_API_KEY is set, _ai_suggest is invoked."""
        mock_ai_suggest.return_value = ExperimentDesignSuggestion(
            hypothesis="AI hypothesis",
            primary_metric="conversion_rate",
            guardrail_metrics=["revenue"],
            recommended_sample_size=500,
            recommended_duration_days=14,
            variant_descriptions=["Control", "Variant A"],
            confidence="ai_generated",
        )
        result = AIDesignService.suggest_experiment_design(
            description="Test AI-powered design"
        )
        mock_ai_suggest.assert_called_once()
        assert result.confidence == "ai_generated"

    @patch(
        "backend.app.services.ai_design_service.AIDesignService.is_ai_available",
        return_value=True,
    )
    @patch(
        "backend.app.services.ai_design_service.AIDesignService._ai_suggest",
        side_effect=Exception("API error"),
    )
    def test_graceful_degradation_on_ai_failure(self, mock_ai_suggest, mock_available):
        """When AI call fails, falls back to template-based suggestion without raising."""
        result = AIDesignService.suggest_experiment_design(
            description="Test graceful degradation when AI fails"
        )
        assert isinstance(result, ExperimentDesignSuggestion)
        assert result.confidence == "template_based"

    def test_suggest_metrics_for_checkout(self):
        """experiment_type='checkout' returns checkout-relevant metrics."""
        metrics = AIDesignService.suggest_metrics_for_experiment("checkout")
        assert "conversion_rate" in metrics
        assert "revenue_per_user" in metrics or "cart_abandonment_rate" in metrics

    def test_suggest_metrics_for_onboarding(self):
        """experiment_type='onboarding' returns onboarding-relevant metrics."""
        metrics = AIDesignService.suggest_metrics_for_experiment("onboarding")
        assert "activation_rate" in metrics
        assert "day7_retention" in metrics

    def test_suggest_metrics_returns_list(self):
        """suggest_metrics_for_experiment always returns a non-empty list."""
        for exp_type in [
            "checkout",
            "onboarding",
            "pricing",
            "email",
            "landing_page",
            "default",
        ]:
            metrics = AIDesignService.suggest_metrics_for_experiment(exp_type)
            assert isinstance(metrics, list)
            assert len(metrics) > 0

    @patch(
        "backend.app.services.ai_design_service.AIDesignService.is_ai_available",
        return_value=False,
    )
    def test_template_based_when_anthropic_not_installed(self, mock_available):
        """When anthropic package is unavailable, returns template-based suggestion."""
        result = AIDesignService.suggest_experiment_design(
            description="Test when anthropic not installed"
        )
        assert isinstance(result, ExperimentDesignSuggestion)
        assert result.confidence == "template_based"


# ---------------------------------------------------------------------------
# TestResultsInterpreter (8 tests)
# ---------------------------------------------------------------------------


class TestResultsInterpreter:
    """Tests for interpret_results and generate_plain_english_summary."""

    def test_interpret_results_returns_interpretation(self):
        """interpret_results returns a ResultsInterpretation object."""
        results = {
            "p_value": 0.03,
            "relative_improvement_pct": 5.0,
            "variant_name": "Variant A",
        }
        result = AIDesignService.interpret_results(results)
        assert isinstance(result, ResultsInterpretation)

    def test_interpretation_has_required_fields(self):
        """ResultsInterpretation has summary, recommendation, confidence_statement, key_findings."""
        results = {
            "p_value": 0.01,
            "relative_improvement_pct": 3.0,
            "variant_name": "B",
        }
        interp = AIDesignService.interpret_results(results)
        assert interp.summary
        assert interp.recommendation in {"ship", "continue_testing", "stop_futility"}
        assert interp.confidence_statement
        assert isinstance(interp.key_findings, list)
        assert len(interp.key_findings) > 0

    @patch(
        "backend.app.services.ai_design_service.AIDesignService.is_ai_available",
        return_value=True,
    )
    @patch("backend.app.services.ai_design_service.AIDesignService._ai_interpret")
    def test_ai_interpret_called_when_available(
        self, mock_ai_interpret, mock_available
    ):
        """When AI is available, _ai_interpret is invoked."""
        mock_ai_interpret.return_value = ResultsInterpretation(
            summary="AI summary",
            recommendation="ship",
            confidence_statement="High confidence",
            key_findings=["Significant improvement"],
            generated_by="ai",
        )
        results = {
            "p_value": 0.02,
            "relative_improvement_pct": 10.0,
            "variant_name": "A",
        }
        result = AIDesignService.interpret_results(results)
        mock_ai_interpret.assert_called_once()
        assert result.generated_by == "ai"

    def test_ship_recommendation_when_significant_positive(self):
        """p_value < 0.05 and positive effect → recommendation is 'ship'."""
        results = {
            "p_value": 0.02,
            "relative_improvement_pct": 8.0,
            "variant_name": "Variant B",
        }
        interp = AIDesignService._template_interpret(results)
        assert interp.recommendation == "ship"

    def test_continue_testing_when_not_significant(self):
        """p_value > 0.05 → recommendation includes 'continue_testing'."""
        results = {
            "p_value": 0.30,
            "relative_improvement_pct": 2.0,
            "variant_name": "Variant C",
        }
        interp = AIDesignService._template_interpret(results)
        assert interp.recommendation == "continue_testing"

    def test_generate_plain_english_summary_returns_string(self):
        """generate_plain_english_summary returns a non-empty string."""
        results = {
            "p_value": 0.04,
            "relative_improvement_pct": 4.5,
            "variant_name": "Test Variant",
        }
        summary = AIDesignService.generate_plain_english_summary(results)
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_summary_mentions_variant_name(self):
        """Plain-English summary mentions the variant name."""
        results = {
            "p_value": 0.04,
            "relative_improvement_pct": 4.5,
            "variant_name": "MyVariant",
        }
        summary = AIDesignService.generate_plain_english_summary(results)
        assert "MyVariant" in summary

    @patch(
        "backend.app.services.ai_design_service.AIDesignService.is_ai_available",
        return_value=True,
    )
    @patch(
        "backend.app.services.ai_design_service.AIDesignService._ai_interpret",
        side_effect=Exception("LLM error"),
    )
    def test_fallback_to_template_on_ai_error(self, mock_ai, mock_available):
        """When AI interpret fails, falls back to template-based interpretation."""
        results = {
            "p_value": 0.10,
            "relative_improvement_pct": 1.0,
            "variant_name": "X",
        }
        interp = AIDesignService.interpret_results(results)
        assert isinstance(interp, ResultsInterpretation)
        assert interp.generated_by == "template"


# ---------------------------------------------------------------------------
# TestSampleSizeAdvisor (4 tests)
# ---------------------------------------------------------------------------


class TestSampleSizeAdvisor:
    """Tests for estimate_sample_size."""

    def test_estimate_sample_size_returns_estimate(self):
        """estimate_sample_size returns a SampleSizeEstimate object."""
        estimate = AIDesignService.estimate_sample_size(
            baseline_rate=0.10, mde=0.02, confidence=0.95, power=0.80
        )
        assert isinstance(estimate, SampleSizeEstimate)
        assert estimate.required_per_variant > 0
        assert estimate.total_required == estimate.required_per_variant * 2

    def test_lower_mde_requires_larger_sample(self):
        """A smaller MDE requires a larger sample size."""
        small_mde = AIDesignService.estimate_sample_size(
            baseline_rate=0.10, mde=0.01, confidence=0.95, power=0.80
        )
        large_mde = AIDesignService.estimate_sample_size(
            baseline_rate=0.10, mde=0.05, confidence=0.95, power=0.80
        )
        assert small_mde.required_per_variant > large_mde.required_per_variant

    def test_higher_power_requires_larger_sample(self):
        """Higher statistical power requires a larger sample size."""
        high_power = AIDesignService.estimate_sample_size(
            baseline_rate=0.10, mde=0.02, confidence=0.95, power=0.90
        )
        low_power = AIDesignService.estimate_sample_size(
            baseline_rate=0.10, mde=0.02, confidence=0.95, power=0.70
        )
        assert high_power.required_per_variant > low_power.required_per_variant

    def test_days_to_significance_with_daily_traffic(self):
        """days_to_significance is computed when daily_traffic is provided."""
        estimate = AIDesignService.estimate_sample_size(
            baseline_rate=0.10,
            mde=0.02,
            confidence=0.95,
            power=0.80,
            daily_traffic=200,
        )
        assert estimate.days_to_significance is not None
        assert estimate.days_to_significance > 0


# ---------------------------------------------------------------------------
# TestGracefulDegradation (5 tests)
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Tests for graceful degradation when ANTHROPIC_API_KEY is absent."""

    def test_is_ai_available_false_when_key_not_set(self):
        """is_ai_available() returns False when ANTHROPIC_API_KEY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure the key is absent
            os.environ.pop("ANTHROPIC_API_KEY", None)
            assert AIDesignService.is_ai_available() is False

    def test_is_ai_available_true_when_key_set(self):
        """is_ai_available() returns True when ANTHROPIC_API_KEY is set."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
            assert AIDesignService.is_ai_available() is True

    @patch(
        "backend.app.services.ai_design_service.AIDesignService.is_ai_available",
        return_value=False,
    )
    def test_fallback_suggestion_when_key_not_set(self, mock_available):
        """When key not set, suggest_experiment_design uses template fallback."""
        result = AIDesignService.suggest_experiment_design(
            description="Experiment without API key configured"
        )
        assert isinstance(result, ExperimentDesignSuggestion)
        assert result.confidence == "template_based"

    @patch(
        "backend.app.services.ai_design_service.AIDesignService.is_ai_available",
        return_value=True,
    )
    @patch(
        "backend.app.services.ai_design_service.AIDesignService._ai_suggest",
        side_effect=RuntimeError("Unexpected"),
    )
    def test_fallback_has_all_required_fields(self, mock_ai, mock_available):
        """Fallback suggestion still has all required fields (no KeyError)."""
        result = AIDesignService.suggest_experiment_design(
            description="Check all fields exist in fallback"
        )
        # All required fields must be present and not None
        assert result.hypothesis is not None
        assert result.primary_metric is not None
        assert result.guardrail_metrics is not None
        assert result.recommended_sample_size is not None
        assert result.recommended_duration_days is not None
        assert result.variant_descriptions is not None

    @patch(
        "backend.app.services.ai_design_service.AIDesignService.is_ai_available",
        return_value=False,
    )
    def test_no_exception_when_ai_unavailable(self, mock_available):
        """No exception is raised when AI is unavailable — graceful degradation."""
        try:
            result = AIDesignService.suggest_experiment_design(
                description="Ensure no exception raised when AI unavailable"
            )
            interp = AIDesignService.interpret_results(
                {"p_value": 0.10, "relative_improvement_pct": 2.0, "variant_name": "V"}
            )
        except Exception as exc:
            pytest.fail(f"Unexpected exception raised: {exc}")
