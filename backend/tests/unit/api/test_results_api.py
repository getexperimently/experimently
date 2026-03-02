"""
Unit tests for EP-016 Analytics & Experiment Results Engine — Results API endpoints.

These are TDD skeleton tests written BEFORE the implementation. They will fail until
the corresponding implementation in backend/app/api/v1/endpoints/results.py and
backend/app/schemas/results.py is complete.

Expected endpoint layout (to be implemented):
  GET  /api/v1/results/{experiment_id}
  GET  /api/v1/results/{experiment_id}/daily
  GET  /api/v1/results/{experiment_id}/sample-size
  POST /api/v1/results/{experiment_id}/invalidate-cache
"""

import pytest
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.deps import get_db, get_current_user
from backend.app.models.user import User

# TODO: implement — these schemas don't exist yet; they will be created as part of EP-016
# from backend.app.schemas.results import (
#     ExperimentResultsResponse,
#     DailyResultsResponse,
#     SampleSizeStatusResponse,
# )

# TODO: implement — AnalysisService will gain new methods as part of EP-016
from backend.app.services.analysis_service import AnalysisService


# ---------------------------------------------------------------------------
# Shared UUIDs used across fixtures
# ---------------------------------------------------------------------------

EXPERIMENT_UUID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONTROL_VARIANT_UUID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TREATMENT_VARIANT_UUID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
METRIC_UUID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
USER_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")
UNKNOWN_EXPERIMENT_UUID = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def experiment_id() -> uuid.UUID:
    """A stable experiment UUID used in all result tests."""
    return EXPERIMENT_UUID


@pytest.fixture
def mock_experiment_results() -> Dict[str, Any]:
    """
    Realistic fake result dict matching the expected ExperimentResultsResponse structure.

    The control variant has no p-value (None), while the treatment variant has a
    p-value < 0.05 and is flagged as statistically significant.
    """
    return {
        "experiment_id": str(EXPERIMENT_UUID),
        "experiment_name": "Button Colour A/B Test",
        "status": "active",
        "start_date": "2026-01-01T00:00:00+00:00",
        "end_date": None,
        "confidence_level": 0.95,
        "correction_method": "none",
        "computed_at": "2026-03-01T12:00:00+00:00",
        "sample_size_adequate": True,
        "metrics": [
            {
                "metric_id": str(METRIC_UUID),
                "metric_name": "Checkout Conversion",
                "metric_type": "conversion",
                "is_primary": True,
                "has_significant_result": True,
                "winning_variant_id": str(TREATMENT_VARIANT_UUID),
                "variants": [
                    {
                        "variant_id": str(CONTROL_VARIANT_UUID),
                        "variant_name": "Control",
                        "is_control": True,
                        "sample_size": 5000,
                        "conversions": 500,
                        "mean": 0.10,  # conversion rate as [0,1]
                        "confidence_interval": [0.0917, 0.1083],
                        "p_value": None,
                        "adjusted_p_value": None,
                        "is_significant": False,
                        "relative_improvement_pct": None,
                        "effect_size": None,
                        "effect_size_label": None,
                        "statistical_test_used": None,
                    },
                    {
                        "variant_id": str(TREATMENT_VARIANT_UUID),
                        "variant_name": "Treatment — Blue Button",
                        "is_control": False,
                        "sample_size": 5000,
                        "conversions": 600,
                        "mean": 0.12,  # conversion rate as [0,1]
                        "confidence_interval": [0.1110, 0.1290],
                        "p_value": 0.0012,
                        "adjusted_p_value": None,
                        "is_significant": True,
                        "relative_improvement_pct": 20.0,
                        "effect_size": 0.062,
                        "effect_size_label": "small",
                        "statistical_test_used": "z_test_proportions",
                    },
                ],
            }
        ],
        "summary": {
            "total_users": 10000,
            "total_events": 1100,
            "total_conversions": 1100,
            "duration_days": 59,
            "has_winner": True,
            "winning_variant_id": str(TREATMENT_VARIANT_UUID),
            "recommendation": "SHIP_VARIANT",
            "recommendation_reason": "Treatment variant shows 20% improvement with p=0.0012.",
        },
    }


