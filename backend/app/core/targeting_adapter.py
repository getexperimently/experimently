"""
Targeting rule adapter: dashboard / native rule shapes -> Enhanced Rules Engine.

Feature flag ``targeting_rules`` are stored as JSONB and historically arrived in
three incompatible shapes:

* the **dashboard editor** shape written by the frontend targeting builder::

      {"logical_operator": "AND"|"OR",
       "groups": [{"logical_operator": "AND"|"OR",
                   "conditions": [{"attribute", "operator", "value"}]}]}

  with operators such as ``equals``, ``semver_gte``, ``is_null`` and dotted
  attributes such as ``user.country`` / ``app.version``;
* the **native** :class:`~backend.app.schemas.targeting_rule.TargetingRules`
  shape used by the Enhanced Rules Engine (``{"rules": [...], "default_rule"}``);
* a **legacy list** shape (``[{"type": "user_id"|"context", ...}]``) that
  :class:`~backend.app.services.feature_flag_service.FeatureFlagService`
  evaluates itself.

:func:`normalise_targeting_rules` turns the first two into ``TargetingRules``
and returns ``None`` for the legacy list (or anything it cannot understand) so
the caller keeps its existing behaviour. :func:`expand_context` flattens an SDK
context into the flat lookup dict the engine expects and adds the
``user.<k>`` / ``device.<k>`` / ``app.<k>`` aliases documented in the flag docs.
:func:`match_targeting_rule` finds the first matching rule *without* applying
the engine's own rollout hashing, so the flag service can bucket users with the
flag-level hash exactly as it does for the global rollout percentage.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from backend.app.core.rules_engine import evaluate_rule
from backend.app.schemas.targeting_rule import (
    Condition,
    LogicalOperator,
    OperatorType,
    RuleGroup,
    TargetingRule,
    TargetingRules,
)

logger = logging.getLogger(__name__)

# Rule id used for the single rule produced from the dashboard shape.
DASHBOARD_RULE_ID = "dashboard"

# Top-level context keys are also reachable under these prefixes so dashboard
# attributes such as ``user.country`` resolve against ``{"country": "US"}``.
CONTEXT_ALIAS_PREFIXES = ("user", "device", "app")

# Dashboard operator -> (engine operator, semantic-version comparison).
_SIMPLE_OPERATOR_MAP: Dict[str, OperatorType] = {
    "equals": OperatorType.EQUALS,
    "not_equals": OperatorType.NOT_EQUALS,
    "contains": OperatorType.CONTAINS,
    "not_contains": OperatorType.NOT_CONTAINS,
    "starts_with": OperatorType.STARTS_WITH,
    "ends_with": OperatorType.ENDS_WITH,
    "greater_than": OperatorType.GREATER_THAN,
    "less_than": OperatorType.LESS_THAN,
    "greater_than_or_equal": OperatorType.GREATER_THAN_OR_EQUAL,
    "less_than_or_equal": OperatorType.LESS_THAN_OR_EQUAL,
    "in": OperatorType.IN,
    "not_in": OperatorType.NOT_IN,
    "regex": OperatorType.MATCH_REGEX,
    "is_null": OperatorType.IS_NULL,
    "is_not_null": OperatorType.IS_NOT_NULL,
    "geo_within_radius": OperatorType.GEO_DISTANCE,
    "time_window": OperatorType.TIME_WINDOW,
    "array_contains": OperatorType.CONTAINS_ALL,
    "array_intersects": OperatorType.CONTAINS_ANY,
}

_SEMVER_OPERATOR_MAP: Dict[str, str] = {
    "semver_eq": "eq",
    "semver_gt": "gt",
    "semver_lt": "lt",
    "semver_gte": "gte",
    "semver_lte": "lte",
}

#: Every dashboard operator the adapter understands.
DASHBOARD_OPERATORS = frozenset(_SIMPLE_OPERATOR_MAP) | frozenset(_SEMVER_OPERATOR_MAP)

_NUMERIC_OPERATORS = frozenset(
    {
        OperatorType.GREATER_THAN,
        OperatorType.GREATER_THAN_OR_EQUAL,
        OperatorType.LESS_THAN,
        OperatorType.LESS_THAN_OR_EQUAL,
    }
)
_LIST_OPERATORS = frozenset(
    {
        OperatorType.IN,
        OperatorType.NOT_IN,
        OperatorType.CONTAINS_ALL,
        OperatorType.CONTAINS_ANY,
    }
)

_NUMBER_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


class TargetingRuleShapeError(ValueError):
    """Raised internally when a dashboard rule cannot be converted."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalise_targeting_rules(raw: Any) -> Optional[TargetingRules]:
    """
    Convert stored ``targeting_rules`` JSON into engine ``TargetingRules``.

    Returns:
        ``TargetingRules`` for the native shape (has ``rules``) and for the
        dashboard shape (has ``groups``); ``None`` for empty input, for the
        legacy list shape (the flag service keeps evaluating that itself) and
        for anything else that cannot be interpreted, so callers fall back to
        the flag's global rollout percentage. Invalid content never raises.
    """
    if raw is None:
        return None
    if isinstance(raw, TargetingRules):
        return raw
    if isinstance(raw, list):
        # Legacy [{"type": ..., "conditions": ...}] shape — owned by the service.
        return None
    if not isinstance(raw, dict) or not raw:
        return None

    if "groups" in raw:
        try:
            return _from_dashboard(raw)
        except (TargetingRuleShapeError, ValidationError, TypeError) as exc:
            logger.warning(
                "Ignoring dashboard targeting rules that could not be converted: %s",
                exc,
            )
            return None

    if "rules" in raw:
        try:
            return TargetingRules.model_validate(raw)
        except ValidationError as exc:
            logger.warning(
                "Ignoring native targeting rules that failed validation: %s", exc
            )
            return None

    return None


