"""
Integration tests for the Real-time Counters REST API (EP-011).

Tests the full HTTP request/response cycle for DynamoDB-backed counter
endpoints.  The DynamoDB service is mocked via FastAPI dependency_overrides
so no live DynamoDB connection is required.

Endpoint coverage:
  GET  /api/v1/counters/{experiment_id}          get counters
  POST /api/v1/counters/{experiment_id}/increment increment (1-1000)
  POST /api/v1/counters/{experiment_id}/bulk      bulk increment (max 100)
  POST /api/v1/counters/{experiment_id}/reset     reset (ADMIN only)
"""

import uuid
import pytest
from unittest.mock import MagicMock

from backend.app.main import app
from backend.app.api.v1.endpoints.realtime_counters import get_counter_service
from backend.app.schemas.realtime_counters import (
    BulkIncrementResponse,
    CounterType,
    ExperimentCounters,
    IncrementResponse,
    VariantCounters,
)


# ---------------------------------------------------------------------------
# Mock factory helpers
# ---------------------------------------------------------------------------

_TEST_EXP_ID = "test-exp-id-001"
_TEST_VARIANT_A = "variant-control"
_TEST_VARIANT_B = "variant-treatment"


def _make_variant_counters(
    variant_id: str,
    assignments: int = 100,
    events: int = 50,
    conversions: int = 15,
) -> VariantCounters:
    """Build a VariantCounters object for mock responses."""
    return VariantCounters(
        variant_id=variant_id,
        variant_name=variant_id,
        is_control=(variant_id == _TEST_VARIANT_A),
        assignments=assignments,
        events=events,
        conversions=conversions,
        conversion_rate=round(conversions / assignments, 4) if assignments > 0 else 0.0,
    )


def _make_experiment_counters(
    experiment_id: str = _TEST_EXP_ID,
    has_data: bool = True,
) -> ExperimentCounters:
    """Build an ExperimentCounters object for mock responses."""
    if not has_data:
        return ExperimentCounters(
            experiment_id=experiment_id,
            total_assignments=0,
            total_events=0,
            total_conversions=0,
            variants=[],
        )
    variants = [
        _make_variant_counters(_TEST_VARIANT_A, assignments=200, events=100, conversions=30),
        _make_variant_counters(_TEST_VARIANT_B, assignments=195, events=95, conversions=40),
    ]
    return ExperimentCounters(
        experiment_id=experiment_id,
        experiment_name="Test Experiment",
        total_assignments=395,
        total_events=195,
        total_conversions=70,
        variants=variants,
        last_updated="2024-01-01T00:00:00Z",
    )


def _mock_counter_service(
    experiment_id: str = _TEST_EXP_ID,
    has_data: bool = True,
    increment_new_value: int = 101,
) -> MagicMock:
    """
    Create a mock DynamoDBCounterService.

    Override get_counter_service() with this to avoid real DynamoDB calls.
    """
    mock = MagicMock()

    # get_experiment_counters
    mock.get_experiment_counters.return_value = _make_experiment_counters(
        experiment_id=experiment_id, has_data=has_data
    )

    # increment_counter
    mock.increment_counter.return_value = increment_new_value

    # bulk_increment — returns BulkIncrementResponse
    mock.bulk_increment.return_value = BulkIncrementResponse(
        processed=2,
        failed=0,
        results=[
            IncrementResponse(
                experiment_id=experiment_id,
                variant_id=_TEST_VARIANT_A,
                counter_type=CounterType.ASSIGNMENT,
                new_value=201,
            ),
            IncrementResponse(
                experiment_id=experiment_id,
                variant_id=_TEST_VARIANT_B,
                counter_type=CounterType.ASSIGNMENT,
                new_value=196,
            ),
        ],
    )

    # reset_counters — returns None
    mock.reset_counters.return_value = None

    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def counter_mock():
    """Provide a mock DynamoDB counter service and clean up overrides after test."""
    mock_svc = _mock_counter_service()
    app.dependency_overrides[get_counter_service] = lambda: mock_svc
    yield mock_svc
    app.dependency_overrides.pop(get_counter_service, None)


@pytest.fixture
def counter_mock_no_data():
    """Mock service returning empty counters (no data scenario)."""
    mock_svc = _mock_counter_service(has_data=False)
    app.dependency_overrides[get_counter_service] = lambda: mock_svc
    yield mock_svc
    app.dependency_overrides.pop(get_counter_service, None)


