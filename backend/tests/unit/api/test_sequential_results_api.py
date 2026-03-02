"""
Unit tests for EP-021 Sequential Testing API endpoints.

Tests for:
  GET /api/v1/results/{experiment_id} — sequential_testing field in response
  GET /api/v1/results/{experiment_id}/sequential — dedicated sequential endpoint
"""

import pytest
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.deps import get_db, get_current_user
from backend.app.models.user import User
from backend.app.services.analysis_service import AnalysisService
from backend.app.services.sequential_testing_service import (
    SequentialTestingService,
    MSPRTResult,
    ConfidenceSequence,
    AlphaSpendingBoundary,
    EvidencePoint,
    LongRunningRisk,
    SequentialAnalysis,
    SequentialTestingMethod,
    SpendingFunction,
    EvidenceStrength,
)

# ---------------------------------------------------------------------------
# Shared UUIDs
# ---------------------------------------------------------------------------

EXPERIMENT_UUID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONTROL_UUID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TREATMENT_UUID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
METRIC_UUID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
USER_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.id = USER_UUID
    user.email = "analyst@example.com"
    user.is_active = True
    user.is_superuser = True
    user.role = "ADMIN"
    return user


@pytest.fixture
def client(mock_db, mock_user):
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

    app.dependency_overrides = {}


