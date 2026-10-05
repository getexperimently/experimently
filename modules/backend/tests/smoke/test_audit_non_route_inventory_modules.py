"""Every change the audit log covers that the modules make outside a route is classified (#221).

The twin of ``backend/tests/smoke/test_audit_non_route_inventory.py``, over
``modules/backend/app`` (every module except the route modules under
``modules/backend/app/api/v1/endpoints/``). It uses the same scanner, so a
site is the same thing: an assignment to an experiment's ``status`` with an
``ExperimentStatus`` member, to ``rollout_percentage``, ``role``,
``is_superuser`` or ``is_active``, or a ``User(...)`` construction, whatever
the object.

``SITES`` classifies each one, with how many times its function does it:

* ``Audited(actions)``: the function passes each ``ActionType`` member to a
  call. That it writes the entry is pinned by
  ``modules/backend/tests/integration/api/test_audit_module_events.py``.
  The SSO sign-in role change is here: D49 lists role changes, so it is
  audited, never exempt.
* ``RouteReached()``: every chain of references to the function ends in a
  module route module (which writes the entry) or in a function nothing
  refers to.
* ``Exempt(reason)``: not on the audited event list.

The comparison is exact. The source is read from this file's own path (no
git).
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, Set, Tuple

import pytest

from backend.app.models.audit_log import ActionType as A
from backend.tests.smoke.test_audit_non_route_inventory import (
    Audited,
    Exempt,
    RouteReached,
    _Walker,
    sites_in,
)

pytestmark = [pytest.mark.smoke]

REPO_ROOT = Path(__file__).resolve().parents[4]
APP = REPO_ROOT / "modules" / "backend" / "app"
ROUTES = "modules/backend/app/api/v1/endpoints/"

#: (module, function, kind) -> (how many times, classification).
SITES: Dict[Tuple[str, str, str], Tuple[int, object]] = {
    # --- SSO sign-in: the role change of an existing account, and JIT -------
    ("modules/backend/app/services/sso_service.py", "provision_user", "role"): (
        1,
        Audited(A.ROLE_ASSIGN),
    ),
    ("modules/backend/app/services/sso_service.py", "provision_user", "User()"): (
        1,
        Audited(A.USER_CREATE),
    ),
    # --- a workspace member's role: PUT .../members/{user_id} writes it ------
    (
        "modules/backend/app/services/workspace_service.py",
        "WorkspaceService.update_member_role",
        "role",
    ): (2, RouteReached()),
    # --- not on the audited event list --------------------------------------
    (
        "modules/backend/app/services/hipaa_service.py",
        "HIPAAService.deactivate_baa",
        "is_active",
    ): (1, Exempt("a business associate agreement's flag, not a user's")),
}


@lru_cache(maxsize=1)
def _parsed() -> Tuple[Tuple[str, ast.Module], ...]:
    found = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        found.append((rel, ast.parse(path.read_text(encoding="utf-8"), filename=rel)))
    return tuple(found)


def all_sites() -> Counter:
    found: Counter = Counter()
    for rel, tree in _parsed():
        if rel.startswith(ROUTES):
            continue
        found.update(sites_in(rel, tree))
    return found


def actions_named(rel: str, qualname: str) -> Set[str]:
    """The ``ActionType`` members the function passes to a call."""
    tree = dict(_parsed())[rel]
    named: Set[str] = set()

    class V(_Walker):
        def visit_Call(self, node):
            if self.qualname == qualname:
                for arg in [*node.args, *(k.value for k in node.keywords)]:
                    if (
                        isinstance(arg, ast.Attribute)
                        and isinstance(arg.value, ast.Name)
                        and arg.value.id == "ActionType"
                    ):
                        named.add(arg.attr)
            self.generic_visit(node)

    V().visit(tree)
    return named


@lru_cache(maxsize=1)
def references() -> Dict[str, Set[Tuple[str, str]]]:
    """name -> {(module, enclosing function)} for every name read in the modules."""
    refs: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)
    for rel, tree in _parsed():

        class V(_Walker):
            def visit_Name(self, node):
                if isinstance(node.ctx, ast.Load):
                    refs[node.id].add((rel, self.qualname))

            def visit_Attribute(self, node):
                if isinstance(node.ctx, ast.Load):
                    refs[node.attr].add((rel, self.qualname))
                self.generic_visit(node)

        V().visit(tree)
    return refs


def roots_outside_routes(names, refs) -> Set[Tuple[str, str]]:
    """Where a chain of references to ``names`` ends outside a route module."""
    roots: Set[Tuple[str, str]] = set()
    seen: Set[str] = set()
    todo = list(names)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for rel, qualname in refs.get(name, ()):
            if rel.startswith(ROUTES):
                continue
            if qualname == "<module>":
                roots.add((rel, qualname))
                continue
            todo.append(qualname.split(".")[-1])
    return roots


#: Actions the modules write outside a route.
NON_ROUTE_ACTIONS: frozenset = frozenset(
    action
    for _, entry in SITES.values()
    if isinstance(entry, Audited)
    for action in entry.actions
)


def test_the_sites_are_exact():
    found = all_sites()
    expected = Counter({key: count for key, (count, _) in SITES.items()})
    assert found == expected, (
        f"unclassified or miscounted: "
        f"{sorted((k, n) for k, n in found.items() if expected.get(k) != n)}; "
        f"gone: {sorted(k for k in expected if k not in found)}"
    )
    assert sum(expected.values()) == 5


def test_the_sso_role_change_is_audited_not_exempt():
    """D49 lists role changes: the SSO sign-in's is recorded as one."""
    _, entry = SITES[
        ("modules/backend/app/services/sso_service.py", "provision_user", "role")
    ]
    assert isinstance(entry, Audited)
    assert A.ROLE_ASSIGN in entry.actions


@pytest.mark.parametrize(
    "key",
    sorted(k for k, (_, e) in SITES.items() if isinstance(e, Audited)),
    ids=lambda k: f"{k[1]} {k[2]}",
)
def test_each_audited_site_names_its_actions(key):
    rel, qualname, _ = key
    _, entry = SITES[key]
    named = actions_named(rel, qualname)
    missing = sorted(a.name for a in entry.actions if a.name not in named)
    assert not missing, f"{qualname} writes no {missing}"


@pytest.mark.parametrize(
    "key",
    sorted(k for k, (_, e) in SITES.items() if isinstance(e, RouteReached)),
    ids=lambda k: f"{k[1]} {k[2]}",
)
def test_each_route_reached_site_is_reached_only_from_routes(key):
    _, qualname, _ = key
    _, entry = SITES[key]
    names = entry.names or (qualname.split(".")[-1],)
    roots = roots_outside_routes(names, references())
    assert roots == set(), f"{qualname} is reached from outside a route: {roots}"


@pytest.mark.parametrize("key", sorted(SITES), ids=lambda k: f"{k[1]} {k[2]}")
def test_each_entry_is_well_formed(key):
    count, entry = SITES[key]
    assert count >= 1
    if isinstance(entry, Audited):
        assert entry.actions and all(isinstance(a, A) for a in entry.actions)
    elif isinstance(entry, RouteReached):
        assert entry.reason.strip()
    else:
        assert isinstance(entry, Exempt) and entry.reason.strip()
