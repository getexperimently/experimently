"""
Infrastructure wiring smoke tests.

These tests catch the class of bugs that slipped through the existing suite
because authentication is mocked at the dependency level in unit/integration tests.
They use FastAPI's TestClient with NO mocks — only the real app startup, real
middleware, and real SQLAlchemy models.

Run these after any:
  - New migration / model change
  - Dependency (deps.py) change
  - Middleware / CORS config change
  - Auth flow change

Usage:
    source venv/bin/activate
    export APP_ENV=test TESTING=true
    python -m pytest backend/tests/smoke/test_wiring.py -v
"""

import inspect

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App fixture — real app, no mocks
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """Import and return the real FastAPI app (triggers full startup)."""
    from backend.app.main import app as _app

    return _app


@pytest.fixture(scope="module")
def client(app):
    """TestClient wrapping the real app — sends real HTTP through middleware."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ===========================================================================
# 1. Database schema — column existence
# ===========================================================================


class TestDatabaseColumns:
    """
    Verify that critical columns declared in SQLAlchemy models actually exist
    in the mapped table metadata.  Catches migration gaps where the model was
    updated but the migration was not applied (or vice-versa).
    """

    def test_user_model_has_role_column(self):
        from backend.app.models.user import User

        col_names = {c.key for c in User.__table__.columns}
        assert "role" in col_names, (
            "users.role column missing — run the Alembic migration that adds it"
        )

    def test_user_model_has_external_id_column(self):
        from backend.app.models.user import User

        col_names = {c.key for c in User.__table__.columns}
        assert "external_id" in col_names, (
            "users.external_id column missing — required for SSO/Cognito JIT provisioning"
        )

    def test_user_model_has_hashed_password_column(self):
        from backend.app.models.user import User

        col_names = {c.key for c in User.__table__.columns}
        assert "hashed_password" in col_names

    def test_user_model_has_is_active_column(self):
        from backend.app.models.user import User

        col_names = {c.key for c in User.__table__.columns}
        assert "is_active" in col_names

    def test_user_model_has_is_superuser_column(self):
        from backend.app.models.user import User

        col_names = {c.key for c in User.__table__.columns}
        assert "is_superuser" in col_names

    def test_user_role_column_has_correct_enum_values(self):
        from backend.app.models.user import User, UserRole

        role_col = User.__table__.columns["role"]
        # The column should be an Enum type
        assert hasattr(role_col.type, "enums") or str(
            role_col.type.__class__.__name__
        ) in ("Enum", "VARCHAR")
        # UserRole enum must include all four roles
        assert set(UserRole) == {
            UserRole.ADMIN,
            UserRole.DEVELOPER,
            UserRole.ANALYST,
            UserRole.VIEWER,
        }

    def test_experiment_model_has_status_column(self):
        from backend.app.models.experiment import Experiment

        col_names = {c.key for c in Experiment.__table__.columns}
        assert "status" in col_names

    def test_feature_flag_model_has_status_column(self):
        from backend.app.models.feature_flag import FeatureFlag

        col_names = {c.key for c in FeatureFlag.__table__.columns}
        # FeatureFlag uses 'status' (ACTIVE/INACTIVE) rather than a boolean 'enabled'
        assert "status" in col_names, (
            "feature_flags.status column missing — FeatureFlag model may have changed"
        )

    def test_llm_experiment_model_has_required_columns(self):
        """EP-046 LLM experiments model wiring check."""
        try:
            from backend.app.models.llm_experiment import LLMExperiment

            col_names = {c.key for c in LLMExperiment.__table__.columns}
            for required in ("status", "task_type", "evaluation_metric"):
                assert required in col_names, (
                    f"llm_experiments.{required} column missing"
                )
        except ImportError:
            pytest.skip("LLMExperiment model not present (EP-046 not deployed)")

    def test_sso_config_model_has_required_columns(self):
        """EP-037 SSO config model wiring check."""
        try:
            from backend.app.models.sso_config import SSOConfig

            col_names = {c.key for c in SSOConfig.__table__.columns}
            for required in ("provider_type", "entity_id", "sso_url"):
                assert required in col_names, f"sso_configs.{required} column missing"
        except ImportError:
            pytest.skip("SSOConfig model not present (EP-037 not deployed)")


# ===========================================================================
# 2. CORS headers — middleware wiring
# ===========================================================================


class TestCORSWiring:
    """
    Verify that CORSMiddleware is actually mounted and returns correct
    Access-Control-Allow-Origin for the expected frontend origins.

    TestClient does NOT send an Origin header by default, so these tests
    explicitly set it — something the unit/integration suite never does.
    """

    EXPECTED_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]

    def test_cors_preflight_localhost_3000(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # 200 or 204 — CORS preflight should not 403/404/500
        assert resp.status_code in (200, 204), (
            f"CORS preflight for localhost:3000 returned {resp.status_code}"
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao in ("http://localhost:3000", "*"), (
            f"Expected ACAO header for localhost:3000, got: {acao!r}"
        )

    def test_cors_preflight_localhost_3001(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3001",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 204), (
            f"CORS preflight for localhost:3001 returned {resp.status_code}"
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao in ("http://localhost:3001", "*"), (
            f"Expected ACAO header for localhost:3001, got: {acao!r}"
        )

    def test_cors_get_request_includes_acao_header(self, client):
        resp = client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
        # 200 when DB is up, 503 when DB is down — both are valid for CORS testing
        assert resp.status_code in (200, 503), (
            f"Unexpected status {resp.status_code} from /health"
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao, (
            "access-control-allow-origin header missing on GET from allowed origin"
        )

    def test_unknown_origin_does_not_get_acao(self, client):
        resp = client.get(
            "/health",
            headers={"Origin": "http://evil.example.com"},
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao not in ("http://evil.example.com", "*"), (
            "Unknown origin was granted CORS access — check allow_origins list"
        )

    def test_cors_allows_authorization_header(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        acah = resp.headers.get("access-control-allow-headers", "")
        assert "authorization" in acah.lower() or acah == "*", (
            "Authorization header not in access-control-allow-headers"
        )

    def test_cors_allows_x_api_key_header(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        acah = resp.headers.get("access-control-allow-headers", "")
        assert "x-api-key" in acah.lower() or acah == "*", (
            "X-API-Key header not in access-control-allow-headers"
        )


# ===========================================================================
# 3. OAuth2 / auth wiring — no mocks
# ===========================================================================


class TestAuthWiring:
    """
    Verify auth wiring WITHOUT mocking deps.get_current_user.

    These tests send real requests through the real dependency chain and
    assert the HTTP-level outcome:

    - bypass off  -> unauthenticated / bad-token requests are rejected with 401
                     (never 500, never silently served)
    - bypass on   -> the request is served as the dev-admin superuser (200)
    - the bypass is ignored outside development/test even when enabled
    """

    @pytest.fixture
    def settings(self):
        from backend.app.core.config import settings as _settings

        return _settings

    @pytest.fixture
    def db_override(self, app, db_session):
        """Route deps.get_db at the per-process test database for one test."""
        from backend.app.api import deps

        def _override():
            yield db_session

        app.dependency_overrides[deps.get_db] = _override
        try:
            yield db_session
        finally:
            app.dependency_overrides.pop(deps.get_db, None)

    def test_unauthenticated_request_returns_401_when_bypass_off(
        self, client, settings, monkeypatch
    ):
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
        resp = client.get("/api/v1/experiments/")
        assert resp.status_code == 401, resp.text
        assert resp.json()["detail"]
        assert resp.headers.get("www-authenticate", "").lower().startswith("bearer")

    def test_invalid_bearer_token_returns_401_when_bypass_off(
        self, client, settings, monkeypatch
    ):
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
        resp = client.get(
            "/api/v1/experiments/",
            headers={"Authorization": "Bearer this.is.not.a.valid.jwt"},
        )
        assert resp.status_code == 401, resp.text

    def test_wrong_auth_scheme_returns_401_when_bypass_off(
        self, client, settings, monkeypatch
    ):
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
        resp = client.get(
            "/api/v1/experiments/",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401, resp.text

    def test_bypass_on_serves_request_as_dev_admin(
        self, client, settings, monkeypatch, db_override
    ):
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", True)
        assert settings.ENVIRONMENT == "test"
        resp = client.get("/api/v1/experiments/")
        assert resp.status_code == 200, resp.text

        from backend.app.api import deps
        from backend.app.models.user import User

        dev_user = (
            db_override.query(User)
            .filter(User.username == deps.DEV_BYPASS_USERNAME)
            .first()
        )
        assert dev_user is not None and dev_user.is_superuser

    def test_bypass_is_ignored_outside_development_and_test(
        self, client, settings, monkeypatch
    ):
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", True)
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        resp = client.get("/api/v1/experiments/")
        assert resp.status_code == 401, resp.text

    def test_login_endpoint_is_mounted(self, client, settings, monkeypatch):
        """POST /auth/login exists (422 on an empty body; 404 would mean the router is missing)."""
        monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 422, resp.text

    def test_api_keys_router_is_mounted(self, client, settings, monkeypatch):
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
        resp = client.get("/api/v1/api-keys")
        assert resp.status_code == 401, resp.text

    def test_token_endpoint_returns_validation_error_not_500(self, client):
        """Empty token request → 422 validation, not 500. Auth router must be wired."""
        resp = client.post("/api/v1/auth/token", json={})
        assert resp.status_code in (400, 422), (
            f"Empty /auth/token body returned {resp.status_code}, expected 400/422. "
            "If 404, the auth router is not registered in api.py."
        )

    def test_oauth2_scheme_has_exactly_one_definition(self):
        """
        Catches the bug where a duplicate oauth2_scheme in deps.py
        overrides the auto_error=False setting from core/security.py.
        """
        import backend.app.api.deps as deps_module

        deps_source = inspect.getsource(deps_module)
        # Should NOT define a new OAuth2PasswordBearer — it should only import
        assert deps_source.count("OAuth2PasswordBearer(") == 0, (
            "deps.py defines its own OAuth2PasswordBearer — this overrides the "
            "auto_error=False setting in core/security.py. Remove the duplicate "
            "and use: from backend.app.core.security import oauth2_scheme"
        )

    def test_oauth2_scheme_never_auto_errors(self):
        """
        auto_error must be False so a missing token reaches get_current_user,
        which decides between the dev bypass and a 401.
        """
        from backend.app.core.security import oauth2_scheme

        assert callable(oauth2_scheme), "oauth2_scheme is not callable — wiring broken"
        assert oauth2_scheme.auto_error is False

    def test_health_endpoint_is_public(self, client):
        """/health must be reachable without auth (200 when DB up, 503 when DB down)."""
        resp = client.get("/health")
        assert resp.status_code in (200, 503), (
            f"/health returned {resp.status_code} — must be 200 (healthy) or 503 (DB down), "
            "never a 4xx auth error or 500 crash"
        )

    def test_docs_endpoint_is_accessible(self, client):
        """/api/v1/openapi.json must return the schema without auth."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "paths" in data, "OpenAPI schema missing 'paths' key"
        assert "info" in data, "OpenAPI schema missing 'info' key"


