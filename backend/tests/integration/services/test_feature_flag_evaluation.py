"""
Integration tests for FeatureFlagService evaluation logic (Phase 4).

These tests exercise the evaluate_flag() method and related helpers with
a real DB session, verifying rollout percentage logic, targeting rules,
and the get_user_flags() aggregation method.
"""

import uuid

import pytest

from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.services.feature_flag_service import FeatureFlagService
from backend.tests.integration.helpers import unique_flag_key


@pytest.mark.integration
@pytest.mark.requires_db
class TestFeatureFlagEvaluationService:
    """Direct service-layer evaluation tests with a real DB session."""

    def test_inactive_flag_evaluates_to_false(self, db_session, make_feature_flag):
        """An INACTIVE flag always returns False regardless of rollout percentage."""
        flag = make_feature_flag(
            key=unique_flag_key("inactive"),
            name="Inactive Flag",
            status=FeatureFlagStatus.INACTIVE,
            rollout_percentage=100,
        )
        service = FeatureFlagService(db_session)
        result = service.evaluate_flag(flag, "any-user")
        assert result is False

    def test_active_flag_at_100pct_evaluates_to_true(
        self, db_session, make_feature_flag
    ):
        """An ACTIVE flag at 100% rollout always returns True."""
        flag = make_feature_flag(
            key=unique_flag_key("full-rollout"),
            name="Full Rollout Flag",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=100,
        )
        service = FeatureFlagService(db_session)
        result = service.evaluate_flag(flag, "test-user-123")
        assert result is True

    def test_active_flag_at_0pct_evaluates_to_false(
        self, db_session, make_feature_flag
    ):
        """An ACTIVE flag at 0% rollout always returns False."""
        flag = make_feature_flag(
            key=unique_flag_key("zero-rollout"),
            name="Zero Rollout Flag",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=0,
        )
        service = FeatureFlagService(db_session)
        result = service.evaluate_flag(flag, "any-user")
        assert result is False

    def test_archived_flag_evaluates_to_false(self, db_session, make_feature_flag):
        """An ARCHIVED flag evaluates to False (not ACTIVE)."""
        flag = make_feature_flag(
            key=unique_flag_key("archived"),
            name="Archived Flag",
            status=FeatureFlagStatus.ARCHIVED,
            rollout_percentage=100,
        )
        service = FeatureFlagService(db_session)
        result = service.evaluate_flag(flag, "user-abc")
        assert result is False

    def test_evaluation_is_deterministic_for_same_user(
        self, db_session, make_feature_flag
    ):
        """For a given user and flag key, evaluation always returns the same result."""
        flag = make_feature_flag(
            key=unique_flag_key("deterministic"),
            name="Deterministic Flag",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=50,
        )
        service = FeatureFlagService(db_session)
        user_id = "stable-user-42"
        first = service.evaluate_flag(flag, user_id)
        second = service.evaluate_flag(flag, user_id)
        assert first == second

    def test_different_users_can_get_different_evaluation_results(
        self, db_session, make_feature_flag
    ):
        """At 50% rollout, different users hash to different buckets."""
        flag = make_feature_flag(
            key=unique_flag_key("split"),
            name="50 50 Split Flag",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=50,
        )
        service = FeatureFlagService(db_session)

        # Evaluate a large set of users; expect a mix of True and False
        results = {service.evaluate_flag(flag, f"user-bucket-{i}") for i in range(50)}
        # With 50 users and 50% rollout it's statistically near-impossible to get all same
        assert True in results and False in results

    def test_evaluate_flag_with_user_id_targeting_rule(
        self, db_session, make_feature_flag
    ):
        """A user_id targeting rule returns True only for listed users."""
        targeting_rules = [
            {
                "type": "user_id",
                "user_ids": ["allowed-user-1", "allowed-user-2"],
                "percentage": 100,
            }
        ]
        flag = make_feature_flag(
            key=unique_flag_key("user-id-rule"),
            name="User ID Rule Flag",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=0,
            targeting_rules=targeting_rules,
        )
        service = FeatureFlagService(db_session)

        assert service.evaluate_flag(flag, "allowed-user-1") is True
        assert service.evaluate_flag(flag, "not-allowed-user") is False

    def test_evaluate_flag_with_context_rule(self, db_session, make_feature_flag):
        """A context-based targeting rule evaluates correctly against user context."""
        targeting_rules = [
            {
                "type": "context",
                "conditions": [
                    {"attribute": "country", "operator": "eq", "value": "US"}
                ],
                "percentage": 100,
            }
        ]
        flag = make_feature_flag(
            key=unique_flag_key("context-rule"),
            name="Context Rule Flag",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=0,
            targeting_rules=targeting_rules,
        )
        service = FeatureFlagService(db_session)

        us_context = {"country": "US"}
        de_context = {"country": "DE"}

        assert service.evaluate_flag(flag, "user-1", us_context) is True
        assert service.evaluate_flag(flag, "user-2", de_context) is False

    def test_get_user_flags_returns_dict_of_active_flags(
        self, db_session, make_feature_flag
    ):
        """get_user_flags() returns a dict mapping active flag keys to boolean values."""
        # Create one active and one inactive flag so we can verify only active are included
        active_flag = make_feature_flag(
            key=unique_flag_key("get-user-active"),
            name="Active For User",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=100,
        )
        make_feature_flag(
            key=unique_flag_key("get-user-inactive"),
            name="Inactive For User",
            status=FeatureFlagStatus.INACTIVE,
            rollout_percentage=100,
        )
        service = FeatureFlagService(db_session)
        flags = service.get_user_flags("test-user-xyz")

        assert isinstance(flags, dict)
        # The active flag key must appear
        assert active_flag.key in flags
        # Value for 100% active flag must be True
        assert flags[active_flag.key] is True

    def test_get_user_flags_excludes_inactive_flags(
        self, db_session, make_feature_flag
    ):
        """get_user_flags() does not include INACTIVE flags in the result dict."""
        inactive_flag = make_feature_flag(
            key=unique_flag_key("exclude-inactive"),
            name="Excluded Inactive",
            status=FeatureFlagStatus.INACTIVE,
            rollout_percentage=100,
        )
        service = FeatureFlagService(db_session)
        flags = service.get_user_flags("user-exclude")

        assert inactive_flag.key not in flags

    def test_get_feature_flag_returns_dict(self, db_session, make_feature_flag):
        """get_feature_flag() returns a dict with expected keys."""
        flag = make_feature_flag(
            key=unique_flag_key("get-service"),
            name="Service Get Flag",
            status=FeatureFlagStatus.ACTIVE,
            rollout_percentage=25,
        )
        service = FeatureFlagService(db_session)
        result = service.get_feature_flag(flag.id)

        assert result is not None
        assert isinstance(result, dict)
        assert result["key"] == flag.key
        assert result["rollout_percentage"] == 25

    def test_get_feature_flag_nonexistent_returns_none(self, db_session):
        """get_feature_flag() with a nonexistent ID returns None."""
        service = FeatureFlagService(db_session)
        result = service.get_feature_flag("00000000-0000-0000-0000-000000000000")
        assert result is None

    def test_count_feature_flags(self, db_session, make_feature_flag):
        """count_feature_flags() reflects the number of flags in the DB."""
        baseline = FeatureFlagService(db_session).count_feature_flags()

        make_feature_flag(key=unique_flag_key("count-a"), name="Count A")
        make_feature_flag(key=unique_flag_key("count-b"), name="Count B")

        total = FeatureFlagService(db_session).count_feature_flags()
        assert total == baseline + 2
