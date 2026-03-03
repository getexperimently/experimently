"""
Unit tests for compliance audit Pydantic schemas.

Tests cover:
- ComplianceAuditEventCreate schema validation
- ComplianceAuditEventResponse schema fields and from_attributes
- ComplianceAuditEventListResponse pagination fields
- AuditAction enum values match model
- AuditOutcome enum values match model
- Field validation and error handling
"""

import pytest
import uuid
from datetime import datetime, timezone
from typing import List

from pydantic import ValidationError

from backend.app.schemas.compliance_audit import (
    ComplianceAuditEventCreate,
    ComplianceAuditEventResponse,
    ComplianceAuditEventListResponse,
    AuditAction,
    AuditOutcome,
)
from backend.app.models.compliance_audit_event import (
    AuditAction as ModelAuditAction,
    AuditOutcome as ModelAuditOutcome,
)


class TestSchemaAuditActionEnum:
    """Tests for AuditAction enum in schemas."""

    def test_schema_audit_action_has_create(self):
        """Schema AuditAction has CREATE."""
        assert AuditAction.CREATE == "CREATE"

    def test_schema_audit_action_has_read(self):
        """Schema AuditAction has READ."""
        assert AuditAction.READ == "READ"

    def test_schema_audit_action_has_update(self):
        """Schema AuditAction has UPDATE."""
        assert AuditAction.UPDATE == "UPDATE"

    def test_schema_audit_action_has_delete(self):
        """Schema AuditAction has DELETE."""
        assert AuditAction.DELETE == "DELETE"

    def test_schema_audit_action_has_login(self):
        """Schema AuditAction has LOGIN."""
        assert AuditAction.LOGIN == "LOGIN"

    def test_schema_audit_action_has_logout(self):
        """Schema AuditAction has LOGOUT."""
        assert AuditAction.LOGOUT == "LOGOUT"

    def test_schema_audit_action_has_login_failed(self):
        """Schema AuditAction has LOGIN_FAILED."""
        assert AuditAction.LOGIN_FAILED == "LOGIN_FAILED"

    def test_schema_audit_action_has_role_grant(self):
        """Schema AuditAction has ROLE_GRANT."""
        assert AuditAction.ROLE_GRANT == "ROLE_GRANT"

    def test_schema_audit_action_has_role_revoke(self):
        """Schema AuditAction has ROLE_REVOKE."""
        assert AuditAction.ROLE_REVOKE == "ROLE_REVOKE"

    def test_schema_audit_action_has_key_create(self):
        """Schema AuditAction has KEY_CREATE."""
        assert AuditAction.KEY_CREATE == "KEY_CREATE"

    def test_schema_audit_action_has_key_revoke(self):
        """Schema AuditAction has KEY_REVOKE."""
        assert AuditAction.KEY_REVOKE == "KEY_REVOKE"

    def test_schema_audit_action_has_export(self):
        """Schema AuditAction has EXPORT."""
        assert AuditAction.EXPORT == "EXPORT"

    def test_schema_audit_action_has_report_generated(self):
        """Schema AuditAction has REPORT_GENERATED."""
        assert AuditAction.REPORT_GENERATED == "REPORT_GENERATED"

    def test_schema_action_values_match_model(self):
        """Schema AuditAction values match model AuditAction values."""
        schema_values = {a.value for a in AuditAction}
        model_values = {a.value for a in ModelAuditAction}
        assert schema_values == model_values


class TestSchemaAuditOutcomeEnum:
    """Tests for AuditOutcome enum in schemas."""

    def test_schema_audit_outcome_has_success(self):
        """Schema AuditOutcome has SUCCESS."""
        assert AuditOutcome.SUCCESS == "SUCCESS"

    def test_schema_audit_outcome_has_failure(self):
        """Schema AuditOutcome has FAILURE."""
        assert AuditOutcome.FAILURE == "FAILURE"

    def test_schema_audit_outcome_has_denied(self):
        """Schema AuditOutcome has DENIED."""
        assert AuditOutcome.DENIED == "DENIED"

    def test_schema_outcome_values_match_model(self):
        """Schema AuditOutcome values match model AuditOutcome values."""
        schema_values = {o.value for o in AuditOutcome}
        model_values = {o.value for o in ModelAuditOutcome}
        assert schema_values == model_values


