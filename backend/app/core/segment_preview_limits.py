"""
Limits on the ruleset an audience preview accepts.

``POST /api/v1/segments/{segment_id}/preview`` evaluates the rules in the
request body against up to ``sample_size`` stored user contexts. The endpoint
calls :func:`preview_ruleset_violations` before it touches the database and
answers 422 with the returned errors when there are any.

Every limit is computed from the request alone, counting every condition and
every group in the ruleset recursively (nested ``groups`` included):

(a) at most ``MAX_PREVIEW_CONDITIONS`` conditions in total, any operator;
(a') at most ``MAX_PREVIEW_GROUPS`` groups in total (the top-level ruleset
    itself is not counted);
(b) at most ``MAX_PREVIEW_REGEX_CONDITIONS`` ``match_regex`` conditions;
(c) at most ``MAX_PREVIEW_LIST_ELEMENTS`` list elements in total across all
    condition values;
(d) ``match_regex`` conditions multiplied by the *requested* ``sample_size``
    at most ``MAX_PREVIEW_REGEX_EVALUATIONS``. One pattern allows a sample of
    500, ten patterns a sample of 50. The minimum ``sample_size`` of 10 never
    reaches (d) before (b) does;
(e) conditions plus groups multiplied by the *requested* ``sample_size`` at
    most ``MAX_PREVIEW_NODE_EVALUATIONS``. The default sample of 1,000 allows
    50 conditions and groups together; a sample of 10,000 allows 5.

The limits bound the work one preview request performs: at most 50,000
condition and group evaluations and 500 pattern searches. If the rules
engine's ``MAX_REGEX_INPUT`` or an operator's implementation changes,
re-measure and re-derive (d) and (e) before changing either.

This module deliberately does not import the rules engine: the counting is a
pure function of the request body, so it can run before anything else.
"""

from typing import Any, Dict, List

#: (a) Conditions in the whole ruleset, nested groups included.
MAX_PREVIEW_CONDITIONS = 50

#: (a') Groups in the whole ruleset, at any depth; the top level is not one.
MAX_PREVIEW_GROUPS = 20

#: (b) ``match_regex`` conditions in the whole ruleset.
MAX_PREVIEW_REGEX_CONDITIONS = 10

#: (c) List elements across every condition value, nested lists included.
MAX_PREVIEW_LIST_ELEMENTS = 1000

#: (d) ``match_regex`` conditions x the requested ``sample_size``.
MAX_PREVIEW_REGEX_EVALUATIONS = 500

#: (e) (conditions + groups) x the requested ``sample_size``.
MAX_PREVIEW_NODE_EVALUATIONS = 50_000

#: The endpoint's own ``sample_size`` minimum (``ge=10``), used only to word advice.
MIN_PREVIEW_SAMPLE_SIZE = 10

#: Operator spellings that select pattern matching: the engine's own and the
#: dashboard alias the targeting adapter maps to it. Compared case-insensitively.
REGEX_OPERATORS = frozenset({"match_regex", "regex"})

_RULES_LOC = ["body", "rules"]
_SAMPLE_SIZE_LOC = ["query", "sample_size"]


def _count_list_elements(value: Any) -> int:
    """Count every element of every list inside ``value`` (iteratively)."""
    total = 0
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            total += len(item)
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
    return total


def _is_regex_operator(operator: Any) -> bool:
    return isinstance(operator, str) and operator.strip().lower() in REGEX_OPERATORS


def count_ruleset(rules: Any) -> Dict[str, int]:
    """
    Count conditions, groups, ``match_regex`` conditions and list elements.

    Every item of a ``conditions`` list counts as a condition and every item
    of a ``groups`` list as a group, whatever its shape; each dict among the
    groups is walked the same way. The walk is iterative, so nesting depth
    does not matter.
    """
    conditions = 0
    groups = 0
    regex_conditions = 0
    list_elements = 0

    stack = [rules]
    while stack:
        group = stack.pop()
        if not isinstance(group, dict):
            continue

        group_conditions = group.get("conditions")
        if isinstance(group_conditions, list):
            for condition in group_conditions:
                conditions += 1
                if not isinstance(condition, dict):
                    continue
                if _is_regex_operator(condition.get("operator")):
                    regex_conditions += 1
                list_elements += _count_list_elements(condition.get("value"))
                list_elements += _count_list_elements(condition.get("additional_value"))

        nested_groups = group.get("groups")
        if isinstance(nested_groups, list):
            groups += len(nested_groups)
            stack.extend(nested_groups)

    return {
        "conditions": conditions,
        "groups": groups,
        "regex_conditions": regex_conditions,
        "list_elements": list_elements,
    }


