"""Feature-flag targeting rules are validated when saved (#535).

``validate_flag_targeting`` runs on ``targeting_rules`` in every flag create and
update (``FeatureFlagCreate`` / ``FeatureFlagUpdate``). Before it, both models
declared ``targeting_rules: Optional[Any]`` and stored any JSON: a flat
``{"country": ["US"]}``, an unknown operator, a string, a number. The flag
evaluator reads rules it cannot convert as "no rules", so the flag's global
rollout decided instead, with nothing said to the caller.

Pinned here, without a database:

* the accept/refuse table, with the exact message for each refusal (V5), and
  both request models refusing each row (V3);
* the message never repeats the submitted value, for a non-ASCII marker in
  every place a value can be (V4);
* parity: for every accepted value, what the flag evaluator does with the
  stored value is what the validator's reading gives -- ``enabled``,
  ``reason`` and ``rule_id``, over a grid of users and contexts (V6);
* nothing accepted is dropped: an accepted non-empty value is never read as
  "no rules" by ``normalise_targeting_rules`` (V7);
* the SDK ruleset vectors split exactly 138 accepted / 4 refused / 2 legacy
  rows the API now refuses (V12).

The experiment validator is unchanged: its own table
(``test_experiment_targeting_validation.py``) is imported here, not copied.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from backend.app.core.targeting_adapter import (
    MAX_LIST_ITEMS,
    TargetingRulesError,
    expand_context,
    match_targeting_rule,
    normalise_targeting_rules,
    validate_experiment_targeting,
    validate_flag_targeting,
)
from backend.app.core.validation_errors import render_validation_errors
from backend.app.models.feature_flag import FeatureFlagStatus
from backend.app.schemas.feature_flag import FeatureFlagCreate, FeatureFlagUpdate
from backend.app.services import feature_flag_service as ffs
from backend.tests.unit.core.test_experiment_targeting_validation import (
    ACCEPTED as EXPERIMENT_ACCEPTED,
)
from backend.tests.unit.core.test_experiment_targeting_validation import (
    NATIVE_US,
    US,
    cond,
    dash,
)
from backend.tests.unit.core.test_experiment_targeting_validation import (
    REFUSED as EXPERIMENT_REFUSED,
)

pytestmark = [pytest.mark.unit]

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
VECTORS = json.loads(
    (REPO_ROOT / "tests" / "sdk-contract" / "ruleset-vectors.json").read_text("utf-8")
)
BUILDER_OUTPUTS = json.loads(
    (
        REPO_ROOT
        / "frontend"
        / "src"
        / "tests"
        / "fixtures"
        / "flag-builder-outputs.json"
    ).read_text("utf-8")
)["rows"]

#: Every value the experiment validator accepts, the flag validator accepts.
ACCEPTED: Dict[str, Any] = dict(EXPERIMENT_ACCEPTED)

#: The experiment rows whose flag message differs, and the flag message.
_FLAG_MESSAGE = {
    "list shape": "targeting rules: a list of rules is not supported; use the groups shape",
    "flat dict (the old documented example)": "targeting rules: unknown key",
    "unknown key": "targeting rules: unknown key",
    "dashboard with unknown key": "targeting rules: unknown key",
    "top-level name": "name: not supported",
    "native duplicate rule ids": "targeting rules: rule ids must be unique",
}

DEFAULT_RULE = {
    "id": "everyone",
    "rule": {
        "operator": "and",
        "conditions": [{"attribute": "country", "operator": "eq", "value": "US"}],
    },
    "rollout_percentage": 100,
}

#: value -> the exact message. Every experiment row, then the flag-only rows.
REFUSED: Dict[str, Tuple[Any, str]] = {
    **{
        name: (value, _FLAG_MESSAGE.get(name, message))
        for name, (value, message) in EXPERIMENT_REFUSED.items()
    },
    "a number": (42, "targeting rules: must be an object"),
    "a float": (3.5, "targeting rules: must be an object"),
    "a string": ("x", "targeting rules: must be an object"),
    "true": (True, "targeting rules: must be an object"),
    "an empty list": (
        [],
        "targeting rules: a list of rules is not supported; use the groups shape",
    ),
    "a legacy list with an unknown operator": (
        [
            {
                "type": "context",
                "conditions": [
                    {"attribute": "plan", "operator": "equalz", "value": "pro"}
                ],
            }
        ],
        "targeting rules: a list of rules is not supported; use the groups shape",
    ),
    "a legacy user-id list": (
        [{"type": "user_id", "user_ids": ["user-1"]}],
        "targeting rules: a list of rules is not supported; use the groups shape",
    ),
    "native default_rule without rules": (
        {"default_rule": DEFAULT_RULE},
        "rules: required",
    ),
    "native default_rule and version without rules": (
        {"version": "1.0", "default_rule": DEFAULT_RULE},
        "rules: required",
    ),
    # ``rules: required`` comes after the unknown-key check.
    "unknown key beside default_rule": (
        {"default_rule": DEFAULT_RULE, "operator": "and"},
        "targeting rules: unknown key",
    ),
    "seed_demo_data's old new_dashboard_ui rules": (
        {"operator": "and", "rules": []},
        "targeting rules: unknown key",
    ),
    "dashboard name, lower-case operators": (
        {"logical_operator": "or", "groups": [{"conditions": [US]}], "name": "n"},
        "name: not supported",
    ),
    "one valid group and one bad group": (
        dash([US], [cond("age", "greater_than", "abc")], top="OR"),
        "groups[1].conditions[0].value: value is not valid for the operator",
    ),
}


def test_every_experiment_row_is_in_the_flag_tables():
    """The flag tables follow the experiment ones; a new experiment row is
    judged here too, not silently left out."""
    assert set(EXPERIMENT_ACCEPTED) <= set(ACCEPTED)
    assert set(EXPERIMENT_REFUSED) <= set(REFUSED)
    assert set(_FLAG_MESSAGE) <= set(EXPERIMENT_REFUSED)


# --- the table (V5) and the request models (V3) ----------------------------


@pytest.mark.regression
@pytest.mark.parametrize("name", list(ACCEPTED))
def test_accepted(name):
    value = copy.deepcopy(ACCEPTED[name])
    first = validate_flag_targeting(value)
    assert value == ACCEPTED[name], "the validator changed the value"
    assert validate_flag_targeting(value) == first
    # Stored as sent: neither model rewrites the value.
    assert FeatureFlagUpdate(targeting_rules=value).targeting_rules == ACCEPTED[name]
    created = FeatureFlagCreate(key="k", name="n", targeting_rules=value)
    assert created.targeting_rules == ACCEPTED[name]


@pytest.mark.regression
@pytest.mark.parametrize("name", list(REFUSED))
def test_refused(name):
    value, message = REFUSED[name]
    with pytest.raises(TargetingRulesError) as caught:
        validate_flag_targeting(copy.deepcopy(value))
    assert str(caught.value) == message


@pytest.mark.regression
@pytest.mark.parametrize("model", ["create", "update"])
@pytest.mark.parametrize("name", list(REFUSED))
def test_both_request_models_refuse(name, model):
    value, message = REFUSED[name]
    with pytest.raises(ValidationError) as caught:
        if model == "create":
            FeatureFlagCreate(key="k", name="n", targeting_rules=copy.deepcopy(value))
        else:
            FeatureFlagUpdate(targeting_rules=copy.deepcopy(value))
    errors = caught.value.errors()
    assert [(e["loc"], e["msg"]) for e in errors] == [
        (("targeting_rules",), f"Value error, {message}")
    ]


def test_null_and_omitted_are_accepted():
    assert FeatureFlagUpdate(targeting_rules=None).model_dump(exclude_unset=True) == {
        "targeting_rules": None
    }
    assert "targeting_rules" not in FeatureFlagUpdate().model_dump(exclude_unset=True)


def test_the_experiment_messages_are_unchanged():
    """The flag wording lives in the flag validator only."""
    for name in _FLAG_MESSAGE:
        value, message = EXPERIMENT_REFUSED[name]
        with pytest.raises(TargetingRulesError) as caught:
            validate_experiment_targeting(copy.deepcopy(value))
        assert str(caught.value) == message
    # The experiment validator still applies a lone default_rule.
    assert validate_experiment_targeting({"default_rule": DEFAULT_RULE}) is not None


# --- the message never repeats the submitted value (V4) --------------------

#: Non-ASCII, so a renderer that escapes or re-encodes it is caught too.
SENTINEL = "zqé漢-7731"


@pytest.mark.regression
@pytest.mark.parametrize(
    "value",
    [
        dash([cond("country", SENTINEL, "US")]),
        dash([cond(SENTINEL, "equals", "US")]),
        dash([cond("app.version", "semver_gte", SENTINEL)]),
        dash([cond("age", "greater_than", SENTINEL)]),
        dash([cond("email", "regex", "(" + SENTINEL)]),
        dash([cond("country", "equals", "US")], top=SENTINEL),
        {SENTINEL: ["US"]},
        dash([US], **{SENTINEL: 1}),
        {"groups": [{"conditions": [US], SENTINEL: True}]},
        {"rules": [{"id": SENTINEL, "rule": {"operator": SENTINEL}}]},
        {"default_rule": {"id": SENTINEL, "rule": {"operator": "and"}}},
        [{"type": "context", "conditions": [{"attribute": SENTINEL}]}],
        SENTINEL,
    ],
    ids=[
        "operator",
        "attribute",
        "semver",
        "number",
        "regex",
        "logical_operator",
        "key",
        "dashboard key",
        "group key",
        "native",
        "default_rule",
        "list",
        "string",
    ],
)
@pytest.mark.parametrize("model", [FeatureFlagCreate, FeatureFlagUpdate])
def test_the_message_never_repeats_the_submitted_value(value, model):
    body = {"targeting_rules": value}
    if model is FeatureFlagCreate:
        body.update(key="k", name="n")
    with pytest.raises(ValidationError) as caught:
        model(**body)
    # What the 422 carries: the application's handler renders exactly this.
    text = render_validation_errors(caught.value.errors()).decode()
    assert '"loc":["targeting_rules"]' in text.replace(" ", "")
    assert "7731" not in text, text
    assert "\\u" not in text and "zq" not in text, text


# --- parity: accepted means evaluated as written (V6) ----------------------

USERS = ["user-1", "user-2", "user-3"]
CONTEXTS: List[Optional[Dict[str, Any]]] = [
    None,
    {"country": "US"},
    {"country": "GB", "plan": "premium"},
    {"user": {"country": "US", "plan": "beta"}},
    {"country": "US", "age": 30, "email": "ann@example.com", "employee": True},
    {"age": "17", "plan": "free", "tier": "premium", "browser": "chrome"},
    {"app_version": "3.4.1", "os_version": "17.4", "app": {"version": "3.2.0"}},
    {"device": {"type": "mobile", "os": "ios"}, "beta_features": ["x", "y"]},
]


def _flag(rules: Any) -> Any:
    return MagicMock(
        id="00000000-0000-0000-0000-000000000535",
        key="parity",
        status=FeatureFlagStatus.ACTIVE,
        rollout_percentage=50,
        targeting_rules=rules,
    )


def _accepted_corpus() -> List[Tuple[str, Any]]:
    rows = [(f"experiment-table: {n}", v) for n, v in ACCEPTED.items()]
    rows += [
        (f"vector: {f['key']}", f["targeting_rules"])
        for f in VECTORS["stored_flags"]
        if _accepts(f["targeting_rules"])
    ]
    rows += [
        (f"builder: {r['name']}", r["sends"])
        for r in BUILDER_OUTPUTS
        if r["outcome"] == "accepted"
    ]
    return rows


def _accepts(value: Any) -> bool:
    try:
        validate_flag_targeting(copy.deepcopy(value))
    except TargetingRulesError:
        return False
    return True


def _expected(service, flag, rules, user_id, context) -> Tuple[bool, str, Any]:
    """What the validator's reading of the rules gives, computed without the
    flag service's own matching."""
    matched = (
        match_targeting_rule(rules, expand_context(context or {})) if rules else None
    )
    if matched is None:
        return service._evaluate_percentage_rollout(flag, user_id), "rollout", None
    enabled = service._evaluate_percentage_rollout(
        flag, user_id, int(matched.rollout_percentage)
    )
    return enabled, "targeting_rule", matched.id