@pytest.fixture
def mock_experiment_results_with_sequential() -> Dict[str, Any]:
    """Experiment results with sequential testing data."""
    return {
        "experiment_id": str(EXPERIMENT_UUID),
        "experiment_name": "Sequential Test",
        "status": "active",
        "start_date": "2026-01-01T00:00:00+00:00",
        "end_date": None,
        "confidence_level": 0.95,
        "correction_method": "none",
        "computed_at": "2026-03-01T12:00:00+00:00",
        "sample_size_adequate": True,
        "sequential_testing_enabled": True,
        "metrics": [
            {
                "metric_id": str(METRIC_UUID),
                "metric_name": "Conversion",
                "metric_type": "conversion",
                "is_primary": True,
                "has_significant_result": True,
                "winning_variant_id": str(TREATMENT_UUID),
                "variants": [
                    {
                        "variant_id": str(CONTROL_UUID),
                        "variant_name": "Control",
                        "is_control": True,
                        "sample_size": 5000,
                        "conversions": 500,
                        "mean": 0.10,
                        "confidence_interval": [0.09, 0.11],
                        "p_value": None,
                        "adjusted_p_value": None,
                        "is_significant": False,
                        "relative_improvement_pct": None,
                        "effect_size": None,
                        "effect_size_label": None,
                        "statistical_test_used": None,
                    },
                    {
                        "variant_id": str(TREATMENT_UUID),
                        "variant_name": "Treatment",
                        "is_control": False,
                        "sample_size": 5000,
                        "conversions": 600,
                        "mean": 0.12,
                        "confidence_interval": [0.11, 0.13],
                        "p_value": 0.001,
                        "adjusted_p_value": None,
                        "is_significant": True,
                        "relative_improvement_pct": 20.0,
                        "effect_size": 0.06,
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
            "duration_days": 30,
            "has_winner": True,
            "winning_variant_id": str(TREATMENT_UUID),
            "recommendation": "SHIP_VARIANT",
            "recommendation_reason": "Treatment wins with p=0.001.",
        },
    }


@pytest.fixture
def mock_sequential_analysis():
    """Mock sequential analysis result."""
    return SequentialAnalysis(
        method=SequentialTestingMethod.MSPRT,
        msprt_result=MSPRTResult(
            lambda_ratio=25.0,
            always_valid_p_value=0.04,
            can_stop=True,
            evidence_strength=EvidenceStrength.STRONG_FOR_EFFECT,
            boundary=20.0,
        ),
        confidence_sequence=ConfidenceSequence(
            lower=0.01,
            upper=0.08,
            width=0.07,
            sample_size=10000,
        ),
        evidence_trajectory=[
            EvidencePoint(sample_size=2000, lambda_ratio=3.5, always_valid_p_value=0.28, can_stop=False),
            EvidencePoint(sample_size=5000, lambda_ratio=12.0, always_valid_p_value=0.08, can_stop=False),
            EvidencePoint(sample_size=10000, lambda_ratio=25.0, always_valid_p_value=0.04, can_stop=True),
        ],
        alpha_spending=[
            AlphaSpendingBoundary(look_number=1, cumulative_alpha=0.001, boundary_z=3.29, boundary_p=0.001),
            AlphaSpendingBoundary(look_number=2, cumulative_alpha=0.01, boundary_z=2.58, boundary_p=0.01),
        ],
        long_running_risk=None,
        recommended_action="stop_for_effect",
    )


# ---------------------------------------------------------------------------
# Tests for sequential_testing field in main results
# ---------------------------------------------------------------------------


class TestSequentialTestingInResults:
    """Tests for sequential_testing field in GET /api/v1/results/{experiment_id}."""

    @pytest.mark.unit
    def test_results_include_sequential_testing_null_when_disabled(
        self, client, mock_experiment_results_with_sequential
    ):
        """Non-sequential experiments should have sequential_testing=null."""
        results = {
            **mock_experiment_results_with_sequential,
            "sequential_testing_enabled": False,
            # No "sequential_testing" key — should remain null in response
        }
        results.pop("sequential_testing", None)

        with patch(
            "backend.app.api.v1.endpoints.results.AnalysisService"
        ) as MockCls:
            mock_instance = MagicMock()
            mock_instance.get_experiment_results.return_value = results
            MockCls.return_value = mock_instance
            response = client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}",
                params={"use_cache": "false"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data.get("sequential_testing") is None

    @pytest.mark.unit
    def test_results_include_sequential_testing_when_enabled(
        self, client, mock_experiment_results_with_sequential, mock_sequential_analysis
    ):
        """Sequential experiments should have sequential_testing populated."""
        results = {
            **mock_experiment_results_with_sequential,
            "sequential_testing": {
                "method": "msprt",
                "msprt_result": {
                    "lambda_ratio": 25.0,
                    "always_valid_p_value": 0.04,
                    "can_stop": True,
                    "evidence_strength": "strong_for_effect",
                    "boundary": 20.0,
                },
                "confidence_sequence": {
                    "lower": 0.01, "upper": 0.08, "width": 0.07, "sample_size": 10000,
                },
                "evidence_trajectory": [],
                "alpha_spending": [],
                "long_running_risk": None,
                "recommended_action": "stop_for_effect",
            },
        }

        with patch(
            "backend.app.api.v1.endpoints.results.AnalysisService"
        ) as MockCls:
            mock_instance = MagicMock()
            mock_instance.get_experiment_results.return_value = results
            MockCls.return_value = mock_instance
            response = client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}",
                params={"use_cache": "false"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["sequential_testing"] is not None
        assert data["sequential_testing"]["method"] == "msprt"
        assert data["sequential_testing"]["recommended_action"] == "stop_for_effect"

    @pytest.mark.unit
    def test_sequential_msprt_result_fields(
        self, client, mock_experiment_results_with_sequential
    ):
        """mSPRT result should contain lambda_ratio, can_stop, evidence_strength."""
        results = {
            **mock_experiment_results_with_sequential,
            "sequential_testing": {
                "method": "msprt",
                "msprt_result": {
                    "lambda_ratio": 25.0,
                    "always_valid_p_value": 0.04,
                    "can_stop": True,
                    "evidence_strength": "strong_for_effect",
                    "boundary": 20.0,
                },
                "evidence_trajectory": [],
                "alpha_spending": [],
                "recommended_action": "stop_for_effect",
            },
        }

        with patch(
            "backend.app.api.v1.endpoints.results.AnalysisService"
        ) as MockCls:
            mock_instance = MagicMock()
            mock_instance.get_experiment_results.return_value = results
            MockCls.return_value = mock_instance
            response = client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}",
                params={"use_cache": "false"},
            )

        assert response.status_code == 200
        msprt = response.json()["sequential_testing"]["msprt_result"]
        assert msprt["lambda_ratio"] == 25.0
        assert msprt["can_stop"] is True
        assert msprt["evidence_strength"] == "strong_for_effect"
        assert msprt["boundary"] == 20.0

    @pytest.mark.unit
    def test_sequential_confidence_sequence_fields(
        self, client, mock_experiment_results_with_sequential
    ):
        """Confidence sequence should contain lower, upper, width, sample_size."""
        results = {
            **mock_experiment_results_with_sequential,
            "sequential_testing": {
                "method": "msprt",
                "confidence_sequence": {
                    "lower": 0.01, "upper": 0.08, "width": 0.07, "sample_size": 10000,
                },
                "evidence_trajectory": [],
                "alpha_spending": [],
                "recommended_action": "stop_for_effect",
            },
        }

        with patch(
            "backend.app.api.v1.endpoints.results.AnalysisService"
        ) as MockCls:
            mock_instance = MagicMock()
            mock_instance.get_experiment_results.return_value = results
            MockCls.return_value = mock_instance
            response = client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}",
                params={"use_cache": "false"},
            )

        assert response.status_code == 200
        cs = response.json()["sequential_testing"]["confidence_sequence"]
        assert cs["lower"] == 0.01
        assert cs["upper"] == 0.08
        assert cs["width"] == 0.07


