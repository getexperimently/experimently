"""When pytest may collect ``modules/backend/tests/live_warehouse``.

The directory holds the founder-run check against a real BigQuery project and
a real Snowflake account.  No CI job may collect it: it is **ignored** (not
skipped) unless the session's ``-m`` expression selects the
``warehouse_live`` marker on purpose.  ``modules/backend/tests/conftest.py``
applies this rule through ``pytest_ignore_collect``.

"On purpose" means both:

* an item carrying only ``warehouse_live`` is selected, and
* an item carrying no marker at all is not.

So ``-m warehouse_live`` and ``-m "warehouse_live and not slow"`` collect it;
no ``-m``, ``-m unit``, ``-m "not unit"`` and ``-m "not warehouse_live"`` do
not.  An expression that cannot be parsed ignores the directory: this rule
fails closed.

Standard library and pytest only, so the modules' conftest can import it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

#: The marker every test in the directory carries.
MARKER = "warehouse_live"

#: The directory this rule guards.
LIVE_DIRECTORY = Path(__file__).resolve().parent


def selects_live_marker(markexpr: Optional[str]) -> bool:
    """Whether ``-m markexpr`` asks for the ``warehouse_live`` tests on purpose."""
    if not markexpr or not markexpr.strip():
        return False
    try:
        from _pytest.mark.expression import Expression

        expression = Expression.compile(markexpr)

        def only_live(name: str, **_kwargs: Any) -> bool:
            return name == MARKER

        def nothing(name: str, **_kwargs: Any) -> bool:
            return False

        return bool(expression.evaluate(only_live)) and not bool(
            expression.evaluate(nothing)
        )
    except Exception:
        # A parse error, or a pytest whose private API moved: do not collect.
        return False


def is_live_path(path: Any) -> bool:
    """Whether ``path`` is the live directory or anything beneath it."""
    resolved = Path(str(path)).resolve()
    return resolved == LIVE_DIRECTORY or LIVE_DIRECTORY in resolved.parents


def ignore_live_directory(path: Any, markexpr: Optional[str]) -> Optional[bool]:
    """``True`` to ignore ``path``; ``None`` (never ``False``) to leave it alone.

    ``False`` from ``pytest_ignore_collect`` would *force* collection over any
    other plugin's or ``--ignore``'s decision, so it is never returned.
    """
    if is_live_path(path) and not selects_live_marker(markexpr):
        return True
    return None


__all__ = [
    "LIVE_DIRECTORY",
    "MARKER",
    "ignore_live_directory",
    "is_live_path",
    "selects_live_marker",
]
