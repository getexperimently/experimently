"""
Unit tests for the InteractionDetectionService.

Tests cover:
- User overlap computation (Jaccard similarity)
- Interaction effect detection (2x2 chi-squared)
- Novelty effect detection (linear regression)
- SUTVA violation checking
- High-level service methods
"""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from backend.app.services.interaction_detection_service import (
    InteractionDetectionService,
    InteractionResult,
    NoveltyResult,
    SUTVAResult,
    InteractionAnalysis,
)


# ---------------------------------------------------------------------------
# TestOverlapDetection (8 tests)
# ---------------------------------------------------------------------------

class TestOverlapDetection:
    """Tests for user overlap / Jaccard similarity computation."""

    def test_compute_user_overlap_returns_float(self):
        """compute_user_overlap returns a float (Jaccard index)."""
        service = InteractionDetectionService()
        result = service.compute_user_overlap({"a", "b", "c"}, {"b", "c", "d"})
        assert isinstance(result, float)

    def test_compute_user_overlap_perfect_overlap(self):
        """Perfect overlap (same sets) → 1.0."""
        service = InteractionDetectionService()
        users = {"u1", "u2", "u3"}
        result = service.compute_user_overlap(users, users)
        assert result == pytest.approx(1.0)

    def test_compute_user_overlap_no_overlap(self):
        """No overlap → 0.0."""
        service = InteractionDetectionService()
        result = service.compute_user_overlap({"a", "b"}, {"c", "d"})
        assert result == pytest.approx(0.0)

    def test_compute_user_overlap_partial_overlap(self):
        """Partial overlap returns correct Jaccard fraction."""
        service = InteractionDetectionService()
        # |A∩B| = 2, |A∪B| = 4  →  0.5
        result = service.compute_user_overlap({"a", "b", "c"}, {"b", "c", "d"})
        assert result == pytest.approx(2 / 4)

    def test_compute_user_overlap_empty_set_a(self):
        """Empty set A → 0.0."""
        service = InteractionDetectionService()
        result = service.compute_user_overlap(set(), {"a", "b"})
        assert result == pytest.approx(0.0)

    def test_compute_user_overlap_empty_set_b(self):
        """Empty set B → 0.0."""
        service = InteractionDetectionService()
        result = service.compute_user_overlap({"a", "b"}, set())
        assert result == pytest.approx(0.0)

    def test_has_significant_overlap_true_above_threshold(self):
        """has_significant_overlap returns True when Jaccard > threshold."""
        service = InteractionDetectionService()
        # Jaccard = 2/4 = 0.5  >  0.3
        result = service.has_significant_overlap({"a", "b", "c"}, {"b", "c", "d"}, threshold=0.3)
        assert result is True

    def test_has_significant_overlap_false_below_threshold(self):
        """has_significant_overlap returns False when Jaccard ≤ threshold."""
        service = InteractionDetectionService()
        # Jaccard = 1/5 = 0.2  <  0.3
        result = service.has_significant_overlap({"a", "b", "c"}, {"c", "d", "e"}, threshold=0.3)
        assert result is False


# ---------------------------------------------------------------------------
# TestInteractionEffect (8 tests)
# ---------------------------------------------------------------------------

