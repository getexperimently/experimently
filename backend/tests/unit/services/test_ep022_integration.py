"""
Integration tests for EP-022: Mutual Exclusion Groups + Global Holdout cross-cutting behavior.

Tests the interaction between the MutualExclusionService, GlobalHoldoutService, and the
Lambda AssignmentService to verify that holdout exclusion, mutual exclusion, deterministic
hashing, traffic allocation edge cases, and activation flows all work correctly together.
"""

import sys
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.global_holdout import GlobalHoldout
from backend.app.models.mutual_exclusion_group import (
    MutualExclusionGroup,
    MutualExclusionGroupStatus,
)
from backend.app.services.global_holdout_service import (
    HOLDOUT_SALT,
    GlobalHoldoutService,
)
from backend.app.services.mutual_exclusion_service import MutualExclusionService

# ---------------------------------------------------------------------------
# Lambda module path setup
# ---------------------------------------------------------------------------
_lambda_base = Path(__file__).resolve().parents[3] / "lambda"
_lambda_shared = str(_lambda_base / "shared")
_lambda_assignment = str(_lambda_base / "assignment")

for _p in (_lambda_shared, _lambda_assignment):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from consistent_hash import ConsistentHasher  # noqa: E402
from models import (  # noqa: E402
    ExperimentConfig,
    ExperimentStatus as LambdaExperimentStatus,
    GlobalHoldoutConfig,
    MutualExclusionGroupConfig,
    VariantConfig,
)
from assignment_service import AssignmentService  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_group(
    group_id=None,
    traffic_allocation=1.0,
    status=MutualExclusionGroupStatus.ACTIVE,
):
    group = MagicMock(spec=MutualExclusionGroup)
    group.id = group_id or uuid4()
    group.traffic_allocation = traffic_allocation
    group.status = status
    return group


def _make_experiment(exp_id=None, status=ExperimentStatus.ACTIVE, group_id=None):
    exp = MagicMock(spec=Experiment)
    exp.id = exp_id or uuid4()
    exp.status = status
    exp.mutual_exclusion_group_id = group_id
    return exp


def _make_holdout(holdout_id=None, percentage=10, is_active=True):
    holdout = MagicMock(spec=GlobalHoldout)
    holdout.id = holdout_id or uuid4()
    holdout.holdout_percentage = percentage
    holdout.is_active = is_active
    return holdout


def _make_lambda_experiment_config(experiment_id=None, key=None):
    """Create an ExperimentConfig suitable for the Lambda AssignmentService."""
    return ExperimentConfig(
        experiment_id=experiment_id or str(uuid4()),
        key=key or f"exp_{uuid4().hex[:8]}",
        status=LambdaExperimentStatus.ACTIVE,
        variants=[
            VariantConfig(key="control", allocation=0.5),
            VariantConfig(key="treatment", allocation=0.5),
        ],
        traffic_allocation=1.0,
    )


def _make_assignment_service():
    """Create an AssignmentService instance (no real AWS resources needed)."""
    return AssignmentService()


def _setup_db_for_selection(mock_db, group, experiments):
    """Wire mock_db so get_group returns `group` and get_active_group_experiments returns `experiments`."""
    call_count = [0]

    def side_effect(model):
        call_count[0] += 1
        result = MagicMock()
        if call_count[0] <= 1:
            result.filter.return_value.first.return_value = group
        else:
            result.filter.return_value.all.return_value = experiments
        return result

    mock_db.query = MagicMock(side_effect=side_effect)


# ---------------------------------------------------------------------------
# 1. Holdout + Exclusion interaction
# ---------------------------------------------------------------------------