def expand_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Flatten an SDK context into the lookup dict the rules engine expects.

    The result contains:

    * every raw key as given (nested dicts are kept as values too);
    * a dotted key for every nested dict entry, recursively
      (``{"app": {"version": "3.2.1"}}`` also answers ``app.version``);
    * ``user.<k>``, ``device.<k>`` and ``app.<k>`` aliases for every top-level
      key (``{"country": "US"}`` also answers ``user.country``; ``{"os_version":
      "17.4.0"}`` also answers ``device.os_version``);
    * the bare key for dotted keys under those prefixes (``user.country`` in
      the context also answers ``country``).

    Explicit keys always win over aliases, so ``{"country": "US", "user":
    {"country": "DE"}}`` resolves ``user.country`` to ``"DE"``.
    """
    if not context or not isinstance(context, dict):
        return {}

    flat: Dict[str, Any] = {}
    _flatten_into(flat, context, prefix="")

    # Forward aliases: top-level key -> <prefix>.key (nested dicts are already
    # reachable through their dotted keys, so they are not aliased themselves)
    for key, value in list(flat.items()):
        if "." in key or isinstance(value, dict):
            continue
        for prefix in CONTEXT_ALIAS_PREFIXES:
            flat.setdefault(f"{prefix}.{key}", value)

    # Reverse aliases: <prefix>.key -> key
    for key, value in list(flat.items()):
        head, sep, tail = key.partition(".")
        if sep and head in CONTEXT_ALIAS_PREFIXES and tail and "." not in tail:
            flat.setdefault(tail, value)

    return flat


def match_targeting_rule(
    rules: Optional[TargetingRules], context: Dict[str, Any]
) -> Optional[TargetingRule]:
    """
    Return the first rule (by priority) whose conditions match ``context``.

    Unlike :func:`backend.app.core.rules_engine.evaluate_targeting_rules` this
    does **not** apply the rule's ``rollout_percentage``: the caller buckets the
    user itself (the flag service hashes ``user_id:flag.key`` so a rule at N%
    selects the same users as the global rollout at N%). When nothing matches
    the ``default_rule`` is returned, mirroring the engine.
    """
    if rules is None:
        return None
    for rule in sorted(rules.rules, key=lambda r: r.priority):
        if evaluate_rule(rule, context):
            return rule
    return rules.default_rule


# ---------------------------------------------------------------------------
# Dashboard shape conversion
# ---------------------------------------------------------------------------


def _from_dashboard(raw: Dict[str, Any]) -> TargetingRules:
    groups: List[RuleGroup] = []
    for index, group in enumerate(raw.get("groups") or []):
        if not isinstance(group, dict):
            raise TargetingRuleShapeError(f"group {index} is not an object")
        conditions = [
            convert_dashboard_condition(condition)
            for condition in group.get("conditions") or []
        ]
        if not conditions:
            # An empty group would match everyone; the editor creates these
            # as placeholders, so they contribute nothing.
            continue
        groups.append(
            RuleGroup(
                operator=_logical_operator(group.get("logical_operator")),
                conditions=conditions,
            )
        )

    if not groups:
        # "No targeting" — an empty rule list falls through to the global rollout.
        return TargetingRules(rules=[])

    rule = TargetingRule(
        id=str(raw.get("id") or DASHBOARD_RULE_ID),
        name=raw.get("name"),
        rule=RuleGroup(
            operator=_logical_operator(raw.get("logical_operator")),
            conditions=[],
            groups=groups,
        ),
        rollout_percentage=_rollout_percentage(raw.get("rollout_percentage")),
        priority=0,
    )
    return TargetingRules(rules=[rule])


def convert_dashboard_condition(condition: Dict[str, Any]) -> Condition:
    """
    Convert one dashboard ``{"attribute", "operator", "value"}`` condition.

    Raises :class:`TargetingRuleShapeError` for unknown operators, blank
    attributes or values that cannot be interpreted for the operator.
    """
    if not isinstance(condition, dict):
        raise TargetingRuleShapeError("condition is not an object")

    attribute = str(condition.get("attribute") or "").strip()
    if not attribute:
        raise TargetingRuleShapeError("condition attribute is required")

    operator = str(condition.get("operator") or "").strip()
    value = condition.get("value")

    if operator in _SEMVER_OPERATOR_MAP:
        return Condition(
            attribute=attribute,
            operator=OperatorType.SEMANTIC_VERSION,
            value=_semver_value(value),
            additional_value=_SEMVER_OPERATOR_MAP[operator],
        )

    engine_operator = _SIMPLE_OPERATOR_MAP.get(operator)
    if engine_operator is None:
        raise TargetingRuleShapeError(f"unknown operator {operator!r}")

    if engine_operator in (OperatorType.IS_NULL, OperatorType.IS_NOT_NULL):
        return Condition(attribute=attribute, operator=engine_operator, value=None)

    if engine_operator in _LIST_OPERATORS:
        return Condition(
            attribute=attribute, operator=engine_operator, value=_list_value(value)
        )

    if engine_operator in _NUMERIC_OPERATORS:
        return Condition(
            attribute=attribute, operator=engine_operator, value=_numeric_value(value)
        )

    if engine_operator == OperatorType.GEO_DISTANCE:
        point, extra = _geo_value(value)
        return Condition(
            attribute=attribute,
            operator=engine_operator,
            value=point,
            additional_value=extra,
        )

    if engine_operator == OperatorType.TIME_WINDOW:
        return Condition(
            attribute=attribute,
            operator=engine_operator,
            value=_time_window_value(value),
        )

    if engine_operator == OperatorType.MATCH_REGEX:
        if not isinstance(value, str) or not value:
            raise TargetingRuleShapeError("regex operator requires a pattern string")
        return Condition(attribute=attribute, operator=engine_operator, value=value)

    return Condition(attribute=attribute, operator=engine_operator, value=value)


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _logical_operator(value: Any) -> LogicalOperator:
    text = str(value or "AND").strip().lower()
    if text == "or":
        return LogicalOperator.OR
    if text == "not":
        return LogicalOperator.NOT
    return LogicalOperator.AND


def _rollout_percentage(value: Any) -> int:
    if value is None or value == "":
        return 100
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return 100


def coerce_number(value: Any) -> Any:
    """Turn editor strings such as ``"17"`` / ``"3.5"`` into numbers; leave the rest alone."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if _NUMBER_RE.match(text):
            try:
                number = float(text)
            except ValueError:
                return value
            return (
                int(number)
                if number.is_integer() and "." not in text and "e" not in text.lower()
                else number
            )
    return value


