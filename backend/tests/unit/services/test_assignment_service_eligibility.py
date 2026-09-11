"""
Unit tests for the eligibility gate in ``AssignmentService.assign_user``.

New users are checked, in order, against the global holdout, the experiment's
mutual exclusion group and its targeting rules.  These tests use a MagicMock
session and stub the holdout / mutual-exclusion services so each branch can be
driven directly; the DB-backed behaviour lives in
``backend/tests/integration/api/test_tracking_api.py::TestAssignEligibility``.
"""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.models.assignment import Assignment
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.schemas.targeting_rule import TargetingRules
from backend.app.services.assignment_service import (
    REASON_ASSIGNED,
    REASON_HOLDOUT,
    REASON_MUTUAL_EXCLUSION,
    REASON_TARGETING,
    AssignmentService,
)

NATIVE_US_ONLY = {
    "version": "1.0",
    "rules": [
        {
            "id": "us_only",
            "rule": {
                "operator": "and",
                "conditions": [
                    {"attribute": "country", "operator": "eq", "value": "US"}
                ],
            },
            "rollout_percentage": 100,
            "priority": 1,
        }
    ],
}

NATIVE_USER_DOT_COUNTRY = {
    "version": "1.0",
    "rules": [
        {
            "id": "us_only_alias",
            "rule": {
                "operator": "and",
                "conditions": [
                    {"attribute": "user.country", "operator": "eq", "value": "US"}
                ],
            },
            "rollout_percentage": 100,
            "priority": 1,
        }
    ],
}

DASHBOARD_US_ONLY = {
    "logical_operator": "AND",
    "groups": [
        {
            "logical_operator": "AND",
            "conditions": [
                {"attribute": "user.country", "operator": "equals", "value": "US"}
            ],
        }
    ],
}


def _variant(name, is_control, allocation=50):
    variant = MagicMock()
    variant.id = uuid4()
    variant.name = name
    variant.is_control = is_control
    variant.traffic_allocation = allocation
    return variant


@pytest.fixture
def experiment():
    exp = MagicMock(spec=Experiment)
    exp.id = uuid4()
    exp.status = ExperimentStatus.ACTIVE
    exp.mutual_exclusion_group_id = None
    exp.targeting_rules = None
    exp.variants = [_variant("control", True), _variant("treatment", False)]
    return exp


@pytest.fixture
def service(experiment):
    """AssignmentService on a MagicMock session that finds ``experiment`` and
    no sticky assignment; holdout and MEG are stubbed as "eligible"."""
    db = MagicMock()
    db.query.return_value.options.return_value.filter.return_value.first.return_value = (
        experiment
    )
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
        None
    )
    svc = AssignmentService(db)
    svc.event_service = MagicMock()
    svc.global_holdout_service = MagicMock()
    svc.global_holdout_service.is_user_in_holdout.return_value = (False, 0, 57)
    svc.mutual_exclusion_service = MagicMock()
    svc.mutual_exclusion_service.is_user_eligible_for_experiment.return_value = True
    return svc


def _control(experiment):
    return next(v for v in experiment.variants if v.is_control)


