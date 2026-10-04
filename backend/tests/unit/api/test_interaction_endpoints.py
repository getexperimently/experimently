"""
Unit tests for the interaction detection API endpoints.

Covers:
- GET /api/v1/interactions/scan
- GET /api/v1/interactions/{exp_a_id}/{exp_b_id}: the refusals, and one
  failure path (any other error is a 500 with a fixed sentence)
- GET /api/v1/interactions/{exp_a_id}/{exp_b_id}/novelty is gone (404)
- Role-based access control
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app.api.deps import get_current_active_user, get_db
from backend.app.main import app
from backend.app.models.experiment import MetricType
from backend.app.models.user import UserRole
from backend.app.services.interaction_detection_service import (
    InteractionAnalysis,
    InteractionDetectionService,
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

SERVICE = "backend.app.services.interaction_detection_service"
FAILURE = "Could not analyse the two experiments"


def _fake_experiment(name):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        variants=[
            SimpleNamespace(id=uuid4(), name="control", is_control=True),
            SimpleNamespace(id=uuid4(), name="treatment", is_control=False),
        ],
        metric_definitions=[
            SimpleNamespace(
                id=uuid4(),
                name="Signup",
                event_name="signup",
                metric_type=MetricType.CONVERSION,
                is_primary=True,
            )
        ],
        mutual_exclusion_group_id=None,
        correction_method="benjamini_hochberg",
        confidence_level=0.95,
    )


def _found(*experiments):
    return patch.object(
        InteractionDetectionService, "load_experiment", side_effect=list(experiments)
    )


def _no_users():
    """Readers for two experiments that share nobody."""
    return (
        patch.object(InteractionDetectionService, "_arm_totals", return_value={}),
        patch.object(
            InteractionDetectionService, "_shared_assignments", return_value={}
        ),
    )


class TestAnalyzePairEndpoint:
    """Tests for GET /api/v1/interactions/{exp_a_id}/{exp_b_id}."""

    def test_analyze_pair_returns_200(self, developer_client):
        client, _, _ = developer_client
        a, b = _fake_experiment("A"), _fake_experiment("B")
        totals, shared = _no_users()
        with _found(a, b), totals, shared:
            response = client.get(f"/api/v1/interactions/{a.id}/{b.id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["experiment_a_id"] == str(a.id)
        assert body["shared_users"] == 0
        assert [r["unavailable_reason"] for r in body["interaction_results"]] == [
            "no_shared_users",
            "no_shared_users",
        ]
        assert body["has_interaction"] is None
        for gone in ("overall_risk", "interaction_result", "novelty_result"):
            assert gone not in body

    def test_analyst_may_ask(self):
        user = _make_user(role=UserRole.ANALYST, is_superuser=False)
        app.dependency_overrides[get_db] = _override_get_db(_make_mock_db())
        app.dependency_overrides[get_current_active_user] = lambda: user
        try:
            a, b = _fake_experiment("A"), _fake_experiment("B")
            totals, shared = _no_users()
            with TestClient(app) as client, _found(a, b), totals, shared:
                response = client.get(f"/api/v1/interactions/{a.id}/{b.id}")
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 200, response.text

    def test_viewer_gets_403_naming_the_roles(self, viewer_client):
        client, _, _ = viewer_client
        response = client.get(f"/api/v1/interactions/{uuid4()}/{uuid4()}")
        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Interaction analysis needs the ANALYST, DEVELOPER or ADMIN role."
        )

    def test_the_same_experiment_twice_is_422(self, developer_client):
        client, _, _ = developer_client
        same = uuid4()
        with patch.object(InteractionDetectionService, "load_experiment") as load:
            response = client.get(f"/api/v1/interactions/{same}/{same}")
        assert response.status_code == 422
        assert response.json()["detail"] == "The two experiments must be different."
        load.assert_not_called()

    @pytest.mark.parametrize("missing", ["experiment_a_id", "experiment_b_id"])
    def test_an_unknown_experiment_is_404_naming_the_parameter(
        self, developer_client, missing
    ):
        client, _, mock_db = developer_client
        a, b = uuid4(), uuid4()
        found = (
            [None] if missing == "experiment_a_id" else [_fake_experiment("A"), None]
        )
        with patch.object(
            InteractionDetectionService, "load_experiment", side_effect=found
        ):
            response = client.get(f"/api/v1/interactions/{a}/{b}")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail == f"{missing} does not match an experiment."
        assert str(a) not in response.text and str(b) not in response.text
        mock_db.rollback.assert_not_called()

    def test_both_unknown_names_experiment_a_id(self, developer_client):
        client, _, _ = developer_client
        with patch.object(
            InteractionDetectionService, "load_experiment", side_effect=[None, None]
        ):
            response = client.get(f"/api/v1/interactions/{uuid4()}/{uuid4()}")
        assert (
            response.json()["detail"] == "experiment_a_id does not match an experiment."
        )

    @pytest.mark.regression
    @pytest.mark.parametrize(
        "failing",
        [
            "load_b",
            "totals_a",
            "totals_b",
            "shared",
            "converters",
        ],
    )
    def test_a_database_error_in_any_read_is_a_500_with_a_fixed_sentence(
        self, developer_client, failing
    ):
        """X2: no read is swallowed, the second experiment's included."""
        client, _, mock_db = developer_client
        a, b = _fake_experiment("A"), _fake_experiment("B")
        boom = OperationalError("SELECT secret_table", {}, Exception("conn reset"))
        found = [a, boom] if failing == "load_b" else [a, b]
        totals = {
            "totals_a": [boom],
            "totals_b": [{str(a.variants[0].id): 1}, boom],
        }.get(failing, [{str(a.variants[0].id): 1}, {str(b.variants[0].id): 1}])
        user_pair = (str(a.variants[0].id), str(b.variants[0].id))
        shared = boom if failing == "shared" else {"u1": user_pair}
        converters = boom if failing == "converters" else set()
        with (
            patch.object(
                InteractionDetectionService, "load_experiment", side_effect=found
            ),
            patch.object(
                InteractionDetectionService, "_arm_totals", side_effect=totals
            ),
            patch.object(
                InteractionDetectionService,
                "_shared_assignments",
                side_effect=[shared],
            ),
            patch(f"{SERVICE}.converting_user_ids", side_effect=[converters] * 4),
        ):
            response = client.get(f"/api/v1/interactions/{a.id}/{b.id}")
        assert response.status_code == 500, response.text
        detail = response.json()["detail"]
        assert detail.startswith(FAILURE)
        for text in ("secret_table", "conn reset", "OperationalError"):
            assert text not in response.text
        mock_db.rollback.assert_called()

    def test_the_novelty_route_is_gone(self, developer_client):
        client, _, _ = developer_client
        response = client.get(f"/api/v1/interactions/{uuid4()}/{uuid4()}/novelty")
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}


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
