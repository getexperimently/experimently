"""
Unit tests for AIExperimentPlannerService (EP-056).

Claude API is always mocked — no real API calls are made.
Tests cover:
- get_planning_advice returns dict with required keys
- Claude API called with correct prompt structure
- Fallback to template when API unavailable
- Template content rules (short runtime, long runtime, large/small MDE)
- Prompt contains key numbers (baseline rate, MDE, runtime)
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.ai_experiment_planner_service import (
    AIExperimentPlannerService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_anthropic_client(response_text: str = "AI planning advice here."):
    """Return a mock anthropic.Anthropic() client."""
    mock_content = MagicMock()
    mock_content.text = response_text

    mock_message = MagicMock()
    mock_message.content = [mock_content]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


def _planner() -> AIExperimentPlannerService:
    return AIExperimentPlannerService()


# ---------------------------------------------------------------------------
# TestIsAIAvailable
# ---------------------------------------------------------------------------


class TestIsAIAvailable:
    def test_returns_false_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert AIExperimentPlannerService.is_ai_available() is False

    def test_returns_true_when_api_key_set(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        assert AIExperimentPlannerService.is_ai_available() is True


# ---------------------------------------------------------------------------
# TestGetPlanningAdviceReturnsDict
# ---------------------------------------------------------------------------


class TestGetPlanningAdviceReturnsDict:
    """get_planning_advice must always return a dict with 'advice' and 'generated_by'."""

    @pytest.mark.asyncio
    async def test_returns_dict(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Test Experiment",
            metric_description="conversion rate",
            baseline_rate=0.05,
            mde=0.10,
            runtime_days=30.0,
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_has_advice_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="My Experiment",
            metric_description="signup rate",
            baseline_rate=0.10,
            mde=0.10,
            runtime_days=14.0,
        )
        assert "advice" in result

    @pytest.mark.asyncio
    async def test_has_generated_by_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="My Experiment",
            metric_description="signup rate",
            baseline_rate=0.10,
            mde=0.10,
            runtime_days=14.0,
        )
        assert "generated_by" in result

    @pytest.mark.asyncio
    async def test_advice_is_non_empty_string(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="My Experiment",
            metric_description="signup rate",
            baseline_rate=0.10,
            mde=0.10,
            runtime_days=14.0,
        )
        assert isinstance(result["advice"], str)
        assert len(result["advice"]) > 20


# ---------------------------------------------------------------------------
# TestTemplateAdvice
# ---------------------------------------------------------------------------


class TestTemplateAdvice:
    """Tests for the template-based fallback advice."""

    @pytest.mark.asyncio
    async def test_generated_by_template_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Test",
            metric_description="clicks",
            baseline_rate=0.05,
            mde=0.10,
            runtime_days=10.0,
        )
        assert result["generated_by"] == "template"

    @pytest.mark.asyncio
    async def test_short_runtime_mentions_good_runtime(self, monkeypatch):
        """Runtime < 7 days should mention 'good runtime'."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Quick Test",
            metric_description="click rate",
            baseline_rate=0.20,
            mde=0.50,
            runtime_days=3.0,
        )
        assert (
            "good runtime" in result["advice"].lower()
            or "excellent" in result["advice"].lower()
        )

    @pytest.mark.asyncio
    async def test_long_runtime_mentions_reduce_scope(self, monkeypatch):
        """Runtime > 90 days should mention reducing scope."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Long Experiment",
            metric_description="revenue per user",
            baseline_rate=0.02,
            mde=0.01,
            runtime_days=120.0,
        )
        advice_lower = result["advice"].lower()
        assert (
            "reduce" in advice_lower
            or "consider" in advice_lower
            or "long" in advice_lower
        )

    @pytest.mark.asyncio
    async def test_advice_mentions_experiment_name(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Checkout Flow Redesign",
            metric_description="purchase rate",
            baseline_rate=0.10,
            mde=0.10,
            runtime_days=20.0,
        )
        assert "Checkout Flow Redesign" in result["advice"]

    @pytest.mark.asyncio
    async def test_advice_mentions_baseline_rate(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Test",
            metric_description="conversion",
            baseline_rate=0.15,
            mde=0.10,
            runtime_days=20.0,
        )
        # 15% should appear in the advice
        assert "15" in result["advice"]

    @pytest.mark.asyncio
    async def test_advice_mentions_mde_percentage(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Test",
            metric_description="conversion",
            baseline_rate=0.10,
            mde=0.20,
            runtime_days=15.0,
        )
        # 20% MDE should appear in the advice
        assert "20" in result["advice"]

    @pytest.mark.asyncio
    async def test_long_runtime_suggests_sequential_testing(self, monkeypatch):
        """Runtime > 14 days should mention sequential/mSPRT testing."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Test",
            metric_description="conversion",
            baseline_rate=0.05,
            mde=0.05,
            runtime_days=60.0,
        )
        advice_lower = result["advice"].lower()
        assert (
            "sequential" in advice_lower
            or "msprt" in advice_lower
            or "early" in advice_lower
        )

    @pytest.mark.asyncio
    async def test_very_small_mde_warns(self, monkeypatch):
        """MDE < 2% should include a warning about small MDE."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Test",
            metric_description="conversion",
            baseline_rate=0.10,
            mde=0.01,
            runtime_days=200.0,
        )
        advice_lower = result["advice"].lower()
        assert (
            "warning" in advice_lower
            or "small" in advice_lower
            or "tiny" in advice_lower
        )

    @pytest.mark.asyncio
    async def test_reasonable_runtime_mentions_normal_window(self, monkeypatch):
        """7-30 day runtime should mention 'reasonable' or 'within normal'."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        planner = _planner()
        result = await planner.get_planning_advice(
            experiment_name="Test",
            metric_description="conversion",
            baseline_rate=0.10,
            mde=0.20,
            runtime_days=14.0,
        )
        advice_lower = result["advice"].lower()
        assert (
            "reasonable" in advice_lower
            or "normal" in advice_lower
            or "14" in result["advice"]
        )


