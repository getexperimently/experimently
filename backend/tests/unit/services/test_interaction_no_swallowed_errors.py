"""
X1 (#219): the pair route has one failure path, and nothing on it swallows an error.

A swallowed read is how the old pair route answered "no overlap" for an
unknown experiment and for a database failure.  So, from the source:

* ``services/interaction_analysis.py`` has no ``try`` at all;
* the pair analysis in ``services/interaction_detection_service.py``
  (``PAIR_FUNCTIONS``) has no ``try`` at all;
* the pair route, ``analyze_pair``, has exactly one ``try`` whose handlers are
  exactly ``except HTTPException: raise`` and then
  ``except Exception as exc: raise unexpected_failure(exc, ..., db=db)``.

``/scan`` and its two helpers are not covered here.
"""

import ast
import pathlib
from typing import List

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = pathlib.Path(__file__).resolve().parents[4]
ANALYSIS = ROOT / "backend/app/services/interaction_analysis.py"
SERVICE = ROOT / "backend/app/services/interaction_detection_service.py"
ROUTES = ROOT / "backend/app/api/v1/endpoints/interactions.py"

#: The pair analysis: every function the pair route reaches in the service.
PAIR_FUNCTIONS = {
    "load_experiment",
    "bound_statement_time",
    "_arm_totals",
    "_shared_assignments",
    "_shared_converters",
    "analyze_pair_interactions",
    "_rows_for",
    "_pair_recommendations",
    "_keep_shared",
    "_variant_order",
    "_metric_type",
    "_rate",
    "_arm",
    "_points",
}


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _tries(node: ast.AST, path: pathlib.Path) -> List[str]:
    return [
        f"{path.relative_to(ROOT)}:{n.lineno}: try in {getattr(node, 'name', '<module>')}"
        for n in ast.walk(node)
        if isinstance(n, ast.Try)
    ]


def test_the_statistics_module_has_no_try():
    tree = ast.parse(ANALYSIS.read_text())
    assert _tries(tree, ANALYSIS) == []


def test_the_pair_analysis_has_no_try():
    tree = ast.parse(SERVICE.read_text())
    found = {f.name: f for f in _functions(tree) if f.name in PAIR_FUNCTIONS}
    assert set(found) == PAIR_FUNCTIONS, "a listed function was renamed or removed"
    problems = [p for f in found.values() for p in _tries(f, SERVICE)]
    assert problems == []


def _is_bare_raise(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Raise) and stmt.exc is None and stmt.cause is None


def _is_unexpected_failure(stmt: ast.stmt, name: str) -> bool:
    if not (isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call)):
        return False
    call = stmt.exc
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "unexpected_failure"
        and bool(call.args)
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == name
        and any(
            k.arg == "db" and isinstance(k.value, ast.Name) and k.value.id == "db"
            for k in call.keywords
        )
    )


def _route_problems(source: str) -> List[str]:
    tree = ast.parse(source)
    [route] = [f for f in _functions(tree) if f.name == "analyze_pair"]
    tries = [n for n in ast.walk(route) if isinstance(n, ast.Try)]
    where = f"{ROUTES.relative_to(ROOT)}"
    if len(tries) != 1:
        return [f"{where}: analyze_pair has {len(tries)} try blocks, expected 1"]
    [block] = tries
    problems = []
    if block.orelse or block.finalbody:
        problems.append(f"{where}:{block.lineno}: else/finally on the try")
    handlers = block.handlers
    if len(handlers) != 2:
        return problems + [
            f"{where}:{block.lineno}: {len(handlers)} handlers, expected 2"
        ]
    first, second = handlers
    if not (
        isinstance(first.type, ast.Name)
        and first.type.id == "HTTPException"
        and first.name is None
        and len(first.body) == 1
        and _is_bare_raise(first.body[0])
    ):
        problems.append(
            f"{where}:{first.lineno}: expected `except HTTPException: raise`"
        )
    if not (
        isinstance(second.type, ast.Name)
        and second.type.id == "Exception"
        and second.name
        and len(second.body) == 1
        and _is_unexpected_failure(second.body[0], second.name)
    ):
        problems.append(
            f"{where}:{second.lineno}: expected `except Exception as exc: "
            "raise unexpected_failure(exc, ..., db=db)`"
        )
    return problems


def test_the_pair_route_has_exactly_the_one_failure_shape():
    assert _route_problems(ROUTES.read_text()) == []


@pytest.mark.parametrize(
    "plant",
    [
        # A handler that swallows.
        (
            "    except Exception as exc:\n        raise unexpected_failure(",
            "    except Exception as exc:\n        return set()\n        raise unexpected_failure(",
        ),
        # The HTTPException pass-through removed: a 404 would become a 500.
        ("    except HTTPException:\n        raise\n", ""),
    ],
)
def test_the_route_check_names_a_planted_defect(plant):
    old, new = plant
    source = ROUTES.read_text()
    head, marker, route = source.partition("def analyze_pair(")
    assert marker and old in route
    assert _route_problems(head + marker + route.replace(old, new, 1))
