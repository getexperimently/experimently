"""The values a journey saves from an API answer, for the steps after it.

An ``api`` step may ``save`` values from its JSON answer, each under a name::

    save:
      experiment-id: {path: items.0.id}
      sdk-key: {path: key, secret: true}

A later step uses a saved value by writing ``{{experiment-id}}`` in an api
step's path or in a string of its body, or in a ``goto``: the runner puts the
value in before the step runs, as a reader pastes an id they were shown. A
value saved with ``secret: true`` (an API key the API answered with) is never
put into a path, a body or an address: a later api step or ``traffic`` step
sends it as its ``key``, in the ``X-API-Key`` header, and it is never written
to the run directory (``redaction.py``).

Nothing here imports Playwright or the product, so the unit job tests it.
"""

from __future__ import annotations

import re
from typing import Any, List, Mapping

#: ``{{name}}``: a saved value's name is a slug, as a step's id is.
PLACEHOLDER = re.compile(r"\{\{([a-z0-9]+(?:-[a-z0-9]+)*)\}\}")


def placeholders(text: str) -> List[str]:
    """The names *text* refers to, in order."""
    return PLACEHOLDER.findall(text)


def placeholders_in(node: Any) -> List[str]:
    """The names every string in a nested body refers to (keys included)."""
    found: List[str] = []
    if isinstance(node, str):
        found.extend(placeholders(node))
    elif isinstance(node, dict):
        for key, value in node.items():
            found.extend(placeholders_in(key))
            found.extend(placeholders_in(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(placeholders_in(value))
    return found


def substitute(text: str, values: Mapping[str, str]) -> str:
    """*text* with each ``{{name}}`` replaced; KeyError naming an unknown one."""

    def value(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"no value saved as {name!r}")
        return values[name]

    return PLACEHOLDER.sub(value, text)


def substitute_in(node: Any, values: Mapping[str, str]) -> Any:
    """A copy of a nested body with every string's placeholders replaced."""
    if isinstance(node, str):
        return substitute(node, values)
    if isinstance(node, dict):
        return {
            substitute_in(key, values): substitute_in(value, values)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [substitute_in(value, values) for value in node]
    return node


def as_text(value: Any) -> str:
    """A saved JSON value as the text put into a path: a string or a number.

    ValueError for anything else (an object, a list, null, a boolean): a
    path or an id is never one of those, so saving one is a mistake to see.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{value!r} is not a string or a number")
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError(f"a {type(value).__name__} is not a string or a number")
