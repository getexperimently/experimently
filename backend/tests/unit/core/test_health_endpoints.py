"""
Tests for the health probes and the guarded Prometheus endpoint
(``backend/app/core/health.py``).

- ``/health/live`` answers 200 without touching the database or Redis
- ``/health/ready`` (and its alias ``/health``) is 200 only when the database
  check passes; Redis only gates readiness when ``REDIS_REQUIRED=true``
- production responses hide check details
- ``/metrics`` honours ``METRICS_TOKEN`` (bearer header or ``?token=``), is
  open without a token in development/test only, and can be disabled
- every response carries ``X-Request-ID`` (RequestIDMiddleware registered)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core import health
from backend.app.main import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


class _SettingsProxy:
    """Assignments go to the real ``settings`` object through monkeypatch (restored on teardown)."""

    def __init__(self, monkeypatch):
        object.__setattr__(self, "_mp", monkeypatch)

    def __setattr__(self, name, value):
        self._mp.setattr(health.settings, name, value)

    def __getattr__(self, name):
        return getattr(health.settings, name)


@pytest.fixture
def fake_settings(monkeypatch):
    """Pin the switches ``health.py`` reads to known values on the real settings object.

    health.py reads ``settings`` only (no ``os.environ`` fallback), so the
    tests drive it through the settings fields.
    """
    proxy = _SettingsProxy(monkeypatch)
    proxy.ENVIRONMENT = "test"
    proxy.METRICS_TOKEN = None
    proxy.METRICS_ENABLED = True
    proxy.REDIS_REQUIRED = False
    return proxy


@pytest.fixture
def healthy_deps(monkeypatch):
    """Make the dependency checks pass without a database or Redis."""
    monkeypatch.setattr(
        health, "check_database", lambda: {"status": "healthy", "latency_ms": 0.1}
    )
    monkeypatch.setattr(
        health, "check_redis", lambda: {"status": "healthy", "latency_ms": 0.1}
    )
    monkeypatch.setattr(
        health, "check_disk", lambda path="/": {"status": "healthy", "free_gb": 50.0}
    )


@pytest.fixture
def db_down(monkeypatch):
    monkeypatch.setattr(
        health,
        "check_database",
        lambda: {"status": "unhealthy", "error": "connection refused"},
    )
    monkeypatch.setattr(
        health, "check_redis", lambda: {"status": "healthy", "latency_ms": 0.1}
    )
    monkeypatch.setattr(
        health, "check_disk", lambda path="/": {"status": "healthy", "free_gb": 50.0}
    )


@pytest.fixture
def redis_down(monkeypatch):
    monkeypatch.setattr(
        health, "check_database", lambda: {"status": "healthy", "latency_ms": 0.1}
    )
    monkeypatch.setattr(
        health, "check_redis", lambda: {"status": "unhealthy", "error": "refused"}
    )
    monkeypatch.setattr(
        health, "check_disk", lambda path="/": {"status": "healthy", "free_gb": 50.0}
    )


@pytest.fixture
def no_metrics_token(fake_settings):
    return fake_settings


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


class TestLiveness:
    def test_live_is_200_and_does_not_touch_dependencies(self, client, monkeypatch):
        def explode():  # pragma: no cover - must not be called
            raise AssertionError("liveness must not check dependencies")

        monkeypatch.setattr(health, "check_database", explode)
        monkeypatch.setattr(health, "check_redis", explode)

        resp = client.get("/health/live")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "alive"
        assert "timestamp" in body

    def test_live_carries_request_id(self, client):
        resp = client.get("/health/live")
        assert resp.headers.get("x-request-id")

    def test_live_echoes_incoming_request_id(self, client):
        resp = client.get("/health/live", headers={"X-Request-ID": "abc-123"})
        assert resp.headers.get("x-request-id") == "abc-123"


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


class TestReadiness:
    def test_ready_when_database_up(self, client, healthy_deps):
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["checks"]["database"]["status"] == "healthy"
        assert body["checks"]["redis"]["status"] == "healthy"

    def test_not_ready_when_database_down(self, client, db_down):
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "unhealthy"
        assert body["checks"]["database"]["status"] == "unhealthy"

    def test_redis_down_does_not_fail_readiness_by_default(
        self, client, redis_down, fake_settings
    ):
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["checks"]["redis"]["status"] == "unhealthy"

    def test_redis_down_fails_readiness_when_required(
        self, client, redis_down, fake_settings
    ):
        fake_settings.REDIS_REQUIRED = True
        resp = client.get("/health/ready")
        assert resp.status_code == 503

    def test_health_alias_matches_ready(self, client, healthy_deps):
        ready = client.get("/health/ready").json()
        alias = client.get("/health").json()
        assert alias["status"] == ready["status"]
        assert alias["checks"].keys() == ready["checks"].keys()

    def test_production_hides_details(self, client, db_down, fake_settings):
        fake_settings.ENVIRONMENT = "production"
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert "environment" not in body
        assert "version" not in body
        assert body["checks"]["database"] == {"status": "unhealthy"}  # no error text

    def test_error_text_never_contains_password(self):
        err = health._safe_error(
            RuntimeError('FATAL: password authentication failed for user "x"')
        )
        assert "password" not in err.lower()


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_open_in_development_without_token(self, client, fake_settings):
        fake_settings.ENVIRONMENT = "development"
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "http_requests_total" in resp.text
        assert "scheduler_last_success_timestamp" in resp.text

    @pytest.mark.parametrize("env", ["production", "staging"])
    def test_forbidden_outside_development_without_token(
        self, client, fake_settings, env
    ):
        fake_settings.ENVIRONMENT = env
        resp = client.get("/metrics")
        assert resp.status_code == 403

    def test_token_required_when_configured(self, client, fake_settings):
        fake_settings.METRICS_TOKEN = "s3cret"

        assert client.get("/metrics").status_code == 401
        assert (
            client.get(
                "/metrics", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/metrics", headers={"Authorization": "Bearer s3cret"}
            ).status_code
            == 200
        )
        assert client.get("/metrics?token=s3cret").status_code == 200

    def test_token_works_in_production(self, client, fake_settings):
        fake_settings.ENVIRONMENT = "production"
        fake_settings.METRICS_TOKEN = "prod-token"
        assert (
            client.get(
                "/metrics", headers={"Authorization": "Bearer prod-token"}
            ).status_code
            == 200
        )

    def test_disabled_returns_404(self, client, fake_settings):
        fake_settings.METRICS_ENABLED = False
        assert client.get("/metrics").status_code == 404

    def test_exposition_content_type(self, client, fake_settings):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
