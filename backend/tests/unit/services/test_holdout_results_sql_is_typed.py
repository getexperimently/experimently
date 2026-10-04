"""The holdout results module builds no raw SQL text (#445, PE C14).

Its window bounds are compared through the columns' own types: a bound on
``events.created_at`` goes through ``UTCTimestampString``, one on a naive
timestamp column is a naive bind.  A ``text()`` or ``literal_column()``
fragment would skip both, so neither may be called in the module, by bare
name or as an attribute (``sa.text``, ``sqlalchemy.text``), nor imported.
"""

import ast
from pathlib import Path

import pytest

import backend.app.services.holdout_results as module

pytestmark = pytest.mark.unit

FORBIDDEN = {"text", "literal_column"}


def forbidden_uses(source: str) -> list:
    """``(line, name)`` for each call to, or import of, a forbidden name."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in FORBIDDEN:
                hits.append((node.lineno, name))
        elif isinstance(node, ast.ImportFrom):
            hits.extend(
                (node.lineno, alias.name)
                for alias in node.names
                if alias.name in FORBIDDEN
            )
    return hits


def test_the_module_calls_no_text_or_literal_column():
    source = Path(module.__file__).read_text()
    assert forbidden_uses(source) == []


@pytest.mark.parametrize(
    "planted",
    [
        'q = text("SELECT 1 WHERE created_at < :w")',
        'q = sa.text("SELECT 1 WHERE created_at < :w")',
        'q = sqlalchemy.text("SELECT 1")',
        'q = literal_column("created_at")',
        'q = sa.literal_column("created_at")',
        "from sqlalchemy import text",
    ],
)
def test_the_check_sees_each_form(planted):
    assert forbidden_uses(planted) != []
