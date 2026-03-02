"""
Unit tests for EP-022 Batch 3: Lambda extensions for mutual exclusion and global holdout.

Tests cover:
- ConsistentHasher.get_normalized_hash extension
- GlobalHoldoutConfig and check_global_holdout
- MutualExclusionGroupConfig and check_mutual_exclusion
- Integration of holdout/exclusion into the assignment flow
"""

import sys
from pathlib import Path
from collections import Counter
from unittest.mock import patch, MagicMock

import pytest

# Add Lambda shared and assignment modules to path so their local imports resolve
_lambda_dir = Path(__file__).resolve().parents[3] / "lambda"
sys.path.insert(0, str(_lambda_dir / "shared"))
sys.path.insert(0, str(_lambda_dir / "assignment"))

from consistent_hash import ConsistentHasher
from models import (
    ExperimentConfig,
    ExperimentStatus,
    VariantConfig,
    MutualExclusionGroupConfig,
    GlobalHoldoutConfig,
)
from assignment_service import AssignmentService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_experiment_config(
    experiment_id: str = "exp_001",
    key: str = "test_experiment",
    status: str = "active",
    traffic_allocation: float = 1.0,
) -> ExperimentConfig:
    """Create a minimal valid ExperimentConfig for testing."""
    return ExperimentConfig(
        experiment_id=experiment_id,
        key=key,
        status=status,
        variants=[
            VariantConfig(key="control", allocation=0.5),
            VariantConfig(key="treatment", allocation=0.5),
        ],
        traffic_allocation=traffic_allocation,
    )


def _make_service() -> AssignmentService:
    """Create an AssignmentService with mocked environment."""
    with patch("assignment_service.get_env_variable", return_value="mock-table"):
        return AssignmentService()


# ===========================================================================
# TestConsistentHasherExtension (6 tests)
# ===========================================================================

class TestConsistentHasherExtension:
    """Tests for ConsistentHasher.get_normalized_hash."""

    def setup_method(self):
        self.hasher = ConsistentHasher()

    def test_get_normalized_hash_returns_in_range(self):
        """get_normalized_hash returns a value in [0, 1)."""
        result = self.hasher.get_normalized_hash("user_123", "salt_abc")
        assert 0.0 <= result < 1.0

    def test_get_normalized_hash_deterministic(self):
        """Same user/salt always produces the same hash."""
        h1 = self.hasher.get_normalized_hash("user_42", "my_salt")
        h2 = self.hasher.get_normalized_hash("user_42", "my_salt")
        assert h1 == h2

    def test_get_normalized_hash_different_users(self):
        """Different user IDs produce different hashes (with very high probability)."""
        h1 = self.hasher.get_normalized_hash("user_alpha", "same_salt")
        h2 = self.hasher.get_normalized_hash("user_beta", "same_salt")
        assert h1 != h2

    def test_get_normalized_hash_distribution(self):
        """Hash values are roughly uniformly distributed across [0, 1)."""
        num_users = 10000
        buckets = [0] * 10  # 10 equal-width buckets
        for i in range(num_users):
            h = self.hasher.get_normalized_hash(f"user_{i}", "dist_salt")
            bucket_idx = min(int(h * 10), 9)
            buckets[bucket_idx] += 1

        expected = num_users / 10  # 1000 per bucket
        for count in buckets:
            # Allow 30% deviation from expected
            assert abs(count - expected) < expected * 0.30, (
                f"Bucket count {count} deviates too much from expected {expected}"
            )

    def test_get_normalized_hash_empty_user_id(self):
        """Empty user_id still produces a valid normalized hash."""
        result = self.hasher.get_normalized_hash("", "some_salt")
        assert 0.0 <= result < 1.0

    def test_get_normalized_hash_special_characters_in_salt(self):
        """Special characters in salt produce a valid normalized hash."""
        result = self.hasher.get_normalized_hash("user_1", "salt/with:special@chars!")
        assert 0.0 <= result < 1.0


# ===========================================================================
# TestGlobalHoldoutCheck (10 tests)
# ===========================================================================