class TestHoldoutExcludesFromAllExperiments:
    """A user in the global holdout should be excluded from ALL experiments,
    even those inside mutual exclusion groups."""

    def test_holdout_user_excluded_from_standalone_experiment(self):
        """Users in holdout get no variant from the Lambda assignment service."""
        hasher = ConsistentHasher()

        # Pick users who ARE in a 20% holdout
        holdout_users = []
        for i in range(500):
            uid = f"holdout_check_{i}"
            bucket = hasher.get_bucket(uid, "global_holdout_v1", num_buckets=100)
            if bucket < 20:
                holdout_users.append(uid)
            if len(holdout_users) >= 5:
                break

        assert len(holdout_users) > 0, "Could not find a user in holdout"

        holdout_config = GlobalHoldoutConfig(holdout_percentage=20, is_active=True)
        exp_config = _make_lambda_experiment_config()

        svc = _make_assignment_service()
        for uid in holdout_users:
            variant = svc.assign_variant(uid, exp_config, holdout_config=holdout_config)
            assert variant is None, f"User {uid} should be excluded by holdout"

    def test_holdout_user_excluded_from_mutual_exclusion_group_experiment(self):
        """Even if a user would be selected for an experiment in a mutual exclusion
        group, holdout takes priority."""
        hasher = ConsistentHasher()

        group_id = str(uuid4())
        exp_ids = sorted([str(uuid4()) for _ in range(3)])
        exclusion_config = MutualExclusionGroupConfig(
            group_id=group_id,
            traffic_allocation=1.0,
            experiment_ids=exp_ids,
        )
        holdout_config = GlobalHoldoutConfig(holdout_percentage=20, is_active=True)

        # Find users in holdout
        holdout_users = []
        for i in range(500):
            uid = f"combo_test_{i}"
            bucket = hasher.get_bucket(uid, "global_holdout_v1", num_buckets=100)
            if bucket < 20:
                holdout_users.append(uid)
            if len(holdout_users) >= 3:
                break

        assert len(holdout_users) > 0

        svc = _make_assignment_service()
        for uid in holdout_users:
            for exp_id in exp_ids:
                exp_config = _make_lambda_experiment_config(experiment_id=exp_id)
                variant = svc.assign_variant(
                    uid, exp_config,
                    holdout_config=holdout_config,
                    exclusion_config=exclusion_config,
                )
                assert variant is None, (
                    f"User {uid} in holdout must be excluded from experiment {exp_id}"
                )

    def test_non_holdout_user_can_be_assigned(self):
        """Users NOT in holdout should still be assignable."""
        hasher = ConsistentHasher()

        holdout_config = GlobalHoldoutConfig(holdout_percentage=5, is_active=True)
        exp_config = _make_lambda_experiment_config()

        # Find a user not in holdout
        non_holdout_user = None
        for i in range(500):
            uid = f"non_holdout_{i}"
            bucket = hasher.get_bucket(uid, "global_holdout_v1", num_buckets=100)
            if bucket >= 5:
                non_holdout_user = uid
                break

        assert non_holdout_user is not None

        svc = _make_assignment_service()
        variant = svc.assign_variant(non_holdout_user, exp_config, holdout_config=holdout_config)
        assert variant is not None, "Non-holdout user should be assigned a variant"


# ---------------------------------------------------------------------------
# 2. Multi-group consistency (deterministic hashing)
# ---------------------------------------------------------------------------


class TestMultiGroupConsistency:
    """A user should always get the same experiment from a group."""

    def test_same_user_same_group_always_same_result(self):
        """Calling select_experiment_for_user many times yields the same experiment."""
        mock_db = MagicMock()
        service = MutualExclusionService(mock_db)

        group = _make_group(traffic_allocation=1.0)
        exp_a = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000001"))
        exp_b = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000002"))
        exp_c = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000003"))

        results = []
        for _ in range(20):
            _setup_db_for_selection(mock_db, group, [exp_a, exp_b, exp_c])
            result = service.select_experiment_for_user("stable_user_42", group.id)
            results.append(result)

        assert len(set(results)) == 1, "All results should be identical for the same user"

    def test_determinism_across_service_instances(self):
        """Different service instances give the same result for the same user+group."""
        group = _make_group(traffic_allocation=1.0)
        exp_a = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000010"))
        exp_b = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000020"))

        results = []
        for _ in range(5):
            db = MagicMock()
            svc = MutualExclusionService(db)
            _setup_db_for_selection(db, group, [exp_a, exp_b])
            results.append(svc.select_experiment_for_user("cross_instance_user", group.id))

        assert len(set(results)) == 1


# ---------------------------------------------------------------------------
# 3. Cross-group independence
# ---------------------------------------------------------------------------