@pytest.mark.regression
def test_what_is_accepted_is_what_the_flag_evaluator_applies(monkeypatch):
    monkeypatch.setattr(ffs, "MetricsService", MagicMock())
    service = ffs.FeatureFlagService(db=MagicMock())
    corpus = _accepted_corpus()
    assert len(corpus) == len(ACCEPTED) + 138 + 446
    with_rules = 0
    diverged = []
    for name, raw in corpus:
        rules = validate_flag_targeting(copy.deepcopy(raw))
        with_rules += rules is not None
        flag = _flag(copy.deepcopy(raw))
        for context in CONTEXTS:
            for user_id in USERS:
                got = service.evaluate_flag_detailed(flag, user_id, context)
                want = _expected(service, flag, rules, user_id, context)
                if (got["enabled"], got["reason"], got["rule_id"]) != want:
                    diverged.append((name, context, user_id, got, want))
    assert diverged == []
    # Guards the comparison: were every row "no rules", it could tell nothing.
    assert with_rules >= 500, with_rules


def test_the_parity_grid_reaches_targeting_rules(monkeypatch):
    """Guards V6: the grid must contain users that a rule matches, through an
    alias (``user.country`` against a bare ``country``) among them."""
    monkeypatch.setattr(ffs, "MetricsService", MagicMock())
    service = ffs.FeatureFlagService(db=MagicMock())
    flag = _flag(dash([cond("user.country", "equals", "US")]))
    reasons = {
        service.evaluate_flag_detailed(flag, u, c)["reason"]
        for c in CONTEXTS
        for u in USERS
    }
    assert reasons == {"targeting_rule", "rollout"}


