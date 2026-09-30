"""No test may request two fixtures that each sign a client in.

``make_client_for_user`` (``backend/tests/integration/conftest.py``)
authenticates by writing ``app.dependency_overrides``, which is app-global.
Every client it has returned then acts as the user of the most recent call.
A test that takes ``admin_client`` and ``developer_client`` therefore runs
every request as whichever fixture pytest set up last -- two "developer can
read results" tests ran as ADMIN this way and passed against a route that
refused developers (#470).

The fix for such a test is to do the setup with one client and make the
actor's client afterwards with ``make_client_for_user`` (or a lazy factory,
as ``modules/backend/tests/integration/warehouse/test_run_sql_roles.py``
does).  This is a static AST scan: no database, no app import.

Not covered: a fixture requested dynamically with
``request.getfixturevalue``, a fixture that reaches ``make_client_for_user``
through a helper in another file, and a client variable kept in a test body
after a later ``make_client_for_user`` call has replaced its user.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple

import pytest

from backend.tests.smoke.modules_manifest import REPO_ROOT

pytestmark = pytest.mark.smoke

# Every fixture that installs the auth override, i.e. calls
# make_client_for_user directly or through a helper in its own file.  Pinned
# against the tree by test_the_fixture_list_is_complete, so a new one cannot be
# missed.  Names are matched tree-wide, which is conservative for the
# file-local ones (cached_client exists in three files).
ROLE_CLIENT_FIXTURES = frozenset(
    {
        # backend/tests/integration/conftest.py
        "admin_client",
        "developer_client",
        "analyst_client",
        "viewer_client",
        # test_experiment_cache_redis.py, test_flag_cache_redis.py
        "cached_client",
        "cached_superuser_client",
        "cached_unreadable_client",
        # test_user_email_and_username_updates.py
        "member",
        "member_as_written",
    }
)
# Defined under modules/backend/tests, which a core build does not have.
MODULE_ROLE_CLIENT_FIXTURES = frozenset({"as_user"})  # test_workspaces_api.py

# The module trees are absent from a core build; scanning what exists is right.
SCAN_ROOTS = ("backend/tests", "modules/backend/tests")

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_ALL = ROLE_CLIENT_FIXTURES | MODULE_ROLE_CLIENT_FIXTURES


def _files() -> Iterator[Path]:
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if base.is_dir():
            yield from sorted(base.rglob("*.py"))


def _modules() -> Iterator[Tuple[str, List[ast.AST]]]:
    """(path relative to REPO_ROOT, every function def in the file)."""
    for path in _files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        funcs = [n for n in ast.walk(tree) if isinstance(n, _FUNCS)]
        yield path.relative_to(REPO_ROOT).as_posix(), funcs


def _params(func: ast.AST) -> Set[str]:
    args = func.args
    return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    return getattr(node, "id", None)


def _is_fixture(func: ast.AST) -> bool:
    for dec in func.decorator_list:
        if _name(dec.func if isinstance(dec, ast.Call) else dec) == "fixture":
            return True
    return False


def _called(func: ast.AST) -> Set[str]:
    return {_name(n.func) for n in ast.walk(func) if isinstance(n, ast.Call)} - {None}


def _signing_in(funcs: List[ast.AST]) -> Set[str]:
    """Names of functions in one file that reach make_client_for_user,
    directly or through other functions of the same file."""
    calls: Dict[str, Set[str]] = {}
    for f in funcs:
        calls.setdefault(f.name, set()).update(_called(f))
    reach = {"make_client_for_user"}
    while True:
        more = {name for name, c in calls.items() if c & reach} - reach
        if not more:
            return reach - {"make_client_for_user"}
        reach |= more


def offenders() -> List[str]:
    """Tests and fixtures that request more than one sign-in fixture."""
    found = []
    for rel, funcs in _modules():
        for func in funcs:
            if not (func.name.startswith("test") or _is_fixture(func)):
                continue
            requested = _params(func) & _ALL
            if len(requested) > 1:
                found.append(
                    f"{rel}:{func.lineno} {func.name} requests {sorted(requested)}"
                )
    return found


@pytest.mark.regression
def test_no_test_requests_two_role_clients():
    bad = offenders()
    assert not bad, (
        "These request more than one fixture that signs a client in. The auth "
        "override is app-global, so every request runs as whichever fixture "
        "was set up last. Do the setup with one client, then make the actor's "
        "client with make_client_for_user:\n  " + "\n  ".join(bad)
    )


def test_the_fixture_list_is_complete():
    """Every fixture that reaches make_client_for_user is in the list above."""
    fixtures = set()
    for _, funcs in _modules():
        signing_in = _signing_in(funcs)
        fixtures |= {f.name for f in funcs if _is_fixture(f) and f.name in signing_in}
    expected = set(ROLE_CLIENT_FIXTURES)
    if (REPO_ROOT / "modules" / "backend" / "tests").is_dir():
        expected |= MODULE_ROLE_CLIENT_FIXTURES
    assert fixtures == expected, (
        f"missing from the lists: {sorted(fixtures - expected)}; "
        f"listed but not found: {sorted(expected - fixtures)}"
    )


def test_the_scan_is_not_vacuous():
    """The scan sees the tests that use these fixtures, so a wrong root or a
    broken parse cannot turn the gate into a pass."""
    users = [
        func.name
        for _, funcs in _modules()
        for func in funcs
        if func.name.startswith("test") and _params(func) & _ALL
    ]
    assert len(users) > 100, len(users)
