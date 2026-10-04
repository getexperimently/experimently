"""Segment rules use the targeting rule format and are checked when saved (#440).

``validate_segment_rules`` accepts the dashboard shape only, with the flag
validator's checks on each condition, refuses the legacy segment shape, the
native shape and empty groups, and caps a segment at 20 groups, 50
conditions, 10 regex conditions and 1,000 list values. Membership is the
flag engine on the expanded context, so a segment's rules mean what the same
rules mean on a feature flag.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.app.core.segment_preview_limits import (
    MAX_PREVIEW_CONDITIONS,
    MAX_PREVIEW_GROUPS,
    MAX_PREVIEW_LIST_ELEMENTS,
    MAX_PREVIEW_REGEX_CONDITIONS,
)
from backend.app.core.targeting_adapter import (
    MAX_SEGMENT_CONDITIONS,
    MAX_SEGMENT_GROUPS,
    MAX_SEGMENT_LIST_ELEMENTS,
    MAX_SEGMENT_REGEX_CONDITIONS,
    TargetingRulesError,
    validate_segment_rules,
)
from backend.app.models.segment import Segment
from backend.app.services.audience_service import AudienceService

pytestmark = pytest.mark.unit

MARKER = "zq_segment_marker_440"


def _cond(attribute="country", operator="equals", value="US"):
    return {"attribute": attribute, "operator": operator, "value": value}


def _rules(*groups, **top):
    return {
        "logical_operator": "AND",
        "groups": [{"logical_operator": "AND", "conditions": list(g)} for g in groups],
        **top,
    }


US = _rules([_cond()])

#: The legacy segment shape every row written before #440 used.
LEGACY = {"operator": "and", "conditions": [_cond(operator="eq", value=MARKER)]}

#: The PE's four invalid dashboard-shaped rows, with the reason each gets.
PE_FOUR = [
    (
        {"groups": [{"conditions": [_cond(operator="eq", value=MARKER)]}]},
        "groups[0].conditions[0].operator: unknown operator",
    ),
    ({"groups": []}, "groups: at least one group is required"),
    (
        {"groups": [{"conditions": []}]},
        "groups[0].conditions: at least one condition is required",
    ),
    ({"groups": "x"}, "groups: must be a list"),
]
PE_FOUR_IDS = ["eq", "no-groups", "empty-group", "groups-text"]

REFUSED = [
    (LEGACY, "rules: unknown key"),
    ({"rules": [], "default_rule": None}, "rules: unknown key"),
    (
        {"version": "1.0", "rules": [{"id": "r", "rule": {"conditions": []}}]},
        "rules: unknown key",
    ),
    (_rules([_cond()], rollout_percentage=50), "rules: unknown key"),
    (_rules([_cond()], id="r1"), "rules: unknown key"),
    (_rules([_cond()], name="n"), "rules: unknown key"),
    ({"anything": [1, 2]}, "rules: unknown key"),
    ({}, "groups: at least one group is required"),
    ({"logical_operator": "AND"}, "groups: at least one group is required"),
    ([US], "rules: must be an object"),
    (None, "rules: must be an object"),
    ("rules", "rules: must be an object"),
    (
        _rules([_cond(operator="equal", value=MARKER)]),
        "groups[0].conditions[0].operator: unknown operator",
    ),
    (
        _rules([_cond(operator="equals ")], [_cond(operator="in_segment")]),
        "groups[1].conditions[0].operator: unknown operator",
    ),
    (
        {"groups": [{"groups": [{"conditions": [_cond()]}]}]},
        "groups[0]: unknown key",
    ),
    (
        _rules([_cond(), {**_cond(), "extra": 1}]),
        "groups[0].conditions[1]: unknown key",
    ),
    (
        _rules([_cond(operator="regex", value="(?<=" + MARKER + ")")]),
        "groups[0].conditions[0]: pattern is not valid",
    ),
    (
        _rules([_cond(operator="greater_than", value=MARKER)]),
        "groups[0].conditions[0].value: value is not valid for the operator",
    ),
    (
        {"logical_operator": "XOR", "groups": [{"conditions": [_cond()]}]},
        "logical_operator: must be and, or or not",
    ),
] + PE_FOUR

REFUSED_IDS = [
    "legacy",
    "native",
    "native-versioned",
    "rollout-percentage",
    "rule-id",
    "name",
    "flat",
    "empty",
    "no-groups-key",
    "list",
    "null",
    "text",
    "typo-operator",
    "in-segment",
    "nested-group",
    "condition-key",
    "bad-regex",
    "number-text",
    "logical-operator",
] + [f"pe-{i}" for i in PE_FOUR_IDS]


@pytest.mark.parametrize("rules, message", REFUSED, ids=REFUSED_IDS)
def test_refused(rules, message):
    with pytest.raises(TargetingRulesError) as exc_info:
        validate_segment_rules(rules)
    assert str(exc_info.value) == message
    assert MARKER not in str(exc_info.value)


@pytest.mark.parametrize(
    "rules",
    [
        US,
        _rules([_cond()], [_cond("plan", "in", "pro, team")]),
        {"groups": [{"conditions": [_cond()]}]},
        _rules([_cond("app.version", "semver_gte", "17.4")]),
        _rules([_cond("email", "regex", r"@example\.com$")]),
        {"logical_operator": "NOT", "groups": [{"conditions": [_cond()]}]},
        _rules([_cond("beta", "is_null", None)]),
    ],
    ids=["one", "two-groups", "bare", "semver", "regex", "not", "is-null"],
)
def test_accepted_rules_are_returned_converted_and_left_as_given(rules):
    before = repr(rules)
    converted = validate_segment_rules(rules)
    assert len(converted.rules) == 1
    assert converted.default_rule is None
    assert repr(rules) == before


def test_the_caps_are_the_preview_limits():
    assert (
        (
            MAX_SEGMENT_GROUPS,
            MAX_SEGMENT_CONDITIONS,
            MAX_SEGMENT_REGEX_CONDITIONS,
            MAX_SEGMENT_LIST_ELEMENTS,
        )
        == (
            MAX_PREVIEW_GROUPS,
            MAX_PREVIEW_CONDITIONS,
            MAX_PREVIEW_REGEX_CONDITIONS,
            MAX_PREVIEW_LIST_ELEMENTS,
        )
        == (20, 50, 10, 1000)
    )


def _groups_of(n):
    return _rules(*[[_cond()] for _ in range(n)])


def _conditions(n):
    # Spread over two groups, so the cap counts across groups.
    return _rules([_cond()] * (n // 2), [_cond()] * (n - n // 2))


def _regexes(n):
    return _rules([_cond("email", "regex", f"^u{i}") for i in range(n)])


def _list_values(n):
    return _rules(
        [_cond("plan", "in", [f"p{i}" for i in range(n // 2)])],
        [_cond("tier", "in", [f"t{i}" for i in range(n - n // 2)])],
    )


def _text_list_values(n):
    # ``in`` with text is a comma-separated list once converted.
    return _rules(
        [_cond("plan", "in", ",".join(f"p{i}" for i in range(n - 1)))],
        [_cond("tier", "in", ["t"])],
    )


CAPS = [
    (_groups_of, 20, "groups: at most 20 groups are allowed"),
    (_conditions, 50, "rules: at most 50 conditions are allowed"),
    (_regexes, 10, "rules: at most 10 regex conditions are allowed"),
    (_list_values, 1000, "rules: at most 1000 list values are allowed in total"),
    (_text_list_values, 1000, "rules: at most 1000 list values are allowed in total"),
]
CAP_IDS = ["groups", "conditions", "regex", "list", "text-list"]


@pytest.mark.regression
@pytest.mark.parametrize("build, cap, message", CAPS, ids=CAP_IDS)
def test_cap_boundaries(build, cap, message):
    validate_segment_rules(build(cap))
    with pytest.raises(TargetingRulesError) as exc_info:
        validate_segment_rules(build(cap + 1))
    assert str(exc_info.value) == message


# ---------------------------------------------------------------------------
# Membership is the flag engine on the expanded context
# ---------------------------------------------------------------------------


def _member(rules, context):
    segment = MagicMock(spec=Segment)
    segment.id = "00000000-0000-0000-0000-000000000440"
    segment.name = "s"
    segment.rules = rules
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = segment
    return AudienceService.evaluate_membership(db, segment.id, context).is_member


@pytest.mark.regression
@pytest.mark.parametrize(
    "context, expected",
    [
        ({"country": "US"}, True),
        ({"country": "DE"}, False),
        ({}, False),
        ({"user": {"country": "US"}}, True),
        ({"user.country": "US"}, True),
        ({"user": {"country": "DE"}}, False),
    ],
    ids=["us", "de", "empty", "nested-alias", "dotted-alias", "nested-de"],
)
def test_a_dashboard_shaped_segment_matches_as_a_flag_would(context, expected):
    """On main, ``equals`` was dropped and DE matched (#440)."""
    assert _member(US, context) is expected


@pytest.mark.parametrize(
    "rules, context, expected",
    [
        (
            _rules([_cond("app.version", "semver_gte", "17.4")]),
            {"app": {"version": "17.10.0"}},
            True,
        ),
        (
            _rules([_cond("app.version", "semver_gte", "17.4")]),
            {"app": {"version": "17.3.9"}},
            False,
        ),
        (_rules([_cond("plan", "in", "pro, team")]), {"plan": "team"}, True),
        (_rules([_cond("plan", "in", "pro, team")]), {"plan": "free"}, False),
        (
            {
                "logical_operator": "OR",
                "groups": [
                    {"conditions": [_cond()]},
                    {"conditions": [_cond("plan", "equals", "pro")]},
                ],
            },
            {"country": "DE", "plan": "pro"},
            True,
        ),
        (
            {"logical_operator": "NOT", "groups": [{"conditions": [_cond()]}]},
            {"country": "DE"},
            True,
        ),
    ],
    ids=["semver-in", "semver-out", "in-text", "in-text-out", "or-groups", "not"],
)
def test_operators_and_groups_behave_as_for_flags(rules, context, expected):
    assert _member(rules, context) is expected