class TestCrossGroupIndependence:
    """Being assigned to experiment A in group 1 should not affect group 2."""

    def test_independent_group_assignments(self):
        """Assignment in group 1 is independent of assignment in group 2."""
        mock_db = MagicMock()
        service = MutualExclusionService(mock_db)

        group1 = _make_group(traffic_allocation=1.0)
        group2 = _make_group(traffic_allocation=1.0)

        exp_g1_a = _make_experiment(exp_id=UUID("10000000-0000-0000-0000-000000000001"))
        exp_g1_b = _make_experiment(exp_id=UUID("10000000-0000-0000-0000-000000000002"))
        exp_g2_a = _make_experiment(exp_id=UUID("20000000-0000-0000-0000-000000000001"))
        exp_g2_b = _make_experiment(exp_id=UUID("20000000-0000-0000-0000-000000000002"))

        # Gather assignments across many users
        group1_results = []
        group2_results = []
        for i in range(200):
            uid = f"cross_group_user_{i}"

            _setup_db_for_selection(mock_db, group1, [exp_g1_a, exp_g1_b])
            r1 = service.select_experiment_for_user(uid, group1.id)
            group1_results.append(r1)

            _setup_db_for_selection(mock_db, group2, [exp_g2_a, exp_g2_b])
            r2 = service.select_experiment_for_user(uid, group2.id)
            group2_results.append(r2)

        # Both groups should assign users (non-trivial)
        assert len(set(group1_results)) > 1 or len(group1_results) > 0
        assert len(set(group2_results)) > 1 or len(group2_results) > 0

        # The assignments should not be perfectly correlated.
        # Build (group1, group2) pairs and verify we see different combos.
        pairs = set(zip(group1_results, group2_results))
        # With 200 users and 2 experiments per group, we expect varied combos
        assert len(pairs) >= 2, (
            "Group assignments should be independent -- expected varied pairs"
        )


# ---------------------------------------------------------------------------
# 4. Traffic allocation edge cases
# ---------------------------------------------------------------------------


class TestTrafficAllocationEdgeCases:
    """0% traffic = no users; 100% traffic = all users get an experiment."""

    def test_zero_traffic_excludes_all(self):
        """With traffic_allocation = 0.0, no user should be assigned."""
        mock_db = MagicMock()
        service = MutualExclusionService(mock_db)

        group = _make_group(traffic_allocation=0.0)
        exp = _make_experiment()

        assigned_count = 0
        for i in range(100):
            _setup_db_for_selection(mock_db, group, [exp])
            result = service.select_experiment_for_user(f"user_{i}", group.id)
            if result is not None:
                assigned_count += 1

        assert assigned_count == 0, "0% traffic should assign nobody"

    def test_full_traffic_assigns_all(self):
        """With traffic_allocation = 1.0, every user should be assigned."""
        mock_db = MagicMock()
        service = MutualExclusionService(mock_db)

        group = _make_group(traffic_allocation=1.0)
        exp = _make_experiment()

        none_count = 0
        for i in range(200):
            _setup_db_for_selection(mock_db, group, [exp])
            result = service.select_experiment_for_user(f"alltraffic_user_{i}", group.id)
            if result is None:
                none_count += 1

        assert none_count == 0, "100% traffic should assign everyone"

    def test_lambda_zero_traffic_mutual_exclusion(self):
        """Lambda AssignmentService: 0% group traffic excludes all users."""
        exclusion_config = MutualExclusionGroupConfig(
            group_id=str(uuid4()),
            traffic_allocation=0.0,
            experiment_ids=[str(uuid4()), str(uuid4())],
        )
        exp_config = _make_lambda_experiment_config(
            experiment_id=exclusion_config.experiment_ids[0]
        )

        svc = _make_assignment_service()
        for i in range(50):
            variant = svc.assign_variant(
                f"zero_traffic_{i}", exp_config, exclusion_config=exclusion_config
            )
            assert variant is None


# ---------------------------------------------------------------------------
# 5. Holdout percentage distribution
# ---------------------------------------------------------------------------


