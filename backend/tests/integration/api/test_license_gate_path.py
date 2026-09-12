"""The licence gate, applied: Enterprise routes refuse without a licence.

Everything else in the suite runs under the session-wide wildcard licence
(``backend/tests/licence_fixtures.py``).  These tests swap it for specific
licences through the ``licensed`` fixture and hit real routes through the
real router, so what is asserted is the wiring in
``backend/app/ee_transitional.py`` -- the same wiring ``ee.register(hooks)``
will carry after the move -- not the verifier on its own.

Regression: until this landed the gate had zero call sites. The dashboard hid
Enterprise navigation for an unlicensed edition while the API served every
Enterprise route to anyone who typed the URL.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.enterprise]


def _refusal(response):
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "feature_not_licensed"
    return detail


class TestUnlicensed:
    def test_enterprise_routes_refuse_and_name_the_feature(
        self, admin_client, licensed
    ):
        licensed(None)
        assert admin_client.get("/api/v1/edition").json()["edition"] == "ce"

        for path, feature in (
            ("/api/v1/workspaces", "workspaces"),
            ("/api/v1/rbac/roles", "rbac"),
            ("/api/v1/hipaa/status", "hipaa"),
            ("/api/v1/integrations", "integrations"),
            ("/api/v1/warehouse/connections", "warehouse"),
        ):
            detail = _refusal(admin_client.get(path))
            assert detail["feature"] == feature, path
            assert detail["status"] == "none", path

    def test_community_routes_are_untouched(self, admin_client, licensed):
        licensed(None)
        assert admin_client.get("/api/v1/experiments").status_code == 200
        assert admin_client.get("/api/v1/feature-flags").status_code == 200
        # The audit event list is Community even though signing is not.
        assert admin_client.get("/api/v1/compliance/audit-events").status_code == 200

    def test_a_registered_but_unlicensed_capability_is_403_not_501(
        self, admin_client, licensed
    ):
        """501 means 'this build does not have it'; 403 means 'it is here and
        needs a licence'. This tree has it."""
        licensed(None)
        detail = _refusal(admin_client.get("/api/v1/compliance/reports/soc2"))
        assert detail["feature"] == "compliance"

    def test_split_url_experiments_cannot_be_created(self, admin_client, licensed):
        licensed(None)
        response = admin_client.post(
            "/api/v1/experiments",
            json={
                "name": "unroutable",
                "experiment_type": "split_url",
                "hypothesis": "nothing routes this",
                "variants": [
                    {"name": "control", "is_control": True, "traffic_allocation": 50},
                    {"name": "b", "is_control": False, "traffic_allocation": 50},
                ],
                "metrics": [{"name": "conv", "event_name": "conv"}],
            },
        )
        # Installed but unlicensed: 403 naming the feature, not the 501 a build
        # without the capability answers.
        detail = _refusal(response)
        assert detail["feature"] == "split_url"


class TestPartiallyLicensed:
    def test_only_the_named_features_open(self, admin_client, licensed):
        licensed(features=["workspaces"])
        assert admin_client.get("/api/v1/workspaces").status_code == 200
        detail = _refusal(admin_client.get("/api/v1/rbac/roles"))
        assert detail["feature"] == "rbac"
        assert detail["status"] == "active"


class TestLapsed:
    def test_grace_behaves_like_active(self, admin_client, licensed):
        licensed(days=-3)  # expired three days ago, inside the 14-day grace
        assert admin_client.get("/api/v1/edition").json()["status"] == "grace"
        assert admin_client.get("/api/v1/workspaces").status_code == 200

    def test_read_only_window_allows_reads_refuses_writes(self, admin_client, licensed):
        licensed(days=-20)  # past grace, inside the 30-day read-only window
        assert admin_client.get("/api/v1/edition").json()["status"] == "expired"
        assert admin_client.get("/api/v1/workspaces").status_code == 200
        detail = _refusal(
            admin_client.post(
                "/api/v1/workspaces", json={"name": "Late", "slug": "late-ws"}
            )
        )
        assert detail["status"] == "expired"

    def test_after_the_read_only_window_reads_are_refused_too(
        self, admin_client, licensed
    ):
        licensed(days=-60)  # 14 + 30 = 44 days of tolerance, all spent
        assert admin_client.get("/api/v1/edition").json()["status"] == "expired"
        _refusal(admin_client.get("/api/v1/workspaces"))

    def test_data_is_never_hidden_from_community_routes(self, admin_client, licensed):
        """A lapsed licence refuses Enterprise *routes*; Community rows that
        carried a workspace_id are still listed by the Community endpoints."""
        licensed(days=-60)
        assert admin_client.get("/api/v1/experiments").status_code == 200


class TestSessionLicence:
    def test_the_rest_of_the_suite_runs_licensed(self, admin_client):
        body = admin_client.get("/api/v1/edition").json()
        assert body["edition"] == "enterprise"
        assert body["status"] == "active"
        assert body["features"] == ["*"]


@pytest.fixture
def anonymous_client(db_session):
    """A client with the database wired in and *no* authentication override.

    The shared `client` fixture overrides `get_current_active_user`, which is
    the opposite of what these tests need.
    """
    from fastapi.testclient import TestClient

    from backend.app.api.deps import get_db
    from backend.app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


