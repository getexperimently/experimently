"""A legacy condition whose operator is not eq/ne/gt/lt/contains/in does not match (#733).

The legacy (list-shaped) targeting rules are evaluated in
``FeatureFlagService._evaluate_rule``. That loop rejects a condition only when
a known operator fails, so before #733 a condition whose ``operator`` was
anything else -- ``equal``, ``equals``, ``gte``, a typo, or no operator at
all -- passed for every user who sent the attribute, whatever its value.

Such a condition now does not match, as in the Lambda evaluator
(``backend/lambda/feature_flag_evaluation/evaluator.py``, the ``else`` branch
of ``evaluate_targeting_rules``). The flag's global rollout then decides.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from backend.app.models.feature_flag import FeatureFlagStatus
from backend.app.services import feature_flag_service as ffs

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_MISSING = object()


def _condition(operator: Any) -> Dict[str, Any]:
    condition: Dict[str, Any] = {"attribute": "plan", "value": "pro"}
    if operator is not _MISSING:
        condition["operator"] = operator
    return condition


def _flag(conditions: List[Dict[str, Any]], rollout: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000733",
        key="legacy-operator",
        status=FeatureFlagStatus.ACTIVE,
        rollout_percentage=rollout,
        targeting_rules=[
            {
                "id": "pro-only",
                "type": "context",
                "conditions": conditions,
                "percentage": 100,
            }
        ],
    )


def _evaluate(
    monkeypatch: pytest.MonkeyPatch,
    flag: SimpleNamespace,
    context: Optional[Dict[str, Any]],
    user_id: str = "user-1",
) -> Dict[str, Any]:
    monkeypatch.setattr(ffs, "MetricsService", MagicMock())
    service = ffs.FeatureFlagService(db=MagicMock())
    return service.evaluate_flag_detailed(flag, user_id, context)


NOT_A_LEGACY_OPERATOR = [
    pytest.param("equal", id="equal"),
    pytest.param("equals", id="equals"),
    pytest.param("gte", id="gte"),
    pytest.param("eqq", id="typo"),
    pytest.param("", id="empty"),
    pytest.param(None, id="null"),
    pytest.param(_MISSING, id="missing"),
    # A stored operator is any JSON value; a list or an object must not raise.
    pytest.param(["eq"], id="list"),
    pytest.param({"op": "eq"}, id="object"),
]


@pytest.mark.parametrize("operator", NOT_A_LEGACY_OPERATOR)
@pytest.mark.parametrize("plan", ["pro", "free"])
def test_a_condition_with_an_operator_outside_the_legacy_set_does_not_match(
    monkeypatch, operator, plan
):
    flag = _flag([_condition(operator)])

    result = _evaluate(monkeypatch, flag, {"plan": plan})

    assert result == {"enabled": False, "reason": "rollout", "rule_id": None}


@pytest.mark.parametrize("operator", NOT_A_LEGACY_OPERATOR)
def test_evaluate_rule_answers_false_for_an_operator_outside_the_legacy_set(
    operator,
):
    service = ffs.FeatureFlagService(db=MagicMock())
    rule = {"type": "context", "conditions": [_condition(operator)]}

    assert service._evaluate_rule(rule, "user-1", {"plan": "pro"}) is False


@pytest.mark.parametrize("operator", NOT_A_LEGACY_OPERATOR)
def test_one_unknown_operator_fails_the_whole_rule(operator):
    """A known condition that matches does not rescue an unknown one beside it."""
    service = ffs.FeatureFlagService(db=MagicMock())
    rule = {
        "type": "context",
        "conditions": [
            {"attribute": "country", "operator": "eq", "value": "US"},
            _condition(operator),
        ],
    }

    assert (
        service._evaluate_rule(rule, "user-1", {"country": "US", "plan": "pro"})
        is False
    )


def test_eq_still_matches(monkeypatch):
    flag = _flag([_condition("eq")])

    assert _evaluate(monkeypatch, flag, {"plan": "pro"}) == {
        "enabled": True,
        "reason": "targeting_rule",
        "rule_id": "pro-only",
    }
    assert _evaluate(monkeypatch, flag, {"plan": "free"}) == {
        "enabled": False,
        "reason": "rollout",
        "rule_id": None,
    }


@pytest.mark.parametrize(
    "operator, value, matching, other",
    [
        ("ne", "free", "pro", "free"),
        ("gt", 5, 6, 5),
        ("lt", 5, 4, 5),
        ("contains", "ro", "pro", "free"),
        ("in", ["pro", "team"], "pro", "free"),
    ],
)
def test_the_other_legacy_operators_are_unchanged(
    monkeypatch, operator, value, matching, other
):
    flag = _flag([{"attribute": "plan", "operator": operator, "value": value}])

    assert _evaluate(monkeypatch, flag, {"plan": matching})["enabled"] is True
    assert _evaluate(monkeypatch, flag, {"plan": other})["enabled"] is False


@pytest.mark.parametrize("operator", NOT_A_LEGACY_OPERATOR)
def test_at_global_zero_percent_a_user_sending_the_attribute_is_not_served(
    monkeypatch, operator
):
    flag = _flag([_condition(operator)], rollout=0)

    served = [
        user_id
        for user_id in (f"user-{n}" for n in range(200))
        if _evaluate(monkeypatch, flag, {"plan": "pro"}, user_id)["enabled"]
    ]

    assert served == []