@pytest.fixture
def mock_daily_results() -> List[Dict[str, Any]]:
    """
    Fake daily results list matching the expected DailyResultsResponse structure.

    Returns two days of cumulative conversion data for one metric with two variants.
    """
    return [
        {
            "date": "2026-01-01",
            "cumulative": True,
            "metrics": [
                {
                    "metric_id": str(METRIC_UUID),
                    "metric_name": "Checkout Conversion",
                    "variants": [
                        {
                            "variant_id": str(CONTROL_VARIANT_UUID),
                            "variant_name": "Control",
                            "is_control": True,
                            "assignments": 100,
                            "conversions": 10,
                            "conversion_rate": 10.0,
                        },
                        {
                            "variant_id": str(TREATMENT_VARIANT_UUID),
                            "variant_name": "Treatment — Blue Button",
                            "is_control": False,
                            "assignments": 100,
                            "conversions": 12,
                            "conversion_rate": 12.0,
                        },
                    ],
                }
            ],
        },
        {
            "date": "2026-01-02",
            "cumulative": True,
            "metrics": [
                {
                    "metric_id": str(METRIC_UUID),
                    "metric_name": "Checkout Conversion",
                    "variants": [
                        {
                            "variant_id": str(CONTROL_VARIANT_UUID),
                            "variant_name": "Control",
                            "is_control": True,
                            "assignments": 220,
                            "conversions": 22,
                            "conversion_rate": 10.0,
                        },
                        {
                            "variant_id": str(TREATMENT_VARIANT_UUID),
                            "variant_name": "Treatment — Blue Button",
                            "is_control": False,
                            "assignments": 215,
                            "conversions": 26,
                            "conversion_rate": 12.09,
                        },
                    ],
                }
            ],
        },
    ]


@pytest.fixture
def auth_headers() -> Dict[str, str]:
    """Authorization headers used in all authenticated requests."""
    return {"Authorization": "Bearer mock_test_token"}


@pytest.fixture
def mock_db():
    """Mock SQLAlchemy database session."""
    return MagicMock()


@pytest.fixture
def mock_user() -> MagicMock:
    """Mock authenticated superuser."""
    user = MagicMock(spec=User)
    user.id = USER_UUID
    user.email = "analyst@example.com"
    user.is_active = True
    user.is_superuser = True
    user.role = "ADMIN"
    return user


@pytest.fixture
def client(mock_db, mock_user):
    """
    FastAPI TestClient with mocked DB and auth dependencies.

    Follows the same pattern used in test_metrics_endpoints.py — override
    get_db and get_current_user in app.dependency_overrides so we never
    touch a real database or real Cognito during unit tests.
    """

    def override_get_db():
        try:
            yield mock_db
        finally:
            pass

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    # Clean up dependency overrides after each test
    app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# TestGetExperimentResults
# ---------------------------------------------------------------------------