def _numeric_value(value: Any) -> Any:
    coerced = coerce_number(value)
    if isinstance(coerced, bool) or not isinstance(coerced, (int, float)):
        raise TargetingRuleShapeError(
            f"numeric comparison requires a number, got {value!r}"
        )
    return coerced


def _list_value(value: Any) -> List[Any]:
    """
    Normalise a list-operator value.

    Accepts a JSON array, a scalar (wrapped) or the editor's comma-separated
    string (``"beta, internal"``). Items are stripped; empties are dropped.
    """
    if value is None:
        raise TargetingRuleShapeError("list operator requires at least one value")
    if isinstance(value, str) and value.strip().startswith("["):
        # A JSON array pasted into the editor.
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    if isinstance(value, (list, tuple, set)):
        items: List[Any] = [
            item.strip() if isinstance(item, str) else item for item in value
        ]
    elif isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    else:
        items = [value]
    items = [item for item in items if not (isinstance(item, str) and item == "")]
    if not items:
        raise TargetingRuleShapeError("list operator requires at least one value")
    return items


def _semver_value(value: Any) -> str:
    """Pad short editor versions (``"17"``, ``"17.4"``) to full semver."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        raise TargetingRuleShapeError("semver operator requires a version string")
    text = value.strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    core, sep, rest = _split_semver_suffix(text)
    parts = core.split(".")
    if not all(part.isdigit() for part in parts) or len(parts) > 3:
        raise TargetingRuleShapeError(f"invalid semantic version {value!r}")
    while len(parts) < 3:
        parts.append("0")
    return ".".join(str(int(part)) for part in parts) + sep + rest


def _split_semver_suffix(text: str):
    """Split ``1.2.3-beta+build`` into (``1.2.3``, ``-``/``+``, remainder)."""
    for index, char in enumerate(text):
        if char in "-+":
            return text[:index], char, text[index + 1 :]
    return text, "", ""


def _geo_value(value: Any):
    """
    Normalise ``geo_within_radius`` into ``([lat, lon], {"radius", "unit"?})``.

    Accepts ``{"lat", "lon", "radius", "unit"?}``, ``[lat, lon, radius, unit?]``
    or the string ``"lat,lon,radius[,unit]"``.
    """
    unit: Optional[str] = None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if len(parts) < 3:
            raise TargetingRuleShapeError(
                "geo_within_radius requires 'lat,lon,radius[,unit]'"
            )
        lat, lon, radius = parts[0], parts[1], parts[2]
        unit = parts[3] if len(parts) > 3 and parts[3] else None
    elif isinstance(value, dict):
        lat = value.get("lat", value.get("latitude"))
        lon = value.get("lon", value.get("lng", value.get("longitude")))
        radius = value.get("radius")
        unit = value.get("unit")
    elif isinstance(value, (list, tuple)) and len(value) >= 3:
        lat, lon, radius = value[0], value[1], value[2]
        unit = value[3] if len(value) > 3 else None
    else:
        raise TargetingRuleShapeError("geo_within_radius requires lat, lon and radius")

    try:
        point = [float(lat), float(lon)]
        radius_value = float(radius)
    except (TypeError, ValueError):
        raise TargetingRuleShapeError(
            "geo_within_radius coordinates and radius must be numeric"
        )

    extra: Dict[str, Any] = {"radius": radius_value}
    if unit:
        extra["unit"] = str(unit)
    return point, extra


def _time_window_value(value: Any) -> Dict[str, Any]:
    """
    Normalise ``time_window`` into the dict the engine reads.

    The ``Condition`` schema requires ``start``/``end`` keys while the engine
    reads ``start_time``/``end_time``; both spellings are kept so the value
    validates and evaluates.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise TargetingRuleShapeError("time_window requires a JSON object")
    if not isinstance(value, dict):
        raise TargetingRuleShapeError("time_window requires an object")

    window = dict(value)
    if "start_time" not in window and "start" in window:
        window["start_time"] = window["start"]
    if "end_time" not in window and "end" in window:
        window["end_time"] = window["end"]
    if "start" not in window and "start_time" in window:
        window["start"] = window["start_time"]
    if "end" not in window and "end_time" in window:
        window["end"] = window["end_time"]
    if "start" not in window or "end" not in window:
        raise TargetingRuleShapeError("time_window requires 'start' and 'end'")
    return window


def _flatten_into(out: Dict[str, Any], value: Dict[str, Any], prefix: str) -> None:
    for key, item in value.items():
        if not isinstance(key, str):
            key = str(key)
        full_key = f"{prefix}{key}" if prefix else key
        out.setdefault(full_key, item)
        if isinstance(item, dict):
            _flatten_into(out, item, prefix=f"{full_key}.")
