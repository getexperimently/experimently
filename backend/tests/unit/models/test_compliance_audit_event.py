"""
Unit tests for ComplianceAuditEvent model.

Tests cover:
- Model existence and inheritance
- Table name and schema
- Column definitions and constraints
- Enum values for AuditAction and AuditOutcome
- Index definitions
"""

import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from backend.app.models.compliance_audit_event import (
    ComplianceAuditEvent,
    AuditAction,
    AuditOutcome,
)
from backend.app.models.base import Base
from backend.app.core.database_config import get_schema_name


class TestComplianceAuditEventModel:
    """Tests for the ComplianceAuditEvent SQLAlchemy model."""

    def test_model_exists(self):
        """ComplianceAuditEvent model can be imported and instantiated."""
        event = ComplianceAuditEvent()
        assert event is not None

    def test_model_inherits_from_base(self):
        """ComplianceAuditEvent inherits from Base."""
        assert issubclass(ComplianceAuditEvent, Base)

    def test_table_name(self):
        """Table name is 'audit_events_v2'."""
        assert ComplianceAuditEvent.__tablename__ == "audit_events_v2"

    def test_table_schema(self):
        """Table has the schema from get_schema_name()."""
        table_args = ComplianceAuditEvent.__table_args__
        # table_args is a tuple where the last element is a dict with 'schema'
        schema_dict = None
        for arg in table_args:
            if isinstance(arg, dict) and "schema" in arg:
                schema_dict = arg
                break
        assert schema_dict is not None
        assert schema_dict["schema"] == get_schema_name()

    def test_has_id_column(self):
        """Model has an 'id' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "id" in columns

    def test_has_timestamp_column(self):
        """Model has a 'timestamp' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "timestamp" in columns

    def test_has_actor_id_column(self):
        """Model has an 'actor_id' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "actor_id" in columns

    def test_has_actor_ip_column(self):
        """Model has an 'actor_ip' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "actor_ip" in columns

    def test_has_actor_user_agent_column(self):
        """Model has an 'actor_user_agent' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "actor_user_agent" in columns

    def test_has_session_id_column(self):
        """Model has a 'session_id' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "session_id" in columns

    def test_has_request_id_column(self):
        """Model has a 'request_id' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "request_id" in columns

    def test_has_action_column(self):
        """Model has an 'action' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "action" in columns

    def test_has_resource_type_column(self):
        """Model has a 'resource_type' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "resource_type" in columns

    def test_has_resource_id_column(self):
        """Model has a 'resource_id' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "resource_id" in columns

    def test_has_old_value_column(self):
        """Model has an 'old_value' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "old_value" in columns

    def test_has_new_value_column(self):
        """Model has a 'new_value' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "new_value" in columns

    def test_has_outcome_column(self):
        """Model has an 'outcome' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "outcome" in columns

    def test_has_hmac_signature_column(self):
        """Model has an 'hmac_signature' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "hmac_signature" in columns

    def test_has_archived_at_column(self):
        """Model has an 'archived_at' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "archived_at" in columns

    def test_has_retention_expires_at_column(self):
        """Model has a 'retention_expires_at' column."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        assert "retention_expires_at" in columns

    def test_total_column_count(self):
        """Model has exactly the expected columns (15+)."""
        columns = {c.name for c in ComplianceAuditEvent.__table__.columns}
        expected = {
            "id", "timestamp", "actor_id", "actor_ip", "actor_user_agent",
            "session_id", "request_id", "action", "resource_type", "resource_id",
            "old_value", "new_value", "outcome", "hmac_signature",
            "archived_at", "retention_expires_at",
        }
        assert expected.issubset(columns)

    def test_id_is_non_nullable(self):
        """id column is non-nullable."""
        col = ComplianceAuditEvent.__table__.columns["id"]
        assert not col.nullable

    def test_timestamp_is_non_nullable(self):
        """timestamp column is non-nullable."""
        col = ComplianceAuditEvent.__table__.columns["timestamp"]
        assert not col.nullable

    def test_action_is_non_nullable(self):
        """action column is non-nullable."""
        col = ComplianceAuditEvent.__table__.columns["action"]
        assert not col.nullable

    def test_resource_type_is_non_nullable(self):
        """resource_type column is non-nullable."""
        col = ComplianceAuditEvent.__table__.columns["resource_type"]
        assert not col.nullable

    def test_outcome_is_non_nullable(self):
        """outcome column is non-nullable."""
        col = ComplianceAuditEvent.__table__.columns["outcome"]
        assert not col.nullable

    def test_actor_id_is_nullable(self):
        """actor_id column is nullable (system events may have no actor)."""
        col = ComplianceAuditEvent.__table__.columns["actor_id"]
        assert col.nullable

    def test_actor_ip_is_nullable(self):
        """actor_ip column is nullable."""
        col = ComplianceAuditEvent.__table__.columns["actor_ip"]
        assert col.nullable

    def test_actor_user_agent_is_nullable(self):
        """actor_user_agent column is nullable."""
        col = ComplianceAuditEvent.__table__.columns["actor_user_agent"]
        assert col.nullable

    def test_session_id_is_nullable(self):
        """session_id column is nullable."""
        col = ComplianceAuditEvent.__table__.columns["session_id"]
        assert col.nullable

    def test_request_id_is_nullable(self):
        """request_id column is nullable."""
        col = ComplianceAuditEvent.__table__.columns["request_id"]
        assert col.nullable

    def test_resource_id_is_nullable(self):
        """resource_id column is nullable (e.g., LOGIN events)."""
        col = ComplianceAuditEvent.__table__.columns["resource_id"]
        assert col.nullable

    def test_old_value_is_nullable(self):
        """old_value column is nullable."""
        col = ComplianceAuditEvent.__table__.columns["old_value"]
        assert col.nullable

    def test_new_value_is_nullable(self):
        """new_value column is nullable."""
        col = ComplianceAuditEvent.__table__.columns["new_value"]
        assert col.nullable

    def test_hmac_signature_is_nullable(self):
        """hmac_signature column is nullable (signed asynchronously)."""
        col = ComplianceAuditEvent.__table__.columns["hmac_signature"]
        assert col.nullable

    def test_archived_at_is_nullable(self):
        """archived_at column is nullable."""
        col = ComplianceAuditEvent.__table__.columns["archived_at"]
        assert col.nullable

    def test_retention_expires_at_is_nullable(self):
        """retention_expires_at column is nullable."""
        col = ComplianceAuditEvent.__table__.columns["retention_expires_at"]
        assert col.nullable

    def test_timestamp_index_exists(self):
        """Index on 'timestamp' exists."""
        index_names = {idx.name for idx in ComplianceAuditEvent.__table__.indexes}
        # At least one index should reference 'timestamp'
        timestamp_indexes = [
            idx for idx in ComplianceAuditEvent.__table__.indexes
            if any(col.name == "timestamp" for col in idx.columns)
        ]
        assert len(timestamp_indexes) >= 1

    def test_actor_id_index_exists(self):
        """Index on 'actor_id' exists."""
        actor_id_indexes = [
            idx for idx in ComplianceAuditEvent.__table__.indexes
            if any(col.name == "actor_id" for col in idx.columns)
        ]
        assert len(actor_id_indexes) >= 1

    def test_instantiation_with_required_fields(self):
        """Model can be instantiated with required fields."""
        event = ComplianceAuditEvent(
            action=AuditAction.CREATE,
            resource_type="feature_flag",
            outcome=AuditOutcome.SUCCESS,
        )
        assert event.action == AuditAction.CREATE
        assert event.resource_type == "feature_flag"
        assert event.outcome == AuditOutcome.SUCCESS

    def test_instantiation_with_all_fields(self):
        """Model can be instantiated with all optional fields."""
        actor_id = uuid.uuid4()
        event = ComplianceAuditEvent(
            id=uuid.uuid4(),
            actor_id=actor_id,
            actor_ip="192.168.1.1",
            actor_user_agent="Mozilla/5.0",
            session_id="sess_abc123",
            request_id="req_xyz789",
            action=AuditAction.UPDATE,
            resource_type="experiment",
            resource_id="exp_001",
            old_value={"status": "draft"},
            new_value={"status": "active"},
            outcome=AuditOutcome.SUCCESS,
            hmac_signature="a" * 64,
        )
        assert event.actor_id == actor_id
        assert event.actor_ip == "192.168.1.1"
        assert event.session_id == "sess_abc123"
        assert event.action == AuditAction.UPDATE
        assert event.outcome == AuditOutcome.SUCCESS