# ---------------------------------------------------------------------------
# GET /api/v1/counters/{experiment_id}
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestGetCounters:
    """GET /api/v1/counters/{experiment_id}"""

    def test_get_counters_returns_200_when_data_exists(self, admin_client, counter_mock):
        """Admin can GET counters — returns 200 with ExperimentCounters data."""
        response = admin_client.get(f"/api/v1/counters/{_TEST_EXP_ID}")
        assert response.status_code == 200, response.text

    def test_get_counters_response_contains_experiment_id(self, admin_client, counter_mock):
        """Response body contains the correct experiment_id."""
        response = admin_client.get(f"/api/v1/counters/{_TEST_EXP_ID}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["experiment_id"] == _TEST_EXP_ID

    def test_get_counters_response_contains_variant_list(self, admin_client, counter_mock):
        """Response body includes a list of variant counters."""
        response = admin_client.get(f"/api/v1/counters/{_TEST_EXP_ID}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "variants" in data
        assert isinstance(data["variants"], list)
        assert len(data["variants"]) == 2

    def test_get_counters_response_contains_totals(self, admin_client, counter_mock):
        """Response includes total_assignments, total_events, total_conversions."""
        response = admin_client.get(f"/api/v1/counters/{_TEST_EXP_ID}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "total_assignments" in data
        assert "total_events" in data
        assert "total_conversions" in data
        assert data["total_assignments"] == 395
        assert data["total_events"] == 195
        assert data["total_conversions"] == 70

    def test_get_counters_404_when_no_data(self, admin_client, counter_mock_no_data):
        """Returns 404 when the experiment has no counter data."""
        response = admin_client.get(f"/api/v1/counters/{_TEST_EXP_ID}")
        assert response.status_code == 404, response.text

    def test_analyst_can_get_counters(self, analyst_client, counter_mock):
        """Analyst can GET counters — no extra permission required."""
        response = analyst_client.get(f"/api/v1/counters/{_TEST_EXP_ID}")
        assert response.status_code == 200, response.text

    def test_developer_can_get_counters(self, developer_client, counter_mock):
        """Developer can GET counters."""
        response = developer_client.get(f"/api/v1/counters/{_TEST_EXP_ID}")
        assert response.status_code == 200, response.text

    def test_variant_counters_contain_required_fields(self, admin_client, counter_mock):
        """Each variant counter entry contains required fields."""
        response = admin_client.get(f"/api/v1/counters/{_TEST_EXP_ID}")
        assert response.status_code == 200, response.text
        variants = response.json()["variants"]
        assert len(variants) > 0
        first = variants[0]
        assert "variant_id" in first
        assert "assignments" in first
        assert "events" in first
        assert "conversions" in first
        assert "conversion_rate" in first

    def test_service_called_with_correct_experiment_id(self, admin_client, counter_mock):
        """The service is called with the experiment_id from the path parameter."""
        custom_exp_id = "custom-experiment-xyz"
        # Override mock to handle this specific experiment_id
        counter_mock.get_experiment_counters.return_value = _make_experiment_counters(
            experiment_id=custom_exp_id, has_data=True
        )
        response = admin_client.get(f"/api/v1/counters/{custom_exp_id}")
        assert response.status_code == 200, response.text
        counter_mock.get_experiment_counters.assert_called_with(custom_exp_id)


# ---------------------------------------------------------------------------
# POST /api/v1/counters/{experiment_id}/increment
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIncrementCounter:
    """POST /api/v1/counters/{experiment_id}/increment"""

    def test_increment_counter_returns_200(self, admin_client, counter_mock):
        """Valid increment request returns 200 with new_value."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_A,
            "counter_type": "assignment",
            "amount": 1,
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
        )
        assert response.status_code == 200, response.text

    def test_increment_counter_response_contains_new_value(self, admin_client, counter_mock):
        """Increment response includes new_value field."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_A,
            "counter_type": "assignment",
            "amount": 1,
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "new_value" in data
        assert data["new_value"] == 101

    def test_increment_counter_response_echoes_identifiers(self, admin_client, counter_mock):
        """Increment response echoes experiment_id, variant_id, counter_type."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_B,
            "counter_type": "conversion",
            "amount": 5,
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["experiment_id"] == _TEST_EXP_ID
        assert data["variant_id"] == _TEST_VARIANT_B
        assert data["counter_type"] == "conversion"

    def test_increment_all_counter_types(self, admin_client, counter_mock):
        """All three counter types (assignment, event, conversion) are accepted."""
        for counter_type in ("assignment", "event", "conversion"):
            payload = {
                "experiment_id": _TEST_EXP_ID,
                "variant_id": _TEST_VARIANT_A,
                "counter_type": counter_type,
                "amount": 1,
            }
            response = admin_client.post(
                f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
            )
            assert response.status_code == 200, (
                f"Counter type '{counter_type}' failed: {response.text}"
            )

    def test_invalid_amount_too_large_returns_422(self, admin_client, counter_mock):
        """amount > 1000 fails schema validation — returns 422."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_A,
            "counter_type": "assignment",
            "amount": 1001,
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
        )
        assert response.status_code == 422, response.text

    def test_invalid_amount_zero_returns_422(self, admin_client, counter_mock):
        """amount of 0 fails schema validation (ge=1) — returns 422."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_A,
            "counter_type": "assignment",
            "amount": 0,
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
        )
        assert response.status_code == 422, response.text

    def test_invalid_amount_negative_returns_422(self, admin_client, counter_mock):
        """Negative amount fails schema validation — returns 422."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_A,
            "counter_type": "assignment",
            "amount": -5,
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
        )
        assert response.status_code == 422, response.text

    def test_missing_variant_id_returns_422(self, admin_client, counter_mock):
        """Missing required variant_id field returns 422."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "counter_type": "assignment",
            "amount": 1,
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
        )
        assert response.status_code == 422, response.text

    def test_invalid_counter_type_returns_422(self, admin_client, counter_mock):
        """Invalid counter_type value returns 422."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_A,
            "counter_type": "invalid_type",
            "amount": 1,
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
        )
        assert response.status_code == 422, response.text

    def test_analyst_can_increment_counter(self, analyst_client, counter_mock):
        """Analyst can increment counters — no special permission required."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_A,
            "counter_type": "event",
            "amount": 1,
        }
        response = analyst_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload
        )
        assert response.status_code == 200, response.text

    def test_service_increment_called_with_correct_args(self, admin_client, counter_mock):
        """Verify the service method is called with the correct arguments."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_A,
            "counter_type": "conversion",
            "amount": 3,
        }
        admin_client.post(f"/api/v1/counters/{_TEST_EXP_ID}/increment", json=payload)

        counter_mock.increment_counter.assert_called_once_with(
            experiment_id=_TEST_EXP_ID,
            variant_id=_TEST_VARIANT_A,
            counter_type=CounterType.CONVERSION,
            amount=3,
        )


