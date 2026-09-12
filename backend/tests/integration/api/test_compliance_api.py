"""
Integration tests for the Compliance Audit API (EP-033).

Tests the full HTTP request/response cycle for:
  GET  /api/v1/compliance/audit-events          — listing + filtering
  GET  /api/v1/compliance/reports/{standard}    — report generation
  GET  /api/v1/compliance/export                — data export (ADMIN only)

All tests use the conftest.py fixtures (admin_client, analyst_client,
developer_client, viewer_client) which wire up dependency overrides so
no real JWT / Cognito token is required.

Because these endpoints do NOT depend on the buggy from_orm() path,
most tests run directly against the real service with the test DB.
For the report and export endpoints we patch the service layer to avoid
the heavy compliance-report computation path when we only need to verify
the HTTP routing and RBAC logic.
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# GET /api/v1/compliance/audit-events
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestListAuditEvents:
    """Tests for GET /api/v1/compliance/audit-events."""

    def test_admin_can_list_audit_events(self, admin_client, db_session):
        """Admin user gets 200 with a paginated list structure."""
        _seed_audit_event(db_session)
        response = admin_client.get("/api/v1/compliance/audit-events")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["total"], int)

    def test_analyst_can_list_audit_events(self, analyst_client, db_session):
        """Analyst role (allowed) gets 200."""
        _seed_audit_event(db_session)
        response = analyst_client.get("/api/v1/compliance/audit-events")
        assert response.status_code == 200, response.text

    def test_developer_cannot_list_audit_events(self, developer_client, db_session):
        """DEVELOPER role is forbidden — expects 403."""
        response = developer_client.get("/api/v1/compliance/audit-events")
        assert response.status_code == 403, response.text

    def test_viewer_cannot_list_audit_events(self, viewer_client, db_session):
        """VIEWER role is forbidden — expects 403."""
        response = viewer_client.get("/api/v1/compliance/audit-events")
        assert response.status_code == 403, response.text

    def test_list_returns_event_fields(self, admin_client, db_session):
        """Response items include required audit event fields."""
        _seed_audit_event(db_session, resource_type="feature_flag")
        response = admin_client.get("/api/v1/compliance/audit-events")
        assert response.status_code == 200, response.text
        data = response.json()
        if data["items"]:
            item = data["items"][0]
            assert "id" in item
            assert "action" in item
            assert "resource_type" in item
            assert "outcome" in item

    def test_default_pagination_values(self, admin_client, db_session):
        """Default page=1 and limit=50 are reflected in the response."""
        response = admin_client.get("/api/v1/compliance/audit-events")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["page"] == 1
        assert data["limit"] == 50

    def test_custom_page_and_limit(self, admin_client, db_session):
        """Custom page and limit query params are accepted."""
        response = admin_client.get(
            "/api/v1/compliance/audit-events", params={"page": 2, "limit": 10}
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["page"] == 2
        assert data["limit"] == 10

    def test_filter_by_resource_type(self, admin_client, db_session):
        """filter resource_type=experiment returns only matching events."""
        _seed_audit_event(db_session, resource_type="experiment")
        _seed_audit_event(db_session, resource_type="feature_flag")
        response = admin_client.get(
            "/api/v1/compliance/audit-events",
            params={"resource_type": "experiment"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        for item in data["items"]:
            assert item["resource_type"] == "experiment"

    def test_filter_by_action(self, admin_client, db_session):
        """filter action=CREATE returns only CREATE events."""
        _seed_audit_event(db_session, action=AuditAction.CREATE)
        _seed_audit_event(db_session, action=AuditAction.DELETE)
        response = admin_client.get(
            "/api/v1/compliance/audit-events",
            params={"action": "CREATE"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        for item in data["items"]:
            assert item["action"] == "CREATE"

    def test_filter_by_actor_id(self, admin_client, db_session, admin_user):
        """filter actor_id returns events by that actor."""
        actor_id = str(admin_user.id)
        _seed_audit_event(db_session, actor_id=actor_id)
        response = admin_client.get(
            "/api/v1/compliance/audit-events",
            params={"actor_id": actor_id},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert str(item["actor_id"]) == actor_id

    def test_filter_by_start_date(self, admin_client, db_session):
        """start_time filter excludes events before that date."""
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        response = admin_client.get(
            "/api/v1/compliance/audit-events",
            params={"start_time": future},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 0

    def test_filter_by_end_date(self, admin_client, db_session):
        """end_time filter excludes events after that date."""
        past = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        response = admin_client.get(
            "/api/v1/compliance/audit-events",
            params={"end_time": past},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 0

    def test_invalid_action_filter_returns_422(self, admin_client):
        """Invalid action value returns 422 Unprocessable Entity."""
        response = admin_client.get(
            "/api/v1/compliance/audit-events",
            params={"action": "INVALID_ACTION"},
        )
        assert response.status_code == 422, response.text

    def test_invalid_page_size_returns_422(self, admin_client):
        """limit > 200 is rejected with 422."""
        response = admin_client.get(
            "/api/v1/compliance/audit-events",
            params={"limit": 999},
        )
        assert response.status_code == 422, response.text

    def test_total_increases_after_seeding(self, admin_client, db_session):
        """Seeding events increases the total count."""
        r1 = admin_client.get("/api/v1/compliance/audit-events")
        baseline = r1.json()["total"]
        _seed_audit_event(db_session)
        _seed_audit_event(db_session)
        r2 = admin_client.get("/api/v1/compliance/audit-events")
        assert r2.json()["total"] >= baseline + 2

    def test_hmac_signature_field_present(self, admin_client, db_session):
        """Response items include the hmac_signature field."""
        _seed_audit_event(db_session)
        response = admin_client.get("/api/v1/compliance/audit-events")
        assert response.status_code == 200, response.text
        data = response.json()
        if data["items"]:
            assert "hmac_signature" in data["items"][0]


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