class TestGlobalHoldoutCheck:
    """Tests for AssignmentService.check_global_holdout."""

    def setup_method(self):
        self.service = _make_service()

    def test_no_holdout_config_not_excluded(self):
        """No holdout config means user is not excluded."""
        assert self.service.check_global_holdout("user_1", None) is False

    def test_inactive_holdout_not_excluded(self):
        """Inactive holdout config means user is not excluded."""
        config = GlobalHoldoutConfig(holdout_percentage=10, is_active=False)
        assert self.service.check_global_holdout("user_1", config) is False

    def test_user_in_holdout_bucket_excluded(self):
        """User whose bucket falls within holdout_percentage is excluded."""
        config = GlobalHoldoutConfig(holdout_percentage=20, is_active=True)
        # Find a user that IS in the holdout (bucket < 20)
        excluded_users = []
        for i in range(200):
            uid = f"user_{i}"
            if self.service.check_global_holdout(uid, config):
                excluded_users.append(uid)
        assert len(excluded_users) > 0, "Expected at least one user to be in holdout"

    def test_user_not_in_holdout_bucket_not_excluded(self):
        """User whose bucket is >= holdout_percentage is not excluded."""
        config = GlobalHoldoutConfig(holdout_percentage=5, is_active=True)
        not_excluded = []
        for i in range(200):
            uid = f"user_{i}"
            if not self.service.check_global_holdout(uid, config):
                not_excluded.append(uid)
        assert len(not_excluded) > 0, "Expected at least one user not in holdout"

    def test_zero_like_holdout_nobody_excluded(self):
        """With holdout_percentage=1 (minimum), very few users excluded."""
        config = GlobalHoldoutConfig(holdout_percentage=1, is_active=True)
        excluded_count = sum(
            1 for i in range(1000)
            if self.service.check_global_holdout(f"user_{i}", config)
        )
        # ~1% of 1000 = ~10, allow generous range
        assert excluded_count < 50, f"Too many excluded: {excluded_count}"

    def test_max_holdout_percentage(self):
        """With holdout_percentage=20 (max), roughly 20% excluded."""
        config = GlobalHoldoutConfig(holdout_percentage=20, is_active=True)
        excluded_count = sum(
            1 for i in range(1000)
            if self.service.check_global_holdout(f"user_{i}", config)
        )
        # ~20% of 1000 = ~200, allow generous range
        assert 100 < excluded_count < 350, f"Unexpected exclusion count: {excluded_count}"

    def test_deterministic_same_user(self):
        """Same user always gets the same holdout result."""
        config = GlobalHoldoutConfig(holdout_percentage=10, is_active=True)
        r1 = self.service.check_global_holdout("consistent_user", config)
        r2 = self.service.check_global_holdout("consistent_user", config)
        assert r1 == r2

    def test_different_percentages_change_boundary(self):
        """Increasing holdout_percentage increases the number of excluded users."""
        config_5 = GlobalHoldoutConfig(holdout_percentage=5, is_active=True)
        config_15 = GlobalHoldoutConfig(holdout_percentage=15, is_active=True)

        excluded_5 = sum(
            1 for i in range(1000)
            if self.service.check_global_holdout(f"user_{i}", config_5)
        )
        excluded_15 = sum(
            1 for i in range(1000)
            if self.service.check_global_holdout(f"user_{i}", config_15)
        )
        assert excluded_15 > excluded_5

    def test_boundary_user_at_holdout_percentage(self):
        """A user whose bucket equals exactly holdout_percentage is NOT excluded (strict <)."""
        config = GlobalHoldoutConfig(holdout_percentage=10, is_active=True)
        # The check is: bucket < holdout_percentage
        # We patch get_bucket to return exactly 10
        with patch.object(self.service.hasher, "get_bucket", return_value=10):
            assert self.service.check_global_holdout("boundary_user", config) is False

    def test_one_percent_holdout_very_few_excluded(self):
        """1% holdout excludes approximately 1% of users."""
        config = GlobalHoldoutConfig(holdout_percentage=1, is_active=True)
        excluded_count = sum(
            1 for i in range(10000)
            if self.service.check_global_holdout(f"user_{i}", config)
        )
        # ~1% of 10000 = ~100, allow generous range
        assert 30 < excluded_count < 250, f"Unexpected exclusion count: {excluded_count}"


