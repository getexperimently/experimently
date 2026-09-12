"""
Integration tests for EP-043: Post-Stratification & BH FDR Correction API.

Tests the full HTTP request/response cycle for:
  POST /api/v1/results/{experiment_id}/post-stratification
  POST /api/v1/results/{experiment_id}/fdr-correction

The PostStratificationService and BenjaminiHochbergService are patched to
return predictable results, keeping tests independent of DB data volume.
"""

import uuid
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.models.experiment import (
    Experiment,
    ExperimentStatus,
    ExperimentType,
    Metric,
    MetricType,
    Variant,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPERIMENT_UUID = uuid.UUID("11111111-1111-1111-1111-111111111111")
NONEXISTENT_UUID = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_experiment_payload(name: str = "EP-043 Test") -> dict:
    """Return a minimal valid ExperimentCreate payload."""
    return {
        "name": name,
        "description": "Post-strat FDR integration test",
        "hypothesis": "Treatment outperforms control",
        "experiment_type": "a_b",
        "variants": [
            {"name": "Control", "is_control": True, "traffic_allocation": 50},
            {"name": "Treatment", "is_control": False, "traffic_allocation": 50},
        ],
        "metrics": [
            {
                "name": "Revenue",
                "event_name": "purchase",
                "metric_type": "conversion",
                "is_primary": True,
                "minimum_sample_size": 100,
            }
        ],
    }


def _create_experiment(client: TestClient, name: str = "EP-043 Test") -> dict:
    """Create experiment via API and return the response JSON."""
    payload = _valid_experiment_payload(name)
    response = client.post("/api/v1/experiments/", json=payload)
    assert response.status_code == 201, f"Failed to create experiment: {response.text}"
    return response.json()


def _make_post_strat_result() -> dict:
    """Return a mock PostStratResult dict as the service would produce."""
    return {
        "metric_name": "metric_value",
        "control_mean": 5.0,
        "treatment_mean": 5.5,
        "effect_size": 0.5,
        "effect_size_relative": 0.1,
        "variance_reduction": 25.5,
        "adjusted_se": 0.12,
        "p_value": 0.001,
        "confidence_interval": (0.26, 0.74),
        "n_strata": 2,
        "strata_sizes": {"A": 500, "B": 500},
    }


def _make_fdr_results() -> list:
    """Return a list of mock FDRResult dicts."""
    return [
        {
            "metric_name": "revenue",
            "raw_p_value": 0.001,
            "adjusted_p_value": 0.01,
            "rank": 1,
            "is_significant": True,
        },
        {
            "metric_name": "clicks",
            "raw_p_value": 0.008,
            "adjusted_p_value": 0.04,
            "rank": 2,
            "is_significant": True,
        },
        {
            "metric_name": "churn",
            "raw_p_value": 0.08,
            "adjusted_p_value": 0.26,
            "rank": 3,
            "is_significant": False,
        },
    ]


# ---------------------------------------------------------------------------
# Tests: POST /results/{id}/post-stratification
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestPostStratificationEndpoint:
    """Integration tests for the post-stratification endpoint."""

    def test_post_strat_returns_200_with_valid_payload(self, admin_client):
        """POST post-stratification with valid stratum_cols returns 200."""
        exp = _create_experiment(admin_client, "PostStrat Basic Test")
        exp_id = exp["id"]

        mock_result = _make_post_strat_result()

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.PostStratificationService.compute",
            return_value=MagicMock(**mock_result),
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/post-stratification",
                json={
                    "stratum_cols": ["country"],
                    "metric_col": "metric_value",
                    "alpha": 0.05,
                },
            )

        assert response.status_code == 200, response.text

    def test_post_strat_response_contains_required_fields(self, admin_client):
        """POST post-stratification response contains all PostStratResult fields."""
        exp = _create_experiment(admin_client, "PostStrat Fields Test")
        exp_id = exp["id"]

        mock_result = _make_post_strat_result()

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.PostStratificationService.compute",
            return_value=MagicMock(**mock_result),
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/post-stratification",
                json={"stratum_cols": ["country"]},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        required_fields = [
            "metric_name",
            "control_mean",
            "treatment_mean",
            "effect_size",
            "effect_size_relative",
            "variance_reduction",
            "adjusted_se",
            "p_value",
            "confidence_interval",
            "n_strata",
            "strata_sizes",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_post_strat_variance_reduction_in_response(self, admin_client):
        """variance_reduction field is returned in the response."""
        exp = _create_experiment(admin_client, "PostStrat VR Test")
        exp_id = exp["id"]

        mock_result = _make_post_strat_result()
        mock_result["variance_reduction"] = 42.5

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.PostStratificationService.compute",
            return_value=MagicMock(**mock_result),
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/post-stratification",
                json={"stratum_cols": ["device"]},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["variance_reduction"] == 42.5

    def test_post_strat_multiple_stratum_cols(self, admin_client):
        """POST post-stratification accepts multiple stratum_cols."""
        exp = _create_experiment(admin_client, "PostStrat MultiStrat Test")
        exp_id = exp["id"]

        mock_result = _make_post_strat_result()
        mock_result["n_strata"] = 4
        mock_result["strata_sizes"] = {
            "US_mobile": 200,
            "US_desktop": 200,
            "UK_mobile": 150,
            "UK_desktop": 150,
        }

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.PostStratificationService.compute",
            return_value=MagicMock(**mock_result),
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/post-stratification",
                json={"stratum_cols": ["country", "device"]},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["n_strata"] == 4

    def test_post_strat_nonexistent_experiment_returns_404(self, admin_client):
        """POST post-stratification with nonexistent experiment_id returns 404."""
        response = admin_client.post(
            f"/api/v1/results/{NONEXISTENT_UUID}/post-stratification",
            json={"stratum_cols": ["country"]},
        )
        assert response.status_code == 404, response.text

    def test_post_strat_missing_stratum_cols_returns_422(self, admin_client):
        """POST post-stratification without stratum_cols returns 422."""
        exp = _create_experiment(admin_client, "PostStrat Validation Test")
        exp_id = exp["id"]

        response = admin_client.post(
            f"/api/v1/results/{exp_id}/post-stratification",
            json={},  # missing stratum_cols
        )
        assert response.status_code == 422, response.text

    def test_post_strat_empty_stratum_cols_returns_422(self, admin_client):
        """POST post-stratification with empty stratum_cols list returns 422."""
        exp = _create_experiment(admin_client, "PostStrat Empty Strat Test")
        exp_id = exp["id"]

        response = admin_client.post(
            f"/api/v1/results/{exp_id}/post-stratification",
            json={"stratum_cols": []},
        )
        assert response.status_code == 422, response.text

    def test_post_strat_custom_alpha(self, admin_client):
        """POST post-stratification with custom alpha=0.01 is accepted."""
        exp = _create_experiment(admin_client, "PostStrat Alpha Test")
        exp_id = exp["id"]

        mock_result = _make_post_strat_result()

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.PostStratificationService.compute",
            return_value=MagicMock(**mock_result),
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/post-stratification",
                json={"stratum_cols": ["tier"], "alpha": 0.01},
            )

        assert response.status_code == 200, response.text

    def test_post_strat_invalid_alpha_returns_422(self, admin_client):
        """POST post-stratification with alpha > 1 returns 422."""
        exp = _create_experiment(admin_client, "PostStrat Bad Alpha Test")
        exp_id = exp["id"]

        response = admin_client.post(
            f"/api/v1/results/{exp_id}/post-stratification",
            json={"stratum_cols": ["country"], "alpha": 1.5},
        )
        assert response.status_code == 422, response.text

    def test_post_strat_service_value_error_returns_422(self, admin_client):
        """POST post-stratification returns 422 when service raises ValueError."""
        exp = _create_experiment(admin_client, "PostStrat ValError Test")
        exp_id = exp["id"]

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.PostStratificationService.compute",
            side_effect=ValueError("Stratum 'region' not found in data"),
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/post-stratification",
                json={"stratum_cols": ["region"]},
            )

        assert response.status_code in (422, 400), response.text


