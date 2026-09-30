"""``GET /api/v1/edge/bootstrap`` is deprecated in favour of the ruleset route (#226).

The route keeps its shape and behaviour; its OpenAPI operation carries
``"deprecated": true`` and a description that names what replaces it. The
stable snapshot already fails if the operation changes; this pins the
direction, so a regenerated snapshot that dropped the flag or the pointer to
``GET /api/v1/sdk/ruleset`` still fails here.
"""

from __future__ import annotations

import pytest

from backend.app.main import app

pytestmark = [pytest.mark.smoke]

BOOTSTRAP = "/api/v1/edge/bootstrap"
OPENFEATURE_FLAGS = "/api/v1/openfeature/flags"
RULESET = "/api/v1/sdk/ruleset"


def _operation(path: str) -> dict:
    return app.openapi()["paths"][path]["get"]


def test_the_ruleset_route_it_points_to_exists():
    """Positive control: the replacement named below is a real operation."""
    assert "get" in app.openapi()["paths"][RULESET]


@pytest.mark.parametrize("path", [BOOTSTRAP, OPENFEATURE_FLAGS])
def test_the_listing_is_deprecated_and_names_the_ruleset_route(path):
    operation = _operation(path)
    assert operation.get("deprecated") is True
    assert f"GET {RULESET}" in operation["description"]
    assert "sdk:ruleset" in operation["description"]
    assert "(deprecated)" in operation["summary"]


def test_the_bootstrap_description_says_it_is_limited_to_the_key_owner():
    description = _operation(BOOTSTRAP)["description"]
    assert "owned by the user who created the API key" in description
    assert "accessible to this API key" not in description