# --- nothing accepted is dropped (V7) --------------------------------------


def _corpus_for_drops() -> List[Tuple[str, Any]]:
    rows = _accepted_corpus()
    rows += [(f"refused: {n}", v) for n, (v, _m) in REFUSED.items()]
    rows += [
        (f"builder: {r['name']}", r["sends"])
        for r in BUILDER_OUTPUTS
        if r["outcome"] != "accepted"
    ]
    rows += [
        (f"vector: {f['key']}", f["targeting_rules"]) for f in VECTORS["stored_flags"]
    ]
    return rows


def _no_rules(rules: Any) -> bool:
    return rules is None or (not rules.rules and rules.default_rule is None)


@pytest.mark.regression
def test_an_accepted_value_is_never_read_as_no_rules():
    dropped = []
    differ = []
    for name, raw in _corpus_for_drops():
        try:
            validated = validate_flag_targeting(copy.deepcopy(raw))
        except TargetingRulesError:
            continue
        read = normalise_targeting_rules(copy.deepcopy(raw), owner="test")
        if isinstance(raw, dict) and raw and read is None and not _no_rules(validated):
            dropped.append(name)
        if not (_no_rules(validated) and _no_rules(read)) and validated != read:
            differ.append(name)
    assert dropped == []
    assert differ == []


# --- the SDK ruleset vectors (V12) -----------------------------------------


@pytest.mark.regression
def test_the_ruleset_vectors_split_exactly():
    """The vectors are stored through the ORM and keep being served; these are
    the ones a create or an update would now refuse."""
    accepted, refused, legacy = [], [], []
    for flag in VECTORS["stored_flags"]:
        rules = flag["targeting_rules"]
        if isinstance(rules, list) and rules:
            legacy.append(flag["key"])
        elif _accepts(rules):
            accepted.append(flag["key"])
        else:
            refused.append(flag["key"])
    assert (len(accepted), len(refused), len(legacy)) == (138, 4, 2)
    assert sorted(refused) == [
        "empty-list",
        "unconvertible-attribute",
        "unconvertible-number",
        "unconvertible-operator",
    ]
    assert sorted(legacy) == ["legacy-context", "legacy-user-ids"]


def test_list_operators_keep_their_limit():
    accepted = dash([cond("user_id", "in", [str(i) for i in range(MAX_LIST_ITEMS)])])
    assert validate_flag_targeting(accepted) is not None
    assert NATIVE_US["rules"][0]["id"] == validate_flag_targeting(NATIVE_US).rules[0].id
