"""The exact set of ``/api/v1/openfeature`` routes (#241).

``POST /openfeature/evaluate`` and ``POST /openfeature/bulk-evaluate`` were
removed; ``GET /openfeature/flags`` stays, deprecated, with its behaviour
unchanged. This pins that as an exact set, so neither a re-mounted evaluate
route nor a quietly dropped listing passes.

Routes are read through ``effective_route_contexts`` (as in
``test_flag_change_routes_guarded.py``): FastAPI keeps ``include_router`` as a
lazy entry, so plain ``app.routes`` would see none of these. The OpenAPI
document is checked separately, because a route can be mounted with
``include_in_schema=False`` and still answer.
"""

from __future__ import annotations

import pytest

from backend.app.main import app

pytestmark = [pytest.mark.smoke, pytest.mark.regression]

PREFIX = "/api/v1/openfeature"

EXPECTED = {("GET", "/api/v1/openfeature/flags")}


def _routes(application):
    """(method, path) for every mounted HTTP route under PREFIX."""
    found = set()
    for route in application.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            continue
        for ctx in contexts() if callable(contexts) else contexts:
            path = ctx.path
            if path != PREFIX and not path.startswith(PREFIX + "/"):
                continue
            for method in getattr(ctx, "methods", None) or ():
                if method != "HEAD":
                    found.add((method, path))
    return found


def test_the_route_set_is_exact():
    assert _routes(app) == EXPECTED


def test_the_listing_is_present():
    """Positive control: the reader sees the route it is meant to keep.

    Without this, a reader that saw nothing (the lazy ``include_router`` entry
    read through plain ``app.routes``) would pass a "no evaluate route" check.
    """
    assert ("GET", "/api/v1/openfeature/flags") in _routes(app)


def test_the_schema_matches_and_the_listing_is_deprecated():
    paths = {
        path: ops
        for path, ops in app.openapi()["paths"].items()
        if path == PREFIX or path.startswith(PREFIX + "/")
    }
    assert set(paths) == {"/api/v1/openfeature/flags"}
    assert set(paths["/api/v1/openfeature/flags"]) == {"get"}
    assert paths["/api/v1/openfeature/flags"]["get"].get("deprecated") is True