# ===========================================================================
# 4. Security headers — middleware wiring
# ===========================================================================


class TestSecurityHeaders:
    """
    Verify SecurityHeadersMiddleware is mounted and emitting the expected
    headers. These headers are set once in middleware — if middleware is
    accidentally removed, every response loses them silently.
    """

    EXPECTED_HEADERS = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
    }

    def test_security_headers_on_health(self, client):
        # SecurityHeadersMiddleware must inject headers regardless of upstream status
        resp = client.get("/health")
        assert resp.status_code in (200, 503), f"Unexpected status: {resp.status_code}"
        for header, expected_value in self.EXPECTED_HEADERS.items():
            actual = resp.headers.get(header, "")
            assert actual == expected_value, (
                f"Security header {header!r} = {actual!r}, expected {expected_value!r}. "
                "SecurityHeadersMiddleware may not be mounted."
            )

    def test_content_type_nosniff_on_api_response(self, client):
        resp = client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_on_api_response(self, client):
        resp = client.get("/health")
        assert resp.headers.get("x-frame-options") == "DENY"


# ===========================================================================
# 5. App startup — all routers register without import errors
# ===========================================================================


def _iter_http_routes(app):
    """Yield ``(path, methods)`` for every HTTP route the app serves.

    FastAPI >= 0.141 no longer flattens ``include_router`` calls into
    ``app.routes``; it keeps a lazy ``_IncludedRouter`` entry whose
    ``effective_route_contexts`` carry the fully prefixed paths. Older
    versions expose plain ``APIRoute`` objects, so both shapes are handled.
    """
    from fastapi.routing import APIRoute

    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route.path, route.methods
            continue
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            contexts = contexts() if callable(contexts) else contexts
            for ctx in contexts:
                yield ctx.path, getattr(ctx, "methods", None)
        elif hasattr(route, "path"):
            yield route.path, getattr(route, "methods", None)


