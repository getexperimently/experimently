"""Refuse request text the database cannot store (#543, #402).

PostgreSQL refuses U+0000 in ``text``, ``varchar`` and ``jsonb``, and a lone
UTF-16 surrogate (U+D800-U+DFFF) cannot be encoded as UTF-8 at all. JSON can
carry both (``"\\u0000"``, ``"\\ud800"``), so a request schema accepts them
unless something refuses them, and the database driver then fails the
request with a 500.

:class:`StorableTextModel` refuses them in every field of a request schema --
a string, or any string inside a dict or list, keys included -- with a
validation error, i.e. 422. The message names the field and never the value.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationInfo, field_validator
from pydantic_core.core_schema import ValidatorFunctionWrapHandler

#: One character class, so the search is linear and cannot backtrack.
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


def contains_unstorable_text(value: Any) -> bool:
    """True if *value*, or any string nested in it, holds NUL or a lone surrogate.

    Walks dicts (keys and values), lists and tuples without recursion, so a
    deeply nested body cannot exhaust the stack.
    """
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if _UNSTORABLE.search(item):
                return True
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return False


def unstorable_text_message(field: str) -> str:
    """The fixed validation message for *field*; it never includes the value."""
    return f"{field} must not contain NUL or unpaired surrogate characters"


class StorableTextModel(BaseModel):
    """Base for request schemas whose text reaches the database.

    Every field is checked twice: the input as received, so the refusal comes
    before any type error about the same value, and the validated value, so
    text produced by a field's own parsing (a JSON-encoded string, say) is
    checked too.
    """

    @field_validator("*", mode="wrap")
    @classmethod
    def _refuse_unstorable_text(
        cls, value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> Any:
        if contains_unstorable_text(value):
            raise ValueError(unstorable_text_message(info.field_name))
        result = handler(value)
        if contains_unstorable_text(result):
            raise ValueError(unstorable_text_message(info.field_name))
        return result
