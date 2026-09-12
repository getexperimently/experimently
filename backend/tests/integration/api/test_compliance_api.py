"""
Integration tests for the Community half of the Compliance Audit API (EP-033).

  GET /api/v1/compliance/audit-events — listing, filtering, pagination and
  the ADMIN/ANALYST role check, in every edition.

The report and export routes keep their URLs in every edition but delegate
their bodies through the seam; their tests are Enterprise and live in
``test_compliance_reports_api.py``.

All tests use the conftest.py fixtures (admin_client, analyst_client,
developer_client, viewer_client) which wire up dependency overrides so no
real JWT / Cognito token is required, and run against the real service and
the test database.
"""

import uuid
from datetime import datetime, timedelta, timezone

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