class TestAppStartup:
    """
    Verify the app imports cleanly and all routers are mounted.
    Catches circular imports, missing modules, or bad router registrations
    that only surface at startup time.
    """

    def test_app_starts_without_exception(self, app):
        assert app is not None

    def test_all_expected_route_prefixes_exist(self, app):
        routes = {path for path, _ in _iter_http_routes(app)}
        expected_prefixes = [
            "/api/v1/experiments",
            "/api/v1/feature-flags",
            "/api/v1/auth",
            "/health",
        ]
        route_str = "\n".join(sorted(routes))
        for prefix in expected_prefixes:
            matching = [r for r in routes if r.startswith(prefix)]
            assert matching, (
                f"No routes found starting with {prefix!r}. "
                f"Router may not be registered.\nAll routes:\n{route_str}"
            )

    def test_openapi_schema_includes_llm_experiments(self, client):
        """Verify EP-046 LLM endpoints are wired into the schema."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        data = resp.json()
        paths = data.get("paths", {})
        llm_paths = [p for p in paths if "llm-experiments" in p]
        assert llm_paths, (
            "No /llm-experiments/* paths in OpenAPI schema — EP-046 router not registered"
        )

    def test_openapi_schema_includes_warehouse_connectors(self, client):
        """Verify warehouse routers (Databricks, ClickHouse, MySQL) are wired."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        data = resp.json()
        paths = data.get("paths", {})
        warehouse_paths = [p for p in paths if "/warehouse/" in p]
        assert warehouse_paths, (
            "No /warehouse/* paths in OpenAPI schema — warehouse routers not registered"
        )

    def test_openapi_schema_includes_power_calculator(self, client):
        """Verify EP-056 power calculator endpoints are wired."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        data = resp.json()
        paths = data.get("paths", {})
        power_paths = [p for p in paths if "/power/" in p]
        assert power_paths, (
            "No /power/* paths in OpenAPI schema — power calculator router not registered"
        )

    def test_openapi_schema_includes_workspaces(self, client):
        """Verify EP-057 workspace endpoints are wired into the schema."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        paths = resp.json().get("paths", {})
        assert any("/workspaces" in p for p in paths), (
            "Workspace router not registered — EP-057 endpoints missing from OpenAPI schema"
        )

    def test_settings_loads_without_exception(self):
        """Config must be importable without crashing."""
        from backend.app.core.config import settings

        assert settings.PROJECT_NAME
        assert settings.API_V1_STR.startswith("/api")

    def test_no_duplicate_route_paths(self, app):
        """
        Duplicate APIRoute registrations cause silent shadowing — first one wins.

        Note: FastAPI internally adds redirect routes (trailing-slash ↔ non-trailing-slash)
        as Starlette `Route` objects. We only check `APIRoute` instances to avoid
        flagging FastAPI's own redirect mechanism as duplicates.
        """
        from collections import Counter

        # Key on (path, frozenset(methods)) — same path with different HTTP verbs is normal
        route_keys = [
            (path, frozenset(methods or []))
            for path, methods in _iter_http_routes(app)
            if not any(c in path for c in ["{", "}"])
        ]
        counts = Counter(route_keys)
        duplicates = {
            f"{p} [{' '.join(sorted(m))}]": n for (p, m), n in counts.items() if n > 1
        }
        assert not duplicates, (
            "Duplicate (path + method) APIRoute registrations found:\n"
            + "\n".join(f"  {k}: registered {v}x" for k, v in duplicates.items())
            + "\nA router may be included twice in api.py — the first registration silently wins."
        )