def preview_ruleset_violations(rules: Any, sample_size: int) -> List[Dict[str, Any]]:
    """
    Return the limits ``rules`` and ``sample_size`` break, as 422 error items.

    Each item has the ``ValidationError`` shape (``loc``, ``msg``, ``type``).
    The messages name the limit and the counted value, never request content.
    An empty list means the preview may run.
    """
    counts = count_ruleset(rules)
    errors: List[Dict[str, Any]] = []

    if counts["conditions"] > MAX_PREVIEW_CONDITIONS:
        errors.append(
            {
                "loc": _RULES_LOC,
                "msg": (
                    f"The ruleset has {counts['conditions']} conditions; "
                    f"a preview accepts at most {MAX_PREVIEW_CONDITIONS}."
                ),
                "type": "value_error",
            }
        )

    if counts["groups"] > MAX_PREVIEW_GROUPS:
        errors.append(
            {
                "loc": _RULES_LOC,
                "msg": (
                    f"The ruleset has {counts['groups']} groups; "
                    f"a preview accepts at most {MAX_PREVIEW_GROUPS}."
                ),
                "type": "value_error",
            }
        )

    if counts["regex_conditions"] > MAX_PREVIEW_REGEX_CONDITIONS:
        errors.append(
            {
                "loc": _RULES_LOC,
                "msg": (
                    f"The ruleset has {counts['regex_conditions']} match_regex "
                    f"conditions; a preview accepts at most "
                    f"{MAX_PREVIEW_REGEX_CONDITIONS}."
                ),
                "type": "value_error",
            }
        )

    if counts["list_elements"] > MAX_PREVIEW_LIST_ELEMENTS:
        errors.append(
            {
                "loc": _RULES_LOC,
                "msg": (
                    f"The condition values hold {counts['list_elements']} list "
                    f"elements in total; a preview accepts at most "
                    f"{MAX_PREVIEW_LIST_ELEMENTS}."
                ),
                "type": "value_error",
            }
        )

    regex_evaluations = counts["regex_conditions"] * sample_size
    if regex_evaluations > MAX_PREVIEW_REGEX_EVALUATIONS:
        largest_sample = MAX_PREVIEW_REGEX_EVALUATIONS // counts["regex_conditions"]
        advice = (
            f" Use a sample_size of {largest_sample} or less, or fewer "
            f"match_regex conditions."
            if largest_sample >= MIN_PREVIEW_SAMPLE_SIZE
            else " Use fewer match_regex conditions."
        )
        errors.append(
            {
                "loc": _SAMPLE_SIZE_LOC,
                "msg": (
                    f"{counts['regex_conditions']} match_regex conditions x "
                    f"sample_size {sample_size} = {regex_evaluations}; a preview "
                    f"accepts at most {MAX_PREVIEW_REGEX_EVALUATIONS}.{advice}"
                ),
                "type": "value_error",
            }
        )

    nodes = counts["conditions"] + counts["groups"]
    node_evaluations = nodes * sample_size
    if node_evaluations > MAX_PREVIEW_NODE_EVALUATIONS:
        largest_sample = MAX_PREVIEW_NODE_EVALUATIONS // nodes
        advice = (
            f" Use a sample_size of {largest_sample} or less, or fewer "
            f"conditions and groups."
            if largest_sample >= MIN_PREVIEW_SAMPLE_SIZE
            else " Use fewer conditions and groups."
        )
        errors.append(
            {
                "loc": _SAMPLE_SIZE_LOC,
                "msg": (
                    f"{nodes} conditions and groups x sample_size {sample_size} "
                    f"= {node_evaluations}; a preview accepts at most "
                    f"{MAX_PREVIEW_NODE_EVALUATIONS}.{advice}"
                ),
                "type": "value_error",
            }
        )

    return errors
