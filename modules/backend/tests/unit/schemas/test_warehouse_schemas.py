"""
Unit tests for Warehouse-Native Analytics Pydantic schemas (Issue #26).

Validates:
 - WarehouseType enum values and behaviour
 - WarehouseConnectionCreate required fields and validation
 - WarehouseConnectionResponse — credential fields absent
 - SyncRequest required / optional fields
 - SyncStatusResponse field structure
 - ConnectionTestResponse field structure
"""

import pytest
from pydantic import ValidationError

from modules.backend.app.schemas.warehouse import (
    ConnectionTestResponse,
    SyncRequest,
    SyncStatusResponse,
    WarehouseConnectionCreate,
    WarehouseConnectionResponse,
    WarehouseType,
)

# ---------------------------------------------------------------------------
# TestWarehouseTypeEnum
# ---------------------------------------------------------------------------


class TestWarehouseTypeEnum:
    """WarehouseType enum correctness."""

    def test_snowflake_enum_value(self):
        assert WarehouseType.SNOWFLAKE == "snowflake"

    def test_bigquery_enum_value(self):
        assert WarehouseType.BIGQUERY == "bigquery"

    def test_redshift_enum_value(self):
        assert WarehouseType.REDSHIFT == "redshift"

    def test_invalid_warehouse_type_raises(self):
        """Passing an unsupported warehouse type to WarehouseConnectionCreate must raise."""
        with pytest.raises(ValidationError):
            WarehouseConnectionCreate(
                name="My Connection",
                warehouse_type="oracle",  # not a valid WarehouseType
            )

    def test_enum_members_count(self):
        assert len(WarehouseType) == 3


# ---------------------------------------------------------------------------
# TestWarehouseConnectionCreate
# ---------------------------------------------------------------------------


class TestWarehouseConnectionCreate:
    """Validation of the connection creation request schema."""

    def test_create_requires_name(self):
        with pytest.raises(ValidationError):
            WarehouseConnectionCreate(warehouse_type=WarehouseType.SNOWFLAKE)

    def test_create_requires_warehouse_type(self):
        with pytest.raises(ValidationError):
            WarehouseConnectionCreate(name="My Connection")

    def test_create_accepts_valid_payload(self):
        schema = WarehouseConnectionCreate(
            name="My Snowflake",
            warehouse_type=WarehouseType.SNOWFLAKE,
            host="account.snowflakecomputing.com",
            username="svc_user",
            password="s3cr3t",
        )
        assert schema.name == "My Snowflake"
        assert schema.warehouse_type == WarehouseType.SNOWFLAKE

    def test_create_name_cannot_be_empty_string(self):
        with pytest.raises(ValidationError):
            WarehouseConnectionCreate(
                name="",
                warehouse_type=WarehouseType.REDSHIFT,
            )

    def test_create_bigquery_accepts_project_id_without_host(self):
        """BigQuery connections use project_id, not host."""
        schema = WarehouseConnectionCreate(
            name="My BigQuery",
            warehouse_type=WarehouseType.BIGQUERY,
            project_id="my-gcp-project",
        )
        assert schema.project_id == "my-gcp-project"
        assert schema.host is None

    def test_create_optional_fields_default_to_none(self):
        schema = WarehouseConnectionCreate(
            name="Minimal",
            warehouse_type=WarehouseType.REDSHIFT,
        )
        assert schema.host is None
        assert schema.database is None
        assert schema.schema_name is None
        assert schema.username is None
        assert schema.password is None
        assert schema.project_id is None


# ---------------------------------------------------------------------------
# TestWarehouseConnectionResponse
# ---------------------------------------------------------------------------


class TestWarehouseConnectionResponse:
    """Response schema must never expose credentials."""

    def _make_response(self, **kwargs):
        defaults = {
            "id": "some-uuid",
            "name": "My Connection",
            "warehouse_type": "snowflake",
            "is_active": True,
        }
        defaults.update(kwargs)
        return WarehouseConnectionResponse(**defaults)

    def test_response_has_id(self):
        resp = self._make_response()
        assert resp.id == "some-uuid"

    def test_response_has_name(self):
        resp = self._make_response()
        assert resp.name == "My Connection"

    def test_response_has_warehouse_type(self):
        resp = self._make_response()
        assert resp.warehouse_type == "snowflake"

    def test_response_has_is_active(self):
        resp = self._make_response()
        assert resp.is_active is True

    def test_response_does_not_have_password_field(self):
        """password must not be a field on the response schema."""
        resp = self._make_response()
        assert not hasattr(resp, "password")

    def test_response_does_not_have_encrypted_credentials_field(self):
        """encrypted_credentials must not be a field on the response schema."""
        resp = self._make_response()
        assert not hasattr(resp, "encrypted_credentials")


# ---------------------------------------------------------------------------
# TestSyncRequest
# ---------------------------------------------------------------------------


class TestSyncRequest:
    """SyncRequest required and optional field validation."""

    def test_sync_request_requires_assignments_table(self):
        with pytest.raises(ValidationError):
            SyncRequest(events_table="events", metric_event="purchase")

    def test_sync_request_requires_events_table(self):
        with pytest.raises(ValidationError):
            SyncRequest(assignments_table="assignments", metric_event="purchase")

    def test_sync_request_requires_metric_event(self):
        with pytest.raises(ValidationError):
            SyncRequest(assignments_table="assignments", events_table="events")

    def test_sync_request_accepts_valid_payload(self):
        req = SyncRequest(
            assignments_table="exp_assignments",
            events_table="exp_events",
            metric_event="checkout_completed",
        )
        assert req.assignments_table == "exp_assignments"
        assert req.events_table == "exp_events"
        assert req.metric_event == "checkout_completed"

    def test_sync_request_optional_dates_default_to_none(self):
        req = SyncRequest(
            assignments_table="a",
            events_table="e",
            metric_event="buy",
        )
        assert req.start_date is None
        assert req.end_date is None


# ---------------------------------------------------------------------------
# TestSyncStatusResponse
# ---------------------------------------------------------------------------


class TestSyncStatusResponse:
    """SyncStatusResponse field structure."""

    def test_sync_status_response_required_fields(self):
        resp = SyncStatusResponse(experiment_id="exp-001", status="success")
        assert resp.experiment_id == "exp-001"
        assert resp.status == "success"
        assert resp.rows_processed == 0
        assert resp.variants_updated == 0
        assert resp.error is None
        assert resp.generated_sql is None

    def test_sync_status_response_with_all_fields(self):
        resp = SyncStatusResponse(
            experiment_id="exp-002",
            status="failed",
            rows_processed=150,
            variants_updated=2,
            error="Connection timeout",
            generated_sql="SELECT ...",
        )
        assert resp.rows_processed == 150
        assert resp.error == "Connection timeout"
        assert resp.generated_sql == "SELECT ..."


# ---------------------------------------------------------------------------
# TestConnectionTestResponse
# ---------------------------------------------------------------------------


class TestConnectionTestResponse:
    """ConnectionTestResponse field structure."""

    def test_connection_test_response_success(self):
        resp = ConnectionTestResponse(success=True, latency_ms=42.5)
        assert resp.success is True
        assert resp.latency_ms == 42.5
        assert resp.error is None

    def test_connection_test_response_failure(self):
        resp = ConnectionTestResponse(
            success=False, latency_ms=0.0, error="Host not reachable"
        )
        assert resp.success is False
        assert resp.error == "Host not reachable"

    def test_connection_test_response_requires_success_and_latency(self):
        with pytest.raises(ValidationError):
            ConnectionTestResponse(latency_ms=10.0)  # missing success
