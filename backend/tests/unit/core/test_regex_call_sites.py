"""
Every pattern that reaches Python's ``re`` in runtime code is fixed text.

Stored and request-supplied patterns (the ``regex`` / ``match_regex`` rule
operator) are compiled and searched by ``backend/app/core/pattern_match.py``
with RE2. This test walks the runtime trees and fails on any call to an ``re``
function -- through any alias of the module or of the function -- whose
pattern argument is not a string literal or a module-level string constant.

Scope: ``backend/app``, ``backend/lambda``, and ``modules/backend/app`` and
``modules/lambda`` when present (a core checkout has no ``modules/``). Tests
are outside it. There is no allow-list: a new dynamic pattern goes through
``pattern_match``, or becomes a module constant.

It uses only pathlib and ast, so it runs the same in ``scripts/core_build.sh``'s
copy of the tree, which has no ``.git``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, List, Set, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

SCAN_ROOTS = (
    "backend/app",
    "backend/lambda",
    "modules/backend/app",
    "modules/lambda",
)

#: Directory names skipped inside the scan roots (test code is not runtime).
SKIP_DIRS = frozenset({"tests", "test", "__pycache__", "node_modules", ".venv"})

RE_FUNCTIONS = frozenset(
    {
        "compile",
        "search",
        "match",
        "fullmatch",
        "findall",
        "finditer",
        "sub",
        "subn",
        "split",
    }
)


def _module_constants(tree: ast.Module) -> Set[str]:
    """Names bound at module level to a str/bytes literal (or a tuple of them)."""

    def literal(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return isinstance(node.value, (str, bytes))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return literal(node.left) and literal(node.right)
        return False

    names: Set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and literal(stmt.value):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif (
            isinstance(stmt, ast.AnnAssign)
            and stmt.value is not None
            and literal(stmt.value)
            and isinstance(stmt.target, ast.Name)
        ):
            names.add(stmt.target.id)
    return names


def _re_aliases(tree: ast.Module) -> Tuple[Set[str], Set[str]]:
    """(names bound to the ``re`` module, names bound to one of its functions)."""
    modules: Set[str] = set()
    functions: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "re":
                    modules.add(alias.asname or "re")
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            for alias in node.names:
                if alias.name in RE_FUNCTIONS or alias.name == "*":
                    functions.add(alias.asname or alias.name)
    if any(name == "*" for name in functions):
        functions.discard("*")
        functions |= RE_FUNCTIONS
    return modules, functions


def find_dynamic_patterns(source: str, filename: str = "<source>") -> List[str]:
    """``file:line`` for every ``re`` call whose pattern is not fixed text."""
    tree = ast.parse(source, filename=filename)
    modules, functions = _re_aliases(tree)
    if not modules and not functions:
        return []
    constants = _module_constants(tree)

    def fixed(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            return True
        return isinstance(node, ast.Name) and node.id in constants

    hits: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_re_call = (
            isinstance(func, ast.Attribute)
            and func.attr in RE_FUNCTIONS
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        ) or (isinstance(func, ast.Name) and func.id in functions)
        if not is_re_call:
            continue
        pattern = node.args[0] if node.args else None
        if pattern is None:
            for keyword in node.keywords:
                if keyword.arg == "pattern":
                    pattern = keyword.value
        if pattern is None or isinstance(pattern, ast.Starred) or not fixed(pattern):
            hits.append(f"{filename}:{node.lineno}")
    return hits


def _runtime_files(root: Path) -> Iterator[Path]:
    for relative in SCAN_ROOTS:
        base = root / relative
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            parts = path.relative_to(base).parts
            if any(part in SKIP_DIRS for part in parts[:-1]):
                continue
            if parts[-1].startswith("test_") or parts[-1] == "conftest.py":
                continue
            yield path


def test_runtime_regex_patterns_are_fixed_text():
    files = list(_runtime_files(REPO_ROOT))
    assert len(files) > 50, (
        f"only {len(files)} runtime files found under {SCAN_ROOTS}; "
        "the walk is not looking where the code is"
    )
    hits: List[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        hits += find_dynamic_patterns(source, str(path.relative_to(REPO_ROOT)))
    assert hits == [], (
        "Python `re` called with a pattern that is not fixed text. Evaluate "
        "rule patterns with backend.app.core.pattern_match; make any other "
        "pattern a module-level constant:\n  " + "\n  ".join(hits)
    )


def test_the_rules_engine_is_scanned():
    """The file that evaluates rule patterns must be inside the walk."""
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in _runtime_files(REPO_ROOT)}
    assert "backend/app/core/rules_engine.py" in scanned
    assert "backend/app/core/pattern_match.py" in scanned


# -- the checker itself -------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import re\ndef f(cond, v):\n    return re.fullmatch(cond.value, v)\n",
        "import re as rx\ndef f(p, v):\n    return rx.search(p, v)\n",
        "from re import compile\ndef f(p):\n    return compile(p)\n",
        "from re import match as m\ndef f(p, v):\n    return m(p, v)\n",
        "from re import *\ndef f(p, v):\n    return sub(p, '', v)\n",
        "import re\ndef f(p, v):\n    return re.match(pattern=p, string=v)\n",
        "import re\ndef f(v):\n    local = r'^a'\n    return re.match(local, v)\n",
        "import re\ndef f(args):\n    return re.compile(*args)\n",
        "import re\ndef f(p, v):\n    return re.split(p + 'x', v)\n",
    ],
)
def test_a_dynamic_pattern_is_reported(source):
    assert find_dynamic_patterns(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "import re\nX = re.compile(r'^a+$')\n",
        "import re\nPAT = r'^a'\ndef f(v):\n    return re.match(PAT, v)\n",
        "import re\nPAT: str = r'^a'\ndef f(v):\n    return re.search(PAT, v)\n",
        "import re\nPAT = (r'^a' r'b$')\ndef f(v):\n    return re.fullmatch(PAT, v)\n",
        "def f(p, v):\n    return p.search(v)\n",
        "import re2\ndef f(p, v):\n    return re2.search(p, v)\n",
    ],
)
def test_fixed_text_is_accepted(source):
    assert find_dynamic_patterns(source) == []
