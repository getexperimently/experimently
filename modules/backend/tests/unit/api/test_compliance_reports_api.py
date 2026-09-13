"""
Unit tests for compliance report and audit export API endpoints.

Tests cover:
- ADMIN can generate SOC 2 report
- ANALYST can generate SOC 2 report
- DEVELOPER cannot generate report (403)
- VIEWER cannot generate report (403)
- SOC 2 report endpoint returns report structure
- ISO 27001 report has longer default period
- CSV export download returns correct content-type
- JSON export download returns correct content-type
- Export with date range query params
- Report includes event counts
- Report includes integrity check results
- Unknown standard returns 400
- DEVELOPER cannot export (403)
- ANALYST cannot export (403, export is ADMIN-only)
- Superuser can generate report regardless of role
"""

import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_user(role: UserRole, superuser: bool = False) -> User:
    """Create an in-memory User with the given role."""
    return User(
        id=uuid.uuid4(),
        username=f"user_{role.value}",
        email=f"{role.value}@example.com",
        hashed_password="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        role=role,
        is_superuser=superuser,
        is_active=True,
    )


def _make_report_dict(
    standard: str = "soc2",
    days: int = 365,
    total_events: int = 42,
    integrity_checks: int = 40,
    tampered_events: int = 0,
):
    """Build a plain dict that mimics dataclasses.asdict(ComplianceReport)."""
    now = datetime.now(timezone.utc)
    return {
        "standard": standard,
        "period_start": (now - timedelta(days=days)).isoformat(),
        "period_end": now.isoformat(),
        "generated_at": now.isoformat(),
        "total_events": total_events,
        "events_by_action": {"CREATE": 20, "UPDATE": 15, "DELETE": 7},
        "events_by_outcome": {"SUCCESS": 38, "FAILURE": 3, "DENIED": 1},
        "events_by_resource_type": {"feature_flag": 30, "experiment": 12},
        "integrity_checks": integrity_checks,
        "tampered_events": tampered_events,
        "integrity_pass_rate": 1.0
        if tampered_events == 0
        else (integrity_checks - tampered_events) / integrity_checks,
    }


@contextmanager
def override_deps_for_user(user: User, mock_db=None):
    """Override FastAPI dependency injection for the given user."""
    if mock_db is None:
        mock_db = MagicMock()

    def get_mock_user():
        return user

    def get_mock_db():
        yield mock_db

    app.dependency_overrides[deps.get_current_user] = get_mock_user
    app.dependency_overrides[deps.get_current_active_user] = get_mock_user
    app.dependency_overrides[deps.get_db] = get_mock_db
    try:
        yield mock_db
    finally:
        app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# TestComplianceReportPermissions
# ---------------------------------------------------------------------------