# ---------------------------------------------------------------------------
# POST /api/v1/counters/{experiment_id}/bulk
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestBulkIncrement:
    """POST /api/v1/counters/{experiment_id}/bulk"""

    def test_bulk_increment_returns_200(self, admin_client, counter_mock):
        """Valid bulk increment request returns 200."""
        payload = {
            "increments": [
                {
                    "experiment_id": _TEST_EXP_ID,
                    "variant_id": _TEST_VARIANT_A,
                    "counter_type": "assignment",
                    "amount": 1,
                },
                {
                    "experiment_id": _TEST_EXP_ID,
                    "variant_id": _TEST_VARIANT_B,
                    "counter_type": "assignment",
                    "amount": 1,
                },
            ]
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/bulk", json=payload
        )
        assert response.status_code == 200, response.text

    def test_bulk_increment_returns_processed_and_failed_counts(
        self, admin_client, counter_mock
    ):
        """Bulk increment response includes processed and failed counts."""
        payload = {
            "increments": [
                {
                    "experiment_id": _TEST_EXP_ID,
                    "variant_id": _TEST_VARIANT_A,
                    "counter_type": "assignment",
                    "amount": 1,
                }
            ]
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/bulk", json=payload
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "processed" in data
        assert "failed" in data
        assert "results" in data

    def test_bulk_increment_multiple_counter_types(self, admin_client, counter_mock):
        """Bulk increment handles mixed counter types in a single request."""
        payload = {
            "increments": [
                {
                    "experiment_id": _TEST_EXP_ID,
                    "variant_id": _TEST_VARIANT_A,
                    "counter_type": "assignment",
                    "amount": 1,
                },
                {
                    "experiment_id": _TEST_EXP_ID,
                    "variant_id": _TEST_VARIANT_A,
                    "counter_type": "event",
                    "amount": 2,
                },
                {
                    "experiment_id": _TEST_EXP_ID,
                    "variant_id": _TEST_VARIANT_A,
                    "counter_type": "conversion",
                    "amount": 1,
                },
            ]
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/bulk", json=payload
        )
        assert response.status_code == 200, response.text

    def test_bulk_increment_too_many_items_returns_422(self, admin_client, counter_mock):
        """More than 100 items in bulk request fails validation — returns 422."""
        increments = [
            {
                "experiment_id": _TEST_EXP_ID,
                "variant_id": f"variant-{i}",
                "counter_type": "assignment",
                "amount": 1,
            }
            for i in range(101)  # 101 items — exceeds max_length=100
        ]
        payload = {"increments": increments}
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/bulk", json=payload
        )
        assert response.status_code == 422, response.text

    def test_bulk_increment_empty_list_returns_422(self, admin_client, counter_mock):
        """Empty increments list fails validation (min_length=1) — returns 422."""
        payload = {"increments": []}
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/bulk", json=payload
        )
        assert response.status_code == 422, response.text

    def test_bulk_increment_missing_increments_field_returns_422(
        self, admin_client, counter_mock
    ):
        """Missing increments field returns 422."""
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/bulk", json={}
        )
        assert response.status_code == 422, response.text

    def test_bulk_service_called_with_increment_list(self, admin_client, counter_mock):
        """The service bulk_increment is called with the list of IncrementRequest objects."""
        payload = {
            "increments": [
                {
                    "experiment_id": _TEST_EXP_ID,
                    "variant_id": _TEST_VARIANT_A,
                    "counter_type": "assignment",
                    "amount": 5,
                }
            ]
        }
        admin_client.post(f"/api/v1/counters/{_TEST_EXP_ID}/bulk", json=payload)
        assert counter_mock.bulk_increment.called

    def test_analyst_can_bulk_increment(self, analyst_client, counter_mock):
        """Analyst can use bulk increment — no special permission required."""
        payload = {
            "increments": [
                {
                    "experiment_id": _TEST_EXP_ID,
                    "variant_id": _TEST_VARIANT_A,
                    "counter_type": "event",
                    "amount": 1,
                }
            ]
        }
        response = analyst_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/bulk", json=payload
        )
        assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# POST /api/v1/counters/{experiment_id}/reset
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestResetCounters:
    """POST /api/v1/counters/{experiment_id}/reset  (ADMIN only)"""

    def test_admin_can_reset_counters(self, admin_client, counter_mock):
        """Admin user can reset counters — returns 200 with status ok."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "reason": "Integration test reset",
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload
        )
        assert response.status_code == 200, response.text

    def test_reset_response_contains_status_ok(self, admin_client, counter_mock):
        """Reset response body includes status=ok and experiment_id."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "reason": "Test reset reason",
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "ok"
        assert data["experiment_id"] == _TEST_EXP_ID

    def test_non_admin_developer_cannot_reset(self, developer_client, counter_mock):
        """Developer cannot reset counters — returns 403."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "reason": "Developer should not reset",
        }
        response = developer_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload
        )
        assert response.status_code == 403, response.text

    def test_analyst_cannot_reset_counters(self, analyst_client, counter_mock):
        """Analyst cannot reset counters — returns 403."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "reason": "Analyst should not reset",
        }
        response = analyst_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload
        )
        assert response.status_code == 403, response.text

    def test_viewer_cannot_reset_counters(self, viewer_client, counter_mock):
        """Viewer cannot reset counters — returns 403."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "reason": "Viewer should not reset",
        }
        response = viewer_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload
        )
        assert response.status_code == 403, response.text

    def test_reset_missing_reason_returns_422(self, admin_client, counter_mock):
        """Missing required 'reason' field returns 422."""
        payload = {"experiment_id": _TEST_EXP_ID}
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload
        )
        assert response.status_code == 422, response.text

    def test_reset_for_specific_variant(self, admin_client, counter_mock):
        """Admin can reset counters for a specific variant — returns 200."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_A,
            "reason": "Resetting specific variant",
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload
        )
        assert response.status_code == 200, response.text

    def test_reset_for_specific_counter_type(self, admin_client, counter_mock):
        """Admin can reset only one counter type — returns 200."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "counter_type": "assignment",
            "reason": "Resetting assignment counter",
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload
        )
        assert response.status_code == 200, response.text

    def test_reset_service_called_with_correct_args(self, admin_client, counter_mock):
        """Verify the service method is called with the correct arguments."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "variant_id": _TEST_VARIANT_B,
            "reason": "Verify args",
        }
        admin_client.post(f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload)

        counter_mock.reset_counters.assert_called_once_with(
            experiment_id=_TEST_EXP_ID,
            variant_id=_TEST_VARIANT_B,
            counter_type=None,
            reason="Verify args",
        )

    def test_reset_reason_too_long_returns_422(self, admin_client, counter_mock):
        """reason field exceeding 256 chars returns 422."""
        payload = {
            "experiment_id": _TEST_EXP_ID,
            "reason": "x" * 257,  # max_length=256
        }
        response = admin_client.post(
            f"/api/v1/counters/{_TEST_EXP_ID}/reset", json=payload
        )
        assert response.status_code == 422, response.text