# ===========================================================================
# 6. Service imports — critical services import without errors
# ===========================================================================


class TestServiceImports:
    """
    Verify that all critical services can be imported without errors.
    Catches missing dependencies, circular imports, or broken module structure
    that only surfaces at import time.
    """

    def test_bayesian_service_imports(self):
        from backend.app.services.bayesian_service import (
            BayesianService,
            compute_posterior,
        )

        assert BayesianService is not None

    def test_cuped_service_imports(self):
        from backend.app.services.cuped_service import CupedService

        assert CupedService is not None

    def test_sequential_testing_service_imports(self):
        from backend.app.services.sequential_testing_service import (
            SequentialTestingService,
        )

        assert SequentialTestingService is not None

    def test_bandit_service_imports(self):
        from backend.app.services.bandit_service import (
            UCB1,
            EpsilonGreedy,
            ThompsonSampling,
        )

        assert ThompsonSampling is not None
        assert UCB1 is not None
        assert EpsilonGreedy is not None

    def test_llm_experiment_service_imports(self):
        from backend.app.services.llm_experiment_service import LLMExperimentService

        assert LLMExperimentService is not None

    def test_llm_analytics_service_imports(self):
        from backend.app.services.llm_analytics_service import (
            LLMEvaluationAnalyticsService,
        )

        assert LLMEvaluationAnalyticsService is not None

    def test_llm_proxy_service_imports(self):
        from backend.app.services.llm_proxy_service import (
            LLMProxyService,
            estimate_cost,
        )

        assert LLMProxyService is not None

    def test_workspace_service_imports(self):
        from backend.app.services.workspace_service import WorkspaceService

        assert WorkspaceService is not None


