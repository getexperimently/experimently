"""Segment conditions refused on write, before any database query (#440).

``validate_flag_targeting`` and ``validate_experiment_targeting`` (the request
schemas run them) refuse, with fixed text keyed by path:

* a segment operator on an attribute other than ``segment``;
* a value that is not a segment id (canonical UUID text);
* more than 10 distinct segments in one ruleset (10 is accepted);
* a segment condition in a native ``default_rule``, which no evaluator
  evaluates (it would mean every user);

and ``validate_segment_rules`` refuses a segment operator inside a segment's
own rules. Whether each segment exists and is active is the routes' check
against the database (``test_segment_targeting_api.py``).
"""

from __future__ import annotations

import uuid

import pytest

from backend.app.core.targeting_adapter import (
    TargetingRulesError,
    segment_ids_in,
    validate_experiment_targeting,
    validate_flag_targeting,
    validate_segment_rules,
)

pytestmark = pytest.mark.unit

SEG = "0b8a3e1c-4a3e-4c55-9a40-000000000440"


def _ids(n: int):
    return [str(uuid.UUID(int=i + 1)) for i in range(n)]


def _dashboard(*conditions, logical="OR"):
    return {
        "logical_operator": logical,
        "groups": [{"logical_operator": logical, "conditions": list(conditions)}],
    }


def _seg(value=SEG, op="in_segment", attribute="segment"):
    return {"attribute": attribute, "operator": op, "value": value}


def _native(*conditions, default_rule=None):
    rules = {
        "rules": [
            {
                "id": "r1",
                "rule": {"operator": "and", "conditions": list(conditions)},
                "rollout_percentage": 100,
            }
        ]
    }
    if default_rule is not None:
        rules["default_rule"] = default_rule
    return rules


FLAG = pytest.param(validate_flag_targeting, "targeting rules: ", id="flag")
EXPERIMENT = pytest.param(validate_experiment_targeting, "", id="experiment")


@pytest.mark.parametrize("validate, _subject", [FLAG, EXPERIMENT])
@pytest.mark.parametrize("op", ["in_segment", "not_in_segment"])
def test_accepted_in_both_shapes(validate, _subject, op):
    dashboard = validate(_dashboard(_seg(op=op)))
    native = validate(_native(_seg(op=op)))
    assert segment_ids_in(dashboard) == segment_ids_in(native) == frozenset({SEG})


@pytest.mark.parametrize("validate, _subject", [FLAG, EXPERIMENT])
@pytest.mark.parametrize(
    "rules, message",
    [
        (
            _dashboard(_seg(attribute="plan")),
            'groups[0].conditions[0].attribute: must be "segment" for this operator',
        ),
        (
            _dashboard(
                {"attribute": "country", "operator": "equals", "value": "US"},
                _seg(value=SEG.upper()),
            ),
            "groups[0].conditions[1].value: must be a segment id",
        ),
        (
            _dashboard(_seg(value="enterprise")),
            "groups[0].conditions[0].value: must be a segment id",
        ),
        (
            _dashboard(_seg(value=SEG.replace("-", ""))),
            "groups[0].conditions[0].value: must be a segment id",
        ),
        (
            _dashboard(_seg(value=None)),
            "groups[0].conditions[0].value: must be a segment id",
        ),
        (
            _native(_seg(value=7)),
            "rules[0].rule.conditions[0].value: must be a segment id",
        ),
        (
            _native(
                {"attribute": "plan", "operator": "eq", "value": "pro"},
                default_rule={
                    "id": "d",
                    "rule": {"operator": "and", "conditions": [_seg()]},
                    "rollout_percentage": 100,
                },
            ),
            "default_rule.rule.conditions[0].operator: a segment condition is not "
            "evaluated in default_rule",
        ),
    ],
    ids=[
        "attribute",
        "upper-case-id",
        "not-a-uuid",
        "uuid-without-hyphens",
        "null",
        "native-number",
        "native-default-rule",
    ],
)
def test_refused_with_fixed_text(validate, _subject, rules, message):
    with pytest.raises(TargetingRulesError) as raised:
        validate(rules)
    assert str(raised.value) == message
    assert "enterprise" not in str(raised.value)


@pytest.mark.parametrize("validate, subject", [FLAG, EXPERIMENT])
def test_ten_segments_accepted_eleven_refused(validate, subject):
    ten = _dashboard(*[_seg(value=v) for v in _ids(10)])
    assert len(segment_ids_in(validate(ten))) == 10
    # The same segment twice counts once.
    repeated = _dashboard(*[_seg(value=v) for v in _ids(10) + _ids(10)])
    assert len(segment_ids_in(validate(repeated))) == 10
    eleven = _dashboard(*[_seg(value=v) for v in _ids(11)])
    with pytest.raises(TargetingRulesError) as raised:
        validate(eleven)
    assert str(raised.value) == f"{subject}at most 10 segments may be referenced"


@pytest.mark.parametrize("op", ["in_segment", "not_in_segment"])
def test_a_segment_cannot_refer_to_a_segment(op):
    rules = {
        "groups": [
            {"conditions": [{"attribute": "plan", "operator": "equals", "value": "x"}]},
            {"conditions": [_seg(op=op)]},
        ]
    }
    with pytest.raises(TargetingRulesError) as raised:
        validate_segment_rules(rules)
    assert str(raised.value) == (
        "groups[1].conditions[0].operator: a segment cannot refer to a segment"
    )


def test_segment_ids_in_reads_nested_native_groups():
    rules = validate_flag_targeting(
        {
            "rules": [
                {
                    "id": "r1",
                    "rule": {
                        "operator": "or",
                        "conditions": [],
                        "groups": [
                            {
                                "operator": "not",
                                "conditions": [],
                                "groups": [{"operator": "and", "conditions": [_seg()]}],
                            }
                        ],
                    },
                }
            ]
        }
    )
    assert segment_ids_in(rules) == frozenset({SEG})