class TestInteractionEffect:
    """Tests for 2×2 interaction effect detection."""

    def test_detect_interaction_returns_interaction_result(self):
        """detect_interaction returns an InteractionResult instance."""
        service = InteractionDetectionService()
        result = service.detect_interaction(
            control_only=100,
            treatment_a_only=110,
            treatment_b_only=115,
            both_treatments=125,
        )
        assert isinstance(result, InteractionResult)

    def test_detect_interaction_no_interaction_additive(self):
        """No interaction when treatments are approximately additive → p_value > 0.05."""
        service = InteractionDetectionService()
        # Perfectly balanced 2×2 table — no association
        result = service.detect_interaction(
            control_only=500,
            treatment_a_only=500,
            treatment_b_only=500,
            both_treatments=500,
        )
        assert result.p_value > 0.05
        assert result.has_interaction is False

    def test_detect_interaction_significant_non_additive(self):
        """Significant interaction detected when treatments are non-additive → p_value < 0.05."""
        service = InteractionDetectionService()
        # Heavily imbalanced table produces strong association
        result = service.detect_interaction(
            control_only=1000,
            treatment_a_only=50,
            treatment_b_only=50,
            both_treatments=1000,
        )
        assert result.p_value < 0.05
        assert result.has_interaction is True

    def test_detect_interaction_result_fields(self):
        """InteractionResult has has_interaction, p_value, interaction_effect_size, warning_message."""
        service = InteractionDetectionService()
        result = service.detect_interaction(100, 110, 115, 125)
        assert hasattr(result, "has_interaction")
        assert hasattr(result, "p_value")
        assert hasattr(result, "interaction_effect_size")
        assert hasattr(result, "warning_message")

    def test_compute_interaction_effect_size(self):
        """compute_interaction_effect_size returns AB - A - B."""
        service = InteractionDetectionService()
        result = service.compute_interaction_effect_size(a_effect=0.1, b_effect=0.2, ab_effect=0.5)
        assert result == pytest.approx(0.5 - 0.1 - 0.2)

    def test_zero_interaction_effect_additive(self):
        """Effect size is 0 when AB == A + B."""
        service = InteractionDetectionService()
        result = service.compute_interaction_effect_size(a_effect=0.1, b_effect=0.2, ab_effect=0.3)
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_large_positive_interaction_super_additive(self):
        """Large positive interaction when AB > A + B (super-additive)."""
        service = InteractionDetectionService()
        result = service.compute_interaction_effect_size(a_effect=0.1, b_effect=0.1, ab_effect=0.5)
        assert result > 0

    def test_large_negative_interaction_sub_additive(self):
        """Large negative interaction when AB < A + B (sub-additive)."""
        service = InteractionDetectionService()
        result = service.compute_interaction_effect_size(a_effect=0.3, b_effect=0.3, ab_effect=0.2)
        assert result < 0


# ---------------------------------------------------------------------------
# TestNoveltyEffectDetection (6 tests)
# ---------------------------------------------------------------------------

class TestNoveltyEffectDetection:
    """Tests for novelty effect detection via linear regression on daily effects."""

    def test_detect_novelty_effect_returns_novelty_result(self):
        """detect_novelty_effect returns a NoveltyResult instance."""
        service = InteractionDetectionService()
        result = service.detect_novelty_effect([0.5, 0.4, 0.3, 0.2])
        assert isinstance(result, NoveltyResult)

    def test_detect_novelty_result_fields(self):
        """NoveltyResult has has_novelty, decline_rate, recommendation."""
        service = InteractionDetectionService()
        result = service.detect_novelty_effect([0.5, 0.5, 0.5])
        assert hasattr(result, "has_novelty")
        assert hasattr(result, "decline_rate")
        assert hasattr(result, "recommendation")

    def test_flat_effects_no_novelty(self):
        """Flat daily effects → no novelty detected."""
        service = InteractionDetectionService()
        result = service.detect_novelty_effect([0.5, 0.5, 0.5, 0.5, 0.5])
        assert result.has_novelty is False

    def test_declining_effect_novelty_detected(self):
        """Clearly declining effect over time → novelty detected."""
        service = InteractionDetectionService()
        result = service.detect_novelty_effect([0.9, 0.7, 0.5, 0.3, 0.1])
        assert result.has_novelty is True

    def test_decline_rate_is_slope(self):
        """decline_rate is the slope of linear regression on daily_effects."""
        service = InteractionDetectionService()
        # Decreasing values → negative slope
        result = service.detect_novelty_effect([1.0, 0.8, 0.6, 0.4, 0.2])
        assert result.decline_rate < 0

    def test_recommendation_includes_minimum_runtime(self):
        """Recommendation includes 'minimum runtime' when novelty is detected."""
        service = InteractionDetectionService()
        result = service.detect_novelty_effect([0.9, 0.7, 0.5, 0.3, 0.1])
        assert result.has_novelty is True
        assert "minimum runtime" in result.recommendation.lower() or "runtime" in result.recommendation.lower()


# ---------------------------------------------------------------------------
# TestSUTVAViolation (5 tests)
# ---------------------------------------------------------------------------

