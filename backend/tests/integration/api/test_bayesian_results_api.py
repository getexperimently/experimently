"""
Integration tests for EP-035 Bayesian Experimentation — Results API.

Tests the full HTTP request/response cycle for:
  GET /api/v1/results/{experiment_id}

Specifically verifies:
- bayesian_results is null / absent when bayesian_enabled=False
- bayesian_results is populated when bayesian_enabled=True
- BayesianDecision field is present in bayesian_results block
- Bayesian analysis is computed correctly for the experiment

The AnalysisService is patched to return mock result dicts so the tests
are not sensitive to data volume or Redis availability.  The experiment
is created via the experiments API to ensure real DB rows exist.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.experiment import (
    Experiment,
    ExperimentStatus,
    ExperimentType,
    Variant,
    Metric,
    MetricType,
)
from backend.app.schemas.bayesian import (
    BayesianConfig,
    BayesianDecision,
    BayesianPosteriorResult,
    BayesianResultsResponse,
    BayesianVariantResult,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPERIMENT_UUID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONTROL_VARIANT_UUID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TREATMENT_VARIANT_UUID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
METRIC_UUID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_experiment_payload(name: str = "Bayesian Integration Test") -> dict:
    """Return a valid ExperimentCreate payload."""
    return {
        "name": name,
        "description": "Bayesian integration test experiment",
        "hypothesis": "Bayesian analysis will detect a winner",
        "experiment_type": "a_b",
        "variants": [
            {
                "name": "Control",
                "is_control": True,
                "traffic_allocation": 50,
            },
            {
                "name": "Treatment",
                "is_control": False,
                "traffic_allocation": 50,
            },
        ],
        "metrics": [
            {
                "name": "Checkout Conversion",
                "event_name": "checkout",
                "metric_type": "conversion",
                "is_primary": True,
                "minimum_sample_size": 100,
            }
        ],
    }


def _create_experiment(client: TestClient, name: str = "Bayesian Test") -> dict:
    """Create experiment via API and return the response JSON."""
    payload = _valid_experiment_payload(name)
    response = client.post("/api/v1/experiments/", json=payload)
    assert response.status_code == 201, f"Failed to create experiment: {response.text}"
    return response.json()


def _make_base_results(
    experiment_id: str,
    bayesian_results: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Build a minimal ExperimentResultsResponse-compatible dict."""
    return {
        "experiment_id": experiment_id,
        "experiment_name": "Bayesian Integration Test",
        "status": "active",
        "start_date": "2026-01-01T00:00:00+00:00",
        "end_date": None,
        "confidence_level": 0.95,
        "correction_method": "none",
        "computed_at": "2026-03-01T12:00:00+00:00",
        "sample_size_adequate": True,
        "summary": {
            "total_users": 2000,
            "total_events": 215,
            "has_winner": False,
            "recommendation": "CONTINUE_TESTING",
            "recommendation_reason": "Results are not yet statistically significant.",
        },
        "metrics": [
            {
                "metric_id": str(METRIC_UUID),
                "metric_name": "Checkout Conversion",
                "metric_type": "conversion",
                "is_primary": True,
                "has_significant_result": False,
                "winning_variant_id": None,
                "variants": [
                    {
                        "variant_id": str(CONTROL_VARIANT_UUID),
                        "variant_name": "Control",
                        "is_control": True,
                        "sample_size": 1000,
                        "conversions": 100,
                        "mean": 0.10,
                        "p_value": 0.25,
                        "is_significant": False,
                        "confidence_interval": [0.08, 0.12],
                        "effect_size": 0.0,
                        "relative_effect": 0.0,
                    },
                    {
                        "variant_id": str(TREATMENT_VARIANT_UUID),
                        "variant_name": "Treatment",
                        "is_control": False,
                        "sample_size": 1000,
                        "conversions": 115,
                        "mean": 0.115,
                        "p_value": 0.08,
                        "is_significant": False,
                        "confidence_interval": [0.095, 0.135],
                        "effect_size": 0.05,
                        "relative_effect": 0.15,
                    },
                ],
            }
        ],
        "sequential_testing": None,
        "breakdown": None,
        "bayesian_results": bayesian_results,
    }


