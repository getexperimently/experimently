"""
Unit tests for real-time counters REST endpoints (P2-B TDD).

All DynamoDB interactions are mocked via dependency_overrides so tests
run without AWS credentials or a real database.

Coverage:
- GET  /api/v1/counters/{experiment_id}          — returns counters or 404
- POST /api/v1/counters/{experiment_id}/increment — returns new value
- POST /api/v1/counters/bulk      — returns processed/failed
- POST /api/v1/counters/{experiment_id}/reset     — ADMIN-only, 403 for others
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole
from modules.backend.app.schemas.realtime_counters import (
    BulkIncrementResponse,
    CounterType,
    ExperimentCounters,
    IncrementResponse,
    VariantCounters,
)
from modules.backend.app.services.dynamodb_counter_service import DynamoDBCounterService

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_admin_user():
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "admin@example.com"
    user.username = "admin"
    user.is_active = True
    user.is_superuser = True
    user.role = UserRole.ADMIN
    return user


def make_analyst_user():
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "analyst@example.com"
    user.username = "analyst"
    user.is_active = True
    user.is_superuser = False
    user.role = UserRole.ANALYST
    return user


def empty_experiment_counters(experiment_id: str) -> ExperimentCounters:
    return ExperimentCounters(
        experiment_id=experiment_id,
        total_assignments=0,
        total_events=0,
        total_conversions=0,
        variants=[],
    )


def sample_experiment_counters(experiment_id: str) -> ExperimentCounters:
    variants = [
        VariantCounters(
            variant_id="v1",
            variant_name="Control",
            is_control=True,
            assignments=100,
            events=80,
            conversions=20,
            conversion_rate=0.20,
        ),
        VariantCounters(
            variant_id="v2",
            variant_name="Treatment",
            is_control=False,
            assignments=100,
            events=90,
            conversions=30,
            conversion_rate=0.30,
        ),
    ]
    return ExperimentCounters(
        experiment_id=experiment_id,
        experiment_name="Test Experiment",
        total_assignments=200,
        total_events=170,
        total_conversions=50,
        variants=variants,
        last_updated="2026-03-01T12:00:00Z",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    """Ensure dependency overrides are cleared between tests."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_counter_service():
    return MagicMock(spec=DynamoDBCounterService)


@pytest.fixture
def admin_client(mock_counter_service):
    """TestClient with admin user injected and counter service mocked."""
    admin = make_admin_user()
    app.dependency_overrides[deps.get_current_active_user] = lambda: admin

    # Override the counter service dependency
    from modules.backend.app.api.v1.endpoints.realtime_counters import (
        get_counter_service,
    )

    app.dependency_overrides[get_counter_service] = lambda: mock_counter_service

    return TestClient(app, raise_server_exceptions=False), mock_counter_service


@pytest.fixture
def analyst_client(mock_counter_service):
    """TestClient with analyst (non-admin) user injected."""
    analyst = make_analyst_user()
    app.dependency_overrides[deps.get_current_active_user] = lambda: analyst

    from modules.backend.app.api.v1.endpoints.realtime_counters import (
        get_counter_service,
    )

    app.dependency_overrides[get_counter_service] = lambda: mock_counter_service

    return TestClient(app, raise_server_exceptions=False), mock_counter_service


# ---------------------------------------------------------------------------
# GET /api/v1/counters/{experiment_id}
# ---------------------------------------------------------------------------