# ---------------------------------------------------------------------------
# TestAIAdvice
# ---------------------------------------------------------------------------


def _make_mock_anthropic_module(response_text: str = "AI planning advice here."):
    """Return a mock 'anthropic' module with a mock Anthropic class."""
    mock_client = _make_mock_anthropic_client(response_text)
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    return mock_anthropic_module, mock_client


class TestAIAdvice:
    """Tests for the AI-based advice path (Claude API mocked)."""

    @pytest.mark.asyncio
    async def test_ai_advice_called_when_api_key_set(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        mock_module, mock_client = _make_mock_anthropic_module(
            "Great experiment design!"
        )

        planner = _planner()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            result = await planner.get_planning_advice(
                experiment_name="AI Test",
                metric_description="revenue",
                baseline_rate=0.10,
                mde=0.10,
                runtime_days=30.0,
            )

        assert result["generated_by"] == "ai"
        assert "Great experiment design!" in result["advice"]

    @pytest.mark.asyncio
    async def test_anthropic_client_created_with_correct_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        mock_module, mock_client = _make_mock_anthropic_module("Advice text")

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            planner = _planner()
            await planner.get_planning_advice(
                experiment_name="Test",
                metric_description="conversion",
                baseline_rate=0.10,
                mde=0.10,
                runtime_days=20.0,
            )

        # Verify messages.create was called
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs.get("model") == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_prompt_contains_baseline_rate(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        mock_module, mock_client = _make_mock_anthropic_module("Advice text")

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            planner = _planner()
            await planner.get_planning_advice(
                experiment_name="Test",
                metric_description="conversion",
                baseline_rate=0.15,
                mde=0.10,
                runtime_days=20.0,
            )

        call_kwargs = mock_client.messages.create.call_args
        prompt_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "15" in prompt_content  # 15% baseline

    @pytest.mark.asyncio
    async def test_prompt_contains_mde(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        mock_module, mock_client = _make_mock_anthropic_module("Advice")

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            planner = _planner()
            await planner.get_planning_advice(
                experiment_name="Test",
                metric_description="conversion",
                baseline_rate=0.10,
                mde=0.25,
                runtime_days=10.0,
            )

        call_kwargs = mock_client.messages.create.call_args
        prompt_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "25" in prompt_content  # 25% MDE

    @pytest.mark.asyncio
    async def test_prompt_contains_runtime_days(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        mock_module, mock_client = _make_mock_anthropic_module("Advice")

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            planner = _planner()
            await planner.get_planning_advice(
                experiment_name="Test",
                metric_description="conversion",
                baseline_rate=0.10,
                mde=0.10,
                runtime_days=45.0,
            )

        call_kwargs = mock_client.messages.create.call_args
        prompt_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "45" in prompt_content  # 45 days runtime

    @pytest.mark.asyncio
    async def test_falls_back_to_template_when_api_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        planner = _planner()
        # Make the AI path raise an exception
        with patch.object(planner, "_ai_advice", side_effect=RuntimeError("API error")):
            result = await planner.get_planning_advice(
                experiment_name="Test",
                metric_description="conversion",
                baseline_rate=0.10,
                mde=0.10,
                runtime_days=20.0,
            )

        assert result["generated_by"] == "template"
        assert len(result["advice"]) > 0

    @pytest.mark.asyncio
    async def test_prompt_contains_experiment_name(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        mock_module, mock_client = _make_mock_anthropic_module("Advice")

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            planner = _planner()
            await planner.get_planning_advice(
                experiment_name="Unique Experiment Name XYZ",
                metric_description="conversion",
                baseline_rate=0.10,
                mde=0.10,
                runtime_days=10.0,
            )

        call_kwargs = mock_client.messages.create.call_args
        prompt_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "Unique Experiment Name XYZ" in prompt_content