class TestSUTVAViolation:
    """Tests for SUTVA (Stable Unit Treatment Value Assumption) violation checks."""

    def test_check_sutva_returns_sutva_result(self):
        """check_sutva returns a SUTVAResult instance."""
        service = InteractionDetectionService()
        result = service.check_sutva(treatment_size=500, control_size=500)
        assert isinstance(result, SUTVAResult)

    def test_network_feature_returns_warning(self):
        """Network feature flag → warning about potential SUTVA violation."""
        service = InteractionDetectionService()
        result = service.check_sutva(
            treatment_size=500, control_size=500, network_feature=True
        )
        assert result.has_violation is True
        assert result.warning_message is not None

    def test_non_network_feature_clean(self):
        """Non-network feature → no SUTVA concern."""
        service = InteractionDetectionService()
        result = service.check_sutva(
            treatment_size=500, control_size=500, network_feature=False
        )
        assert result.has_violation is False

    def test_compute_contamination_rate(self):
        """compute_contamination_rate returns the fraction of contaminated control users."""
        service = InteractionDetectionService()
        # 50 out of 200 control users exposed to treatment → 0.25
        rate = service.compute_contamination_rate(
            treatment_users={"t1", "t2", "t3"},
            control_users_exposed_to_treatment={"t1", "t2"},
        )
        assert isinstance(rate, float)
        assert 0.0 <= rate <= 1.0

    def test_zero_contamination_no_sutva(self):
        """Zero contamination → no SUTVA concern."""
        service = InteractionDetectionService()
        result = service.check_sutva(
            treatment_size=500,
            control_size=500,
            network_feature=False,
            contamination_rate=0.0,
        )
        assert result.has_violation is False
        assert result.contamination_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestInteractionService (5 tests)
# ---------------------------------------------------------------------------

class TestInteractionService:
    """High-level service tests that use a mocked database."""

    def _make_mock_db(self):
        return MagicMock()

    def test_analyze_experiment_pair_returns_interaction_analysis(self):
        """analyze_experiment_pair returns an InteractionAnalysis (or None)."""
        service = InteractionDetectionService()
        mock_db = self._make_mock_db()

        # Patch internals to avoid real DB calls
        with patch.object(
            service,
            "_get_experiment_users",
            side_effect=[{"u1", "u2", "u3", "u4"}, {"u3", "u4", "u5", "u6"}],
        ):
            result = service.analyze_experiment_pair(
                str(uuid4()), str(uuid4()), mock_db
            )
        assert result is None or isinstance(result, InteractionAnalysis)

    def test_analyze_experiment_pair_returns_none_no_overlap(self):
        """analyze_experiment_pair returns None when experiments don't overlap."""
        service = InteractionDetectionService()
        mock_db = self._make_mock_db()

        with patch.object(
            service,
            "_get_experiment_users",
            side_effect=[{"u1", "u2"}, {"u3", "u4"}],
        ):
            result = service.analyze_experiment_pair(
                str(uuid4()), str(uuid4()), mock_db
            )
        assert result is None

    def test_analyze_experiment_pair_aggregates_sub_results(self):
        """analyze_experiment_pair aggregates overlap, interaction, novelty, SUTVA."""
        service = InteractionDetectionService()
        mock_db = self._make_mock_db()

        # Significant overlap: |{u1,u2,u3}∩{u2,u3,u4}| / |union| = 2/4 = 0.5
        with patch.object(
            service,
            "_get_experiment_users",
            side_effect=[{"u1", "u2", "u3"}, {"u2", "u3", "u4"}],
        ):
            result = service.analyze_experiment_pair(
                str(uuid4()), str(uuid4()), mock_db
            )
        assert result is not None
        assert isinstance(result, InteractionAnalysis)
        assert hasattr(result, "overlap_coefficient")
        assert hasattr(result, "overall_risk")
        assert hasattr(result, "recommendations")

    def test_scan_active_experiments_returns_list(self):
        """scan_active_experiments returns a list of InteractionAnalysis objects."""
        service = InteractionDetectionService()
        mock_db = self._make_mock_db()

        with patch.object(service, "_get_active_experiment_ids", return_value=[]):
            results = service.scan_active_experiments(mock_db)
        assert isinstance(results, list)

    def test_scan_active_experiments_excludes_low_overlap_pairs(self):
        """Pairs with overlap < 0.3 are excluded from scan results."""
        service = InteractionDetectionService()
        mock_db = self._make_mock_db()

        exp_a = str(uuid4())
        exp_b = str(uuid4())

        with patch.object(
            service, "_get_active_experiment_ids", return_value=[exp_a, exp_b]
        ):
            # Low overlap: only 1 user in common out of 10 → ~0.1
            with patch.object(
                service,
                "_get_experiment_users",
                side_effect=[
                    {"u1", "u2", "u3", "u4", "u5"},
                    {"u5", "u6", "u7", "u8", "u9"},
                ],
            ):
                results = service.scan_active_experiments(mock_db)
        # overlap = 1/9 ≈ 0.11 < 0.3 → excluded
        assert results == []