def _assigned_dict(experiment, variant):
    return {
        "id": str(uuid4()),
        "user_id": "user-1",
        "experiment_id": str(experiment.id),
        "variant_id": str(variant.id),
        "variant_name": variant.name,
        "is_control": variant.is_control,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


def _assert_not_assigned(result, experiment, reason):
    control = _control(experiment)
    assert result["assigned"] is False
    assert result["reason"] == reason
    assert result["experiment_id"] == str(experiment.id)
    assert result["user_id"] == "user-1"
    assert result["variant_id"] == str(control.id)
    assert result["variant_name"] == "control"
    assert result["is_control"] is True
    assert result["id"] is None
    assert result["created_at"] is None


class TestHoldout:
    def test_user_in_holdout_is_not_assigned(self, service, experiment):
        service.global_holdout_service.is_user_in_holdout.return_value = (True, 10, 3)

        result = service.assign_user("user-1", experiment.id, context={"country": "US"})

        _assert_not_assigned(result, experiment, REASON_HOLDOUT)
        assert "10%" in result["detail"] and "bucket 3" in result["detail"]
        service.db.add.assert_not_called()
        service.db.commit.assert_not_called()
        service.event_service.track_exposure.assert_not_called()
        # Later gates are never consulted
        service.mutual_exclusion_service.is_user_eligible_for_experiment.assert_not_called()

    def test_user_outside_holdout_is_assigned(self, service, experiment):
        treatment = experiment.variants[1]
        with patch.object(
            service,
            "get_assignment",
            return_value=_assigned_dict(experiment, treatment),
        ), patch.object(service, "_hash_user_to_variant", return_value=treatment.id):
            result = service.assign_user("user-1", experiment.id)

        assert result["assigned"] is True
        assert result["reason"] == REASON_ASSIGNED
        assert result["variant_id"] == str(treatment.id)
        service.db.add.assert_called_once()
        service.db.commit.assert_called_once()
        service.event_service.track_exposure.assert_called_once()


class TestMutualExclusion:
    def test_group_selecting_another_experiment_blocks_assignment(
        self, service, experiment
    ):
        experiment.mutual_exclusion_group_id = uuid4()
        service.mutual_exclusion_service.is_user_eligible_for_experiment.return_value = (
            False
        )

        result = service.assign_user("user-1", experiment.id)

        _assert_not_assigned(result, experiment, REASON_MUTUAL_EXCLUSION)
        service.mutual_exclusion_service.is_user_eligible_for_experiment.assert_called_once_with(
            "user-1", experiment.id
        )
        service.db.add.assert_not_called()
        service.event_service.track_exposure.assert_not_called()

    def test_experiment_without_group_skips_the_check(self, service, experiment):
        treatment = experiment.variants[1]
        with patch.object(
            service,
            "get_assignment",
            return_value=_assigned_dict(experiment, treatment),
        ), patch.object(service, "_hash_user_to_variant", return_value=treatment.id):
            result = service.assign_user("user-1", experiment.id)

        assert result["assigned"] is True
        service.mutual_exclusion_service.is_user_eligible_for_experiment.assert_not_called()

    def test_holdout_wins_over_mutual_exclusion(self, service, experiment):
        experiment.mutual_exclusion_group_id = uuid4()
        service.global_holdout_service.is_user_in_holdout.return_value = (True, 5, 1)
        service.mutual_exclusion_service.is_user_eligible_for_experiment.return_value = (
            False
        )

        result = service.assign_user("user-1", experiment.id)

        assert result["reason"] == REASON_HOLDOUT


class TestTargeting:
    def test_non_matching_context_is_not_assigned(self, service, experiment):
        experiment.targeting_rules = NATIVE_US_ONLY

        result = service.assign_user("user-1", experiment.id, context={"country": "DE"})

        _assert_not_assigned(result, experiment, REASON_TARGETING)
        assert "No targeting rules matched" in result["detail"]
        service.db.add.assert_not_called()
        service.event_service.track_exposure.assert_not_called()

    def test_missing_context_is_not_assigned(self, service, experiment):
        experiment.targeting_rules = NATIVE_US_ONLY

        result = service.assign_user("user-1", experiment.id)

        _assert_not_assigned(result, experiment, REASON_TARGETING)

    def test_matching_context_is_assigned_and_exposure_keeps_raw_context(
        self, service, experiment
    ):
        experiment.targeting_rules = json.dumps(NATIVE_US_ONLY)
        treatment = experiment.variants[1]
        with patch.object(
            service,
            "get_assignment",
            return_value=_assigned_dict(experiment, treatment),
        ), patch.object(service, "_hash_user_to_variant", return_value=treatment.id):
            result = service.assign_user(
                "user-1", experiment.id, context={"country": "US"}
            )

        assert result["assigned"] is True
        assert result["reason"] == REASON_ASSIGNED
        service.db.add.assert_called_once()
        # The exposure event records the request context as sent, not the
        # alias-expanded lookup dict.
        service.event_service.track_exposure.assert_called_once()
        assert service.event_service.track_exposure.call_args.kwargs["properties"] == {
            "country": "US"
        }

    def test_top_level_context_answers_user_dot_alias(self, service, experiment):
        experiment.targeting_rules = NATIVE_USER_DOT_COUNTRY
        treatment = experiment.variants[1]
        with patch.object(
            service,
            "get_assignment",
            return_value=_assigned_dict(experiment, treatment),
        ), patch.object(service, "_hash_user_to_variant", return_value=treatment.id):
            result = service.assign_user(
                "user-1", experiment.id, context={"country": "US"}
            )

        assert result["assigned"] is True

    def test_dashboard_shape_is_normalised(self, service, experiment):
        experiment.targeting_rules = DASHBOARD_US_ONLY
        treatment = experiment.variants[1]

        blocked = service.assign_user(
            "user-1", experiment.id, context={"country": "DE"}
        )
        _assert_not_assigned(blocked, experiment, REASON_TARGETING)

        with patch.object(
            service,
            "get_assignment",
            return_value=_assigned_dict(experiment, treatment),
        ), patch.object(service, "_hash_user_to_variant", return_value=treatment.id):
            allowed = service.assign_user(
                "user-1", experiment.id, context={"country": "US"}
            )
        assert allowed["assigned"] is True

    @pytest.mark.parametrize(
        "rules",
        [
            {},
            {"rules": []},
            {"version": "1.0", "rules": []},
            {"logical_operator": "AND", "groups": []},
            [],
            [{"type": "user_id", "conditions": [], "percentage": 100}],
        ],
        ids=[
            "empty-dict",
            "empty-rules",
            "versioned-empty",
            "empty-dashboard",
            "empty-list",
            "legacy-list",
        ],
    )
    def test_rule_containers_without_rules_admit_everyone(
        self, service, experiment, rules
    ):
        experiment.targeting_rules = rules
        treatment = experiment.variants[1]
        with patch.object(
            service,
            "get_assignment",
            return_value=_assigned_dict(experiment, treatment),
        ), patch.object(service, "_hash_user_to_variant", return_value=treatment.id):
            result = service.assign_user("user-1", experiment.id)

        assert result["assigned"] is True, rules

    def test_mutual_exclusion_wins_over_targeting(self, service, experiment):
        experiment.mutual_exclusion_group_id = uuid4()
        experiment.targeting_rules = NATIVE_US_ONLY
        service.mutual_exclusion_service.is_user_eligible_for_experiment.return_value = (
            False
        )

        result = service.assign_user("user-1", experiment.id, context={"country": "DE"})

        assert result["reason"] == REASON_MUTUAL_EXCLUSION


class TestStickyAssignments:
    def test_existing_row_bypasses_every_gate(self, service, experiment):
        treatment = experiment.variants[1]
        existing = MagicMock(spec=Assignment)
        existing.variant_id = treatment.id
        service.db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            existing
        )
        # The user would now fail all three checks ...
        service.global_holdout_service.is_user_in_holdout.return_value = (True, 20, 2)
        experiment.mutual_exclusion_group_id = uuid4()
        service.mutual_exclusion_service.is_user_eligible_for_experiment.return_value = (
            False
        )
        experiment.targeting_rules = NATIVE_US_ONLY

        with patch.object(
            service,
            "get_assignment",
            return_value=_assigned_dict(experiment, treatment),
        ):
            result = service.assign_user(
                "user-1", experiment.id, context={"country": "DE"}
            )

        # ... but keeps the stored variant and is reported as assigned.
        assert result["assigned"] is True
        assert result["reason"] == REASON_ASSIGNED
        assert result["variant_id"] == str(treatment.id)
        service.db.add.assert_not_called()
        service.event_service.track_exposure.assert_called_once()
        service.global_holdout_service.is_user_in_holdout.assert_not_called()
        service.mutual_exclusion_service.is_user_eligible_for_experiment.assert_not_called()


