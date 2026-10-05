"""
A missing attribute makes only its own condition false on experiments (#822).

Experiment assignment used to refuse a user outright when the context lacked
any attribute a rule named, even one used only in another ``OR`` branch, and
so also refused ``is_null`` on an absent attribute and a ``NOT`` group on it.
Flags never did: the evaluator treats an absent attribute as "this condition
is false" (``is_null`` true) and composes AND, OR and NOT from there.

Every case here runs the dashboard shape through ``normalise_targeting_rules``
and ``expand_context``, then asks both the experiment path (as
``AssignmentService`` runs it, attribute validation on) and the flag path
(``match_targeting_rule``), and pins the answer, so the two cannot drift apart
together.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from backend.app.core.targeting_adapter import (
    expand_context,
    match_targeting_rule,
    normalise_targeting_rules,
)
from backend.app.services.assignment_service import AssignmentService

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _cond(attribute: str, operator: str, value=None) -> dict:
    return {"attribute": attribute, "operator": operator, "value": value}


def _groups(*groups: dict, logical_operator: str = "AND") -> dict:
    return {"logical_operator": logical_operator, "groups": list(groups)}


def _group(*conditions: dict, logical_operator: str = "AND") -> dict:
    return {"logical_operator": logical_operator, "conditions": list(conditions)}


US = _cond("country", "equals", "US")
PRO = _cond("plan", "equals", "pro")

# (id, dashboard rules, context, expected match)
CASES = [
    # OR across two groups: the user lacks the other branch's attribute.
    (
        "or-groups-country-only",
        _groups(_group(US), _group(PRO), logical_operator="OR"),
        {"country": "US"},
        True,
    ),
    (
        "or-groups-plan-only",
        _groups(_group(US), _group(PRO), logical_operator="OR"),
        {"plan": "pro"},
        True,
    ),
    # OR inside one group.
    (
        "or-conditions-country-only",
        _groups(_group(US, PRO, logical_operator="OR")),
        {"country": "US"},
        True,
    ),
    # OR still needs one branch to hold.
    (
        "or-neither-holds",
        _groups(_group(US), _group(PRO), logical_operator="OR"),
        {"country": "FR"},
        False,
    ),
    # AND still refuses a user lacking one of its attributes.
    (
        "and-conditions-country-only",
        _groups(_group(US, PRO)),
        {"country": "US"},
        False,
    ),
    (
        "and-groups-country-only",
        _groups(_group(US), _group(PRO)),
        {"country": "US"},
        False,
    ),
    # is_null on an absent attribute is true.
    (
        "is-null-absent",
        _groups(_group(_cond("plan", "is_null"))),
        {"country": "US"},
        True,
    ),
    # NOT group on an absent attribute: the inner condition is false, so the
    # NOT holds and the user matches, as on flags.
    (
        "not-group-absent",
        _groups(_group(US, logical_operator="NOT")),
        {"plan": "pro"},
        True,
    ),
    (
        "not-group-present-us",
        _groups(_group(US, logical_operator="NOT")),
        {"country": "US"},
        False,
    ),
    # not_equals on an absent attribute is false (the condition itself needs
    # the attribute), on both paths.
    (
        "not-equals-absent",
        _groups(_group(_cond("country", "not_equals", "US"))),
        {"plan": "pro"},
        False,
    ),
]


def _experiment_eligible(raw: dict, context: dict) -> bool:
    service = AssignmentService(Mock())
    experiment = SimpleNamespace(id=uuid4(), targeting_rules=raw)
    result = service._evaluate_experiment_targeting(
        experiment, expand_context(context), user_id="user-822"
    )
    return result["eligible"]


def _flag_matches(raw: dict, context: dict) -> bool:
    rules = normalise_targeting_rules(raw, owner="flag:822")
    assert rules is not None
    return match_targeting_rule(rules, expand_context(context)) is not None


@pytest.mark.parametrize(
    "raw, context, expected",
    [pytest.param(raw, ctx, exp, id=cid) for cid, raw, ctx, exp in CASES],
)
def test_experiment_targeting_matches_the_flag_answer(raw, context, expected):
    assert _flag_matches(raw, context) is expected
    assert _experiment_eligible(raw, context) is expected