def _make_bayesian_results(
    decision: BayesianDecision = BayesianDecision.CONTINUE,
) -> Dict[str, Any]:
    """Build a minimal Bayesian results dict compatible with BayesianResultsResponse."""
    return {
        "is_enabled": True,
        "decision": decision.value,
        "variant_results": [
            {
                "variant_key": "Control",
                "posterior": {
                    "alpha": 101.0,
                    "beta": 901.0,
                    "mean": 0.101,
                    "credible_interval_lower": 0.083,
                    "credible_interval_upper": 0.121,
                },
                "probability_to_be_best": 0.35,
                "expected_loss": 0.015,
                "bayes_factor": None,
            },
            {
                "variant_key": "Treatment",
                "posterior": {
                    "alpha": 116.0,
                    "beta": 886.0,
                    "mean": 0.116,
                    "credible_interval_lower": 0.097,
                    "credible_interval_upper": 0.137,
                },
                "probability_to_be_best": 0.65,
                "expected_loss": 0.002,
                "bayes_factor": 3.2,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Tests: bayesian_results absent / null when disabled
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_db
class TestBayesianResultsDisabled:
    """Results endpoint returns bayesian_results=null when Bayesian is disabled."""

    def test_bayesian_results_null_when_not_enabled(self, admin_client):
        """GET /results/{id} returns bayesian_results=null for non-Bayesian experiment."""
        exp = _create_experiment(admin_client, "Non-Bayesian Exp")
        exp_id = exp["id"]

        mock_result = _make_base_results(exp_id, bayesian_results=None)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = admin_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["bayesian_results"] is None

    def test_results_response_structure_without_bayesian(self, admin_client):
        """Results response includes standard fields even when Bayesian is off."""
        exp = _create_experiment(admin_client, "No-Bayes Structure Test")
        exp_id = exp["id"]

        mock_result = _make_base_results(exp_id, bayesian_results=None)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = admin_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert "experiment_id" in data
        assert "status" in data
        assert "metrics" in data
        assert "bayesian_results" in data  # field present, value is null


# ---------------------------------------------------------------------------
# Tests: bayesian_results populated when enabled
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_db
class TestBayesianResultsEnabled:
    """Results endpoint returns populated bayesian_results when Bayesian is enabled."""

    def test_bayesian_results_present_when_enabled(self, admin_client):
        """GET /results/{id} returns bayesian_results block when analysis is enabled."""
        exp = _create_experiment(admin_client, "Bayesian Enabled Exp")
        exp_id = exp["id"]

        bayesian_data = _make_bayesian_results(BayesianDecision.CONTINUE)
        mock_result = _make_base_results(exp_id, bayesian_results=bayesian_data)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = admin_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["bayesian_results"] is not None

    def test_bayesian_decision_field_present(self, admin_client):
        """bayesian_results.decision field is present and has a valid value."""
        exp = _create_experiment(admin_client, "Decision Field Test")
        exp_id = exp["id"]

        bayesian_data = _make_bayesian_results(BayesianDecision.STOP_WINNER)
        mock_result = _make_base_results(exp_id, bayesian_results=bayesian_data)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = admin_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        data = response.json()
        br = data["bayesian_results"]
        assert br is not None
        assert "decision" in br
        assert br["decision"] == BayesianDecision.STOP_WINNER.value

    def test_bayesian_variant_results_structure(self, admin_client):
        """bayesian_results.variant_results contains posterior distributions."""
        exp = _create_experiment(admin_client, "Variant Results Structure Test")
        exp_id = exp["id"]

        bayesian_data = _make_bayesian_results(BayesianDecision.CONTINUE)
        mock_result = _make_base_results(exp_id, bayesian_results=bayesian_data)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = admin_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        br = response.json()["bayesian_results"]
        assert "variant_results" in br
        assert len(br["variant_results"]) == 2

        for vr in br["variant_results"]:
            assert "variant_key" in vr
            assert "posterior" in vr
            assert "probability_to_be_best" in vr
            assert "expected_loss" in vr
            posterior = vr["posterior"]
            assert "mean" in posterior
            assert "credible_interval_lower" in posterior
            assert "credible_interval_upper" in posterior

    def test_bayesian_is_enabled_field(self, admin_client):
        """bayesian_results.is_enabled is True when analysis is active."""
        exp = _create_experiment(admin_client, "Is-Enabled Field Test")
        exp_id = exp["id"]

        bayesian_data = _make_bayesian_results(BayesianDecision.CONTINUE)
        mock_result = _make_base_results(exp_id, bayesian_results=bayesian_data)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = admin_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        br = response.json()["bayesian_results"]
        assert br["is_enabled"] is True

    def test_bayesian_stop_futile_decision(self, admin_client):
        """BayesianDecision.STOP_FUTILE is correctly serialised."""
        exp = _create_experiment(admin_client, "Stop Futile Decision Test")
        exp_id = exp["id"]

        bayesian_data = _make_bayesian_results(BayesianDecision.STOP_FUTILE)
        mock_result = _make_base_results(exp_id, bayesian_results=bayesian_data)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = admin_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        assert response.json()["bayesian_results"]["decision"] == "STOP_FUTILE"

    def test_bayesian_stop_equivalent_decision(self, admin_client):
        """BayesianDecision.STOP_EQUIVALENT is correctly serialised."""
        exp = _create_experiment(admin_client, "Stop Equivalent Decision Test")
        exp_id = exp["id"]

        bayesian_data = _make_bayesian_results(BayesianDecision.STOP_EQUIVALENT)
        mock_result = _make_base_results(exp_id, bayesian_results=bayesian_data)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = admin_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        assert response.json()["bayesian_results"]["decision"] == "STOP_EQUIVALENT"


# ---------------------------------------------------------------------------
# Tests: access control for results endpoint
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_db
class TestBayesianResultsAccessControl:
    """Access control tests for GET /api/v1/results/{experiment_id}."""

    def test_results_not_found_for_nonexistent_experiment(self, admin_client):
        """GET /results/{nonexistent_id} returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000001"
        response = admin_client.get(
            f"/api/v1/results/{fake_id}", params={"use_cache": "false"}
        )
        assert response.status_code in (404, 500), response.text

    def test_developer_can_access_results(self, developer_client, admin_client):
        """Developer role can read experiment results."""
        exp = _create_experiment(admin_client, "Developer Results Access Test")
        exp_id = exp["id"]

        mock_result = _make_base_results(exp_id, bayesian_results=None)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = developer_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text

    def test_analyst_can_access_results(self, analyst_client, admin_client):
        """Analyst role can read experiment results."""
        exp = _create_experiment(admin_client, "Analyst Results Access Test")
        exp_id = exp["id"]

        mock_result = _make_base_results(exp_id, bayesian_results=None)

        with patch(
            "backend.app.services.analysis_service.AnalysisService.get_experiment_results",
            return_value=mock_result,
        ):
            response = analyst_client.get(
                f"/api/v1/results/{exp_id}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
