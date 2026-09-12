"""`backend/app/ee_loader.py` — how the Enterprise edition gets into the process.

The loader's one promise is that the Community API starts whatever the state
of the Enterprise code. These tests pin that, plus the transitional fallback
that stands in for `ee.register(hooks)` while the Enterprise modules still
live in this tree.
"""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest

from backend.app import ee_loader
from backend.app.core import hooks


def _effective_routes(router):
    """``(path, dependencies)`` for every route, through FastAPI >= 0.141's lazy
    ``_IncludedRouter`` entries (see ``test_wiring.py::_iter_http_routes``)."""
    from fastapi.routing import APIRoute

    for route in router.routes:
        if isinstance(route, APIRoute):
            yield route.path, route.dependencies
            continue
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            continue
        contexts = contexts() if callable(contexts) else contexts
        for ctx in contexts:
            yield ctx.path, getattr(ctx, "dependencies", []) or []


@pytest.fixture
def fresh_hooks():
    """Run each test against empty registries, then put the real ones back."""
    saved_signer = hooks.audit_signer
    with hooks._lock:
        saved = (
            list(hooks._router_registrars),
            list(hooks._model_modules),
            list(hooks._tags_metadata),
            dict(hooks._capabilities),
        )
    hooks.reset()
    ee_loader.reset()
    try:
        yield
    finally:
        hooks.reset()
        with hooks._lock:
            hooks._router_registrars.extend(saved[0])
            hooks._model_modules.extend(saved[1])
            hooks._tags_metadata.extend(saved[2])
            hooks._capabilities.update(saved[3])
        hooks.set_audit_signer(saved_signer)
        ee_loader.reset()


@pytest.mark.enterprise
class TestTransitionalFallback:
    def test_the_in_tree_registration_is_used_when_ee_has_no_register(
        self, fresh_hooks
    ):
        """`ee/` holds only a LICENSE today, so it imports as a namespace
        package without `register`; the loader falls back to the module that
        has the shape ee/backend/app/register.py will have."""
        assert ee_loader.load_enterprise(force=True) is True

        assert type(hooks.audit_signer).__name__ == "AuditSigningService"
        assert len(hooks.import_registered_models()) == 7
        assert set(hooks.capability_names()) == {
            "compliance.export",
            "compliance.report",
            "counters.service",
            "split_url.preview",
            "split_url.routing",
        }
        names = {tag["name"] for tag in hooks.extra_tags_metadata()}
        assert {"RBAC", "Workspaces", "HIPAA", "SSO", "Integrations"} <= names

    @pytest.mark.regression
    def test_every_enterprise_router_is_mounted_behind_its_feature(self, fresh_hooks):
        """No Enterprise route without a `require_feature` dependency: that
        is the gap the dashboard's gating exposed (it hid navigation the API
        still served)."""
        from fastapi import APIRouter

        ee_loader.load_enterprise(force=True)
        router = APIRouter()
        assert hooks.apply_routers(router) == 1

        expected = {
            "/rbac": "rbac",
            "/counters": "counters",
            "/etl": "etl",
            "/warehouse": "warehouse",
            "/integrations": "integrations",
            "/auth/sso": "sso",
            "/workspaces": "workspaces",
            "/hipaa": "hipaa",
        }
        seen = {}
        for path, dependencies in _effective_routes(router):
            prefix = next((p for p in expected if path.startswith(p)), None)
            if prefix is None:
                continue
            gate_names = {
                d.dependency.__name__
                for d in dependencies
                if getattr(d, "dependency", None) is not None
            }
            assert f"require_feature_{expected[prefix]}" in gate_names, (
                f"{path} is mounted without require_feature({expected[prefix]!r})"
            )
            seen[prefix] = True
        assert set(seen) == set(expected), (
            f"routers not mounted: {set(expected) - set(seen)}"
        )

    def test_loading_is_idempotent(self, fresh_hooks):
        assert ee_loader.load_enterprise(force=True) is True
        assert ee_loader.load_enterprise() is True
        assert ee_loader.load_enterprise(force=True) is True
        # Registries de-duplicate: one registrar, seven modules, no repeats.
        with hooks._lock:
            assert len(hooks._router_registrars) == 1
            assert len(hooks._model_modules) == 7


