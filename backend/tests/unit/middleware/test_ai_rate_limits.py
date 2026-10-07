"""AI design and results interpretation have their own rate limits.

``POST /api/v1/ai/design`` allows 10 requests a minute per client address.
``POST /api/v1/ai/interpret/{experiment_id}`` allows 10 a minute per client
address for every experiment id together: the route does not use the id, so
the counter is keyed on the ``/api/v1/ai/interpret/`` prefix, as the export
routes' counter is keyed on ``/api/v1/export/``.

The paths come from the application's own router (``app.url_path_for``), and
the requests go through the real routes with the real ``RateLimitMiddleware``
in front (``enabled=True``; the application turns it off under test), counting
in memory. ``ANTHROPIC_API_KEY`` is unset, so the routes answer with their
templates and call nothing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app as real_app
from backend.app.middleware.rate_limiter import (
    DEFAULT_RATE_LIMIT,
    DEFAULT_SDK_RATE_LIMIT_PER_MINUTE,
    EXPORT_PATH_PREFIX,
    EXPORT_RATE_LIMIT,
    RATE_LIMIT_CONFIG,
    RateLimitMiddleware,
    SlidingWindowRateLimiter,
    rate_limit_key,
    resolve_rate_limit,
)
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.unit, pytest.mark.regression]

DESIGN = "/api/v1/ai/design"
INTERPRET = "/api/v1/ai/interpret/"
LIMIT = 10

DESIGN_BODY = {
    "description": "Test a shorter checkout form to raise conversion",
    "experiment_type": "checkout",
}


def _interpret_body(experiment_id: str) -> dict:
    return {
        "experiment_id": experiment_id,
        "variant_name": "treatment",
        "p_value": 0.01,
        "relative_improvement_pct": 4.2,
    }


@pytest.fixture
def client(monkeypatch):
    """The real application behind an enabled limiter, as a VIEWER."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "viewer"
    user.email = "viewer@example.com"
    user.role = UserRole.VIEWER
    user.is_active = True
    user.is_superuser = False
    user.hashed_password = "hashed"
    previous = dict(real_app.dependency_overrides)
    real_app.dependency_overrides[deps.get_current_active_user] = lambda: user
    limited = RateLimitMiddleware(real_app, enabled=True)
    # In memory: a shared Redis would carry counts between runs.
    limited._limiter = SlidingWindowRateLimiter()
    try:
        yield TestClient(limited)
    finally:
        real_app.dependency_overrides.clear()
        real_app.dependency_overrides.update(previous)


def test_the_routes_are_where_the_limits_are():
    assert real_app.url_path_for("suggest_design") == DESIGN
    assert (
        real_app.url_path_for("interpret_results", experiment_id="exp-1")
        == f"{INTERPRET}exp-1"
    )


def test_design_has_its_own_limit_of_ten_a_minute():
    assert RATE_LIMIT_CONFIG.get(DESIGN) == (LIMIT, 60)
    assert resolve_rate_limit(DESIGN) == (LIMIT, 60)
    assert rate_limit_key("10.0.0.1", DESIGN) == f"10.0.0.1:{DESIGN}"


@pytest.mark.parametrize(
    "experiment_id", ["exp-1", "3f2b8c1e-9d4a-4e6f-8a7b-1c2d3e4f5a6b", "x"]
)
def test_every_interpretation_path_has_the_interpretation_limit(experiment_id):
    assert resolve_rate_limit(f"{INTERPRET}{experiment_id}") == (LIMIT, 60)


def test_two_interpretation_ids_share_one_counter():
    first = rate_limit_key("10.0.0.1", f"{INTERPRET}exp-1")
    second = rate_limit_key("10.0.0.1", f"{INTERPRET}exp-2")
    assert first == second == f"10.0.0.1:{INTERPRET}"
    # Per client address, and apart from the design and export counters.
    assert rate_limit_key("10.0.0.2", f"{INTERPRET}exp-1") != first
    assert rate_limit_key("10.0.0.1", DESIGN) != first
    assert rate_limit_key("10.0.0.1", f"{EXPORT_PATH_PREFIX}experiments") != first


def test_the_neighbouring_paths_keep_their_limits():
    for path in (
        "/api/v1/ai/sample-size",
        "/api/v1/ai/templates",
        "/api/v1/ai/templates/checkout",
    ):
        assert resolve_rate_limit(path) == DEFAULT_RATE_LIMIT, path
        assert rate_limit_key("10.0.0.1", path) == f"10.0.0.1:{path}", path
    assert resolve_rate_limit(f"{EXPORT_PATH_PREFIX}experiments") == EXPORT_RATE_LIMIT
    assert resolve_rate_limit("/api/v1/tracking/track") == (
        DEFAULT_SDK_RATE_LIMIT_PER_MINUTE,
        60,
    )


def test_the_eleventh_design_request_in_a_minute_is_429(client):
    for i in range(LIMIT):
        response = client.post(DESIGN, json=DESIGN_BODY)
        assert response.status_code == 200, (i, response.text)
        assert response.headers["X-RateLimit-Limit"] == str(LIMIT)
        assert response.headers["X-RateLimit-Remaining"] == str(LIMIT - i - 1)

    refused = client.post(DESIGN, json=DESIGN_BODY)
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "60"
    assert refused.headers["X-RateLimit-Limit"] == str(LIMIT)
    assert refused.headers["X-RateLimit-Remaining"] == "0"

    # Interpretation and the other AI routes keep their own budgets.
    assert (
        client.post(f"{INTERPRET}exp-1", json=_interpret_body("exp-1")).status_code
        == 200
    )
    assert client.get("/api/v1/ai/templates").status_code == 200


def test_interpretations_share_ten_a_minute_whatever_the_id(client):
    for i in range(LIMIT):
        experiment_id = f"exp-{i}"
        response = client.post(
            f"{INTERPRET}{experiment_id}", json=_interpret_body(experiment_id)
        )
        assert response.status_code == 200, (i, response.text)
        assert response.headers["X-RateLimit-Limit"] == str(LIMIT)
        assert response.headers["X-RateLimit-Remaining"] == str(LIMIT - i - 1)

    # The eleventh is refused, for an id not used above as for one that was.
    for experiment_id in ("exp-new", "exp-0"):
        refused = client.post(
            f"{INTERPRET}{experiment_id}", json=_interpret_body(experiment_id)
        )
        assert refused.status_code == 429, experiment_id
        assert refused.headers["Retry-After"] == "60"
        assert refused.headers["X-RateLimit-Remaining"] == "0"

    # Design keeps its own budget.
    assert client.post(DESIGN, json=DESIGN_BODY).status_code == 200
