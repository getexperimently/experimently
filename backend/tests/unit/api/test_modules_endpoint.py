"""
API tests for ``GET /api/v1/modules`` (``backend/app/api/v1/endpoints/modules.py``).

The endpoint is public, so these tests pin two things hard: the response shape
the dashboard chrome relies on -- exactly three keys -- and that the response
never says more than the profile, the module names and the version.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app import modules_loader
from backend.app.core import hooks
from backend.app.core.config import settings
from backend.app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestModulesEndpointShape:
    def test_endpoint_is_unauthenticated(self, client):
        """No Authorization header, no 401 -- the chrome asks before login."""
        assert client.get("/api/v1/modules").status_code == 200

    def test_exactly_three_keys(self, client):
        body = client.get("/api/v1/modules").json()
        assert set(body) == {"profile", "modules", "version"}
        assert body["profile"] in ("core", "full")
        assert isinstance(body["modules"], list)
        assert body["version"] == settings.VERSION

    def test_profile_matches_the_loader(self, client):
        body = client.get("/api/v1/modules").json()
        if modules_loader.load_modules():
            assert body["profile"] == "full"
            assert body["modules"] == list(hooks.installed_modules())
        else:
            assert body["profile"] == "core"
            assert body["modules"] == []


class TestModulesEndpointCore:
    def test_the_core_profile_reports_no_modules(self, client):
        with patch(
            "backend.app.api.v1.endpoints.modules.modules_active", return_value=False
        ):
            body = client.get("/api/v1/modules").json()

        assert body == {"profile": "core", "modules": [], "version": settings.VERSION}


class TestTheEndpointNeverRegisters:
    """It called ``load_modules()``, which re-runs the registration when the
    process loaded for a schema (``with_routers=False``): an unauthenticated
    GET could make the event loop import eleven endpoint modules (~3.5 s),
    holding the loader's lock, once per process -- and, before the loader
    stopped downgrading a failed second run, drop the audit signer with it.
    """

    @pytest.mark.regression
    def test_a_request_runs_no_registration(self, client):
        with patch.object(modules_loader, "_find_register") as find:
            body = client.get("/api/v1/modules").json()

        assert find.call_count == 0
        assert body["profile"] in ("core", "full")

    @pytest.mark.regression
    def test_a_schema_only_process_still_reports_the_full_profile(self, client):
        """`modules_active()` reads the cache, so it says "full" for a process
        that registered without the routers -- without importing them."""
        with patch.object(modules_loader, "_state", True):
            with patch.object(modules_loader, "_routers", False):
                with patch.object(modules_loader, "_find_register") as find:
                    body = client.get("/api/v1/modules").json()

        assert body["profile"] == "full"
        assert find.call_count == 0


class TestADegradedProfileIsNotReportedAsFull:
    """Registering the module routers and mounting them are two steps.

    When ``mount_module_routers`` fails, the registration itself has already
    succeeded -- ``register_modules`` is its last line -- so ``modules_active()``
    is True and ``hooks.installed_modules()`` still holds all ten names, while
    not one module route is mounted.  This endpoint answered
    ``{"profile": "full", "modules": [ten]}`` to that, and the dashboard then
    rendered every module page against a 404: exactly the state its ``error``
    path exists to avoid.
    """

    @pytest.mark.regression
    def test_a_mount_failure_reads_as_the_core_profile(self, client):
        failure = "mounting the modules' routers raised AttributeError: x"
        with patch(
            "backend.app.api.v1.endpoints.modules.modules_active", return_value=True
        ):
            with patch(
                "backend.app.api.v1.endpoints.modules.modules_failure",
                return_value=failure,
            ):
                body = client.get("/api/v1/modules").json()

        assert body == {"profile": "core", "modules": [], "version": settings.VERSION}

    @pytest.mark.regression
    def test_a_healthy_full_profile_is_unaffected(self, client):
        """The failure read must not cost a working deployment its modules."""
        with patch(
            "backend.app.api.v1.endpoints.modules.modules_active", return_value=True
        ):
            with patch(
                "backend.app.api.v1.endpoints.modules.modules_failure",
                return_value=None,
            ):
                body = client.get("/api/v1/modules").json()

        assert body["profile"] == "full"
        assert body["modules"] == list(hooks.installed_modules())


@pytest.mark.modules
class TestModulesEndpointFull:
    def test_the_full_profile_lists_every_known_module(self, client):
        body = client.get("/api/v1/modules").json()

        assert body["profile"] == "full"
        assert body["modules"] == list(hooks.KNOWN_MODULES)
        assert set(body) == {"profile", "modules", "version"}

    def test_module_names_are_the_known_names_in_order(self, client):
        """The dashboard indexes ``MODULES`` by these strings; order and
        spelling are part of the contract (see test_module_names.py)."""
        names = client.get("/api/v1/modules").json()["modules"]
        assert names == [name for name in hooks.KNOWN_MODULES if name in names]
        assert set(names) <= set(hooks.KNOWN_MODULES)
