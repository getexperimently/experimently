"""Every route that can change a segment is accounted for (#440).

Segments use the EXPERIMENT permissions (``segments._require_permission``):
ANALYST and VIEWER read, DEVELOPER and ADMIN change. A route that forgot the
call would let any signed-in user change who a segment holds, so this pins the
exact set of mutating routes under ``/api/v1/segments`` and the action each
one checks. A new mutating route there fails ``test_the_inventory_is_exact``
until it is classified here.

Routes are read through ``effective_route_contexts``, as
``test_flag_change_routes_guarded.py`` does: plain ``app.routes`` holds the
included routers lazily.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.routing import APIRoute

from backend.app.main import app

pytestmark = [pytest.mark.smoke, pytest.mark.regression]

PREFIX = "/api/v1/segments"
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

#: (method, path) -> the ``Action`` member the route passes to
#: ``_require_permission(current_user, Action.<X>)``.
INVENTORY = {
    ("POST", "/api/v1/segments"): "CREATE",
    ("PUT", "/api/v1/segments/{segment_id}"): "UPDATE",
    ("DELETE", "/api/v1/segments/{segment_id}"): "DELETE",
    ("POST", "/api/v1/segments/{segment_id}/members"): "UPDATE",
    ("POST", "/api/v1/segments/{segment_id}/members/remove"): "UPDATE",
    # POSTs that only read: any role may call them.
    ("POST", "/api/v1/segments/bulk-evaluate"): "READ",
    ("POST", "/api/v1/segments/{segment_id}/evaluate"): "READ",
    ("POST", "/api/v1/segments/{segment_id}/preview"): "READ",
}


def _contexts(application):
    for route in application.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            if not isinstance(route, APIRoute):
                continue
            contexts = (route,)
        for ctx in contexts() if callable(contexts) else contexts:
            for method in getattr(ctx, "methods", None) or ():
                yield method, ctx.path, ctx


def _mutating_routes(application):
    return {
        (method, path): ctx
        for method, path, ctx in _contexts(application)
        if method in MUTATING and (path == PREFIX or path.startswith(PREFIX + "/"))
    }


def test_the_inventory_is_exact():
    found = set(_mutating_routes(app))
    assert found == set(INVENTORY), (
        f"unclassified: {sorted(found - set(INVENTORY))}; "
        f"gone: {sorted(set(INVENTORY) - found)}"
    )
    assert len(INVENTORY) == 8


@pytest.mark.parametrize("key", sorted(INVENTORY), ids=lambda k: f"{k[0]} {k[1]}")
def test_each_route_checks_its_action(key):
    source = inspect.getsource(_mutating_routes(app)[key].endpoint)
    action = INVENTORY[key]
    calls = [
        line.strip()
        for line in source.splitlines()
        if "_require_permission(" in line and not line.strip().startswith("#")
    ]
    assert calls == [f"_require_permission(current_user, Action.{action})"], calls