class TestAuthenticationComesFirst:
    """The gate runs *after* authentication on routes that need a user.

    Before this, the router-level licence dependency ran first, so an
    anonymous request to an Enterprise route got a 403 naming the feature and
    the licence state instead of the 401 it always got -- and an
    unauthenticated probe could enumerate which Enterprise routers were
    installed and the licence state per prefix.
    """

    def test_anonymous_requests_get_401_not_licence_details(
        self, anonymous_client, licensed
    ):
        licensed(None)
        for path in (
            "/api/v1/workspaces",
            "/api/v1/rbac/roles",
            "/api/v1/hipaa/status",
            "/api/v1/integrations",
            "/api/v1/warehouse/connections",
            "/api/v1/auth/sso/configs",
        ):
            response = anonymous_client.get(path)
            assert response.status_code == 401, (path, response.text)
            assert "feature_not_licensed" not in response.text, path

    def test_public_routes_are_still_public_but_gated(self, client, licensed):
        """Webhooks, the SSO login flow and the invite preview carry no user
        authentication by design; they answer the licence, not a 401."""
        licensed(None)
        detail = _refusal(client.get("/api/v1/workspaces/invites/some-token"))
        assert detail["feature"] == "workspaces"
        detail = _refusal(client.get("/api/v1/auth/sso/oidc/okta/login"))
        assert detail["feature"] == "sso"
        detail = _refusal(client.post("/api/v1/integrations/webhooks/jira", json={}))
        assert detail["feature"] == "integrations"

    def test_public_routes_work_when_licensed(self, client):
        # Not found, not forbidden: the gate passed and the handler ran.
        assert client.get("/api/v1/workspaces/invites/no-such-token").status_code == 404


class TestReadOnlyWindowFollowsWhatTheRouteDoes:
    """A POST that reads is a read.

    The read-only window exists so a customer whose licence has lapsed can
    still read their data. Classifying by verb alone let them list their
    warehouse connections and refused them every metric behind a POST.
    """

    def test_post_reads_pass_in_the_read_only_window(self, admin_client, licensed):
        licensed(days=-20)
        # Past the gate: whatever these answer, it is not the licence 403.
        for path, body in (
            ("/api/v1/warehouse/clickhouse/query", {"sql": "SELECT 1"}),
            ("/api/v1/etl/query", {"query": "SELECT 1"}),
            ("/api/v1/hipaa/decrypt", {"ciphertext": "x"}),
        ):
            response = admin_client.post(path, json=body)
            assert response.status_code != 403 or (
                "feature_not_licensed" not in response.text
            ), (path, response.text)

    def test_post_writes_are_still_refused(self, admin_client, licensed):
        licensed(days=-20)
        detail = _refusal(
            admin_client.post("/api/v1/hipaa/baa", json={"organization_name": "x"})
        )
        assert detail["status"] == "expired"

    def test_sso_configuration_is_a_write_but_signing_in_is_not(
        self, admin_client, client, licensed
    ):
        licensed(days=-20)
        # The login flow stays open (read-only): not the licence 403.
        response = client.get("/api/v1/auth/sso/oidc/okta/login")
        assert "feature_not_licensed" not in response.text
        # Configuring SSO is a write: refused.
        detail = _refusal(
            admin_client.post("/api/v1/auth/sso/configs", json={"name": "late"})
        )
        assert detail["status"] == "expired"

    @pytest.mark.regression
    def test_inbound_webhooks_are_reads(self, client, licensed):
        """They read the integration config and parse the event, persisting
        nothing; refusing them in the window would only make the provider
        record a month of failed deliveries."""
        licensed(days=-20)
        for provider in ("jira", "salesforce", "github"):
            response = client.post(f"/api/v1/integrations/webhooks/{provider}", json={})
            assert "feature_not_licensed" not in response.text, (
                provider,
                response.text,
            )

    def test_split_url_creation_is_a_write(self, admin_client, licensed):
        """The availability probe used to answer with write=False, so a
        split-URL experiment could be stored while every other Enterprise
        write was refused."""
        licensed(days=-20)
        response = admin_client.post(
            "/api/v1/experiments",
            json={
                "name": "late split",
                "experiment_type": "split_url",
                "hypothesis": "nothing routes this",
                "variants": [
                    {"name": "control", "is_control": True, "traffic_allocation": 50},
                    {"name": "b", "is_control": False, "traffic_allocation": 50},
                ],
                "metrics": [{"name": "conv", "event_name": "conv"}],
            },
        )
        detail = _refusal(response)
        assert detail["feature"] == "split_url"
        assert detail["status"] == "expired"

    def test_counters_are_read_in_the_read_only_window(self, licensed):
        from backend.app.core.enterprise_features import realtime_counter_service

        licensed(days=-20)
        assert realtime_counter_service() is not None
        licensed(days=-60)
        assert realtime_counter_service() is None


class TestRoleBeforeEdition:
    @pytest.mark.regression
    def test_a_viewer_is_refused_the_split_url_preview_by_role(
        self, viewer_client, licensed
    ):
        """Same order as the compliance routes: a VIEWER learns nothing about
        which bodies the build has, or the licence state, from this route."""
        licensed(None)
        response = viewer_client.get(
            "/api/v1/experiments/00000000-0000-0000-0000-000000000000/split-url/preview",
            params={"user_id": "u1"},
        )
        assert response.status_code == 403
        assert "feature_not_licensed" not in response.text
        assert "DEVELOPER or ADMIN" in response.text

    @pytest.mark.regression
    def test_a_viewer_is_refused_the_report_by_role_in_every_edition(
        self, viewer_client, licensed
    ):
        """The role check used to live only in the Enterprise handler, so in a
        build without it (501) or without a licence (403 feature_not_licensed)
        a VIEWER learnt which bodies the build lacked instead of being told no."""
        licensed(None)
        response = viewer_client.get("/api/v1/compliance/reports/soc2")
        assert response.status_code == 403
        assert "feature_not_licensed" not in response.text
        assert "ADMIN or ANALYST" in response.text

        response = viewer_client.get("/api/v1/compliance/export")
        assert response.status_code == 403
        assert "ADMIN role" in response.text
