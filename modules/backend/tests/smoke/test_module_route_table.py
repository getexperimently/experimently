"""The full application's route table for the warehouse and ETL prefixes.

The warehouse endpoints and ``POST /api/v1/etl/query`` were removed; warehouse
analysis is being rebuilt (#312).  This pins the result as exact sets rather
than prefix rules:

* no route at all under ``/api/v1/warehouse``;
* ``/api/v1/etl`` serves exactly the five method+path pairs below.

A prefix deny-list would have to be loosened the day #312 adds its new
routes; an exact set fails on any addition, and the change that adds a route
amends the set on purpose.

The positive control matters as much as the absence checks.  A modules
registration that loaded but mounted nothing would make "no warehouse route"
pass for the wrong reason, so the same route table must also carry an SSO
route and ``POST /api/v1/etl/jobs/run``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.smoke

WAREHOUSE_PREFIX = "/api/v1/warehouse"
ETL_PREFIX = "/api/v1/etl"

#: Every (method, path) the ETL router serves.  HEAD/OPTIONS are not listed:
#: FastAPI does not add them to an ``APIRoute``'s methods.
EXPECTED_ETL_ROUTES = frozenset(
    {
        ("POST", "/api/v1/etl/jobs/run"),
        ("GET", "/api/v1/etl/jobs/{run_id}/status"),
        ("POST", "/api/v1/etl/partitions/add"),
        ("GET", "/api/v1/etl/crawler/status"),
        ("POST", "/api/v1/etl/crawler/run"),
    }
)

#: Routes that must be present, so the absence checks cannot pass vacuously.
POSITIVE_CONTROL = frozenset(
    {
        ("GET", "/api/v1/auth/sso/saml/{config_id}/metadata"),
        ("POST", "/api/v1/etl/jobs/run"),
    }
)


def _route_table(app) -> set[tuple[str, str]]:
    """Every ``(method, path)`` pair *app* serves.

    FastAPI >= 0.141 keeps a lazy ``_IncludedRouter`` entry per
    ``include_router`` whose ``effective_route_contexts`` carry the fully
    prefixed paths; older versions expose plain routes.  Both shapes are
    handled, as in ``backend/tests/smoke/test_wiring.py``.
    """
    from fastapi.routing import APIRoute

    pairs: set[tuple[str, str]] = set()

    def add(path, methods):
        if not path:
            return
        for method in methods or ("*",):
            pairs.add((method, path))

    for route in app.routes:
        if isinstance(route, APIRoute):
            add(route.path, route.methods)
            continue
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            contexts = contexts() if callable(contexts) else contexts
            for ctx in contexts:
                add(getattr(ctx, "path", None), getattr(ctx, "methods", None))
        else:
            add(getattr(route, "path", None), getattr(route, "methods", None))
    return pairs


@pytest.fixture(scope="module")
def route_table() -> set[tuple[str, str]]:
    from backend.app.main import app

    return _route_table(app)


def test_the_positive_control_routes_are_mounted(route_table):
    missing = sorted(POSITIVE_CONTROL - route_table)
    assert not missing, (
        f"the modules' routes are not mounted: {missing}. The other checks "
        "in this file prove nothing until they are."
    )


def test_no_route_under_the_warehouse_prefix(route_table):
    assert POSITIVE_CONTROL <= route_table, "positive control failed"
    found = sorted(
        (method, path)
        for method, path in route_table
        if path.startswith(WAREHOUSE_PREFIX)
    )
    assert found == [], f"routes under {WAREHOUSE_PREFIX}: {found}"


def test_the_etl_routes_are_exactly_the_five(route_table):
    assert POSITIVE_CONTROL <= route_table, "positive control failed"
    etl = {
        (method, path)
        for method, path in route_table
        if path == ETL_PREFIX or path.startswith(ETL_PREFIX + "/")
    }
    assert etl == EXPECTED_ETL_ROUTES, (
        f"unexpected: {sorted(etl - EXPECTED_ETL_ROUTES)}; "
        f"missing: {sorted(EXPECTED_ETL_ROUTES - etl)}"
    )