class TestGetExperimentResults:
    """Tests for GET /api/v1/results/{experiment_id}."""

    @pytest.mark.unit
    def test_get_results_returns_200_for_valid_experiment(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
        mock_experiment_results: Dict[str, Any],
    ):
        """
        A valid experiment ID should return HTTP 200 and the results payload.

        The AnalysisService.get_experiment_results method is mocked to avoid DB
        interaction; we only care that the endpoint marshals the response correctly.
        """
        # TODO: implement — patch the final location of AnalysisService once the
        # full endpoint is wired up in results.py
        with patch.object(
            AnalysisService,
            "get_experiment_results",
            return_value=mock_experiment_results,
        ):
            response = client.get(f"/api/v1/results/{experiment_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["experiment_id"] == str(experiment_id)
        assert "metrics" in data
        assert "summary" in data

    @pytest.mark.unit
    def test_get_results_returns_404_for_unknown_experiment(
        self,
        client: TestClient,
    ):
        """
        A non-existent experiment ID must yield HTTP 404.

        The service raises ValueError when the experiment is not found; the endpoint
        is expected to convert that into a 404 HTTPException.
        """
        with patch.object(
            AnalysisService,
            "get_experiment_results",
            side_effect=ValueError(f"Experiment {UNKNOWN_EXPERIMENT_UUID} not found"),
        ):
            response = client.get(
                f"/api/v1/results/{UNKNOWN_EXPERIMENT_UUID}"
            )

        assert response.status_code == 404

    @pytest.mark.unit
    def test_get_results_returns_400_when_no_assignments(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
    ):
        """
        If the experiment exists but has received zero assignments the endpoint
        should return HTTP 400 with a descriptive error message.

        This guards against computing statistics on empty data which would produce
        meaningless (or division-by-zero) results.
        """
        # TODO: implement — AnalysisService will raise a specific exception type
        # (e.g. InsufficientDataError) when there are no assignments
        with patch.object(
            AnalysisService,
            "get_experiment_results",
            side_effect=ValueError("Experiment has no assignments; cannot compute results"),
        ):
            # use_cache=false ensures the service is called (not served from Redis cache)
            response = client.get(
                f"/api/v1/results/{experiment_id}",
                params={"use_cache": "false"},
            )

        # Endpoint should map "no assignments" to 400, not 404
        assert response.status_code in (400, 404)

    @pytest.mark.unit
    def test_get_results_respects_confidence_level_param(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
        mock_experiment_results: Dict[str, Any],
    ):
        """
        The ?confidence_level query parameter (e.g. 0.99) must be forwarded to
        AnalysisService so the correct z-score is used for confidence intervals.
        """
        # Override confidence level in the expected response
        high_confidence_results = {
            **mock_experiment_results,
            "confidence_level": 0.99,
        }

        with patch.object(
            AnalysisService,
            "get_experiment_results",
            return_value=high_confidence_results,
        ) as mock_service:
            response = client.get(
                f"/api/v1/results/{experiment_id}",
                params={"confidence_level": 0.99},
            )

        assert response.status_code == 200
        data = response.json()
        # The service should have been called; confidence_level forwarded
        assert data.get("confidence_level") == 0.99

    @pytest.mark.unit
    def test_get_results_applies_bonferroni_correction(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
        mock_experiment_results: Dict[str, Any],
    ):
        """
        Passing ?correction_method=bonferroni should trigger Bonferroni correction
        and be reflected in the response payload.

        Bonferroni multiplies each p-value by the number of metrics tested;
        this keeps family-wise error rate under control for multi-metric experiments.
        """
        bonferroni_results = {
            **mock_experiment_results,
            "correction_method": "bonferroni",
        }

        with patch.object(
            AnalysisService,
            "get_experiment_results",
            return_value=bonferroni_results,
        ):
            response = client.get(
                f"/api/v1/results/{experiment_id}",
                params={"correction_method": "bonferroni"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data.get("correction_method") == "bonferroni"

    @pytest.mark.unit
    def test_get_results_response_schema_is_valid(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
        mock_experiment_results: Dict[str, Any],
    ):
        """
        The JSON response must contain all top-level fields required by
        ExperimentResultsResponse (to be defined in backend/app/schemas/results.py).

        Required top-level keys:
          experiment_id, experiment_name, status, metrics, summary
        """
        with patch.object(
            AnalysisService,
            "get_experiment_results",
            return_value=mock_experiment_results,
        ):
            response = client.get(f"/api/v1/results/{experiment_id}")

        assert response.status_code == 200
        data = response.json()

        # Top-level schema fields
        required_keys = {
            "experiment_id",
            "experiment_name",
            "status",
            "metrics",
            "summary",
        }
        for key in required_keys:
            assert key in data, f"Missing required key '{key}' in response"

        # Validate a variant result sub-schema
        assert len(data["metrics"]) > 0
        variant_results = data["metrics"][0]["variants"]
        assert len(variant_results) > 0
        variant_keys = {
            "variant_id",
            "variant_name",
            "is_control",
            "sample_size",
            "mean",
            "confidence_interval",
            "is_significant",
        }
        for vr in variant_results:
            for key in variant_keys:
                assert key in vr, f"Missing variant result key '{key}'"

    @pytest.mark.unit
    def test_get_results_control_variant_has_no_p_value(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
        mock_experiment_results: Dict[str, Any],
    ):
        """
        The control variant's p_value must be None.

        Statistical significance is always measured relative to the control, so
        comparing the control to itself is meaningless.  The response must
        explicitly set p_value=null for the control variant.
        """
        with patch.object(
            AnalysisService,
            "get_experiment_results",
            return_value=mock_experiment_results,
        ):
            response = client.get(f"/api/v1/results/{experiment_id}")

        assert response.status_code == 200
        data = response.json()

        variant_results = data["metrics"][0]["variants"]
        control_results = [vr for vr in variant_results if vr["is_control"]]
        assert len(control_results) == 1, "Expected exactly one control variant"
        assert control_results[0]["p_value"] is None, (
            "Control variant p_value must be null — it has no baseline to compare against"
        )

    @pytest.mark.unit
    def test_get_results_significant_variant_is_flagged(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
        mock_experiment_results: Dict[str, Any],
    ):
        """
        Any treatment variant whose p_value < alpha must have is_significant=True.

        This test verifies the endpoint surfaces statistical significance correctly
        for consumers (dashboards, automated decision systems).
        """
        with patch.object(
            AnalysisService,
            "get_experiment_results",
            return_value=mock_experiment_results,
        ):
            response = client.get(f"/api/v1/results/{experiment_id}")

        assert response.status_code == 200
        data = response.json()

        variant_results = data["metrics"][0]["variants"]
        treatment_results = [vr for vr in variant_results if not vr["is_control"]]
        # The fixture has p_value=0.0012 for the treatment variant (< 0.05 threshold)
        for vr in treatment_results:
            if vr.get("p_value") is not None and vr["p_value"] < 0.05:
                assert vr["is_significant"] is True, (
                    f"Variant {vr['variant_name']} has p_value={vr['p_value']} < 0.05 "
                    f"but is_significant is not True"
                )


# ---------------------------------------------------------------------------
# TestGetDailyResults
# ---------------------------------------------------------------------------


class TestGetDailyResults:
    """Tests for GET /api/v1/results/{experiment_id}/daily."""

    @pytest.mark.unit
    def test_get_daily_results_returns_200(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
        mock_daily_results: List[Dict[str, Any]],
    ):
        """
        The daily results endpoint must return HTTP 200 and a list of daily data points.
        """
        # TODO: implement — wire up the /daily endpoint in results.py
        with patch.object(
            AnalysisService,
            "get_daily_results",
            return_value=mock_daily_results,
        ):
            response = client.get(
                f"/api/v1/results/{experiment_id}/daily"
            )

        assert response.status_code == 200
        data = response.json()
        # DailyResultsResponse is a dict with experiment_id, metric_id, series
        assert isinstance(data, dict)
        assert "series" in data
        assert isinstance(data["series"], list)
        # fixture has 2 days × 2 variants — each variant gets one VariantTimeSeries
        assert len(data["series"]) > 0

    @pytest.mark.unit
    def test_get_daily_results_returns_cumulative_series(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
        mock_daily_results: List[Dict[str, Any]],
    ):
        """
        Each VariantTimeSeries in the response must have both a values list (daily)
        and a cumulative list (running totals).

        Cumulative series are required for sequential testing dashboards where
        analysts need to see whether the trajectory is converging.
        """
        with patch.object(
            AnalysisService,
            "get_daily_results",
            return_value=mock_daily_results,
        ):
            response = client.get(
                f"/api/v1/results/{experiment_id}/daily",
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["series"]) > 0
        for variant_series in data["series"]:
            assert "values" in variant_series, "Each series must have a 'values' list"
            assert "cumulative" in variant_series, "Each series must have a 'cumulative' list"
            assert len(variant_series["values"]) > 0, "values must not be empty"
            assert len(variant_series["cumulative"]) > 0, "cumulative must not be empty"

    @pytest.mark.unit
    def test_get_daily_results_filters_by_metric_id(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
        mock_daily_results: List[Dict[str, Any]],
    ):
        """
        The ?metric_id query parameter must be passed through to the service.

        When provided, the service is expected to return only data for that metric.
        """
        with patch.object(
            AnalysisService,
            "get_daily_results",
            return_value=mock_daily_results,
        ) as mock_svc:
            response = client.get(
                f"/api/v1/results/{experiment_id}/daily",
                params={"metric_id": str(METRIC_UUID)},
            )

        assert response.status_code == 200
        # Verify the service was called with the metric_id
        mock_svc.assert_called_once()
        call_kwargs = mock_svc.call_args
        assert str(METRIC_UUID) in str(call_kwargs), (
            "Service must be called with the metric_id filter"
        )


# ---------------------------------------------------------------------------
# TestGetSampleSize
# ---------------------------------------------------------------------------


class TestGetSampleSize:
    """Tests for GET /api/v1/results/{experiment_id}/sample-size."""

    @pytest.mark.unit
    def test_sample_size_returns_adequate_when_large_enough(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
    ):
        """
        When the experiment has accumulated enough assignments the response must
        indicate that the sample size is adequate (adequate=True, status="adequate").

        Adequate sample size is determined against the pre-configured minimum
        detectable effect (MDE) and power settings for each metric.
        """
        # TODO: implement — endpoint and service method for sample size assessment
        adequate_response = {
            "required_sample_size_per_variant": 3843,
            "current_sample_size_per_variant": 5000,
            "is_adequate": True,
            "achieved_power": 0.91,
            "days_to_significance": None,
            "projected_completion_date": None,
            "baseline_rate": 0.10,
            "mde": 0.05,
            "confidence_level": 0.95,
            "power_target": 0.80,
        }

        with patch.object(
            AnalysisService,
            "get_sample_size_status",
            return_value=adequate_response,
            create=True,
        ):
            response = client.get(
                f"/api/v1/results/{experiment_id}/sample-size"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["is_adequate"] is True
        assert data["current_sample_size_per_variant"] >= data["required_sample_size_per_variant"]

    @pytest.mark.unit
    def test_sample_size_returns_inadequate_when_small(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
    ):
        """
        When not enough data has been collected the endpoint must return
        adequate=False and status="inadequate" so the dashboard can warn users
        not to call the experiment early.

        Early stopping due to peeking is a well-known source of inflated
        false-positive rates in online experimentation.
        """
        inadequate_response = {
            "required_sample_size_per_variant": 3843,
            "current_sample_size_per_variant": 150,
            "is_adequate": False,
            "achieved_power": 0.12,
            "days_to_significance": 45,
            "projected_completion_date": None,
            "baseline_rate": 0.10,
            "mde": 0.05,
            "confidence_level": 0.95,
            "power_target": 0.80,
        }

        with patch.object(
            AnalysisService,
            "get_sample_size_status",
            return_value=inadequate_response,
            create=True,
        ):
            response = client.get(
                f"/api/v1/results/{experiment_id}/sample-size"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["is_adequate"] is False
        assert data["current_sample_size_per_variant"] < data["required_sample_size_per_variant"]

    @pytest.mark.unit
    def test_sample_size_validates_baseline_rate_range(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
    ):
        """
        Passing an invalid baseline_conversion_rate (outside [0, 1]) must cause
        a 422 Unprocessable Entity validation error from FastAPI before the
        service layer is even invoked.
        """
        # baseline_conversion_rate must be 0 < x < 1
        response = client.get(
            f"/api/v1/results/{experiment_id}/sample-size",
            params={"baseline_conversion_rate": 1.5},  # invalid — > 1
        )

        # FastAPI should reject with 422 validation error
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# TestInvalidateCache
# ---------------------------------------------------------------------------


class TestInvalidateCache:
    """Tests for POST /api/v1/results/{experiment_id}/invalidate-cache."""

    @pytest.mark.unit
    def test_invalidate_cache_returns_200(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
    ):
        """
        A successful cache invalidation request must return HTTP 200.

        The results cache stores pre-computed statistical results to reduce
        database load.  When new events arrive, the cache must be invalidated
        so the next request recomputes fresh results.
        """
        # TODO: implement — cache invalidation method on AnalysisService
        response = client.post(
            f"/api/v1/results/{experiment_id}/invalidate-cache"
        )

        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("experiment_id") == str(experiment_id)

    @pytest.mark.unit
    def test_invalidate_cache_requires_admin(
        self,
        client: TestClient,
        experiment_id: uuid.UUID,
    ):
        """
        Cache invalidation is a privileged operation that must be restricted to
        ADMIN (or DEVELOPER) users.  A VIEWER user must receive HTTP 403.

        This prevents non-privileged users from triggering expensive recomputation
        on demand.
        """
        # Override the current user with a non-privileged viewer
        viewer_user = MagicMock(spec=User)
        viewer_user.id = uuid.uuid4()
        viewer_user.is_active = True
        viewer_user.is_superuser = False
        viewer_user.role = "VIEWER"

        async def viewer_get_current_user():
            return viewer_user

        # Temporarily override with a viewer user
        original_override = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = viewer_get_current_user

        try:
            response = client.post(
                f"/api/v1/results/{experiment_id}/invalidate-cache"
            )
        finally:
            # Restore original override (admin user) so other tests are not affected
            if original_override is not None:
                app.dependency_overrides[get_current_user] = original_override

        # A viewer must not be allowed to invalidate the cache
        assert response.status_code in (403, 401), (
            f"Expected 403 or 401 for VIEWER role, got {response.status_code}"
        )
