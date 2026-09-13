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


def resp_text(body) -> str:
    """The whole payload as one string, for "this must not appear" checks."""
    import json

    return json.dumps(body)


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

    def test_ready_reports_the_profile(self, client, healthy_deps):
        """`profile` is `full` here: the test tree has `modules/`."""
        body = client.get("/health/ready").json()
        assert body["profile"] in ("core", "full")
        assert body["checks"]["modules"]["status"] == "healthy"
        assert body["checks"]["modules"]["profile"] == body["profile"]

    def test_a_broken_registration_is_reported_but_does_not_fail_readiness(
        self, client, healthy_deps, monkeypatch
    ):
        """A failed modules registration leaves the process on the core
        profile.  Outside development/test `main.py` refuses to start on it,
        so a probe never sees it there; where a probe does see it, it is
        reported and not gated -- every core route still serves, and failing
        readiness would only turn a visible degradation into a crash loop."""
        from backend.app import modules_loader

        monkeypatch.setattr(
            modules_loader, "_failure", "modules.register(hooks) raised boom"
        )
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["checks"]["modules"]["status"] == "unhealthy"
        assert body["checks"]["modules"]["error"] == (
            "modules.register(hooks) raised boom"
        )

    def test_production_reports_the_profile_but_not_the_cause(
        self, client, healthy_deps, fake_settings, monkeypatch
    ):
        """The profile is operational information an operator needs from the
        probe; the failure string stays behind the same production redaction
        as every other check detail."""
        from backend.app import modules_loader

        monkeypatch.setattr(modules_loader, "_failure", "boom in modules")
        fake_settings.ENVIRONMENT = "production"
        body = client.get("/health/ready").json()
        assert body["profile"] in ("core", "full")
        assert body["checks"]["modules"] == {"status": "unhealthy"}
        assert "boom in modules" not in resp_text(body)

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


# ---------------------------------------------------------------------------
# What an unauthenticated probe is allowed to publish
# ---------------------------------------------------------------------------


class TestTheProbePublishesNoCredential:
    """`/health/ready` is unauthenticated and, outside production, reports each
    check's own error text.

    The modules check used to return `modules_failure()` verbatim, bypassing
    the sanitiser every other check uses: the loader builds that string out of
    whatever module code raised, and a psycopg2 failure there put a DSN --
    host, user, password -- into the body of a public endpoint. Production
    reduces the body to statuses, so the exposure was development *and*
    staging.
    """

    @pytest.mark.regression
    def test_a_modules_failure_carrying_a_dsn_is_not_published(
        self, client, healthy_deps, monkeypatch
    ):
        from backend.app import modules_loader

        monkeypatch.setattr(
            modules_loader,
            "_failure",
            "modules.register(hooks) raised OperationalError: connection to "
            'server failed: FATAL:  password authentication failed for user "exp"',
        )
        body = client.get("/health/ready").json()

        assert body["checks"]["modules"]["status"] == "unhealthy"
        assert "password" not in resp_text(body).lower()
        assert "exp" not in body["checks"]["modules"]["error"]

    @pytest.mark.regression
    def test_a_modules_failure_carrying_a_url_credential_is_not_published(
        self, client, healthy_deps, monkeypatch
    ):
        from backend.app import modules_loader

        monkeypatch.setattr(
            modules_loader,
            "_failure",
            "modules.register(hooks) raised OperationalError: could not "
            "connect: postgresql://exp:hunter2@db.internal:5432/experimentation",
        )
        error = client.get("/health/ready").json()["checks"]["modules"]["error"]

        assert "hunter2" not in error
        # Still a diagnosis: the host and the failure are what an operator needs.
        assert "db.internal" in error
        assert "OperationalError" in error

    @pytest.mark.regression
    def test_the_failure_is_one_line_and_bounded(
        self, client, healthy_deps, monkeypatch
    ):
        from backend.app import modules_loader

        monkeypatch.setattr(
            modules_loader,
            "_failure",
            "modules.register(hooks) raised RuntimeError: first line\n"
            + "second line\n" * 50,
        )
        error = client.get("/health/ready").json()["checks"]["modules"]["error"]

        assert error == "modules.register(hooks) raised RuntimeError: first line"

    def test_a_failure_with_nothing_to_hide_is_reported_in_full(
        self, client, healthy_deps, monkeypatch
    ):
        """Redaction that ate the diagnosis would be its own bug: the common
        failure is a rejected setting, and its field name is the whole point."""
        from backend.app import modules_loader

        monkeypatch.setattr(
            modules_loader,
            "_failure",
            "modules.register(hooks) raised ValidationError: AUDIT_HMAC_KEY: "
            "must be at least 32 characters",
        )
        error = client.get("/health/ready").json()["checks"]["modules"]["error"]

        assert "AUDIT_HMAC_KEY" in error
        assert "at least 32 characters" in error