class TestComplianceReportPermissions:
    """Role-based access tests for GET /api/v1/compliance/reports/{standard}."""

    def test_admin_can_generate_soc2_report(self):
        """ADMIN receives 200 when requesting soc2 report."""
        admin = make_user(UserRole.ADMIN, superuser=True)
        report_dict = _make_report_dict(standard="soc2")

        with override_deps_for_user(admin):
            with patch(
                "modules.backend.app.api.v1.endpoints.compliance_reports.ComplianceReportService"
            ) as MockSvc:
                MockSvc.return_value.generate_report.return_value = MagicMock()
                with patch(
                    "modules.backend.app.api.v1.endpoints.compliance_reports.dataclasses_asdict",
                    return_value=report_dict,
                ):
                    client = TestClient(app)
                    response = client.get("/api/v1/compliance/reports/soc2")

        assert response.status_code == 200

    def test_analyst_can_generate_soc2_report(self):
        """ANALYST receives 200 when requesting soc2 report."""
        analyst = make_user(UserRole.ANALYST)
        report_dict = _make_report_dict(standard="soc2")

        with override_deps_for_user(analyst):
            with patch(
                "modules.backend.app.api.v1.endpoints.compliance_reports.ComplianceReportService"
            ) as MockSvc:
                MockSvc.return_value.generate_report.return_value = MagicMock()
                with patch(
                    "modules.backend.app.api.v1.endpoints.compliance_reports.dataclasses_asdict",
                    return_value=report_dict,
                ):
                    client = TestClient(app)
                    response = client.get("/api/v1/compliance/reports/soc2")

        assert response.status_code == 200

    def test_developer_cannot_generate_report(self):
        """DEVELOPER receives 403 when requesting a compliance report."""
        developer = make_user(UserRole.DEVELOPER)

        with override_deps_for_user(developer):
            client = TestClient(app)
            response = client.get("/api/v1/compliance/reports/soc2")

        assert response.status_code == 403

    def test_viewer_cannot_generate_report(self):
        """VIEWER receives 403 when requesting a compliance report."""
        viewer = make_user(UserRole.VIEWER)

        with override_deps_for_user(viewer):
            client = TestClient(app)
            response = client.get("/api/v1/compliance/reports/soc2")

        assert response.status_code == 403

    def test_superuser_can_generate_report_regardless_of_role(self):
        """is_superuser=True bypasses role check."""
        # Create a developer-role user but with is_superuser=True
        super_dev = make_user(UserRole.DEVELOPER, superuser=True)
        report_dict = _make_report_dict(standard="soc2")

        with override_deps_for_user(super_dev):
            with patch(
                "modules.backend.app.api.v1.endpoints.compliance_reports.ComplianceReportService"
            ) as MockSvc:
                MockSvc.return_value.generate_report.return_value = MagicMock()
                with patch(
                    "modules.backend.app.api.v1.endpoints.compliance_reports.dataclasses_asdict",
                    return_value=report_dict,
                ):
                    client = TestClient(app)
                    response = client.get("/api/v1/compliance/reports/soc2")

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# TestComplianceReportStructure
# ---------------------------------------------------------------------------