# ===========================================================================
# TestMutualExclusionCheck (12 tests)
# ===========================================================================

class TestMutualExclusionCheck:
    """Tests for AssignmentService.check_mutual_exclusion."""

    def setup_method(self):
        self.service = _make_service()

    def test_no_exclusion_config_not_excluded(self):
        """No exclusion config means user is not excluded."""
        assert self.service.check_mutual_exclusion("user_1", "exp_1", None) is False

    def test_user_excluded_from_entire_group(self):
        """User with hash >= traffic_allocation is excluded from the entire group."""
        config = MutualExclusionGroupConfig(
            group_id="group_1",
            traffic_allocation=0.5,
            experiment_ids=["exp_1", "exp_2"],
        )
        # Find a user excluded from the entire group
        excluded = False
        for i in range(200):
            uid = f"user_{i}"
            h = self.service.hasher.get_normalized_hash(uid, "group_1")
            if h >= 0.5:
                assert self.service.check_mutual_exclusion(uid, "exp_1", config) is True
                excluded = True
                break
        assert excluded, "Could not find a user excluded from entire group"

    def test_user_selected_for_this_experiment_not_excluded(self):
        """User selected for the requested experiment is NOT excluded."""
        config = MutualExclusionGroupConfig(
            group_id="group_sel",
            traffic_allocation=1.0,
            experiment_ids=["exp_a", "exp_b"],
        )
        # With traffic_allocation=1.0, everyone is in group.
        # For each user, one of the two experiments should NOT be excluded.
        found_not_excluded = False
        for i in range(200):
            uid = f"user_{i}"
            for exp_id in ["exp_a", "exp_b"]:
                if not self.service.check_mutual_exclusion(uid, exp_id, config):
                    found_not_excluded = True
                    break
            if found_not_excluded:
                break
        assert found_not_excluded

    def test_user_selected_for_different_experiment_excluded(self):
        """User selected for a different experiment IS excluded from this one."""
        config = MutualExclusionGroupConfig(
            group_id="group_diff",
            traffic_allocation=1.0,
            experiment_ids=["exp_x", "exp_y"],
        )
        # For each user in group, exactly one experiment should exclude them
        found_excluded = False
        for i in range(200):
            uid = f"user_{i}"
            excluded_x = self.service.check_mutual_exclusion(uid, "exp_x", config)
            excluded_y = self.service.check_mutual_exclusion(uid, "exp_y", config)
            # One should be excluded and the other not
            if excluded_x != excluded_y:
                found_excluded = True
                break
        assert found_excluded

    def test_single_experiment_in_group_always_selected(self):
        """With a single experiment in the group, all in-group users are selected for it."""
        config = MutualExclusionGroupConfig(
            group_id="group_single",
            traffic_allocation=1.0,
            experiment_ids=["exp_only"],
        )
        for i in range(100):
            uid = f"user_{i}"
            # traffic_allocation=1.0 so nobody is out-of-group
            # single experiment, so user should always be selected
            assert self.service.check_mutual_exclusion(uid, "exp_only", config) is False

    def test_two_experiments_deterministic_selection(self):
        """With two experiments, the same user is always assigned to the same one."""
        config = MutualExclusionGroupConfig(
            group_id="group_det",
            traffic_allocation=1.0,
            experiment_ids=["exp_1", "exp_2"],
        )
        for i in range(50):
            uid = f"det_user_{i}"
            r1_1 = self.service.check_mutual_exclusion(uid, "exp_1", config)
            r1_2 = self.service.check_mutual_exclusion(uid, "exp_1", config)
            r2_1 = self.service.check_mutual_exclusion(uid, "exp_2", config)
            r2_2 = self.service.check_mutual_exclusion(uid, "exp_2", config)
            assert r1_1 == r1_2, "Determinism failed for exp_1"
            assert r2_1 == r2_2, "Determinism failed for exp_2"

    def test_three_experiments_proportional_distribution(self):
        """With three experiments, users are roughly equally distributed."""
        config = MutualExclusionGroupConfig(
            group_id="group_three",
            traffic_allocation=1.0,
            experiment_ids=["exp_a", "exp_b", "exp_c"],
        )
        selections = Counter()
        num_users = 3000
        for i in range(num_users):
            uid = f"prop_user_{i}"
            for exp_id in ["exp_a", "exp_b", "exp_c"]:
                if not self.service.check_mutual_exclusion(uid, exp_id, config):
                    selections[exp_id] += 1
                    break

        expected = num_users / 3  # ~1000 each
        for exp_id in ["exp_a", "exp_b", "exp_c"]:
            count = selections[exp_id]
            assert abs(count - expected) < expected * 0.30, (
                f"{exp_id}: {count} selections, expected ~{expected}"
            )

    def test_traffic_allocation_zero_everyone_excluded(self):
        """With traffic_allocation=0, everyone is excluded."""
        config = MutualExclusionGroupConfig(
            group_id="group_zero",
            traffic_allocation=0.0,
            experiment_ids=["exp_1"],
        )
        for i in range(100):
            uid = f"user_{i}"
            assert self.service.check_mutual_exclusion(uid, "exp_1", config) is True

    def test_traffic_allocation_one_everyone_eligible(self):
        """With traffic_allocation=1.0, everyone is eligible for the group."""
        config = MutualExclusionGroupConfig(
            group_id="group_full",
            traffic_allocation=1.0,
            experiment_ids=["exp_1"],
        )
        for i in range(100):
            uid = f"user_{i}"
            # Single experiment, so all in-group users are selected
            assert self.service.check_mutual_exclusion(uid, "exp_1", config) is False

    def test_consistent_across_repeated_calls(self):
        """Mutual exclusion results are consistent across repeated invocations."""
        config = MutualExclusionGroupConfig(
            group_id="group_repeat",
            traffic_allocation=0.7,
            experiment_ids=["exp_1", "exp_2"],
        )
        for i in range(50):
            uid = f"repeat_user_{i}"
            first = self.service.check_mutual_exclusion(uid, "exp_1", config)
            second = self.service.check_mutual_exclusion(uid, "exp_1", config)
            assert first == second

    def test_different_group_ids_different_selections(self):
        """Different group_ids produce different experiment selections for same user."""
        config_a = MutualExclusionGroupConfig(
            group_id="group_alpha",
            traffic_allocation=1.0,
            experiment_ids=["exp_1", "exp_2"],
        )
        config_b = MutualExclusionGroupConfig(
            group_id="group_beta",
            traffic_allocation=1.0,
            experiment_ids=["exp_1", "exp_2"],
        )
        # Across many users, at least one should differ between the two groups
        differences = 0
        for i in range(200):
            uid = f"group_user_{i}"
            r_a = self.service.check_mutual_exclusion(uid, "exp_1", config_a)
            r_b = self.service.check_mutual_exclusion(uid, "exp_1", config_b)
            if r_a != r_b:
                differences += 1
        assert differences > 0, "Expected different group_ids to produce different selections"

    def test_empty_experiment_ids_excluded(self):
        """Empty experiment_ids list results in exclusion (fallback)."""
        config = MutualExclusionGroupConfig(
            group_id="group_empty",
            traffic_allocation=1.0,
            experiment_ids=[],
        )
        # slot_size is 0 when experiment_ids is empty, so the loop never matches
        # and the fallback return True (excluded) is reached
        assert self.service.check_mutual_exclusion("user_1", "exp_1", config) is True