# ---------------------------------------------------------------------------
# Tests: POST /results/{id}/fdr-correction
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestFDRCorrectionEndpoint:
    """Integration tests for the BH FDR correction endpoint."""

    def test_fdr_correction_returns_200_with_valid_pvalues(self, admin_client):
        """POST fdr-correction with valid p_values returns 200."""
        exp = _create_experiment(admin_client, "FDR Basic Test")
        exp_id = exp["id"]

        mock_results = _make_fdr_results()

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.BenjaminiHochbergService.correct",
            return_value=[MagicMock(**r) for r in mock_results],
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/fdr-correction",
                json={
                    "p_values": {"revenue": 0.001, "clicks": 0.008, "churn": 0.08},
                    "fdr_threshold": 0.05,
                },
            )

        assert response.status_code == 200, response.text

    def test_fdr_correction_response_is_list(self, admin_client):
        """POST fdr-correction returns a JSON list."""
        exp = _create_experiment(admin_client, "FDR List Test")
        exp_id = exp["id"]

        mock_results = _make_fdr_results()

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.BenjaminiHochbergService.correct",
            return_value=[MagicMock(**r) for r in mock_results],
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/fdr-correction",
                json={"p_values": {"a": 0.01, "b": 0.05, "c": 0.5}},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert isinstance(data, list)

    def test_fdr_correction_response_contains_required_fields(self, admin_client):
        """POST fdr-correction response items contain all FDRResult fields."""
        exp = _create_experiment(admin_client, "FDR Fields Test")
        exp_id = exp["id"]

        mock_results = _make_fdr_results()

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.BenjaminiHochbergService.correct",
            return_value=[MagicMock(**r) for r in mock_results],
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/fdr-correction",
                json={"p_values": {"revenue": 0.001, "clicks": 0.008, "churn": 0.08}},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data) == 3
        required_fields = [
            "metric_name",
            "raw_p_value",
            "adjusted_p_value",
            "rank",
            "is_significant",
        ]
        for item in data:
            for field in required_fields:
                assert field in item, (
                    f"Missing field '{field}' in response item: {item}"
                )

    def test_fdr_correction_nonexistent_experiment_returns_404(self, admin_client):
        """POST fdr-correction with nonexistent experiment_id returns 404."""
        response = admin_client.post(
            f"/api/v1/results/{NONEXISTENT_UUID}/fdr-correction",
            json={"p_values": {"metric": 0.05}},
        )
        assert response.status_code == 404, response.text

    def test_fdr_correction_missing_pvalues_returns_422(self, admin_client):
        """POST fdr-correction without p_values returns 422."""
        exp = _create_experiment(admin_client, "FDR Missing PV Test")
        exp_id = exp["id"]

        response = admin_client.post(
            f"/api/v1/results/{exp_id}/fdr-correction",
            json={},  # missing p_values
        )
        assert response.status_code == 422, response.text

    def test_fdr_correction_pvalue_above_1_returns_422(self, admin_client):
        """POST fdr-correction with p_value > 1 returns 422."""
        exp = _create_experiment(admin_client, "FDR PV>1 Test")
        exp_id = exp["id"]

        response = admin_client.post(
            f"/api/v1/results/{exp_id}/fdr-correction",
            json={"p_values": {"bad_metric": 1.5}},
        )
        assert response.status_code == 422, response.text

    def test_fdr_correction_pvalue_below_0_returns_422(self, admin_client):
        """POST fdr-correction with p_value < 0 returns 422."""
        exp = _create_experiment(admin_client, "FDR PV<0 Test")
        exp_id = exp["id"]

        response = admin_client.post(
            f"/api/v1/results/{exp_id}/fdr-correction",
            json={"p_values": {"bad_metric": -0.1}},
        )
        assert response.status_code == 422, response.text

    def test_fdr_correction_custom_threshold(self, admin_client):
        """POST fdr-correction with custom fdr_threshold=0.10 is accepted."""
        exp = _create_experiment(admin_client, "FDR Custom Threshold Test")
        exp_id = exp["id"]

        mock_results = _make_fdr_results()

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.BenjaminiHochbergService.correct",
            return_value=[MagicMock(**r) for r in mock_results],
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/fdr-correction",
                json={
                    "p_values": {"m1": 0.01, "m2": 0.06},
                    "fdr_threshold": 0.10,
                },
            )

        assert response.status_code == 200, response.text

    def test_fdr_correction_empty_pvalues_returns_422(self, admin_client):
        """POST fdr-correction with empty p_values dict returns 422."""
        exp = _create_experiment(admin_client, "FDR Empty PV Test")
        exp_id = exp["id"]

        response = admin_client.post(
            f"/api/v1/results/{exp_id}/fdr-correction",
            json={"p_values": {}},
        )
        assert response.status_code == 422, response.text

    def test_fdr_correction_is_significant_field_present(self, admin_client):
        """POST fdr-correction response items include is_significant boolean."""
        exp = _create_experiment(admin_client, "FDR Significance Test")
        exp_id = exp["id"]

        mock_results = _make_fdr_results()

        with patch(
            "backend.app.api.v1.endpoints.post_stratification.BenjaminiHochbergService.correct",
            return_value=[MagicMock(**r) for r in mock_results],
        ):
            response = admin_client.post(
                f"/api/v1/results/{exp_id}/fdr-correction",
                json={"p_values": {"revenue": 0.001, "clicks": 0.008, "churn": 0.08}},
            )

        assert response.status_code == 200, response.text
        data = response.json()
        for item in data:
            assert isinstance(item["is_significant"], bool)

    def test_fdr_correction_invalid_threshold_returns_422(self, admin_client):
        """POST fdr-correction with fdr_threshold > 1 returns 422."""
        exp = _create_experiment(admin_client, "FDR Bad Threshold Test")
        exp_id = exp["id"]

        response = admin_client.post(
            f"/api/v1/results/{exp_id}/fdr-correction",
            json={"p_values": {"m1": 0.05}, "fdr_threshold": 2.0},
        )
        assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Tests: Unauthenticated access
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestPostStratAuthRequired:
    """Tests that endpoints require authentication."""

    def test_post_strat_requires_auth(self):
        """POST post-stratification without auth returns 401 or 403."""
        from backend.app.api import deps
        from backend.app.main import app

        unauthenticated_client = TestClient(app, raise_server_exceptions=False)
        response = unauthenticated_client.post(
            f"/api/v1/results/{EXPERIMENT_UUID}/post-stratification",
            json={"stratum_cols": ["country"]},
        )
        assert response.status_code in (401, 403, 422), response.text

    def test_fdr_correction_requires_auth(self):
        """POST fdr-correction without auth returns 401 or 403."""
        from backend.app.main import app

        unauthenticated_client = TestClient(app, raise_server_exceptions=False)
        response = unauthenticated_client.post(
            f"/api/v1/results/{EXPERIMENT_UUID}/fdr-correction",
            json={"p_values": {"m1": 0.05}},
        )
        assert response.status_code in (401, 403, 422), response.text