# ---------------------------------------------------------------------------
# Tests for dedicated sequential endpoint
# ---------------------------------------------------------------------------


class TestGetSequentialResults:
    """Tests for GET /api/v1/results/{experiment_id}/sequential."""

    @pytest.mark.unit
    def test_sequential_endpoint_returns_200(self, client, mock_sequential_analysis):
        """Dedicated sequential endpoint returns 200 with evidence trajectory."""
        with patch(
            "backend.app.api.v1.endpoints.results.SequentialTestingService"
        ) as MockService:
            mock_instance = MockService.return_value
            mock_instance.run_sequential_analysis.return_value = mock_sequential_analysis

            # Also need to mock the experiment lookup
            mock_experiment = MagicMock()
            mock_experiment.sequential_testing_enabled = True
            mock_experiment.sequential_testing_method = "msprt"
            mock_experiment.sequential_testing_config = {"tau_squared": 0.001}
            mock_experiment.status.value = "active"
            mock_experiment.start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

            with patch(
                "backend.app.api.v1.endpoints.results._get_experiment_for_sequential",
                return_value=mock_experiment,
            ):
                with patch(
                    "backend.app.api.v1.endpoints.results._get_sequential_data",
                    return_value=(500, 5000, 600, 5000),
                ):
                    response = client.get(
                        f"/api/v1/results/{EXPERIMENT_UUID}/sequential"
                    )

        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "msprt"
        assert data["recommended_action"] == "stop_for_effect"

    @pytest.mark.unit
    def test_sequential_endpoint_returns_404_when_not_enabled(self, client):
        """Returns 404 when sequential testing not enabled for experiment."""
        mock_experiment = MagicMock()
        mock_experiment.sequential_testing_enabled = False

        with patch(
            "backend.app.api.v1.endpoints.results._get_experiment_for_sequential",
            return_value=mock_experiment,
        ):
            response = client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}/sequential"
            )

        assert response.status_code == 404

    @pytest.mark.unit
    def test_sequential_endpoint_returns_evidence_trajectory(
        self, client, mock_sequential_analysis
    ):
        """Evidence trajectory should contain data points for charting."""
        with patch(
            "backend.app.api.v1.endpoints.results.SequentialTestingService"
        ) as MockService:
            mock_instance = MockService.return_value
            mock_instance.run_sequential_analysis.return_value = mock_sequential_analysis

            mock_experiment = MagicMock()
            mock_experiment.sequential_testing_enabled = True
            mock_experiment.sequential_testing_method = "msprt"
            mock_experiment.sequential_testing_config = {"tau_squared": 0.001}
            mock_experiment.status.value = "active"
            mock_experiment.start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

            with patch(
                "backend.app.api.v1.endpoints.results._get_experiment_for_sequential",
                return_value=mock_experiment,
            ):
                with patch(
                    "backend.app.api.v1.endpoints.results._get_sequential_data",
                    return_value=(500, 5000, 600, 5000),
                ):
                    response = client.get(
                        f"/api/v1/results/{EXPERIMENT_UUID}/sequential"
                    )

        assert response.status_code == 200
        data = response.json()
        assert len(data["evidence_trajectory"]) == 3
        assert data["evidence_trajectory"][0]["sample_size"] == 2000

    @pytest.mark.unit
    def test_sequential_endpoint_returns_alpha_spending(
        self, client, mock_sequential_analysis
    ):
        """Alpha spending boundaries should be included."""
        with patch(
            "backend.app.api.v1.endpoints.results.SequentialTestingService"
        ) as MockService:
            mock_instance = MockService.return_value
            mock_instance.run_sequential_analysis.return_value = mock_sequential_analysis

            mock_experiment = MagicMock()
            mock_experiment.sequential_testing_enabled = True
            mock_experiment.sequential_testing_method = "msprt"
            mock_experiment.sequential_testing_config = {"tau_squared": 0.001}
            mock_experiment.status.value = "active"
            mock_experiment.start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

            with patch(
                "backend.app.api.v1.endpoints.results._get_experiment_for_sequential",
                return_value=mock_experiment,
            ):
                with patch(
                    "backend.app.api.v1.endpoints.results._get_sequential_data",
                    return_value=(500, 5000, 600, 5000),
                ):
                    response = client.get(
                        f"/api/v1/results/{EXPERIMENT_UUID}/sequential"
                    )

        assert response.status_code == 200
        data = response.json()
        assert len(data["alpha_spending"]) == 2
        assert data["alpha_spending"][0]["look_number"] == 1

    @pytest.mark.unit
    def test_sequential_endpoint_returns_404_for_missing_experiment(self, client):
        """Returns 404 when experiment doesn't exist."""
        with patch(
            "backend.app.api.v1.endpoints.results._get_experiment_for_sequential",
            return_value=None,
        ):
            response = client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}/sequential"
            )

        assert response.status_code == 404

    @pytest.mark.unit
    def test_sequential_continue_recommendation(self, client):
        """When evidence is insufficient, recommended_action should be 'continue'."""
        analysis = SequentialAnalysis(
            method=SequentialTestingMethod.MSPRT,
            msprt_result=MSPRTResult(
                lambda_ratio=3.0,
                always_valid_p_value=0.33,
                can_stop=False,
                evidence_strength=EvidenceStrength.INCONCLUSIVE,
                boundary=20.0,
            ),
            confidence_sequence=None,
            evidence_trajectory=[],
            alpha_spending=[],
            long_running_risk=None,
            recommended_action="continue",
        )

        with patch(
            "backend.app.api.v1.endpoints.results.SequentialTestingService"
        ) as MockService:
            mock_instance = MockService.return_value
            mock_instance.run_sequential_analysis.return_value = analysis

            mock_experiment = MagicMock()
            mock_experiment.sequential_testing_enabled = True
            mock_experiment.sequential_testing_method = "msprt"
            mock_experiment.sequential_testing_config = {"tau_squared": 0.001}
            mock_experiment.status.value = "active"
            mock_experiment.start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

            with patch(
                "backend.app.api.v1.endpoints.results._get_experiment_for_sequential",
                return_value=mock_experiment,
            ):
                with patch(
                    "backend.app.api.v1.endpoints.results._get_sequential_data",
                    return_value=(100, 1000, 100, 1000),
                ):
                    response = client.get(
                        f"/api/v1/results/{EXPERIMENT_UUID}/sequential"
                    )

        assert response.status_code == 200
        assert response.json()["recommended_action"] == "continue"
