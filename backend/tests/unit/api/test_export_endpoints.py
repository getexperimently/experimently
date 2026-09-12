"""
Unit tests for export API endpoints (EP-020).
Uses TestClient with mocked ExportService and auth dependencies.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api.deps import get_current_user, get_db
from backend.app.main import app
from backend.app.models.user import User

USER_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def mock_user() -> MagicMock:
    """Mock authenticated admin user."""
    user = MagicMock(spec=User)
    user.id = USER_UUID
    user.email = "admin@example.com"
    user.is_active = True
    user.is_superuser = True
    user.role = "ADMIN"
    return user


@pytest.fixture
def client(mock_user):
    """
    FastAPI TestClient with mocked DB and auth dependencies.

    Overrides get_db and get_current_user so no real database or Cognito
    interaction occurs during unit tests.
    """
    mock_db = MagicMock()

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
def admin_token() -> str:
    return "mock_admin_token"


# ---------------------------------------------------------------------------
# Export experiments endpoint
# ---------------------------------------------------------------------------


class TestExportExperimentsEndpoint:
    def test_export_csv_returns_200(self, client, admin_token):
        """GET /export/experiments returns 200 with valid CSV mock"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = (
                "col1,col2\nv1,v2\n",
                "text/csv",
            )
            response = client.get(
                "/api/v1/export/experiments",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    def test_export_csv_content_type(self, client, admin_token):
        """CSV export response has text/csv content type"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = (
                "h1,h2\nv1,v2\n",
                "text/csv",
            )
            response = client.get(
                "/api/v1/export/experiments?format=csv",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert "text/csv" in response.headers["content-type"]

    def test_export_csv_has_content_disposition_header(self, client, admin_token):
        """CSV export includes Content-Disposition: attachment header"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = (
                "h1\nv1\n",
                "text/csv",
            )
            response = client.get(
                "/api/v1/export/experiments?format=csv",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]
        assert "experiments_" in response.headers["content-disposition"]
        assert ".csv" in response.headers["content-disposition"]

    def test_export_json_returns_200(self, client, admin_token):
        """GET /export/experiments?format=json returns 200"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = (
                '[{"experiment_id":"1"}]',
                "application/json",
            )
            response = client.get(
                "/api/v1/export/experiments?format=json",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    def test_export_json_has_content_disposition_header(self, client, admin_token):
        """JSON export includes Content-Disposition attachment with .json extension"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = (
                '[{"experiment_id":"1"}]',
                "application/json",
            )
            response = client.get(
                "/api/v1/export/experiments?format=json",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]
        assert ".json" in response.headers["content-disposition"]

    def test_export_requires_authentication(self, client):
        """Unauthenticated requests return 401"""
        # Temporarily remove the auth override
        app.dependency_overrides = {}
        try:
            response = client.get("/api/v1/export/experiments")
            assert response.status_code == 401
        finally:
            # Restore the mock user override for other tests
            async def override_get_current_user():
                user = MagicMock(spec=User)
                user.id = USER_UUID
                user.is_active = True
                user.is_superuser = True
                return user

            app.dependency_overrides[get_current_user] = override_get_current_user


# ---------------------------------------------------------------------------
# Export variants endpoint
# ---------------------------------------------------------------------------


class TestExportVariantsEndpoint:
    def test_export_variants_returns_200(self, client, admin_token):
        """GET /export/variants returns 200"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_variants.return_value = (
                "variant_id,experiment_id\nv1,e1\n",
                "text/csv",
            )
            response = client.get(
                "/api/v1/export/variants",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    def test_export_variants_csv_content_type(self, client, admin_token):
        """Variant CSV export has text/csv content type"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_variants.return_value = (
                "h1\nv1\n",
                "text/csv",
            )
            response = client.get(
                "/api/v1/export/variants?format=csv",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert "text/csv" in response.headers["content-type"]

    def test_export_variants_has_content_disposition(self, client, admin_token):
        """Variant export has attachment Content-Disposition header"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_variants.return_value = (
                "h1\nv1\n",
                "text/csv",
            )
            response = client.get(
                "/api/v1/export/variants",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]
        assert "variants_" in response.headers["content-disposition"]


# ---------------------------------------------------------------------------
# Export feature flags endpoint
# ---------------------------------------------------------------------------


class TestExportFeatureFlagsEndpoint:
    def test_export_feature_flags_returns_200(self, client, admin_token):
        """GET /export/feature-flags returns 200"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_feature_flags.return_value = (
                "flag_id,flag_key\nf1,key1\n",
                "text/csv",
            )
            response = client.get(
                "/api/v1/export/feature-flags",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    def test_export_feature_flags_csv_content_type(self, client, admin_token):
        """Feature flags CSV export has text/csv content type"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_feature_flags.return_value = (
                "h1\nv1\n",
                "text/csv",
            )
            response = client.get(
                "/api/v1/export/feature-flags?format=csv",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert "text/csv" in response.headers["content-type"]

    def test_export_feature_flags_has_content_disposition(self, client, admin_token):
        """Feature flags export has attachment Content-Disposition header"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_feature_flags.return_value = (
                "h1\nv1\n",
                "text/csv",
            )
            response = client.get(
                "/api/v1/export/feature-flags",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]
        assert "feature_flags_" in response.headers["content-disposition"]


