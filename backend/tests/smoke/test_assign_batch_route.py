"""``POST /api/v1/tracking/assign/batch`` (#441): how it is served and published.

* The handler is a plain ``def``: FastAPI runs it in the thread pool, so a
  batch of 1,000 users does not hold the event loop. Found through the route
  walk, not by importing the function, so it is the function actually routed.
* It is in the committed stable snapshot, marked beta. A route missing from
  ``docs/api/openapi-v1.stable.json`` is only a warning in
  ``test_openapi_snapshot.py``, so the operation is pinned here by name.
"""

from __future__ import annotations

import inspect
import json

import pytest

from backend.app.main import app
from backend.tests.smoke.modules_manifest import REPO_ROOT

pytestmark = [pytest.mark.smoke]

PATH = "/api/v1/tracking/assign/batch"
SNAPSHOT = REPO_ROOT / "docs" / "api" / "openapi-v1.stable.json"


def _routed(path: str, method: str):
    found = []
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            continue
        for ctx in contexts() if callable(contexts) else contexts:
            if ctx.path == path and method in (getattr(ctx, "methods", None) or ()):
                found.append(ctx)
    return found


def test_the_batch_route_is_a_plain_def():
    routed = _routed(PATH, "POST")
    assert len(routed) == 1, routed
    assert not inspect.iscoroutinefunction(routed[0].endpoint)


def test_the_walk_can_tell_async_from_sync():
    """Guard the guard: the single assign route is ``async def``."""
    routed = _routed("/api/v1/tracking/assign", "POST")
    assert len(routed) == 1, routed
    assert inspect.iscoroutinefunction(routed[0].endpoint)


def test_the_batch_route_is_in_the_stable_snapshot_as_beta():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    operation = snapshot["paths"][PATH]["post"]
    assert operation["x-stability"] == "beta"
    assert set(operation["responses"]) >= {"200", "401", "403", "404", "409", "422"}
    request = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request["$ref"].endswith("/AssignmentBatchRequest")
    users = snapshot["components"]["schemas"]["AssignmentBatchRequest"]["properties"][
        "users"
    ]
    assert (users["minItems"], users["maxItems"]) == (1, 1000)
