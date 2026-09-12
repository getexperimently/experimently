"""
Unit tests for interaction detection Pydantic schemas.

Verifies validation, field constraints, and serialization of all
interaction-related schema classes.
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.interaction import (
    ActiveInteractionScanResponse,
    InteractionAnalysisResponse,
    InteractionResultSchema,
    NoveltyResultSchema,
    RiskLevel,
    SUTVAResultSchema,
)


class TestInteractionResultSchema:
    """Tests for InteractionResultSchema."""

    def test_valid_no_interaction(self):
        schema = InteractionResultSchema(
            has_interaction=False,
            p_value=0.42,
            interaction_effect_size=0.01,
        )
        assert schema.has_interaction is False
        assert schema.p_value == pytest.approx(0.42)

    def test_valid_with_interaction(self):
        schema = InteractionResultSchema(
            has_interaction=True,
            p_value=0.01,
            interaction_effect_size=0.15,
            warning_message="Significant interaction detected.",
        )
        assert schema.has_interaction is True
        assert schema.warning_message is not None

    def test_warning_message_optional(self):
        schema = InteractionResultSchema(
            has_interaction=False,
            p_value=0.9,
            interaction_effect_size=0.0,
        )
        assert schema.warning_message is None


class TestNoveltyResultSchema:
    """Tests for NoveltyResultSchema."""

    def test_valid_novelty_schema(self):
        schema = NoveltyResultSchema(
            has_novelty=True,
            decline_rate=-0.2,
            recommendation="Extend minimum runtime.",
        )
        assert schema.has_novelty is True
        assert schema.decline_rate == pytest.approx(-0.2)

    def test_no_novelty_schema(self):
        schema = NoveltyResultSchema(
            has_novelty=False,
            decline_rate=0.0,
            recommendation="No novelty detected.",
        )
        assert schema.has_novelty is False

    def test_recommendation_required(self):
        with pytest.raises(ValidationError):
            NoveltyResultSchema(has_novelty=False, decline_rate=0.0)


class TestSUTVAResultSchema:
    """Tests for SUTVAResultSchema."""

    def test_valid_no_violation(self):
        schema = SUTVAResultSchema(has_violation=False, contamination_rate=0.0)
        assert schema.has_violation is False
        assert schema.contamination_rate == pytest.approx(0.0)

    def test_valid_with_violation(self):
        schema = SUTVAResultSchema(
            has_violation=True,
            contamination_rate=0.12,
            warning_message="SUTVA violated.",
        )
        assert schema.has_violation is True

    def test_warning_message_optional(self):
        schema = SUTVAResultSchema(has_violation=False, contamination_rate=0.0)
        assert schema.warning_message is None


class TestInteractionAnalysisResponse:
    """Tests for InteractionAnalysisResponse."""

    def _make_valid(self, **overrides):
        base = {
            "experiment_a_id": "exp-a",
            "experiment_b_id": "exp-b",
            "overlap_coefficient": 0.45,
            "has_significant_overlap": True,
            "overall_risk": RiskLevel.MEDIUM,
            "recommendations": ["Check overlap."],
        }
        base.update(overrides)
        return InteractionAnalysisResponse(**base)

    def test_valid_response(self):
        schema = self._make_valid()
        assert schema.experiment_a_id == "exp-a"
        assert schema.overall_risk == RiskLevel.MEDIUM

    def test_overlap_coefficient_lower_bound(self):
        with pytest.raises(ValidationError):
            self._make_valid(overlap_coefficient=-0.1)

    def test_overlap_coefficient_upper_bound(self):
        with pytest.raises(ValidationError):
            self._make_valid(overlap_coefficient=1.1)

    def test_overall_risk_valid_values(self):
        for level in ("low", "medium", "high"):
            schema = self._make_valid(overall_risk=level)
            assert schema.overall_risk == RiskLevel(level)

    def test_overall_risk_invalid_value(self):
        with pytest.raises(ValidationError):
            self._make_valid(overall_risk="critical")

    def test_recommendations_default_empty(self):
        schema = InteractionAnalysisResponse(
            experiment_a_id="a",
            experiment_b_id="b",
            overlap_coefficient=0.5,
            has_significant_overlap=True,
            overall_risk=RiskLevel.LOW,
        )
        assert schema.recommendations == []

    def test_sub_results_optional(self):
        schema = self._make_valid()
        assert schema.interaction_result is None
        assert schema.novelty_result is None
        assert schema.sutva_result is None


class TestActiveInteractionScanResponse:
    """Tests for ActiveInteractionScanResponse."""

    def test_valid_empty_scan(self):
        schema = ActiveInteractionScanResponse(
            total_active_experiments=0,
            pairs_analyzed=0,
            high_risk_pairs=0,
            analyses=[],
        )
        assert schema.pairs_analyzed == 0
        assert schema.analyses == []

    def test_valid_scan_with_analyses(self):
        analysis = InteractionAnalysisResponse(
            experiment_a_id="a",
            experiment_b_id="b",
            overlap_coefficient=0.6,
            has_significant_overlap=True,
            overall_risk=RiskLevel.HIGH,
        )
        schema = ActiveInteractionScanResponse(
            total_active_experiments=3,
            pairs_analyzed=1,
            high_risk_pairs=1,
            analyses=[analysis],
        )
        assert schema.pairs_analyzed == len(schema.analyses)
        assert schema.high_risk_pairs == 1
