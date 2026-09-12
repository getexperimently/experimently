"""
Enterprise compliance API — report generation and audit export.

Split out of ``test_compliance_api.py`` so that file tests only what a
Community build serves (``GET /compliance/audit-events`` and the audit
events themselves) and the Community build can delete this one.  The two
routes below keep their URLs in every edition but delegate their bodies
through the seam; without the Enterprise registration they answer 501, and
without a licence 403 (see ``test_license_gate_path.py``).
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.compliance_audit_event import (
    AuditAction,
    AuditOutcome,
    ComplianceAuditEvent,
)
from backend.app.services.audit_log_service import AuditLogService


def _seed_audit_event(
    db_session: Session,
    *,
    resource_type: str = "experiment",
    action: AuditAction = AuditAction.CREATE,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    actor_id: str = None,
) -> ComplianceAuditEvent:
    """Insert a single ComplianceAuditEvent directly into the test DB."""
    event = ComplianceAuditEvent(
        id=uuid.uuid4(),
        timestamp=datetime.now(timezone.utc),
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        outcome=outcome,
        hmac_signature="test_sig",
        retention_expires_at=datetime.now(timezone.utc) + timedelta(days=365),
    )
    db_session.add(event)
    db_session.commit()
    return event


def _make_fake_report(standard: str = "soc2") -> Dict[str, Any]:
    """Build a minimal compliance report dict matching the dataclass structure."""
    return {
        "standard": standard,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_start": (datetime.now(timezone.utc) - timedelta(days=365)).isoformat(),
        "period_end": datetime.now(timezone.utc).isoformat(),
        "total_events": 42,
        "events_by_action": {"CREATE": 10, "UPDATE": 20, "DELETE": 12},
        "events_by_outcome": {"SUCCESS": 40, "FAILURE": 2},
        "events_by_resource_type": {"experiment": 30, "feature_flag": 12},
        "hmac_verified_count": 42,
        "hmac_failed_count": 0,
        "summary": "All events verified.",
    }


# ---------------------------------------------------------------------------
# GET /api/v1/compliance/reports/{standard}
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestComplianceReports:
    """Tests for GET /api/v1/compliance/reports/{standard}."""

    def test_soc2_report_returns_200(self, admin_client, db_session):
        """GET /reports/soc2 returns 200 with report fields."""
        fake_report = _make_fake_report("soc2")
        with patch(
            "backend.app.services.compliance_report_service.ComplianceReportService.generate_report",
            return_value=MagicMock(
                **fake_report, __iter__=lambda self: iter(fake_report.items())
            ),
        ):
            # Use dataclasses_asdict fallback — patch the dataclass conversion
            from dataclasses import dataclass

            @dataclass
            class FakeReport:
                standard: str = "soc2"
                generated_at: str = fake_report["generated_at"]
                period_start: str = fake_report["period_start"]
                period_end: str = fake_report["period_end"]
                total_events: int = fake_report["total_events"]
                events_by_action: dict = None
                events_by_outcome: dict = None
                events_by_resource_type: dict = None
                hmac_verified_count: int = fake_report["hmac_verified_count"]
                hmac_failed_count: int = fake_report["hmac_failed_count"]
                summary: str = fake_report["summary"]

                def __post_init__(self):
                    if self.events_by_action is None:
                        self.events_by_action = fake_report["events_by_action"]
                    if self.events_by_outcome is None:
                        self.events_by_outcome = fake_report["events_by_outcome"]
                    if self.events_by_resource_type is None:
                        self.events_by_resource_type = fake_report[
                            "events_by_resource_type"
                        ]

            with patch(
                "backend.app.services.compliance_report_service.ComplianceReportService.generate_report",
                return_value=FakeReport(),
            ):
                response = admin_client.get("/api/v1/compliance/reports/soc2")

        assert response.status_code == 200, response.text

    def test_iso27001_report_returns_200(self, admin_client, db_session):
        """GET /reports/iso27001 returns 200."""
        from dataclasses import dataclass

        @dataclass
        class FakeIsoReport:
            standard: str = "iso27001"
            generated_at: str = datetime.now(timezone.utc).isoformat()
            period_start: str = (
                datetime.now(timezone.utc) - timedelta(days=730)
            ).isoformat()
            period_end: str = datetime.now(timezone.utc).isoformat()
            total_events: int = 0
            events_by_action: dict = None
            events_by_outcome: dict = None
            events_by_resource_type: dict = None
            hmac_verified_count: int = 0
            hmac_failed_count: int = 0
            summary: str = "ISO 27001 report"

            def __post_init__(self):
                if self.events_by_action is None:
                    self.events_by_action = {}
                if self.events_by_outcome is None:
                    self.events_by_outcome = {}
                if self.events_by_resource_type is None:
                    self.events_by_resource_type = {}

        with patch(
            "backend.app.services.compliance_report_service.ComplianceReportService.generate_report",
            return_value=FakeIsoReport(),
        ):
            response = admin_client.get("/api/v1/compliance/reports/iso27001")

        assert response.status_code == 200, response.text

    def test_unknown_standard_returns_400(self, admin_client):
        """GET /reports/unknown_standard returns 400 Bad Request."""
        response = admin_client.get("/api/v1/compliance/reports/gdpr")
        assert response.status_code == 400, response.text

    def test_analyst_can_generate_soc2_report(self, analyst_client, db_session):
        """Analyst role can generate reports (ADMIN + ANALYST allowed)."""
        from dataclasses import dataclass

        @dataclass
        class FakeReport:
            standard: str = "soc2"
            generated_at: str = datetime.now(timezone.utc).isoformat()
            period_start: str = datetime.now(timezone.utc).isoformat()
            period_end: str = datetime.now(timezone.utc).isoformat()
            total_events: int = 0
            events_by_action: dict = None
            events_by_outcome: dict = None
            events_by_resource_type: dict = None
            hmac_verified_count: int = 0
            hmac_failed_count: int = 0
            summary: str = "ok"

            def __post_init__(self):
                if self.events_by_action is None:
                    self.events_by_action = {}
                if self.events_by_outcome is None:
                    self.events_by_outcome = {}
                if self.events_by_resource_type is None:
                    self.events_by_resource_type = {}

        with patch(
            "backend.app.services.compliance_report_service.ComplianceReportService.generate_report",
            return_value=FakeReport(),
        ):
            response = analyst_client.get("/api/v1/compliance/reports/soc2")

        assert response.status_code == 200, response.text

    def test_developer_cannot_generate_report(self, developer_client):
        """DEVELOPER role is forbidden from compliance reports."""
        response = developer_client.get("/api/v1/compliance/reports/soc2")
        assert response.status_code == 403, response.text

    def test_viewer_cannot_generate_report(self, viewer_client):
        """VIEWER role is forbidden from compliance reports."""
        response = viewer_client.get("/api/v1/compliance/reports/iso27001")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# GET /api/v1/compliance/export
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestAuditExport:
    """Tests for GET /api/v1/compliance/export."""

    def test_admin_can_export_json(self, admin_client, db_session):
        """Admin can export audit events as JSON (default format)."""
        with patch(
            "backend.app.services.compliance_report_service.ComplianceReportService.export_events",
            return_value=b'[{"id": "test"}]',
        ):
            response = admin_client.get(
                "/api/v1/compliance/export", params={"format": "json"}
            )
        assert response.status_code == 200, response.text
        assert "application/json" in response.headers.get("content-type", "")

    def test_admin_can_export_csv(self, admin_client, db_session):
        """Admin can export audit events as CSV."""
        with patch(
            "backend.app.services.compliance_report_service.ComplianceReportService.export_events",
            return_value=b"id,action,resource_type\ntest,CREATE,experiment\n",
        ):
            response = admin_client.get(
                "/api/v1/compliance/export", params={"format": "csv"}
            )
        assert response.status_code == 200, response.text
        assert "text/csv" in response.headers.get("content-type", "")

    def test_export_has_content_disposition_header(self, admin_client, db_session):
        """Export response includes Content-Disposition attachment header."""
        with patch(
            "backend.app.services.compliance_report_service.ComplianceReportService.export_events",
            return_value=b"[]",
        ):
            response = admin_client.get(
                "/api/v1/compliance/export", params={"format": "json"}
            )
        assert response.status_code == 200, response.text
        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition

    def test_analyst_cannot_export(self, analyst_client):
        """Analyst role cannot export — only ADMIN may do full dumps."""
        response = analyst_client.get(
            "/api/v1/compliance/export", params={"format": "json"}
        )
        assert response.status_code == 403, response.text

    def test_developer_cannot_export(self, developer_client):
        """Developer role cannot export audit data."""
        response = developer_client.get("/api/v1/compliance/export")
        assert response.status_code == 403, response.text

    def test_viewer_cannot_export(self, viewer_client):
        """Viewer role cannot export audit data."""
        response = viewer_client.get("/api/v1/compliance/export")
        assert response.status_code == 403, response.text

    def test_invalid_format_rejected(self, admin_client):
        """Invalid format parameter returns 422."""
        response = admin_client.get(
            "/api/v1/compliance/export", params={"format": "xml"}
        )
        assert response.status_code == 422, response.text

    def test_export_json_default_format(self, admin_client, db_session):
        """Default format is json when not specified."""
        with patch(
            "backend.app.services.compliance_report_service.ComplianceReportService.export_events",
            return_value=b"[]",
        ):
            response = admin_client.get("/api/v1/compliance/export")
        assert response.status_code == 200, response.text
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type or "json" in content_type

    def test_export_filename_contains_format(self, admin_client, db_session):
        """Content-Disposition filename matches the requested format."""
        with patch(
            "backend.app.services.compliance_report_service.ComplianceReportService.export_events",
            return_value=b"a,b\n1,2\n",
        ):
            response = admin_client.get(
                "/api/v1/compliance/export", params={"format": "csv"}
            )
        assert response.status_code == 200, response.text
        disposition = response.headers.get("content-disposition", "")
        assert "csv" in disposition
