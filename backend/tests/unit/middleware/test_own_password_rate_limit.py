"""The own-password route is rate limited like the other password routes (#344).

Limits are keyed on the exact request path, so an entry in
``RATE_LIMIT_CONFIG`` that does not match the route's real path limits
nothing. The path here comes from the application's own router
(``app.url_path_for``), not from a copy of the string in the config, and the
real ``RateLimitMiddleware`` is driven with ``enabled=True`` (the application
turns it off under test).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.main import app as real_app
from backend.app.middleware.rate_limiter import (
    RateLimitMiddleware,
    SlidingWindowRateLimiter,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

LIMIT = 5


@pytest.fixture
def path() -> str:
    return real_app.url_path_for("change_own_password")


def _limited_app(path: str):
    routes = FastAPI()

    @routes.post(path, status_code=204)
    async def change():
        return None

    middleware = RateLimitMiddleware(routes, enabled=True)
    # In memory: a shared Redis would carry counts between runs.
    middleware._limiter = SlidingWindowRateLimiter()
    return middleware


def test_the_route_is_where_the_limit_is(path):
    assert path == "/api/v1/users/me/password"


def test_the_sixth_attempt_in_a_minute_is_429(path):
    client = TestClient(_limited_app(path))
    statuses = [client.post(path).status_code for _ in range(LIMIT + 1)]
    assert statuses == [204] * LIMIT + [429], statuses