# ===========================================================================
# TestAssignmentFlowIntegration (6 tests)
# ===========================================================================

class TestAssignmentFlowIntegration:
    """Tests for the complete assignment flow with holdout and exclusion checks."""

    def setup_method(self):
        self.service = _make_service()
        self.experiment_config = _make_experiment_config()

    def test_normal_flow_without_holdout_exclusion(self):
        """Assignment works unchanged when no holdout/exclusion configs are provided."""
        variant = self.service.assign_variant(
            user_id="normal_user",
            experiment_config=self.experiment_config,
        )
        assert variant in ("control", "treatment")

    def test_holdout_user_gets_none(self):
        """A user in the holdout group gets None from assign_variant."""
        holdout_config = GlobalHoldoutConfig(holdout_percentage=20, is_active=True)

        # Find a user that IS in the holdout
        for i in range(500):
            uid = f"holdout_test_{i}"
            if self.service.check_global_holdout(uid, holdout_config):
                variant = self.service.assign_variant(
                    user_id=uid,
                    experiment_config=self.experiment_config,
                    holdout_config=holdout_config,
                )
                assert variant is None
                return
        pytest.fail("Could not find a user in the holdout after 500 attempts")

    def test_excluded_by_mutual_exclusion_gets_none(self):
        """A user excluded by mutual exclusion gets None from assign_variant."""
        exclusion_config = MutualExclusionGroupConfig(
            group_id="test_group",
            traffic_allocation=1.0,
            experiment_ids=["exp_001", "exp_002"],
        )

        # Find a user that IS excluded from exp_001 (selected for exp_002)
        for i in range(500):
            uid = f"excl_test_{i}"
            if self.service.check_mutual_exclusion(uid, "exp_001", exclusion_config):
                variant = self.service.assign_variant(
                    user_id=uid,
                    experiment_config=self.experiment_config,
                    exclusion_config=exclusion_config,
                )
                assert variant is None
                return
        pytest.fail("Could not find an excluded user after 500 attempts")

    def test_holdout_checked_before_exclusion(self):
        """When both configs present, holdout is checked first."""
        holdout_config = GlobalHoldoutConfig(holdout_percentage=20, is_active=True)
        exclusion_config = MutualExclusionGroupConfig(
            group_id="test_group",
            traffic_allocation=1.0,
            experiment_ids=["exp_001", "exp_002"],
        )

        # Patch both checks to track call order
        call_order = []

        original_holdout = self.service.check_global_holdout
        original_exclusion = self.service.check_mutual_exclusion

        def mock_holdout(user_id, config):
            call_order.append("holdout")
            return True  # Excluded by holdout

        def mock_exclusion(user_id, experiment_id, config):
            call_order.append("exclusion")
            return True

        self.service.check_global_holdout = mock_holdout
        self.service.check_mutual_exclusion = mock_exclusion

        variant = self.service.assign_variant(
            user_id="order_user",
            experiment_config=self.experiment_config,
            holdout_config=holdout_config,
            exclusion_config=exclusion_config,
        )

        assert variant is None
        # Holdout should be checked first, and since it returns True,
        # exclusion should NOT be checked
        assert call_order == ["holdout"]

    def test_eligible_user_through_both_checks_gets_assignment(self):
        """A user passing both holdout and exclusion checks gets a variant."""
        holdout_config = GlobalHoldoutConfig(holdout_percentage=5, is_active=True)
        exclusion_config = MutualExclusionGroupConfig(
            group_id="pass_group",
            traffic_allocation=1.0,
            experiment_ids=["exp_001"],  # Single experiment, so all in-group users pass
        )

        # Find a user that passes holdout
        for i in range(500):
            uid = f"eligible_{i}"
            if not self.service.check_global_holdout(uid, holdout_config):
                variant = self.service.assign_variant(
                    user_id=uid,
                    experiment_config=self.experiment_config,
                    holdout_config=holdout_config,
                    exclusion_config=exclusion_config,
                )
                assert variant in ("control", "treatment")
                return
        pytest.fail("Could not find an eligible user after 500 attempts")

    def test_holdout_only_no_exclusion_works(self):
        """Config with only holdout (no exclusion) works correctly."""
        holdout_config = GlobalHoldoutConfig(holdout_percentage=5, is_active=True)

        # Find a user NOT in holdout
        for i in range(500):
            uid = f"holdout_only_{i}"
            if not self.service.check_global_holdout(uid, holdout_config):
                variant = self.service.assign_variant(
                    user_id=uid,
                    experiment_config=self.experiment_config,
                    holdout_config=holdout_config,
                    exclusion_config=None,
                )
                assert variant in ("control", "treatment")
                return
        pytest.fail("Could not find a non-holdout user after 500 attempts")