# ===========================================================================
# 7. Model imports — critical models import and have expected structure
# ===========================================================================


class TestModelImports:
    """
    Verify that new feature models import cleanly and have the expected
    table names and column structure.
    """

    def test_llm_experiment_model_table_name(self):
        from backend.app.models.llm_experiment import LLMExperiment

        assert LLMExperiment.__tablename__ == "llm_experiments"

    def test_llm_variant_model_table_name(self):
        from backend.app.models.llm_experiment import LLMVariant

        assert LLMVariant.__tablename__ == "llm_variants"

    def test_llm_evaluation_model_table_name(self):
        from backend.app.models.llm_experiment import LLMEvaluation

        assert LLMEvaluation.__tablename__ == "llm_evaluations"

    def test_workspace_model_table_name(self):
        from backend.app.models.workspace import Workspace

        assert Workspace.__tablename__ == "workspaces"

    def test_workspace_member_model_table_name(self):
        from backend.app.models.workspace import WorkspaceMember

        assert WorkspaceMember.__tablename__ == "workspace_members"

    def test_llm_experiment_enums_exist(self):
        from backend.app.models.llm_experiment import (
            LLMEvaluationMetric,
            LLMExperimentStatus,
            LLMProvider,
            LLMTaskType,
        )

        assert len(LLMExperimentStatus) >= 4
        assert len(LLMTaskType) >= 4
        assert len(LLMProvider) >= 4

    def test_workspace_enums_exist(self):
        from backend.app.models.workspace import WorkspaceMemberRole, WorkspacePlan

        assert len(WorkspacePlan) >= 3
        assert len(WorkspaceMemberRole) >= 5


# ===========================================================================
# 8. OpenAPI schema — new feature endpoints registered
# ===========================================================================


class TestNewFeatureEndpoints:
    """
    Verify that endpoints from recent epics are registered in the OpenAPI
    schema. These checks complement the TestAppStartup checks above with
    more specific endpoint validation.
    """

    def test_openapi_schema_includes_bandit(self, client):
        """Verify MAB/bandit endpoints are wired (Bayesian served via results)."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        paths = resp.json().get("paths", {})
        bandit_paths = [p for p in paths if "bandit" in p.lower()]
        assert bandit_paths, (
            "No /bandit/* paths in OpenAPI schema — MAB router not registered"
        )

    def test_openapi_schema_includes_sequential_testing(self, client):
        """Verify EP-021 sequential testing endpoints are wired."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        paths = resp.json().get("paths", {})
        seq_paths = [p for p in paths if "sequential" in p.lower()]
        assert seq_paths, (
            "No sequential testing paths in OpenAPI schema — EP-021 router not registered"
        )

    def test_openapi_schema_includes_cuped(self, client):
        """Verify CUPED variance reduction endpoints are wired."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        paths = resp.json().get("paths", {})
        cuped_paths = [p for p in paths if "cuped" in p.lower()]
        assert cuped_paths, (
            "No CUPED paths in OpenAPI schema — variance reduction router not registered"
        )

    def test_openapi_schema_includes_compliance(self, client):
        """Verify EP-033 compliance audit endpoints are wired."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        paths = resp.json().get("paths", {})
        compliance_paths = [
            p for p in paths if "compliance" in p.lower() or "audit" in p.lower()
        ]
        assert compliance_paths, (
            "No compliance/audit paths in OpenAPI schema — EP-033 router not registered"
        )

    def test_openapi_schema_includes_integrations(self, client):
        """Verify EP-034 third-party integration endpoints are wired."""
        from backend.app.core.config import settings

        resp = client.get(f"{settings.API_V1_STR}/openapi.json")
        paths = resp.json().get("paths", {})
        int_paths = [p for p in paths if "integration" in p.lower()]
        assert int_paths, (
            "No integration paths in OpenAPI schema — EP-034 router not registered"
        )