class TestComplianceAuditEventCreate:
    """Tests for ComplianceAuditEventCreate schema."""

    def test_create_with_required_fields(self):
        """Schema validates with only required fields."""
        data = ComplianceAuditEventCreate(
            action=AuditAction.CREATE,
            resource_type="feature_flag",
            outcome=AuditOutcome.SUCCESS,
        )
        assert data.action == AuditAction.CREATE
        assert data.resource_type == "feature_flag"
        assert data.outcome == AuditOutcome.SUCCESS

    def test_create_with_all_optional_fields(self):
        """Schema validates with all optional fields provided."""
        actor_id = uuid.uuid4()
        data = ComplianceAuditEventCreate(
            action=AuditAction.UPDATE,
            resource_type="experiment",
            outcome=AuditOutcome.SUCCESS,
            actor_id=actor_id,
            actor_ip="10.0.0.1",
            actor_user_agent="TestAgent/1.0",
            session_id="sess_123",
            request_id="req_456",
            resource_id="exp_001",
            old_value={"status": "draft"},
            new_value={"status": "active"},
        )
        assert data.actor_id == actor_id
        assert data.actor_ip == "10.0.0.1"
        assert data.session_id == "sess_123"
        assert data.request_id == "req_456"
        assert data.resource_id == "exp_001"

    def test_create_missing_action_raises_validation_error(self):
        """Missing action field raises ValidationError."""
        with pytest.raises(ValidationError):
            ComplianceAuditEventCreate(
                resource_type="feature_flag",
                outcome=AuditOutcome.SUCCESS,
            )

    def test_create_missing_resource_type_raises_validation_error(self):
        """Missing resource_type field raises ValidationError."""
        with pytest.raises(ValidationError):
            ComplianceAuditEventCreate(
                action=AuditAction.CREATE,
                outcome=AuditOutcome.SUCCESS,
            )

    def test_create_missing_outcome_raises_validation_error(self):
        """Missing outcome field raises ValidationError."""
        with pytest.raises(ValidationError):
            ComplianceAuditEventCreate(
                action=AuditAction.CREATE,
                resource_type="feature_flag",
            )

    def test_create_invalid_action_raises_validation_error(self):
        """Invalid action value raises ValidationError."""
        with pytest.raises(ValidationError):
            ComplianceAuditEventCreate(
                action="INVALID_ACTION",
                resource_type="feature_flag",
                outcome=AuditOutcome.SUCCESS,
            )

    def test_create_invalid_outcome_raises_validation_error(self):
        """Invalid outcome value raises ValidationError."""
        with pytest.raises(ValidationError):
            ComplianceAuditEventCreate(
                action=AuditAction.CREATE,
                resource_type="feature_flag",
                outcome="INVALID_OUTCOME",
            )

    def test_create_optional_fields_default_to_none(self):
        """Optional fields default to None when not provided."""
        data = ComplianceAuditEventCreate(
            action=AuditAction.LOGIN,
            resource_type="session",
            outcome=AuditOutcome.SUCCESS,
        )
        assert data.actor_id is None
        assert data.actor_ip is None
        assert data.actor_user_agent is None
        assert data.session_id is None
        assert data.request_id is None
        assert data.resource_id is None
        assert data.old_value is None
        assert data.new_value is None


class TestComplianceAuditEventResponse:
    """Tests for ComplianceAuditEventResponse schema."""

    def test_response_schema_has_id_field(self):
        """Response schema includes id field."""
        fields = ComplianceAuditEventResponse.model_fields
        assert "id" in fields

    def test_response_schema_has_timestamp_field(self):
        """Response schema includes timestamp field."""
        fields = ComplianceAuditEventResponse.model_fields
        assert "timestamp" in fields

    def test_response_schema_has_action_field(self):
        """Response schema includes action field."""
        fields = ComplianceAuditEventResponse.model_fields
        assert "action" in fields

    def test_response_schema_has_resource_type_field(self):
        """Response schema includes resource_type field."""
        fields = ComplianceAuditEventResponse.model_fields
        assert "resource_type" in fields

    def test_response_schema_has_outcome_field(self):
        """Response schema includes outcome field."""
        fields = ComplianceAuditEventResponse.model_fields
        assert "outcome" in fields

    def test_response_schema_has_hmac_signature_field(self):
        """Response schema includes hmac_signature field."""
        fields = ComplianceAuditEventResponse.model_fields
        assert "hmac_signature" in fields

    def test_response_from_attributes_enabled(self):
        """Response schema has from_attributes=True (ORM mode)."""
        config = ComplianceAuditEventResponse.model_config
        assert config.get("from_attributes") is True

    def test_response_can_be_built_from_dict(self):
        """Response schema validates from a dict."""
        data = ComplianceAuditEventResponse(
            id=uuid.uuid4(),
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            action=AuditAction.CREATE,
            resource_type="feature_flag",
            outcome=AuditOutcome.SUCCESS,
            hmac_signature=None,
        )
        assert data.action == AuditAction.CREATE
        assert data.outcome == AuditOutcome.SUCCESS


class TestComplianceAuditEventListResponse:
    """Tests for ComplianceAuditEventListResponse schema."""

    def test_list_response_has_items_field(self):
        """List response schema has items field."""
        fields = ComplianceAuditEventListResponse.model_fields
        assert "items" in fields

    def test_list_response_has_total_field(self):
        """List response schema has total field."""
        fields = ComplianceAuditEventListResponse.model_fields
        assert "total" in fields

    def test_list_response_has_page_field(self):
        """List response schema has page field."""
        fields = ComplianceAuditEventListResponse.model_fields
        assert "page" in fields

    def test_list_response_has_limit_field(self):
        """List response schema has limit field."""
        fields = ComplianceAuditEventListResponse.model_fields
        assert "limit" in fields

    def test_list_response_validates(self):
        """List response schema validates correctly."""
        response_item = ComplianceAuditEventResponse(
            id=uuid.uuid4(),
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            action=AuditAction.READ,
            resource_type="experiment",
            outcome=AuditOutcome.SUCCESS,
            hmac_signature=None,
        )
        list_resp = ComplianceAuditEventListResponse(
            items=[response_item],
            total=1,
            page=1,
            limit=20,
        )
        assert list_resp.total == 1
        assert list_resp.page == 1
        assert list_resp.limit == 20
        assert len(list_resp.items) == 1

    def test_list_response_empty_items(self):
        """List response schema validates with empty items list."""
        list_resp = ComplianceAuditEventListResponse(
            items=[],
            total=0,
            page=1,
            limit=20,
        )
        assert list_resp.total == 0
        assert list_resp.items == []
