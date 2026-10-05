"""
Unit tests for EP-021 Sequential Testing API endpoints.

Tests for:
  GET /api/v1/results/{experiment_id} — sequential_testing field in response
  GET /api/v1/results/{experiment_id}/sequential — dedicated sequential endpoint
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api.deps import get_current_user, get_db
from backend.app.main import app
from backend.app.models.user import User
from backend.app.services.analysis_service import AnalysisService
from backend.app.services.sequential_testing_service import (
    AlphaSpendingBoundary,
    ConfidenceSequence,
    EvidencePoint,
    EvidenceStrength,
    LongRunningRisk,
    MSPRTResult,
    SequentialAnalysis,
    SequentialTestingMethod,
    SequentialTestingService,
    SpendingFunction,
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
    db = MagicMock()
    # The results route reads the experiment's stored analysis settings
    # (#580); these tests were written for an uncorrected 0.95.
    experiment = db.query.return_value.filter.return_value.first.return_value
    experiment.correction_method = "none"
    experiment.confidence_level = 0.95
    return db


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
            EvidencePoint(
                sample_size=2000,
                lambda_ratio=3.5,
                always_valid_p_value=0.28,
                can_stop=False,
            ),
            EvidencePoint(
                sample_size=5000,
                lambda_ratio=12.0,
                always_valid_p_value=0.08,
                can_stop=False,
            ),
            EvidencePoint(
                sample_size=10000,
                lambda_ratio=25.0,
                always_valid_p_value=0.04,
                can_stop=True,
            ),
        ],
        alpha_spending=[
            AlphaSpendingBoundary(
                look_number=1, cumulative_alpha=0.001, boundary_z=3.29, boundary_p=0.001
            ),
            AlphaSpendingBoundary(
                look_number=2, cumulative_alpha=0.01, boundary_z=2.58, boundary_p=0.01
            ),
        ],
        long_running_risk=None,
        recommended_action="stop_for_effect",
    )


# ---------------------------------------------------------------------------
# Tests for sequential_testing field in main results
# ---------------------------------------------------------------------------


class _DictCache:
    """An in-memory stand-in for the Redis-backed results cache."""

    def __init__(self) -> None:
        self.store: Dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, expire: int = 0) -> None:
        self.store[key] = value


def _results_experiment(mock_db, enabled: bool):
    """The experiment the results route loads, with sequential testing on or off.

    The flag is set explicitly: a bare MagicMock attribute is truthy, which
    would send a "disabled" test down the enabled path.
    """
    experiment = mock_db.query.return_value.filter.return_value.first.return_value
    experiment.id = EXPERIMENT_UUID
    experiment.sequential_testing_enabled = enabled
    experiment.sequential_testing_method = "msprt"
    experiment.sequential_testing_config = {"tau_squared": 0.001}
    experiment.start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return experiment


class TestSequentialTestingInResults:
    """The sequential_testing block of GET /api/v1/results/{experiment_id} (#922).

    These tests drive the experiment's ``sequential_testing_enabled`` flag and
    let the route compute the block.  They used to have the mocked analysis
    service return a ``sequential_testing`` key itself, a key the real service
    never produces, so they passed while the field was always null.
    """

    @staticmethod
    def _get_results(client, results, sequential_data=(500, 5000, 600, 5000), **kw):
        with (
            patch("backend.app.api.v1.endpoints.results.AnalysisService") as MockCls,
            patch(
                "backend.app.api.v1.endpoints.results._get_sequential_data",
                **(
                    {"side_effect": sequential_data}
                    if isinstance(sequential_data, BaseException)
                    else {"return_value": sequential_data}
                ),
            ),
        ):
            MockCls.return_value.get_experiment_results.return_value = results
            return client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}",
                params={"use_cache": "false", **kw},
            )

    @pytest.mark.unit
    def test_results_include_sequential_testing_null_when_disabled(
        self, client, mock_db, mock_experiment_results_with_sequential
    ):
        """Sequential testing off: null, and the analysis is never computed."""
        _results_experiment(mock_db, enabled=False)
        with patch(
            "backend.app.api.v1.endpoints.results._compute_sequential_response"
        ) as compute:
            response = self._get_results(
                client, mock_experiment_results_with_sequential
            )

        assert response.status_code == 200
        assert response.json()["sequential_testing"] is None
        compute.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.regression
    def test_results_include_sequential_testing_when_enabled(
        self,
        client,
        mock_db,
        mock_experiment_results_with_sequential,
        mock_sequential_analysis,
    ):
        """Sequential testing on: the route computes the block from the experiment."""
        _results_experiment(mock_db, enabled=True)
        results = dict(mock_experiment_results_with_sequential)
        assert "sequential_testing" not in results  # the service never sets it

        with patch(
            "backend.app.api.v1.endpoints.results.SequentialTestingService"
        ) as MockService:
            MockService.return_value.run_sequential_analysis.return_value = (
                mock_sequential_analysis
            )
            response = self._get_results(client, results)

        assert response.status_code == 200
        data = response.json()
        assert data["sequential_testing"] is not None
        assert data["sequential_testing"]["method"] == "msprt"
        assert data["sequential_testing"]["recommended_action"] == "stop_for_effect"
        assert data["sequential_testing"]["analysis_status"] == "beta"
        kwargs = MockService.return_value.run_sequential_analysis.call_args.kwargs
        assert (
            kwargs["control_successes"],
            kwargs["control_total"],
            kwargs["treatment_successes"],
            kwargs["treatment_total"],
        ) == (500, 5000, 600, 5000)

    @pytest.mark.unit
    def test_sequential_msprt_result_fields(
        self,
        client,
        mock_db,
        mock_experiment_results_with_sequential,
        mock_sequential_analysis,
    ):
        """mSPRT result should contain lambda_ratio, can_stop, evidence_strength."""
        _results_experiment(mock_db, enabled=True)
        with patch(
            "backend.app.api.v1.endpoints.results.SequentialTestingService"
        ) as MockService:
            MockService.return_value.run_sequential_analysis.return_value = (
                mock_sequential_analysis
            )
            response = self._get_results(
                client, mock_experiment_results_with_sequential
            )

        assert response.status_code == 200
        msprt = response.json()["sequential_testing"]["msprt_result"]
        assert msprt["lambda_ratio"] == 25.0
        assert msprt["can_stop"] is True
        assert msprt["evidence_strength"] == "strong_for_effect"
        assert msprt["boundary"] == 20.0

    @pytest.mark.unit
    def test_sequential_confidence_sequence_fields(
        self,
        client,
        mock_db,
        mock_experiment_results_with_sequential,
        mock_sequential_analysis,
    ):
        """Confidence sequence should contain lower, upper, width, sample_size."""
        _results_experiment(mock_db, enabled=True)
        with patch(
            "backend.app.api.v1.endpoints.results.SequentialTestingService"
        ) as MockService:
            MockService.return_value.run_sequential_analysis.return_value = (
                mock_sequential_analysis
            )
            response = self._get_results(
                client, mock_experiment_results_with_sequential
            )

        assert response.status_code == 200
        cs = response.json()["sequential_testing"]["confidence_sequence"]
        assert cs["lower"] == 0.01
        assert cs["upper"] == 0.08
        assert cs["width"] == 0.07
        assert cs["sample_size"] == 10000

    @pytest.mark.unit
    @pytest.mark.regression
    def test_a_failed_sequential_analysis_is_null_and_logged(
        self, client, mock_db, mock_experiment_results_with_sequential
    ):
        """A failure is null plus one warning naming the experiment; still 200."""
        _results_experiment(mock_db, enabled=True)
        with patch("backend.app.api.v1.endpoints.results.logger") as log:
            response = self._get_results(
                client,
                mock_experiment_results_with_sequential,
                sequential_data=RuntimeError("boom"),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["sequential_testing"] is None
        assert data["metrics"]  # the rest of the response is unaffected
        warnings = [
            c.args[0] % c.args[1:]
            for c in log.warning.call_args_list
            if "Sequential analysis" in c.args[0]
        ]
        assert len(warnings) == 1, warnings
        assert str(EXPERIMENT_UUID) in warnings[0]
        assert "RuntimeError" in warnings[0]
        assert "boom" not in warnings[0]  # the class name only, not the message

    @pytest.mark.unit
    @pytest.mark.regression
    def test_the_sequential_block_survives_the_results_cache(
        self,
        client,
        mock_db,
        mock_experiment_results_with_sequential,
        mock_sequential_analysis,
    ):
        """A cached answer carries the same block as the fresh one."""
        _results_experiment(mock_db, enabled=True)
        cache = _DictCache()
        with (
            patch(
                "backend.app.api.v1.endpoints.results._get_cache_service",
                return_value=cache,
            ),
            patch(
                "backend.app.api.v1.endpoints.results.SequentialTestingService"
            ) as MockService,
        ):
            MockService.return_value.run_sequential_analysis.return_value = (
                mock_sequential_analysis
            )
            fresh = self._get_results(client, mock_experiment_results_with_sequential)
            assert len(cache.store) == 1
            with patch(
                "backend.app.api.v1.endpoints.results.AnalysisService"
            ) as NotCalled:
                cached = client.get(f"/api/v1/results/{EXPERIMENT_UUID}")
                NotCalled.assert_not_called()

        assert fresh.status_code == cached.status_code == 200
        assert fresh.json()["sequential_testing"] is not None
        assert cached.json()["sequential_testing"] == fresh.json()["sequential_testing"]


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
            mock_instance.run_sequential_analysis.return_value = (
                mock_sequential_analysis
            )

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
            response = client.get(f"/api/v1/results/{EXPERIMENT_UUID}/sequential")

        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Sequential testing is not enabled for this experiment"
        )

    @pytest.mark.unit
    def test_sequential_endpoint_returns_evidence_trajectory(
        self, client, mock_sequential_analysis
    ):
        """Evidence trajectory should contain data points for charting."""
        with patch(
            "backend.app.api.v1.endpoints.results.SequentialTestingService"
        ) as MockService:
            mock_instance = MockService.return_value
            mock_instance.run_sequential_analysis.return_value = (
                mock_sequential_analysis
            )

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
    def test_sequential_endpoint_returns_no_alpha_spending(
        self, client, mock_sequential_analysis
    ):
        """The route reports no planned-looks table, even if the service had one.

        Contract change (#232): this test used to assert two boundaries passed
        through from the service.  The boundaries did not hold their stated
        significance level, and the route now always answers ``[]`` with a
        notice.
        """
        with patch(
            "backend.app.api.v1.endpoints.results.SequentialTestingService"
        ) as MockService:
            mock_instance = MockService.return_value
            mock_instance.run_sequential_analysis.return_value = (
                mock_sequential_analysis
            )

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
        assert data["alpha_spending"] == []
        assert data["analysis_status"] == "beta"
        assert "alpha_spending is always empty" in data["analysis_notice"]

    @pytest.mark.unit
    def test_sequential_endpoint_returns_404_for_missing_experiment(self, client):
        """Returns 404 when experiment doesn't exist."""
        with patch(
            "backend.app.api.v1.endpoints.results._get_experiment_for_sequential",
            return_value=None,
        ):
            response = client.get(f"/api/v1/results/{EXPERIMENT_UUID}/sequential")

        assert response.status_code == 404
        assert response.json()["detail"] == "Experiment not found"

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