class TestGetCounters:
    def test_returns_200_with_counters_when_data_exists(self, admin_client):
        client, svc = admin_client
        exp_id = "exp-abc"
        svc.get_experiment_counters.return_value = sample_experiment_counters(exp_id)

        resp = client.get(f"/api/v1/counters/{exp_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["experiment_id"] == exp_id
        assert data["total_assignments"] == 200

    def test_returns_404_when_no_counters_exist(self, admin_client):
        client, svc = admin_client
        exp_id = "exp-nonexistent"
        svc.get_experiment_counters.return_value = empty_experiment_counters(exp_id)

        resp = client.get(f"/api/v1/counters/{exp_id}")
        assert resp.status_code == 404

    def test_variants_included_in_response(self, admin_client):
        client, svc = admin_client
        exp_id = "exp-abc"
        svc.get_experiment_counters.return_value = sample_experiment_counters(exp_id)

        resp = client.get(f"/api/v1/counters/{exp_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["variants"]) == 2

    def test_returns_401_without_auth(self, client):
        resp = client.get("/api/v1/counters/exp-abc")
        assert resp.status_code in (401, 403)

    def test_analyst_can_read_counters(self, analyst_client):
        client, svc = analyst_client
        exp_id = "exp-abc"
        svc.get_experiment_counters.return_value = sample_experiment_counters(exp_id)

        resp = client.get(f"/api/v1/counters/{exp_id}")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/counters/{experiment_id}/increment
# ---------------------------------------------------------------------------


class TestIncrementCounter:
    def test_increment_returns_new_value(self, admin_client):
        client, svc = admin_client
        svc.increment_counter.return_value = 42

        resp = client.post(
            "/api/v1/counters/exp-1/increment",
            json={
                "experiment_id": "exp-1",
                "variant_id": "v1",
                "counter_type": "assignment",
                "amount": 1,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_value"] == 42
        assert data["counter_type"] == "assignment"

    def test_increment_calls_service_with_correct_args(self, admin_client):
        client, svc = admin_client
        svc.increment_counter.return_value = 5

        client.post(
            "/api/v1/counters/exp-1/increment",
            json={
                "experiment_id": "exp-1",
                "variant_id": "v-control",
                "counter_type": "event",
                "amount": 3,
            },
        )
        svc.increment_counter.assert_called_once_with(
            experiment_id="exp-1",
            variant_id="v-control",
            counter_type=CounterType.EVENT,
            amount=3,
        )

    def test_increment_with_invalid_amount_returns_422(self, admin_client):
        client, svc = admin_client
        resp = client.post(
            "/api/v1/counters/exp-1/increment",
            json={
                "experiment_id": "exp-1",
                "variant_id": "v1",
                "counter_type": "assignment",
                "amount": 0,  # invalid: must be >= 1
            },
        )
        assert resp.status_code == 422

    def test_increment_with_invalid_counter_type_returns_422(self, admin_client):
        client, svc = admin_client
        resp = client.post(
            "/api/v1/counters/exp-1/increment",
            json={
                "experiment_id": "exp-1",
                "variant_id": "v1",
                "counter_type": "invalid_type",
            },
        )
        assert resp.status_code == 422

    def test_service_error_returns_500(self, admin_client):
        client, svc = admin_client
        svc.increment_counter.side_effect = Exception("DynamoDB unavailable")

        resp = client.post(
            "/api/v1/counters/exp-1/increment",
            json={
                "experiment_id": "exp-1",
                "variant_id": "v1",
                "counter_type": "assignment",
            },
        )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/counters/bulk
# ---------------------------------------------------------------------------


class TestBulkIncrement:
    def test_bulk_returns_processed_and_failed_counts(self, admin_client):
        client, svc = admin_client
        svc.bulk_increment.return_value = BulkIncrementResponse(
            processed=3,
            failed=0,
            results=[
                IncrementResponse(
                    experiment_id="exp-1",
                    variant_id="v1",
                    counter_type=CounterType.ASSIGNMENT,
                    new_value=10,
                ),
                IncrementResponse(
                    experiment_id="exp-1",
                    variant_id="v2",
                    counter_type=CounterType.EVENT,
                    new_value=5,
                ),
                IncrementResponse(
                    experiment_id="exp-1",
                    variant_id="v1",
                    counter_type=CounterType.CONVERSION,
                    new_value=2,
                ),
            ],
        )

        resp = client.post(
            "/api/v1/counters/bulk",
            json={
                "increments": [
                    {
                        "experiment_id": "exp-1",
                        "variant_id": "v1",
                        "counter_type": "assignment",
                    },
                    {
                        "experiment_id": "exp-1",
                        "variant_id": "v2",
                        "counter_type": "event",
                    },
                    {
                        "experiment_id": "exp-1",
                        "variant_id": "v1",
                        "counter_type": "conversion",
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 3
        assert data["failed"] == 0

    def test_bulk_empty_list_returns_422(self, admin_client):
        client, svc = admin_client
        resp = client.post(
            "/api/v1/counters/bulk",
            json={"increments": []},
        )
        assert resp.status_code == 422

    def test_bulk_partial_failure_reflected_in_response(self, admin_client):
        client, svc = admin_client
        svc.bulk_increment.return_value = BulkIncrementResponse(
            processed=1,
            failed=1,
            results=[
                IncrementResponse(
                    experiment_id="exp-1",
                    variant_id="v1",
                    counter_type=CounterType.ASSIGNMENT,
                    new_value=1,
                )
            ],
        )

        resp = client.post(
            "/api/v1/counters/bulk",
            json={
                "increments": [
                    {
                        "experiment_id": "exp-1",
                        "variant_id": "v1",
                        "counter_type": "assignment",
                    },
                    {
                        "experiment_id": "exp-1",
                        "variant_id": "v2",
                        "counter_type": "event",
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1


# ---------------------------------------------------------------------------
# POST /api/v1/counters/{experiment_id}/reset  (ADMIN only)
# ---------------------------------------------------------------------------


class TestResetCounters:
    def test_admin_can_reset_counters(self, admin_client):
        client, svc = admin_client
        svc.reset_counters.return_value = None

        resp = client.post(
            "/api/v1/counters/exp-1/reset",
            json={
                "experiment_id": "exp-1",
                "reason": "Experiment restarted",
            },
        )
        assert resp.status_code == 200

    def test_reset_calls_service_with_correct_args(self, admin_client):
        client, svc = admin_client
        svc.reset_counters.return_value = None

        client.post(
            "/api/v1/counters/exp-1/reset",
            json={
                "experiment_id": "exp-1",
                "variant_id": "v1",
                "counter_type": "conversion",
                "reason": "Bug fix applied",
            },
        )
        svc.reset_counters.assert_called_once_with(
            experiment_id="exp-1",
            variant_id="v1",
            counter_type=CounterType.CONVERSION,
            reason="Bug fix applied",
        )

    def test_non_admin_cannot_reset_counters(self, analyst_client):
        client, svc = analyst_client
        resp = client.post(
            "/api/v1/counters/exp-1/reset",
            json={
                "experiment_id": "exp-1",
                "reason": "Should not be allowed",
            },
        )
        assert resp.status_code == 403

    def test_reset_without_auth_returns_401_or_403(self, client):
        resp = client.post(
            "/api/v1/counters/exp-1/reset",
            json={"experiment_id": "exp-1", "reason": "Unauthorized"},
        )
        assert resp.status_code in (401, 403)

    def test_reset_with_empty_reason_returns_422(self, admin_client):
        client, svc = admin_client
        resp = client.post(
            "/api/v1/counters/exp-1/reset",
            json={"experiment_id": "exp-1", "reason": ""},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# The path parameter is not decoration (#95)
# ---------------------------------------------------------------------------


def make_developer_user():
    """A DEVELOPER: passes `experiment: update` by role, not by superuser.

    The admin fixtures set `is_superuser=True`, which short-circuits several
    checks. DEVELOPER is the role this endpoint argues is the normal writer,
    so the refusals below are proved for it rather than only for a superuser.
    """
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "dev@example.com"
    user.username = "dev"
    user.is_active = True
    user.is_superuser = False
    user.role = UserRole.DEVELOPER
    return user


@pytest.fixture
def developer_client(mock_counter_service):
    app.dependency_overrides[deps.get_current_active_user] = make_developer_user

    from modules.backend.app.api.v1.endpoints.realtime_counters import (
        get_counter_service,
    )

    app.dependency_overrides[get_counter_service] = lambda: mock_counter_service
    return TestClient(app, raise_server_exceptions=False), mock_counter_service


class TestTheWriteLandsWhereTheUrlSays:
    """These routes took `{experiment_id}` and then wrote to `body.experiment_id`.

    The path parameter appeared only in an error log, so a POST to one
    experiment's URL incremented another's counters and nothing noticed. That
    matters beyond tidiness: these counters are the first source
    ``BanditScheduler`` consults, so a write that lands on the wrong
    experiment re-weights live traffic there -- and everything keyed on the
    request path (access log, audit trail, WAF rule, rate limit) records an
    experiment the write never touched.

    The handlers now pass the **path** value to the service, so the write is
    correct by construction; the refusals below are what stops a caller whose
    body disagrees being quietly redirected instead of told.
    """

    @pytest.mark.regression
    def test_increment_refuses_a_body_naming_another_experiment(self, developer_client):
        client, svc = developer_client
        resp = client.post(
            "/api/v1/counters/exp-mine/increment",
            json={
                "experiment_id": "exp-someone-elses",
                "variant_id": "v1",
                "counter_type": "conversion",
                "amount": 1,
            },
        )

        assert resp.status_code == 400, resp.text
        assert "exp-someone-elses" in resp.json()["detail"]
        assert "exp-mine" in resp.json()["detail"]
        svc.increment_counter.assert_not_called()

    @pytest.mark.regression
    def test_increment_writes_and_reports_the_path_experiment(self, developer_client):
        """The service call and the response body both name the URL's experiment."""
        client, svc = developer_client
        svc.increment_counter.return_value = 7

        resp = client.post(
            "/api/v1/counters/exp-1/increment",
            json={
                "experiment_id": "exp-1",
                "variant_id": "v1",
                "counter_type": "assignment",
                "amount": 1,
            },
        )

        assert resp.status_code == 200, resp.text
        assert svc.increment_counter.call_args.kwargs["experiment_id"] == "exp-1"
        assert resp.json()["experiment_id"] == "exp-1"

    @pytest.mark.regression
    def test_reset_refuses_a_body_naming_another_experiment(self, admin_client):
        """Reset discards data, so landing on the wrong experiment is the worst
        of the three. ADMIN-only, so this one cannot use the developer client."""
        client, svc = admin_client

        resp = client.post(
            "/api/v1/counters/exp-1/reset",
            json={"experiment_id": "exp-elsewhere", "reason": "cleanup"},
        )

        assert resp.status_code == 400, resp.text
        svc.reset_counters.assert_not_called()

    @pytest.mark.regression
    def test_reset_checks_the_role_before_the_path(self, developer_client):
        """A DEVELOPER's mismatched reset is 403, not 400.

        Not because 400 would disclose anything -- the comparison touches no
        database and only echoes what the caller sent, and `GET
        /api/v1/counters/{id}` on this same router already answers 200 or 404
        by whether data exists. It is that "you may not do this at all" is the
        more specific answer, and reordering the two would change a refusal
        into a complaint about the request.
        """
        client, svc = developer_client

        resp = client.post(
            "/api/v1/counters/exp-1/reset",
            json={"experiment_id": "exp-elsewhere", "reason": "cleanup"},
        )

        assert resp.status_code == 403, resp.text
        svc.reset_counters.assert_not_called()

    @pytest.mark.regression
    def test_increment_checks_the_role_before_the_path(self, analyst_client):
        client, svc = analyst_client

        resp = client.post(
            "/api/v1/counters/exp-1/increment",
            json={
                "experiment_id": "exp-elsewhere",
                "variant_id": "v1",
                "counter_type": "conversion",
                "amount": 1,
            },
        )

        assert resp.status_code == 403, resp.text
        svc.increment_counter.assert_not_called()

    @pytest.mark.regression
    def test_bulk_still_accepts_a_batch_spanning_experiments(self, developer_client):
        """The capability the path parameter would have removed.

        `BulkIncrementRequest.increments` is a list whose every entry names
        its own experiment, so a collector can flush one buffer covering
        several. An earlier version of this fix required them all to equal a
        path segment, which turned that into a 400 and made the route's own
        "does not abort on first error" false. `/bulk` has no path segment.
        """
        client, svc = developer_client
        svc.bulk_increment.return_value = BulkIncrementResponse(
            processed=2,
            failed=0,
            results=[
                IncrementResponse(
                    experiment_id="exp-a",
                    variant_id="v1",
                    counter_type=CounterType.ASSIGNMENT,
                    new_value=1,
                ),
                IncrementResponse(
                    experiment_id="exp-b",
                    variant_id="v1",
                    counter_type=CounterType.CONVERSION,
                    new_value=1,
                ),
            ],
        )

        resp = client.post(
            "/api/v1/counters/bulk",
            json={
                "increments": [
                    {
                        "experiment_id": "exp-a",
                        "variant_id": "v1",
                        "counter_type": "assignment",
                        "amount": 1,
                    },
                    {
                        "experiment_id": "exp-b",
                        "variant_id": "v1",
                        "counter_type": "conversion",
                        "amount": 1,
                    },
                ]
            },
        )

        assert resp.status_code == 200, resp.text
        svc.bulk_increment.assert_called_once()
        sent = {i.experiment_id for i in svc.bulk_increment.call_args.args[0]}
        assert sent == {"exp-a", "exp-b"}

    @pytest.mark.regression
    def test_bulk_takes_no_experiment_in_the_path(self, developer_client):
        """The old URL must not still work, or both shapes ship at once."""
        client, svc = developer_client
        resp = client.post(
            "/api/v1/counters/exp-1/bulk",
            json={"increments": []},
        )
        assert resp.status_code == 404, resp.text
        svc.bulk_increment.assert_not_called()