class TestScrub:
    """`_scrub` is what stands between an exception from any check and an
    unauthenticated response body."""

    def test_url_userinfo_goes(self):
        assert health._scrub("could not connect: amqp://guest:s3cret@broker:5672/") == (
            "could not connect: amqp://***:***@broker:5672/"
        )

    def test_a_named_secret_keeps_its_name_and_loses_its_value(self):
        assert health._scrub('OAuthError: client_secret="abc123" was rejected') == (
            "OAuthError: client_secret=*** was rejected"
        )
        assert health._scrub("redis error: token: abc123") == "redis error: token=***"

    def test_an_arn_keeps_its_resource_and_loses_the_account(self):
        scrubbed = health._scrub(
            "ClientError: User arn:aws:iam::123456789012:user/etl is not authorized"
        )
        assert "123456789012" not in scrubbed
        assert "arn:aws:iam::***:user/etl" in scrubbed

    def test_a_password_message_is_dropped_whole(self):
        assert "password" not in health._scrub(
            'FATAL: password authentication failed for user "exp"'
        )

    def test_it_is_one_line_and_at_most_200_characters(self):
        assert health._scrub("first\nsecond") == "first"
        assert len(health._scrub("x" * 500)) == 200
        assert health._scrub("") == ""

    def test_an_ordinary_message_is_untouched(self):
        message = "OperationalError: could not translate host name 'db' to address"
        assert health._scrub(message) == message


class TestTheProbeNeverRegisters:
    """`check_modules` called `load_modules()`, so an unauthenticated probe
    could make a process that had registered for a *schema* re-run the whole
    registration -- eleven endpoint modules, ~3.5 s, on the event loop, under
    the loader's lock -- once per process."""

    @pytest.mark.regression
    def test_a_probe_runs_no_registration(self, client, healthy_deps, monkeypatch):
        from unittest.mock import patch

        from backend.app import modules_loader

        monkeypatch.setattr(modules_loader, "_state", True)
        monkeypatch.setattr(modules_loader, "_routers", False)
        with patch.object(modules_loader, "_find_register") as find:
            body = client.get("/health/ready").json()

        assert find.call_count == 0
        assert body["profile"] == "full"


class TestMetricsTokenComparison:
    """A wrong token is a 401, whatever bytes it is made of.

    Starlette decodes headers as latin-1, so `Authorization: Bearer caf\xe9`
    arrives as a `str` with a non-ASCII code point and `hmac.compare_digest`
    raises TypeError on it -- a 500 from an unauthenticated endpoint, and an
    exception traceback in the logs for every scrape that gets it wrong.
    """

    @pytest.mark.regression
    def test_a_non_ascii_bearer_header_is_a_401(self, client, fake_settings):
        fake_settings.METRICS_TOKEN = "s3cret"
        # Raw bytes: httpx will not encode a non-ASCII str header.
        resp = client.get("/metrics", headers={b"Authorization": b"Bearer caf\xe9"})
        assert resp.status_code == 401

    @pytest.mark.regression
    def test_a_non_ascii_query_token_is_a_401(self, client, fake_settings):
        fake_settings.METRICS_TOKEN = "s3cret"
        assert client.get("/metrics?token=caf%E9").status_code == 401

    def test_the_right_token_still_passes(self, client, fake_settings):
        fake_settings.METRICS_TOKEN = "s3cret"
        assert (
            client.get("/metrics", headers={"Authorization": "Bearer s3cret"})
        ).status_code == 200