# ---------------------------------------------------------------------------
# Platform overview report endpoint
# ---------------------------------------------------------------------------


class TestPlatformOverviewEndpoint:
    def test_overview_report_returns_200(self, client, admin_token):
        """GET /export/reports/overview returns 200"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            from backend.app.schemas.export import PlatformOverviewReport

            mock_report = PlatformOverviewReport(
                generated_at="2024-01-01T00:00:00+00:00",
                period_start=None,
                period_end=None,
                total_experiments=10,
                active_experiments=3,
                completed_experiments=5,
                total_feature_flags=8,
                active_feature_flags=4,
                total_assignments=50000,
                total_events=120000,
                experiments_with_winners=2,
                average_experiment_duration_days=14.5,
            )
            mock_svc.return_value.generate_platform_overview.return_value = mock_report
            response = client.get(
                "/api/v1/export/reports/overview",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    def test_overview_report_returns_json(self, client, admin_token):
        """Platform overview report response is valid JSON"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            from backend.app.schemas.export import PlatformOverviewReport

            mock_report = PlatformOverviewReport(
                generated_at="2024-01-01T00:00:00+00:00",
                period_start=None,
                period_end=None,
                total_experiments=10,
                active_experiments=3,
                completed_experiments=5,
                total_feature_flags=8,
                active_feature_flags=4,
                total_assignments=50000,
                total_events=120000,
                experiments_with_winners=2,
                average_experiment_duration_days=14.5,
            )
            mock_svc.return_value.generate_platform_overview.return_value = mock_report
            response = client.get(
                "/api/v1/export/reports/overview",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        data = response.json()
        assert "total_experiments" in data
        assert "active_experiments" in data
        assert "total_feature_flags" in data
        assert "generated_at" in data

    def test_overview_report_json_values(self, client, admin_token):
        """Platform overview report contains correct values from service"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            from backend.app.schemas.export import PlatformOverviewReport

            mock_report = PlatformOverviewReport(
                generated_at="2024-01-01T00:00:00+00:00",
                period_start=None,
                period_end=None,
                total_experiments=42,
                active_experiments=7,
                completed_experiments=30,
                total_feature_flags=15,
                active_feature_flags=8,
                total_assignments=100000,
                total_events=250000,
                experiments_with_winners=12,
                average_experiment_duration_days=21.0,
            )
            mock_svc.return_value.generate_platform_overview.return_value = mock_report
            response = client.get(
                "/api/v1/export/reports/overview",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        data = response.json()
        assert data["total_experiments"] == 42
        assert data["active_experiments"] == 7
        assert data["total_feature_flags"] == 15

    def test_overview_report_requires_authentication(self, client):
        """Unauthenticated requests to overview report return 401"""
        app.dependency_overrides = {}
        try:
            response = client.get("/api/v1/export/reports/overview")
            assert response.status_code == 401
        finally:

            async def override_get_current_user():
                user = MagicMock(spec=User)
                user.id = USER_UUID
                user.is_active = True
                user.is_superuser = True
                return user

            app.dependency_overrides[get_current_user] = override_get_current_user


# ---------------------------------------------------------------------------
# Experiment report endpoint
# ---------------------------------------------------------------------------


class TestExperimentReportEndpoint:
    def test_experiment_report_returns_200(self, client, admin_token):
        """GET /export/reports/experiments/{id} returns 200"""
        exp_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = (
                '[{"experiment_id":"' + exp_id + '"}]',
                "application/json",
            )
            mock_svc.return_value.export_variants.return_value = (
                "[]",
                "application/json",
            )
            response = client.get(
                f"/api/v1/export/reports/experiments/{exp_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    def test_experiment_report_returns_json_body(self, client, admin_token):
        """Experiment report returns a JSON object body"""
        exp_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = (
                '[{"experiment_id":"'
                + exp_id
                + '","experiment_name":"My Test","status":"completed"}]',
                "application/json",
            )
            mock_svc.return_value.export_variants.return_value = (
                "[]",
                "application/json",
            )
            response = client.get(
                f"/api/v1/export/reports/experiments/{exp_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        data = response.json()
        assert "experiment_id" in data or isinstance(data, list)


# ---------------------------------------------------------------------------
# Query parameter forwarding
# ---------------------------------------------------------------------------


class TestQueryParameters:
    def test_start_date_query_param_accepted(self, client, admin_token):
        """start_date query parameter is accepted without error"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = ("", "text/csv")
            response = client.get(
                "/api/v1/export/experiments?start_date=2024-01-01T00:00:00Z",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    def test_end_date_query_param_accepted(self, client, admin_token):
        """end_date query parameter is accepted without error"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = ("", "text/csv")
            response = client.get(
                "/api/v1/export/experiments?end_date=2024-12-31T23:59:59Z",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    def test_scope_param_accepted(self, client, admin_token):
        """scope query parameter is accepted without error"""
        with patch("backend.app.api.v1.endpoints.export.ExportService") as mock_svc:
            mock_svc.return_value.export_experiments.return_value = ("", "text/csv")
            response = client.get(
                "/api/v1/export/experiments?scope=summary",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    def test_invalid_format_returns_422(self, client, admin_token):
        """Invalid format query parameter returns 422 Unprocessable Entity"""
        response = client.get(
            "/api/v1/export/experiments?format=xml",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422