class TestHoldoutPercentageDistribution:
    """With N% holdout, approximately N% of random users should be excluded."""

    @pytest.mark.parametrize("holdout_pct", [5, 10, 15, 20])
    def test_holdout_percentage_matches_distribution(self, holdout_pct):
        """The fraction of users hashed into holdout should approximate the percentage."""
        num_users = 5000
        in_holdout = 0
        for i in range(num_users):
            is_in, _ = GlobalHoldoutService.is_user_in_holdout_static(
                f"dist_user_{i}", holdout_pct
            )
            if is_in:
                in_holdout += 1

        actual_pct = (in_holdout / num_users) * 100
        # Allow +/- 3 percentage points tolerance
        assert abs(actual_pct - holdout_pct) < 3.0, (
            f"Expected ~{holdout_pct}% in holdout, got {actual_pct:.1f}%"
        )

    def test_holdout_service_agrees_with_static(self):
        """Instance method and static method should produce identical results."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = GlobalHoldoutService(mock_db)

        for i in range(100):
            uid = f"agree_user_{i}"
            instance_bucket = service._get_holdout_bucket(uid)
            static_bucket = GlobalHoldoutService._get_holdout_bucket_static(uid)
            assert instance_bucket == static_bucket


# ---------------------------------------------------------------------------
# 6. Mutual exclusion fairness
# ---------------------------------------------------------------------------


class TestMutualExclusionFairness:
    """With equal traffic, each experiment in a group should get roughly equal share."""

    def test_two_experiments_equal_split(self):
        """Two experiments in a group with 100% traffic should each get ~50%."""
        mock_db = MagicMock()
        service = MutualExclusionService(mock_db)

        group = _make_group(traffic_allocation=1.0)
        exp_a = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000001"))
        exp_b = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000002"))

        counts = Counter()
        num_users = 5000
        for i in range(num_users):
            _setup_db_for_selection(mock_db, group, [exp_a, exp_b])
            result = service.select_experiment_for_user(f"fair_user_{i}", group.id)
            counts[result] += 1

        pct_a = counts[exp_a.id] / num_users * 100
        pct_b = counts[exp_b.id] / num_users * 100

        # Each should be ~50% with tolerance
        assert 40 < pct_a < 60, f"Experiment A got {pct_a:.1f}%, expected ~50%"
        assert 40 < pct_b < 60, f"Experiment B got {pct_b:.1f}%, expected ~50%"

    def test_three_experiments_equal_split(self):
        """Three experiments should each get ~33%."""
        mock_db = MagicMock()
        service = MutualExclusionService(mock_db)

        group = _make_group(traffic_allocation=1.0)
        exp_a = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000001"))
        exp_b = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000002"))
        exp_c = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000003"))

        counts = Counter()
        num_users = 6000
        for i in range(num_users):
            _setup_db_for_selection(mock_db, group, [exp_a, exp_b, exp_c])
            result = service.select_experiment_for_user(f"fair3_user_{i}", group.id)
            counts[result] += 1

        for exp in [exp_a, exp_b, exp_c]:
            pct = counts[exp.id] / num_users * 100
            assert 25 < pct < 42, f"Experiment {exp.id} got {pct:.1f}%, expected ~33%"

    def test_fairness_with_partial_traffic(self):
        """With 60% traffic and 2 experiments, each gets ~30% of total users."""
        mock_db = MagicMock()
        service = MutualExclusionService(mock_db)

        group = _make_group(traffic_allocation=0.6)
        exp_a = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000001"))
        exp_b = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000002"))

        counts = Counter()
        excluded = 0
        num_users = 5000
        for i in range(num_users):
            _setup_db_for_selection(mock_db, group, [exp_a, exp_b])
            result = service.select_experiment_for_user(f"partial_user_{i}", group.id)
            if result is None:
                excluded += 1
            else:
                counts[result] += 1

        excluded_pct = excluded / num_users * 100
        # ~40% should be excluded
        assert 30 < excluded_pct < 50, f"Excluded {excluded_pct:.1f}%, expected ~40%"

        # Among assigned users, each experiment should get ~50%
        total_assigned = sum(counts.values())
        if total_assigned > 0:
            for exp in [exp_a, exp_b]:
                pct = counts[exp.id] / total_assigned * 100
                assert 40 < pct < 60, (
                    f"Experiment {exp.id} got {pct:.1f}% of assigned, expected ~50%"
                )


# ---------------------------------------------------------------------------
# 7. Activation / deactivation flows
# ---------------------------------------------------------------------------


class TestActivationDeactivationFlows:
    """Activating one holdout should deactivate the currently active one."""

    def test_activating_new_holdout_deactivates_previous(self):
        """When we activate holdout B, holdout A should become inactive."""
        mock_db = MagicMock()
        service = GlobalHoldoutService(mock_db)

        holdout_a = _make_holdout(percentage=10, is_active=True)
        holdout_b = _make_holdout(percentage=5, is_active=False)

        # First, activate A (it is already active)
        mock_db.query.return_value.filter.return_value.first.return_value = holdout_a
        service.activate_holdout(holdout_a.id)
        assert holdout_a.is_active is True

        # Now activate B -- the service should call _deactivate_all first
        mock_db.reset_mock()
        mock_db.query.return_value.filter.return_value.first.return_value = holdout_b
        service.activate_holdout(holdout_b.id)

        assert holdout_b.is_active is True
        # _deactivate_all calls update() on the query
        mock_db.query.return_value.filter.return_value.update.assert_called()
        mock_db.flush.assert_called()

    def test_deactivating_holdout_allows_all_users(self):
        """After deactivating a holdout, no user should be excluded."""
        mock_db = MagicMock()
        service = GlobalHoldoutService(mock_db)

        # No active holdout
        mock_db.query.return_value.filter.return_value.first.return_value = None

        for i in range(50):
            is_in, pct, bucket = service.is_user_in_holdout(f"post_deactivate_{i}")
            assert is_in is False
            assert pct == 0

    def test_only_one_holdout_active_at_a_time(self):
        """Activating a holdout should ensure exactly one is active."""
        mock_db = MagicMock()
        service = GlobalHoldoutService(mock_db)

        holdout = _make_holdout(percentage=10, is_active=False)
        mock_db.query.return_value.filter.return_value.first.return_value = holdout

        service.activate_holdout(holdout.id)

        # _deactivate_all should have been called (flush is called inside it)
        mock_db.flush.assert_called()
        assert holdout.is_active is True


# ---------------------------------------------------------------------------
# 8. Adding / removing experiments from groups
# ---------------------------------------------------------------------------


class TestAddRemoveExperimentsFromGroups:
    """After adding a new experiment to a group, traffic should redistribute."""

    def test_adding_experiment_changes_some_assignments(self):
        """When a third experiment is added, some users previously assigned to
        experiment A or B should now be assigned to experiment C."""
        mock_db = MagicMock()
        service = MutualExclusionService(mock_db)

        group = _make_group(traffic_allocation=1.0)
        exp_a = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000001"))
        exp_b = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000002"))
        exp_c = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000003"))

        users = [f"redist_user_{i}" for i in range(500)]

        # Phase 1: 2 experiments
        phase1 = {}
        for uid in users:
            _setup_db_for_selection(mock_db, group, [exp_a, exp_b])
            phase1[uid] = service.select_experiment_for_user(uid, group.id)

        # Phase 2: 3 experiments (exp_c added)
        phase2 = {}
        for uid in users:
            _setup_db_for_selection(mock_db, group, [exp_a, exp_b, exp_c])
            phase2[uid] = service.select_experiment_for_user(uid, group.id)

        # Some users should now be assigned to exp_c
        assigned_to_c = sum(1 for v in phase2.values() if v == exp_c.id)
        assert assigned_to_c > 0, "Adding experiment C should give it some users"

        # Some users should have changed assignments
        changed = sum(1 for uid in users if phase1[uid] != phase2[uid])
        assert changed > 0, "Adding a new experiment should change some assignments"

    def test_removing_experiment_redistributes(self):
        """When an experiment is removed, its users should be reassigned."""
        mock_db = MagicMock()
        service = MutualExclusionService(mock_db)

        group = _make_group(traffic_allocation=1.0)
        exp_a = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000001"))
        exp_b = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000002"))
        exp_c = _make_experiment(exp_id=UUID("00000000-0000-0000-0000-000000000003"))

        users = [f"remove_user_{i}" for i in range(500)]

        # Phase 1: 3 experiments
        phase1 = {}
        for uid in users:
            _setup_db_for_selection(mock_db, group, [exp_a, exp_b, exp_c])
            phase1[uid] = service.select_experiment_for_user(uid, group.id)

        users_in_c = [uid for uid in users if phase1[uid] == exp_c.id]
        assert len(users_in_c) > 0, "Some users should be in experiment C"

        # Phase 2: experiment C removed
        phase2 = {}
        for uid in users:
            _setup_db_for_selection(mock_db, group, [exp_a, exp_b])
            phase2[uid] = service.select_experiment_for_user(uid, group.id)

        # Users that were in C should now be in A or B
        for uid in users_in_c:
            assert phase2[uid] in (exp_a.id, exp_b.id), (
                f"User {uid} was in C, should now be in A or B"
            )

        # No user should be unassigned (traffic=1.0, experiments exist)
        for uid in users:
            assert phase2[uid] is not None

    def test_lambda_mutual_exclusion_redistributes_on_new_experiment(self):
        """Lambda AssignmentService: adding a third experiment changes some outcomes."""
        group_id = str(uuid4())
        exp_ids_2 = sorted([str(uuid4()), str(uuid4())])
        exp_ids_3 = sorted(exp_ids_2 + [str(uuid4())])

        config_2 = MutualExclusionGroupConfig(
            group_id=group_id, traffic_allocation=1.0, experiment_ids=exp_ids_2
        )
        config_3 = MutualExclusionGroupConfig(
            group_id=group_id, traffic_allocation=1.0, experiment_ids=exp_ids_3
        )

        svc = _make_assignment_service()
        changed = 0
        for i in range(300):
            uid = f"lambda_redist_{i}"
            # With 2 experiments: is user excluded from first experiment?
            excluded_2 = svc.check_mutual_exclusion(uid, exp_ids_2[0], config_2)
            # With 3 experiments: is user excluded from first experiment?
            excluded_3 = svc.check_mutual_exclusion(uid, exp_ids_3[0], config_3)
            if excluded_2 != excluded_3:
                changed += 1

        assert changed > 0, "Adding a third experiment should change some exclusion outcomes"