class TestNeverRaises:
    @pytest.mark.regression
    def test_a_register_that_blows_up_leaves_community_running(self, fresh_hooks):
        broken = types.SimpleNamespace(
            register=lambda hooks_: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with patch.object(
            ee_loader, "_find_register", return_value=(broken.register, "x")
        ):
            assert ee_loader.load_enterprise(force=True) is False
        assert type(hooks.audit_signer).__name__ == "NullAuditSigner"
        assert hooks.capability_names() == ()

    @pytest.mark.regression
    def test_a_model_module_that_fails_to_import_rolls_everything_back(
        self, fresh_hooks
    ):
        """A router registered before a model module failed would serve routes
        against tables that do not exist. The loader wipes the half-applied
        registration and reports Community."""

        def half_register(h):
            h.register_router(lambda router: None)
            h.register_capability("split_url.routing", lambda: None)
            h.register_model_module("backend.app.models.no_such_module")

        with patch.object(
            ee_loader, "_find_register", return_value=(half_register, "x")
        ):
            assert ee_loader.load_enterprise(force=True) is False

        with hooks._lock:
            assert hooks._router_registrars == []
            assert hooks._model_modules == []
        assert hooks.capability_names() == ()

    @pytest.mark.regression
    def test_an_enterprise_package_that_fails_to_import_leaves_community_running(
        self, fresh_hooks, monkeypatch
    ):
        """`_find_register` caught only ImportError around `import ee`, so a
        SyntaxError or a RuntimeError from a missing optional dependency
        propagated out of `load_enterprise()` and killed `import
        backend.app.main`. Reproduced with a meta-path finder that raises."""
        import sys

        class Exploding:
            def find_spec(self, name, path=None, target=None):
                if name == ee_loader.EE_PACKAGE:
                    raise RuntimeError("optional dependency missing")
                return

        monkeypatch.setattr(sys, "meta_path", [Exploding(), *sys.meta_path])
        monkeypatch.delitem(sys.modules, ee_loader.EE_PACKAGE, raising=False)
        # Nothing propagated -- and a package that is present but broken is
        # reported as such, not replaced by the in-tree code.
        assert ee_loader.load_enterprise(force=True) is False
        assert ee_loader.enterprise_failure() is not None

    @pytest.mark.regression
    def test_a_nested_missing_module_is_reported_not_mistaken_for_community(
        self, fresh_hooks, monkeypatch
    ):
        """`ModuleNotFoundError` for a module *inside* ee is a broken install,
        logged at ERROR with the module named -- not "no ee package" at DEBUG.
        (`caplog` is unusable in the unit tree: its conftest replaces
        `logging.getLogger`; the module logger is patched instead.)"""
        import sys

        real_import = ee_loader.importlib.import_module

        def bad_import(name, package=None):
            if name == ee_loader.EE_PACKAGE:
                raise ModuleNotFoundError(
                    "No module named 'snowflake'", name="snowflake"
                )
            return real_import(name, package)

        monkeypatch.setattr(ee_loader.importlib, "import_module", bad_import)
        monkeypatch.delitem(sys.modules, ee_loader.EE_PACKAGE, raising=False)
        with patch.object(ee_loader, "logger") as log:
            ee_loader._find_register()
        assert log.exception.called
        assert "snowflake" in str(log.exception.call_args)
        assert not log.debug.called

    @pytest.mark.regression
    def test_a_broken_real_package_never_falls_through_to_the_in_tree_code(
        self, fresh_hooks, monkeypatch
    ):
        """When `import ee` raises, the loader used to log the error and then
        load the transitional module anyway -- two contradictory log lines,
        and the in-tree code silently serving in place of the package the
        operator installed."""
        import sys

        real_import = ee_loader.importlib.import_module

        def bad_import(name, package=None):
            if name == ee_loader.EE_PACKAGE:
                raise RuntimeError("SyntaxError in disguise")
            return real_import(name, package)

        monkeypatch.setattr(ee_loader.importlib, "import_module", bad_import)
        monkeypatch.delitem(sys.modules, ee_loader.EE_PACKAGE, raising=False)
        assert ee_loader.load_enterprise(force=True) is False
        assert hooks.capability_names() == ()
        assert "could not be imported" in (ee_loader.enterprise_failure() or "")

    @pytest.mark.regression
    def test_schema_builders_refuse_a_half_registered_edition(self, fresh_hooks):
        """alembic env.py, bootstrap and conftest go through
        require_enterprise_or_absent(): with the registration broken the
        metadata would hold only the Community tables, and autogenerate would
        propose dropping every Enterprise table."""

        def broken(h):
            h.register_model_module("backend.app.models.workspace")
            raise RuntimeError("boom")

        with patch.object(ee_loader, "_find_register", return_value=(broken, "x")):
            with pytest.raises(RuntimeError) as excinfo:
                ee_loader.require_enterprise_or_absent()
        assert "refusing to build a schema" in str(excinfo.value)
        assert "boom" in str(excinfo.value)

    def test_schema_builders_accept_a_community_tree(self, fresh_hooks):
        with patch.object(ee_loader, "_find_register", return_value=(None, None)):
            assert ee_loader.require_enterprise_or_absent() is False

    def test_the_entry_point_may_live_in_the_application_module(
        self, fresh_hooks, monkeypatch
    ):
        """#89 places register() in ee/backend/app/register.py; the loader must
        find it there when the top-level package does not re-export it."""
        import sys
        import types

        top = types.ModuleType(ee_loader.EE_PACKAGE)
        top.__path__ = []  # a package, but with no register attribute
        app_module = types.ModuleType(f"{ee_loader.EE_PACKAGE}.backend.app.register")
        seen = []
        app_module.register = lambda h: seen.append(h)
        real_import = ee_loader.importlib.import_module

        def fake_import(name, package=None):
            if name == ee_loader.EE_PACKAGE:
                return top
            if name == f"{ee_loader.EE_PACKAGE}.backend.app.register":
                return app_module
            return real_import(name, package)

        monkeypatch.setattr(ee_loader.importlib, "import_module", fake_import)
        register, origin = ee_loader._find_register()
        assert origin == f"{ee_loader.EE_PACKAGE}.backend.app.register"
        register(hooks)
        assert seen == [hooks]

    def test_nothing_to_load_is_community(self, fresh_hooks):
        with patch.object(ee_loader, "_find_register", return_value=(None, None)):
            assert ee_loader.load_enterprise(force=True) is False
        assert hooks.capability_names() == ()


class TestCrossEditionForeignKeys:
    """The workspace foreign keys exist exactly when the Enterprise models do."""

    @pytest.mark.enterprise
    @pytest.mark.regression
    def test_enterprise_metadata_carries_the_workspace_foreign_keys(self):
        """Migration a7b8c9d0e1f2 dropped them from the Community models and
        nothing re-added them for Enterprise, so a fresh Enterprise bootstrap
        lost referential integrity and ON DELETE SET NULL. The Enterprise
        model module attaches them (use_alter) whenever it is loaded."""
        from sqlalchemy import ForeignKeyConstraint

        from backend.app.models.experiment import Experiment
        from backend.app.models.feature_flag import FeatureFlag

        ee_loader.load_enterprise()
        for model, name in (
            (Experiment, "experiments_workspace_id_fkey"),
            (FeatureFlag, "feature_flags_workspace_id_fkey"),
        ):
            fks = [
                c
                for c in model.__table__.constraints
                if isinstance(c, ForeignKeyConstraint) and c.name == name
            ]
            assert len(fks) == 1, f"{name} attached {len(fks)} times"
            assert fks[0].ondelete == "SET NULL"
            assert fks[0].use_alter is True
            assert list(fks[0].column_keys) == ["workspace_id"]

    def test_the_community_registry_has_no_such_constraint(self):
        """Checked in a fresh interpreter: this process has the Enterprise
        models loaded, so it cannot answer the Community question itself."""
        from backend.tests.smoke.test_core_model_registry import (
            _run_in_fresh_interpreter,
        )

        result = _run_in_fresh_interpreter(
            """
            import json
            from backend.app.models import register_core_models
            from backend.app.models.experiment import Experiment
            register_core_models()
            names = sorted(c.name for c in Experiment.__table__.constraints if c.name)
            print(json.dumps({"constraints": names}))
            """
        )
        assert "experiments_workspace_id_fkey" not in result["constraints"]