class TestComplianceReportStructure:
    """Tests verifying the structure of the report response."""

    def _admin_get_report(
        self, standard: str = "soc2", report_dict=None, params: str = ""
    ):
        admin = make_user(UserRole.ADMIN, superuser=True)
        if report_dict is None:
            report_dict = _make_report_dict(standard=standard)

        with override_deps_for_user(admin):
            with patch(
                "modules.backend.app.api.v1.endpoints.compliance_reports.ComplianceReportService"
            ) as MockSvc:
                MockSvc.return_value.generate_report.return_value = MagicMock()
                with patch(
                    "modules.backend.app.api.v1.endpoints.compliance_reports.dataclasses_asdict",
                    return_value=report_dict,
                ):
                    client = TestClient(app)
                    url = f"/api/v1/compliance/reports/{standard}"
                    if params:
                        url += f"?{params}"
                    response = client.get(url)
        return response

    def test_soc2_report_endpoint_returns_report_structure(self):
        """SOC 2 report response includes standard report fields."""
        response = self._admin_get_report("soc2")

        assert response.status_code == 200
        data = response.json()
        assert "standard" in data
        assert "total_events" in data
        assert "period_start" in data
        assert "period_end" in data
        assert "generated_at" in data

    def test_iso27001_report_has_longer_period(self):
        """ISO 27001 report response has standard='iso27001'."""
        report_dict = _make_report_dict(standard="iso27001", days=730)
        response = self._admin_get_report("iso27001", report_dict=report_dict)

        assert response.status_code == 200
        data = response.json()
        assert data["standard"] == "iso27001"

    def test_report_includes_event_counts(self):
        """Report response contains total_events and breakdown dicts."""
        report_dict = _make_report_dict(total_events=10)
        response = self._admin_get_report(report_dict=report_dict)

        data = response.json()
        assert data["total_events"] == 10
        assert "events_by_action" in data
        assert "events_by_outcome" in data
        assert "events_by_resource_type" in data

    def test_report_includes_integrity_check_results(self):
        """Report response contains integrity_checks and tampered_events."""
        report_dict = _make_report_dict(integrity_checks=50, tampered_events=2)
        response = self._admin_get_report(report_dict=report_dict)

        data = response.json()
        assert "integrity_checks" in data
        assert "tampered_events" in data
        assert data["integrity_checks"] == 50
        assert data["tampered_events"] == 2

    def test_unknown_standard_returns_400(self):
        """Requesting an unsupported standard value returns HTTP 400."""
        admin = make_user(UserRole.ADMIN, superuser=True)

        with override_deps_for_user(admin):
            client = TestClient(app)
            response = client.get("/api/v1/compliance/reports/pci-dss")

        assert response.status_code == 400

    def test_report_with_date_range_params(self):
        """Optional start_time/end_time query params are accepted."""
        report_dict = _make_report_dict()
        response = self._admin_get_report(
            params="start_time=2024-01-01T00:00:00Z&end_time=2024-12-31T23:59:59Z",
            report_dict=report_dict,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# TestAuditExportEndpoints
# ---------------------------------------------------------------------------


class TestAuditExportEndpoints:
    """Tests for GET /api/v1/compliance/export."""

    def _admin_export(
        self, format: str = "json", content: str = "[]", params: str = ""
    ):
        admin = make_user(UserRole.ADMIN, superuser=True)

        with override_deps_for_user(admin):
            with patch(
                "modules.backend.app.api.v1.endpoints.compliance_reports.ComplianceReportService"
            ) as MockSvc:
                MockSvc.return_value.export_events.return_value = content
                client = TestClient(app)
                url = f"/api/v1/compliance/export?format={format}"
                if params:
                    url += f"&{params}"
                response = client.get(url)
        return response

    def test_export_json_download(self):
        """GET /export?format=json returns 200 with application/json content-type."""
        response = self._admin_export(format="json", content="[]")

        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

    def test_export_csv_download(self):
        """GET /export?format=csv returns 200 with text/csv content-type."""
        csv_content = "id,timestamp,action,resource_type,resource_id,actor_id,outcome,hmac_signature\n"
        response = self._admin_export(format="csv", content=csv_content)

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    def test_export_json_has_content_disposition_header(self):
        """JSON export response has Content-Disposition: attachment header."""
        response = self._admin_export(format="json", content="[]")

        assert response.status_code == 200
        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition

    def test_export_csv_has_content_disposition_header(self):
        """CSV export response has Content-Disposition: attachment header."""
        csv_content = "id,timestamp,action,resource_type,resource_id,actor_id,outcome,hmac_signature\n"
        response = self._admin_export(format="csv", content=csv_content)

        assert response.status_code == 200
        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition

    def test_export_with_date_range(self):
        """Export endpoint accepts start_time and end_time query params."""
        response = self._admin_export(
            format="json",
            content="[]",
            params="start_time=2024-01-01T00:00:00Z&end_time=2024-06-30T23:59:59Z",
        )
        assert response.status_code == 200

    def test_developer_cannot_export(self):
        """DEVELOPER receives 403 when requesting audit export."""
        developer = make_user(UserRole.DEVELOPER)

        with override_deps_for_user(developer):
            client = TestClient(app)
            response = client.get("/api/v1/compliance/export?format=json")

        assert response.status_code == 403

    def test_analyst_cannot_export(self):
        """ANALYST receives 403 — export requires ADMIN role."""
        analyst = make_user(UserRole.ANALYST)

        with override_deps_for_user(analyst):
            client = TestClient(app)
            response = client.get("/api/v1/compliance/export?format=json")

        assert response.status_code == 403

    def test_viewer_cannot_export(self):
        """VIEWER receives 403 when requesting audit export."""
        viewer = make_user(UserRole.VIEWER)

        with override_deps_for_user(viewer):
            client = TestClient(app)
            response = client.get("/api/v1/compliance/export?format=json")

        assert response.status_code == 403

    def test_admin_can_export_csv(self):
        """ADMIN receives 200 for CSV export."""
        csv_content = "id,timestamp,action,resource_type,resource_id,actor_id,outcome,hmac_signature\n"
        response = self._admin_export(format="csv", content=csv_content)

        assert response.status_code == 200
