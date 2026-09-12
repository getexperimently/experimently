"""
Unit tests for the interaction detection API endpoints.

Covers:
- GET /api/v1/interactions/scan
- GET /api/v1/interactions/{exp_a_id}/{exp_b_id}
- GET /api/v1/interactions/{exp_a_id}/{exp_b_id}/novelty
- Role-based access control
- Schema validation
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.api.deps import get_current_active_user, get_db
from backend.app.main import app
from backend.app.models.user import UserRole
from backend.app.services.interaction_detection_service import (
    InteractionAnalysis,
    InteractionResult,
    NoveltyResult,
    SUTVAResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db():
    return MagicMock()


def _override_get_db(mock_db):
    def _get_db():
        try:
            yield mock_db
        finally:
            pass

    return _get_db


def _make_user(role=UserRole.DEVELOPER, is_superuser=False):
    user = MagicMock()
    user.id = uuid4()
    user.username = "testuser"
    user.email = "test@example.com"
    user.is_active = True
    user.is_superuser = is_superuser
    user.role = role
    return user


def _make_analysis(
    exp_a_id: str,
    exp_b_id: str,
    overall_risk: str = "medium",
    has_interaction: bool = False,
    has_sutva: bool = False,
):
    return InteractionAnalysis(
        experiment_a_id=exp_a_id,
        experiment_b_id=exp_b_id,
        overlap_coefficient=0.5,
        has_significant_overlap=True,
        interaction_result=InteractionResult(
            has_interaction=has_interaction,
            p_value=0.04 if has_interaction else 0.42,
            interaction_effect_size=0.1 if has_interaction else 0.0,
            warning_message="Interaction warning." if has_interaction else None,
        ),
        novelty_result=NoveltyResult(
            has_novelty=False,
            decline_rate=0.0,
            recommendation="No novelty.",
        ),
        sutva_result=SUTVAResult(
            has_violation=has_sutva,
            contamination_rate=0.0,
            warning_message="SUTVA warning." if has_sutva else None,
        ),
        overall_risk=overall_risk,
        recommendations=["Check overlap."],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def developer_client():
    user = _make_user(role=UserRole.DEVELOPER)
    mock_db = _make_mock_db()
    app.dependency_overrides[get_db] = _override_get_db(mock_db)
    app.dependency_overrides[get_current_active_user] = lambda: user
    with TestClient(app) as client:
        yield client, user, mock_db
    app.dependency_overrides.clear()


@pytest.fixture
def viewer_client():
    user = _make_user(role=UserRole.VIEWER, is_superuser=False)
    mock_db = _make_mock_db()
    app.dependency_overrides[get_db] = _override_get_db(mock_db)
    app.dependency_overrides[get_current_active_user] = lambda: user
    with TestClient(app) as client:
        yield client, user, mock_db
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client():
    user = _make_user(role=UserRole.ADMIN, is_superuser=True)
    mock_db = _make_mock_db()
    app.dependency_overrides[get_db] = _override_get_db(mock_db)
    app.dependency_overrides[get_current_active_user] = lambda: user
    with TestClient(app) as client:
        yield client, user, mock_db
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestScanEndpoint
# ---------------------------------------------------------------------------


class TestScanEndpoint:
    """Tests for GET /api/v1/interactions/scan."""

    def test_scan_returns_200(self, developer_client):
        client, _, mock_db = developer_client
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.scan_active_experiments.return_value = []
            MockSvc.return_value._get_active_experiment_ids.return_value = []
            response = client.get("/api/v1/interactions/scan")
        assert response.status_code == 200

    def test_scan_returns_active_interaction_scan_response_shape(
        self, developer_client
    ):
        client, _, mock_db = developer_client
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.scan_active_experiments.return_value = []
            MockSvc.return_value._get_active_experiment_ids.return_value = []
            response = client.get("/api/v1/interactions/scan")
        data = response.json()
        assert "total_active_experiments" in data
        assert "pairs_analyzed" in data
        assert "high_risk_pairs" in data
        assert "analyses" in data

    def test_scan_empty_when_no_overlapping_pairs(self, developer_client):
        client, _, mock_db = developer_client
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.scan_active_experiments.return_value = []
            MockSvc.return_value._get_active_experiment_ids.return_value = []
            response = client.get("/api/v1/interactions/scan")
        data = response.json()
        assert data["analyses"] == []
        assert data["pairs_analyzed"] == 0

    def test_scan_pairs_analyzed_matches_analyses_length(self, developer_client):
        client, _, mock_db = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        analysis = _make_analysis(exp_a, exp_b)
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.scan_active_experiments.return_value = [analysis]
            MockSvc.return_value._get_active_experiment_ids.return_value = [
                exp_a,
                exp_b,
            ]
            response = client.get("/api/v1/interactions/scan")
        data = response.json()
        assert data["pairs_analyzed"] == len(data["analyses"])

    def test_scan_requires_developer_or_higher_role(self, viewer_client):
        client, _, mock_db = viewer_client
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.scan_active_experiments.return_value = []
            MockSvc.return_value._get_active_experiment_ids.return_value = []
            response = client.get("/api/v1/interactions/scan")
        assert response.status_code == 403

    def test_scan_viewer_gets_403(self, viewer_client):
        """VIEWER role explicitly returns 403."""
        client, _, _ = viewer_client
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ):
            response = client.get("/api/v1/interactions/scan")
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# TestAnalyzePairEndpoint
# ---------------------------------------------------------------------------


class TestAnalyzePairEndpoint:
    """Tests for GET /api/v1/interactions/{exp_a_id}/{exp_b_id}."""

    def test_analyze_pair_returns_200(self, developer_client):
        client, _, _ = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        analysis = _make_analysis(exp_a, exp_b)
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.analyze_experiment_pair.return_value = analysis
            response = client.get(f"/api/v1/interactions/{exp_a}/{exp_b}")
        assert response.status_code == 200

    def test_analyze_pair_returns_404_when_exp_a_not_found(self, developer_client):
        client, _, _ = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.analyze_experiment_pair.side_effect = ValueError(
                f"Experiment {exp_a} not found"
            )
            response = client.get(f"/api/v1/interactions/{exp_a}/{exp_b}")
        assert response.status_code == 404

    def test_analyze_pair_returns_404_when_exp_b_not_found(self, developer_client):
        client, _, _ = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.analyze_experiment_pair.side_effect = ValueError(
                f"Experiment {exp_b} not found"
            )
            response = client.get(f"/api/v1/interactions/{exp_a}/{exp_b}")
        assert response.status_code == 404

    def test_analyze_pair_non_overlapping_returns_200_with_flag(self, developer_client):
        """Non-overlapping experiments: service returns None, endpoint returns 200 with has_significant_overlap=false."""
        client, _, _ = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.analyze_experiment_pair.return_value = None
            response = client.get(f"/api/v1/interactions/{exp_a}/{exp_b}")
        assert response.status_code == 200
        data = response.json()
        assert data["has_significant_overlap"] is False

    def test_analyze_pair_response_includes_overall_risk(self, developer_client):
        client, _, _ = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        analysis = _make_analysis(exp_a, exp_b, overall_risk="high")
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.analyze_experiment_pair.return_value = analysis
            response = client.get(f"/api/v1/interactions/{exp_a}/{exp_b}")
        data = response.json()
        assert "overall_risk" in data

    def test_analyze_pair_response_includes_recommendations(self, developer_client):
        client, _, _ = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        analysis = _make_analysis(exp_a, exp_b)
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.analyze_experiment_pair.return_value = analysis
            response = client.get(f"/api/v1/interactions/{exp_a}/{exp_b}")
        data = response.json()
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)

    def test_analyze_pair_overlap_coefficient_in_valid_range(self, developer_client):
        client, _, _ = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        analysis = _make_analysis(exp_a, exp_b)
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.analyze_experiment_pair.return_value = analysis
            response = client.get(f"/api/v1/interactions/{exp_a}/{exp_b}")
        data = response.json()
        assert 0.0 <= data["overlap_coefficient"] <= 1.0


# ---------------------------------------------------------------------------
# TestNoveltyEndpoint
# ---------------------------------------------------------------------------


class TestNoveltyEndpoint:
    """Tests for GET /api/v1/interactions/{exp_a_id}/{exp_b_id}/novelty."""

    def test_novelty_returns_novelty_result_schema(self, developer_client):
        client, _, _ = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        novelty = NoveltyResult(
            has_novelty=False,
            decline_rate=0.0,
            recommendation="Stable effect.",
        )
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.analyze_experiment_pair.return_value = _make_analysis(
                exp_a, exp_b
            )
            response = client.get(f"/api/v1/interactions/{exp_a}/{exp_b}/novelty")
        assert response.status_code == 200
        data = response.json()
        assert "has_novelty" in data
        assert "decline_rate" in data
        assert "recommendation" in data


# ---------------------------------------------------------------------------
# TestHighRiskPairs
# ---------------------------------------------------------------------------


class TestHighRiskPairs:
    """Tests for correct high_risk_pairs counting in scan response."""

    def test_high_risk_pairs_counted_correctly(self, developer_client):
        client, _, _ = developer_client
        exp_a = str(uuid4())
        exp_b = str(uuid4())
        # Analysis with interaction = high risk
        high_risk_analysis = _make_analysis(
            exp_a, exp_b, overall_risk="high", has_interaction=True
        )
        with patch(
            "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"
        ) as MockSvc:
            MockSvc.return_value.scan_active_experiments.return_value = [
                high_risk_analysis
            ]
            MockSvc.return_value._get_active_experiment_ids.return_value = [
                exp_a,
                exp_b,
            ]
            response = client.get("/api/v1/interactions/scan")
        data = response.json()
        assert data["high_risk_pairs"] >= 1
