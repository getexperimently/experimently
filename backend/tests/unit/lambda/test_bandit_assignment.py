"""
Unit tests for Lambda MAB assignment extensions — Issue #22 Batch C.

Covers:
- get_bandit_weights()             DynamoDB fetch + fallback
- weighted_variant_selection       consistent, weighted
- assign_variant_mab()             full MAB pipeline
- BanditWeightsConfig model
"""

import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inject Lambda paths so their local imports resolve
# ---------------------------------------------------------------------------
_lambda_dir = Path(__file__).resolve().parents[3] / "lambda"
sys.path.insert(0, str(_lambda_dir / "shared"))
sys.path.insert(0, str(_lambda_dir / "assignment"))

from assignment_service import AssignmentService
from consistent_hash import ConsistentHasher
from models import (
    BanditWeightsConfig,
    ExperimentConfig,
    ExperimentStatus,
    GlobalHoldoutConfig,
    MutualExclusionGroupConfig,
    VariantConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_experiment(
    experiment_id: str = "exp_001",
    key: str = "test_experiment",
    status: str = "active",
    traffic_allocation: float = 1.0,
    variants=None,
) -> ExperimentConfig:
    if variants is None:
        variants = [
            VariantConfig(key="control", allocation=0.5),
            VariantConfig(key="treatment", allocation=0.5),
        ]
    return ExperimentConfig(
        experiment_id=experiment_id,
        key=key,
        status=status,
        variants=variants,
        traffic_allocation=traffic_allocation,
    )


def _make_bandit_weights(
    weights: Dict[str, float] = None,
    algorithm: str = "thompson_sampling",
) -> BanditWeightsConfig:
    if weights is None:
        weights = {"control": 0.5, "treatment": 0.5}
    return BanditWeightsConfig(
        experiment_id="exp_001",
        algorithm=algorithm,
        weights=weights,
        last_updated="2026-01-01T00:00:00Z",
    )


def _make_service() -> AssignmentService:
    with patch("assignment_service.get_env_variable", return_value="mock-table"):
        return AssignmentService()


# ===========================================================================
# Tests
# ===========================================================================


class TestBanditWeightsConfig:
    """Tests for the BanditWeightsConfig Pydantic model."""

    def test_model_round_trips_valid_data(self):
        """BanditWeightsConfig parses correctly from valid dict."""
        config = BanditWeightsConfig(
            experiment_id="exp_abc",
            algorithm="ucb1",
            weights={"control": 0.3, "treatment": 0.7},
            last_updated="2026-01-01T00:00:00Z",
        )
        assert config.experiment_id == "exp_abc"
        assert config.algorithm == "ucb1"
        assert config.weights["treatment"] == pytest.approx(0.7)

    def test_last_updated_defaults_to_none(self):
        """last_updated field is optional and defaults to None."""
        config = BanditWeightsConfig(
            experiment_id="exp_xyz",
            algorithm="epsilon_greedy",
            weights={"v1": 0.9, "v2": 0.1},
        )
        assert config.last_updated is None


class TestGetBanditWeights:
    """Tests for AssignmentService.get_bandit_weights()."""

    # -----------------------------------------------------------------------
    # 1. Returns BanditWeightsConfig from DynamoDB
    # -----------------------------------------------------------------------
    def test_get_bandit_weights_returns_config_from_dynamodb(self):
        """get_bandit_weights returns a BanditWeightsConfig when DynamoDB has data."""
        service = _make_service()

        mock_item = {
            "experiment_id": "exp_001",
            "algorithm": "thompson_sampling",
            "weights": {"control": "0.3", "treatment": "0.7"},
            "last_updated": "2026-01-01T00:00:00Z",
        }

        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": mock_item}
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        with patch("assignment_service.get_env_variable", return_value="bandit-table"):
            with patch(
                "assignment_service.get_dynamodb_resource", return_value=mock_dynamodb
            ):
                result = service.get_bandit_weights("exp_001")

        assert isinstance(result, BanditWeightsConfig)
        assert result.weights["treatment"] == pytest.approx(0.7)

    # -----------------------------------------------------------------------
    # 2. Returns None when no state in DynamoDB
    # -----------------------------------------------------------------------
    def test_get_bandit_weights_returns_none_when_missing(self):
        """Returns None when the DynamoDB item is not found."""
        service = _make_service()

        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # No "Item" key
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        with patch("assignment_service.get_env_variable", return_value="bandit-table"):
            with patch(
                "assignment_service.get_dynamodb_resource", return_value=mock_dynamodb
            ):
                result = service.get_bandit_weights("exp_999")

        assert result is None

    # -----------------------------------------------------------------------
    # 3. Falls back to None when DynamoDB is unavailable
    # -----------------------------------------------------------------------
    def test_get_bandit_weights_falls_back_to_none_on_error(self):
        """Returns None when DynamoDB raises an exception."""
        service = _make_service()

        with patch("assignment_service.get_env_variable", return_value="bandit-table"):
            with patch(
                "assignment_service.get_dynamodb_resource",
                side_effect=Exception("DynamoDB error"),
            ):
                result = service.get_bandit_weights("exp_001")

        assert result is None


class TestWeightedVariantSelection:
    """Tests for AssignmentService.get_weighted_variant()."""

    # -----------------------------------------------------------------------
    # 4. Deterministic: same user+experiment always gets same variant
    # -----------------------------------------------------------------------
    def test_weighted_variant_selection_is_deterministic(self):
        """Same (user_id, experiment) always produces the same variant."""
        service = _make_service()
        exp = _make_experiment()
        weights = _make_bandit_weights({"control": 0.3, "treatment": 0.7})

        result1 = service.get_weighted_variant("user_42", exp, weights)
        result2 = service.get_weighted_variant("user_42", exp, weights)

        assert result1 == result2

    # -----------------------------------------------------------------------
    # 5. Higher-weight variant selected more often
    # -----------------------------------------------------------------------
    def test_higher_weight_variant_selected_more_often(self):
        """Over many users, the higher-weight variant is chosen more frequently."""
        service = _make_service()
        exp = _make_experiment()
        # Treatment gets 80% weight
        weights = _make_bandit_weights({"control": 0.2, "treatment": 0.8})

        counts: Counter = Counter()
        for i in range(10_000):
            variant = service.get_weighted_variant(f"user_{i}", exp, weights)
            if variant:
                counts[variant] += 1

        # Treatment should be selected significantly more than control
        assert counts["treatment"] > counts["control"]
        # Should be roughly 80 / 20 ratio (allow generous tolerance)
        total = counts["control"] + counts["treatment"]
        assert total > 0
        treatment_ratio = counts["treatment"] / total
        assert 0.65 < treatment_ratio < 0.95

    # -----------------------------------------------------------------------
    # 6. Single variant → always selected
    # -----------------------------------------------------------------------
    def test_single_variant_always_selected(self):
        """When one variant has 100% weight, it is always chosen.

        ExperimentConfig requires at least 2 variants, so we use two variants
        but assign 100% weight to one (forcing only that arm to be selected).
        """
        service = _make_service()
        # Two-variant experiment (required by Pydantic validation)
        exp = ExperimentConfig(
            experiment_id="exp_single",
            key="single_variant_exp",
            status=ExperimentStatus.ACTIVE,
            variants=[
                VariantConfig(key="dominant", allocation=0.5),
                VariantConfig(key="other", allocation=0.5),
            ],
            traffic_allocation=1.0,
        )
        # All weight goes to "dominant"
        weights = BanditWeightsConfig(
            experiment_id="exp_single",
            algorithm="ucb1",
            weights={"dominant": 1.0, "other": 0.0},
        )

        results = set()
        for i in range(100):
            result = service.get_weighted_variant(f"user_{i}", exp, weights)
            if result is not None:
                results.add(result)

        # Only the dominant variant should ever be selected
        assert results <= {"dominant"}

    # -----------------------------------------------------------------------
    # 7. Weights summing to 1.0 → all variants eligible
    # -----------------------------------------------------------------------
    def test_all_variants_eligible_with_balanced_weights(self):
        """With equal weights, both variants appear across many users."""
        service = _make_service()
        exp = _make_experiment()
        weights = _make_bandit_weights({"control": 0.5, "treatment": 0.5})

        seen = set()
        for i in range(200):
            v = service.get_weighted_variant(f"user_{i}", exp, weights)
            if v:
                seen.add(v)

        assert "control" in seen
        assert "treatment" in seen

    # -----------------------------------------------------------------------
    # 8. Falls back to equal weights when bandit_weights is None
    # -----------------------------------------------------------------------
    def test_falls_back_to_equal_weights_when_no_bandit_weights(self):
        """With bandit_weights=None, falls back to static uniform allocation."""
        service = _make_service()
        exp = _make_experiment()

        # Should not raise; returns a variant via uniform allocation
        result = service.get_weighted_variant("user_abc", exp, None)
        # Result may be None (excluded by traffic) or a variant key
        assert result in (None, "control", "treatment")


class TestAssignVariantMAB:
    """Tests for AssignmentService.assign_variant_mab()."""

    # -----------------------------------------------------------------------
    # 9. Uses bandit weights instead of uniform hash
    # -----------------------------------------------------------------------
    def test_assign_variant_mab_uses_bandit_weights(self):
        """assign_variant_mab calls get_weighted_variant with bandit weights."""
        service = _make_service()
        exp = _make_experiment()
        weights = _make_bandit_weights({"control": 0.1, "treatment": 0.9})

        with patch.object(
            service, "get_weighted_variant", wraps=service.get_weighted_variant
        ) as mock_weighted:
            service.assign_variant_mab("user_001", exp, bandit_weights=weights)

        mock_weighted.assert_called_once_with("user_001", exp, weights)

    # -----------------------------------------------------------------------
    # 10. Deterministic for same (user_id, experiment_id)
    # -----------------------------------------------------------------------
    def test_assign_variant_mab_deterministic(self):
        """Same (user_id, experiment_id) always produces the same assignment."""
        service = _make_service()
        exp = _make_experiment()
        weights = _make_bandit_weights({"control": 0.3, "treatment": 0.7})

        result1 = service.assign_variant_mab("user_42", exp, bandit_weights=weights)
        result2 = service.assign_variant_mab("user_42", exp, bandit_weights=weights)

        assert result1 == result2

    # -----------------------------------------------------------------------
    # 11. Respects global holdout: returns None for held-out users
    # -----------------------------------------------------------------------
    def test_assign_variant_mab_respects_holdout(self):
        """Users in the global holdout group receive None (not assigned).

        GlobalHoldoutConfig caps holdout_percentage at 20. We verify that
        when a user falls within the holdout bucket they are excluded.
        We use a known user_id whose hash bucket falls within 1-20%.
        """
        service = _make_service()
        exp = _make_experiment()
        weights = _make_bandit_weights()

        # Find a user that IS in the top-20% holdout bucket
        # (i.e., bucket < 20 with num_buckets=100)
        holdout = GlobalHoldoutConfig(holdout_percentage=20, is_active=True)

        # Brute-force: find a user whose bucket < 20
        from consistent_hash import ConsistentHasher

        hasher = ConsistentHasher()
        user_id_in_holdout = None
        for i in range(1000):
            uid = f"holdout_candidate_{i}"
            bucket = hasher.get_bucket(uid, "global_holdout_v1", num_buckets=100)
            if bucket < 20:
                user_id_in_holdout = uid
                break

        assert user_id_in_holdout is not None, (
            "Could not find a user in the holdout bucket"
        )

        result = service.assign_variant_mab(
            user_id_in_holdout, exp, holdout_config=holdout, bandit_weights=weights
        )

        assert result is None

    # -----------------------------------------------------------------------
    # 12. Falls back to equal weights when DynamoDB unavailable
    # -----------------------------------------------------------------------
    def test_assign_variant_mab_falls_back_to_uniform_when_no_weights(self):
        """When bandit_weights=None, assigns via uniform traffic allocation."""
        service = _make_service()
        exp = _make_experiment()

        # Should complete without error
        result = service.assign_variant_mab("user_999", exp, bandit_weights=None)
        assert result in (None, "control", "treatment")

    # -----------------------------------------------------------------------
    # 13. MAB weights stored in DynamoDB bandit-weights table
    # -----------------------------------------------------------------------
    def test_get_bandit_weights_reads_from_bandit_weights_table(self):
        """get_bandit_weights targets the BANDIT_WEIGHTS_TABLE env variable."""
        service = _make_service()

        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "experiment_id": "exp_001",
                "algorithm": "thompson_sampling",
                "weights": {"control": "0.5", "treatment": "0.5"},
            }
        }
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        table_calls = []

        def capture_env(name, default=None):
            table_calls.append(name)
            return "my-bandit-weights-table"

        with patch("assignment_service.get_env_variable", side_effect=capture_env):
            with patch(
                "assignment_service.get_dynamodb_resource", return_value=mock_dynamodb
            ):
                service.get_bandit_weights("exp_001")

        assert "BANDIT_WEIGHTS_TABLE" in table_calls
        mock_dynamodb.Table.assert_called_with("my-bandit-weights-table")

    # -----------------------------------------------------------------------
    # 14. Full pipeline: holdout → exclusion → MAB weights → assign
    # -----------------------------------------------------------------------
    def test_assignment_flow_holdout_exclusion_then_mab_weights(self):
        """Full MAB pipeline: holdout first, then exclusion, then weighted assign."""
        service = _make_service()
        exp = _make_experiment(experiment_id="exp_pipeline", key="pipeline_exp")
        weights = _make_bandit_weights({"control": 0.3, "treatment": 0.7})

        # No holdout, no exclusion → should reach MAB assignment
        result = service.assign_variant_mab(
            "user_pipeline",
            exp,
            holdout_config=None,
            exclusion_config=None,
            bandit_weights=weights,
        )

        assert result in ("control", "treatment")

    # -----------------------------------------------------------------------
    # 15. Analyst can also call get_weighted_variant (pure logic, no role checks)
    # -----------------------------------------------------------------------
    def test_weighted_variant_selection_consistent_across_calls(self):
        """Consistent hashing ensures the same user always gets the same variant."""
        service = _make_service()
        exp = _make_experiment()
        weights = _make_bandit_weights({"control": 0.4, "treatment": 0.6})

        assignments = {}
        for i in range(50):
            uid = f"stable_user_{i}"
            v = service.get_weighted_variant(uid, exp, weights)
            assignments[uid] = v

        # Re-run and verify no changes
        for uid, expected in assignments.items():
            got = service.get_weighted_variant(uid, exp, weights)
            assert got == expected, f"User {uid}: expected {expected}, got {got}"