class TestCheckEligibility:
    def test_eligible_result_shape(self, service, experiment):
        result = service.check_eligibility("user-1", experiment, {"country": "US"})
        assert result == {"eligible": True, "reason": REASON_ASSIGNED, "detail": None}

    def test_order_is_holdout_then_group_then_targeting(self, service, experiment):
        experiment.mutual_exclusion_group_id = uuid4()
        experiment.targeting_rules = NATIVE_US_ONLY
        service.mutual_exclusion_service.is_user_eligible_for_experiment.return_value = (
            False
        )
        ctx = {"country": "DE"}

        service.global_holdout_service.is_user_in_holdout.return_value = (True, 20, 0)
        assert (
            service.check_eligibility("user-1", experiment, ctx)["reason"]
            == REASON_HOLDOUT
        )

        service.global_holdout_service.is_user_in_holdout.return_value = (False, 20, 99)
        assert (
            service.check_eligibility("user-1", experiment, ctx)["reason"]
            == REASON_MUTUAL_EXCLUSION
        )

        service.mutual_exclusion_service.is_user_eligible_for_experiment.return_value = (
            True
        )
        assert (
            service.check_eligibility("user-1", experiment, ctx)["reason"]
            == REASON_TARGETING
        )

        assert service.check_eligibility("user-1", experiment, {"country": "US"})[
            "eligible"
        ]


class TestControlVariantFallback:
    def test_first_variant_used_when_none_is_flagged_control(self, service, experiment):
        for variant in experiment.variants:
            variant.is_control = False
        service.global_holdout_service.is_user_in_holdout.return_value = (True, 10, 0)

        result = service.assign_user("user-1", experiment.id)

        assert result["assigned"] is False
        assert result["variant_id"] == str(experiment.variants[0].id)
        assert result["is_control"] is False

    def test_no_variants_raises(self, service, experiment):
        experiment.variants = []
        service.global_holdout_service.is_user_in_holdout.return_value = (True, 10, 0)

        with pytest.raises(ValueError, match="has no variants"):
            service.assign_user("user-1", experiment.id)


class TestCoerceTargetingRules:
    def test_native_dict_and_json_string(self):
        rules, why = AssignmentService._coerce_targeting_rules(NATIVE_US_ONLY)
        assert isinstance(rules, TargetingRules) and why is None
        assert rules.rules[0].id == "us_only"

        rules, why = AssignmentService._coerce_targeting_rules(
            json.dumps(NATIVE_US_ONLY)
        )
        assert isinstance(rules, TargetingRules) and why is None

    def test_targeting_rules_instance_passthrough(self):
        obj = TargetingRules(**NATIVE_US_ONLY)
        rules, why = AssignmentService._coerce_targeting_rules(obj)
        assert rules is obj and why is None

    def test_dashboard_shape_is_converted(self):
        rules, why = AssignmentService._coerce_targeting_rules(DASHBOARD_US_ONLY)
        assert isinstance(rules, TargetingRules) and why is None
        condition = rules.rules[0].rule.groups[0].conditions[0]
        assert condition.attribute == "user.country"
        assert condition.value == "US"

    def test_legacy_list_is_ignored(self):
        rules, why = AssignmentService._coerce_targeting_rules(
            [{"type": "user_id", "conditions": [], "percentage": 100}]
        )
        assert rules is None and "List-shaped" in why
