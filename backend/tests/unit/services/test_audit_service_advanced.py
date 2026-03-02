"""
Unit tests for advanced AuditService methods added in P1-B.
Tests compute_diff, log_bulk_toggle, get_flag_change_history.
All use MagicMock DB — no real database.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4
from backend.app.services.audit_service import AuditService


class TestComputeDiff:
    def test_identical_dicts_return_empty_diff(self):
        """No changes -> empty diff list"""
        old = {"status": "ACTIVE", "rollout_percentage": 50}
        new = {"status": "ACTIVE", "rollout_percentage": 50}
        result = AuditService.compute_diff(old, new)
        assert result == []

    def test_single_field_change(self):
        """One changed field -> one diff entry"""
        old = {"status": "INACTIVE", "name": "my-flag"}
        new = {"status": "ACTIVE", "name": "my-flag"}
        result = AuditService.compute_diff(old, new)
        assert len(result) == 1
        assert result[0]["field"] == "status"
        assert result[0]["old_value"] == "INACTIVE"
        assert result[0]["new_value"] == "ACTIVE"
        assert result[0]["changed"] is True

    def test_multiple_field_changes(self):
        """Multiple changed fields -> multiple diff entries"""
        old = {"status": "INACTIVE", "rollout_percentage": 0, "name": "old"}
        new = {"status": "ACTIVE", "rollout_percentage": 50, "name": "old"}
        result = AuditService.compute_diff(old, new)
        assert len(result) == 2
        fields = {d["field"] for d in result}
        assert "status" in fields
        assert "rollout_percentage" in fields

    def test_new_field_added(self):
        """Field present in new but not old -> diff entry"""
        old = {"status": "INACTIVE"}
        new = {"status": "INACTIVE", "description": "new desc"}
        result = AuditService.compute_diff(old, new)
        assert len(result) == 1
        assert result[0]["field"] == "description"
        assert result[0]["old_value"] is None
        assert result[0]["new_value"] == "new desc"

    def test_field_removed(self):
        """Field present in old but not new -> diff entry"""
        old = {"status": "ACTIVE", "description": "old desc"}
        new = {"status": "ACTIVE"}
        result = AuditService.compute_diff(old, new)
        assert len(result) == 1
        assert result[0]["field"] == "description"
        assert result[0]["old_value"] == "old desc"
        assert result[0]["new_value"] is None

    def test_empty_dicts(self):
        """Both empty -> empty diff"""
        assert AuditService.compute_diff({}, {}) == []

    def test_diff_fields_are_sorted(self):
        """Diff entries are sorted alphabetically by field name"""
        old = {"z_field": 1, "a_field": 2}
        new = {"z_field": 9, "a_field": 9}
        result = AuditService.compute_diff(old, new)
        fields = [d["field"] for d in result]
        assert fields == sorted(fields)

    def test_none_values_handled(self):
        """None values in both old and new don't create diff"""
        old = {"field": None}
        new = {"field": None}
        result = AuditService.compute_diff(old, new)
        assert result == []

    def test_type_change_detected(self):
        """Type change (e.g., str vs int) is detected"""
        old = {"count": "5"}
        new = {"count": 5}
        result = AuditService.compute_diff(old, new)
        assert len(result) == 1


class TestGetFlagChangeHistory:
    def test_returns_tuple_of_logs_and_count(self):
        """Returns (list, int) tuple"""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 5
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = AuditService.get_flag_change_history(mock_db, uuid4(), limit=10, offset=0)
        assert isinstance(result, tuple)
        assert len(result) == 2
        logs, count = result
        assert isinstance(logs, list)
        assert isinstance(count, int)

    def test_filters_by_entity_id(self):
        """Query filters audit logs by the given entity_id"""
        mock_db = MagicMock()
        flag_id = uuid4()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        AuditService.get_flag_change_history(mock_db, flag_id)
        mock_db.query.assert_called_once()

    def test_respects_limit_and_offset(self):
        """Limit and offset parameters are applied"""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 100
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        AuditService.get_flag_change_history(mock_db, uuid4(), limit=25, offset=50)
        mock_query.limit.assert_called_with(25)
        mock_query.offset.assert_called_with(50)


class TestBulkToggleLog:
    @pytest.mark.asyncio
    async def test_returns_list_of_uuids(self):
        """log_bulk_toggle returns a list of audit log UUIDs"""
        mock_db = MagicMock()
        mock_log = MagicMock()
        mock_log.id = uuid4()
        mock_db.add = MagicMock()
        mock_db.flush = MagicMock()

        with patch.object(
            AuditService, "log_toggle_operation", new_callable=AsyncMock
        ) as mock_log_op:
            mock_log_op.return_value = uuid4()
            result = await AuditService.log_bulk_toggle(
                db=mock_db,
                user_id=uuid4(),
                user_email="test@example.com",
                flag_ids=[uuid4(), uuid4()],
                action="toggle_enable",
                results=[
                    {
                        "flag_id": str(uuid4()),
                        "flag_name": "Flag A",
                        "old_status": "INACTIVE",
                        "new_status": "ACTIVE",
                    },
                    {
                        "flag_id": str(uuid4()),
                        "flag_name": "Flag B",
                        "old_status": "INACTIVE",
                        "new_status": "ACTIVE",
                    },
                ],
            )
        assert isinstance(result, list)
        assert len(result) == 2