class TestAuditActionEnum:
    """Tests for AuditAction enum."""

    def test_audit_action_exists(self):
        """AuditAction enum can be imported."""
        assert AuditAction is not None

    def test_action_create(self):
        """CREATE action exists."""
        assert AuditAction.CREATE == "CREATE"

    def test_action_read(self):
        """READ action exists."""
        assert AuditAction.READ == "READ"

    def test_action_update(self):
        """UPDATE action exists."""
        assert AuditAction.UPDATE == "UPDATE"

    def test_action_delete(self):
        """DELETE action exists."""
        assert AuditAction.DELETE == "DELETE"

    def test_action_login(self):
        """LOGIN action exists."""
        assert AuditAction.LOGIN == "LOGIN"

    def test_action_logout(self):
        """LOGOUT action exists."""
        assert AuditAction.LOGOUT == "LOGOUT"

    def test_action_login_failed(self):
        """LOGIN_FAILED action exists."""
        assert AuditAction.LOGIN_FAILED == "LOGIN_FAILED"

    def test_action_role_grant(self):
        """ROLE_GRANT action exists."""
        assert AuditAction.ROLE_GRANT == "ROLE_GRANT"

    def test_action_role_revoke(self):
        """ROLE_REVOKE action exists."""
        assert AuditAction.ROLE_REVOKE == "ROLE_REVOKE"

    def test_action_key_create(self):
        """KEY_CREATE action exists."""
        assert AuditAction.KEY_CREATE == "KEY_CREATE"

    def test_action_key_revoke(self):
        """KEY_REVOKE action exists."""
        assert AuditAction.KEY_REVOKE == "KEY_REVOKE"

    def test_action_export(self):
        """EXPORT action exists."""
        assert AuditAction.EXPORT == "EXPORT"

    def test_action_report_generated(self):
        """REPORT_GENERATED action exists."""
        assert AuditAction.REPORT_GENERATED == "REPORT_GENERATED"

    def test_all_expected_actions_present(self):
        """All 13 expected AuditAction values are present."""
        expected = {
            "CREATE", "READ", "UPDATE", "DELETE",
            "LOGIN", "LOGOUT", "LOGIN_FAILED",
            "ROLE_GRANT", "ROLE_REVOKE",
            "KEY_CREATE", "KEY_REVOKE",
            "EXPORT", "REPORT_GENERATED",
        }
        actual = {action.value for action in AuditAction}
        assert expected == actual

    def test_audit_action_is_str_enum(self):
        """AuditAction members are strings (str, Enum)."""
        assert isinstance(AuditAction.CREATE, str)
        assert AuditAction.CREATE == "CREATE"


class TestAuditOutcomeEnum:
    """Tests for AuditOutcome enum."""

    def test_audit_outcome_exists(self):
        """AuditOutcome enum can be imported."""
        assert AuditOutcome is not None

    def test_outcome_success(self):
        """SUCCESS outcome exists."""
        assert AuditOutcome.SUCCESS == "SUCCESS"

    def test_outcome_failure(self):
        """FAILURE outcome exists."""
        assert AuditOutcome.FAILURE == "FAILURE"

    def test_outcome_denied(self):
        """DENIED outcome exists."""
        assert AuditOutcome.DENIED == "DENIED"

    def test_all_expected_outcomes_present(self):
        """All 3 AuditOutcome values are present."""
        expected = {"SUCCESS", "FAILURE", "DENIED"}
        actual = {o.value for o in AuditOutcome}
        assert expected == actual

    def test_audit_outcome_is_str_enum(self):
        """AuditOutcome members are strings (str, Enum)."""
        assert isinstance(AuditOutcome.SUCCESS, str)
        assert AuditOutcome.SUCCESS == "SUCCESS"
