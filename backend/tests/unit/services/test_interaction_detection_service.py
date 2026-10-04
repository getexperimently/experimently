"""
Unit tests for the InteractionDetectionService.

Tests cover the overlap computation and the ``/scan`` methods.  The pair
route's analysis is tested in ``test_interaction_pair_analysis.py``.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.services.interaction_detection_service import (
    InteractionAnalysis,
    InteractionDetectionService,
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
        result = service.has_significant_overlap(
            {"a", "b", "c"}, {"b", "c", "d"}, threshold=0.3
        )
        assert result is True

    def test_has_significant_overlap_false_below_threshold(self):
        """has_significant_overlap returns False when Jaccard ≤ threshold."""
        service = InteractionDetectionService()
        # Jaccard = 1/5 = 0.2  <  0.3
        result = service.has_significant_overlap(
            {"a", "b", "c"}, {"c", "d", "e"}, threshold=0.3
        )
        assert result is False


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

    def test_analyze_experiment_pair_reports_overlap_and_no_sub_results(self):
        """Only the overlap is measured: the sub-results are None (#219)."""
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
        assert result.overlap_coefficient == 0.5
        assert result.interaction_result is None
        assert result.novelty_result is None
        assert result.sutva_result is None
        assert result.overall_risk == "medium"
        assert result.recommendations

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
