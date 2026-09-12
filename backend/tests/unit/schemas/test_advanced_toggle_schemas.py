"""
Unit tests for advanced toggle Pydantic schemas.
Tests validation, defaults, and field constraints.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.schemas.advanced_toggle import (
    AuditDiff,
    BulkToggleAction,
    BulkToggleRequest,
    BulkToggleResponse,
    BulkToggleResult,
)


class TestBulkToggleRequest:
    def test_valid_enable_request(self):
        req = BulkToggleRequest(flag_ids=[str(uuid4())], action=BulkToggleAction.ENABLE)
        assert req.action == BulkToggleAction.ENABLE
        assert len(req.flag_ids) == 1

    def test_valid_disable_request(self):
        req = BulkToggleRequest(
            flag_ids=[str(uuid4()), str(uuid4())], action=BulkToggleAction.DISABLE
        )
        assert req.action == BulkToggleAction.DISABLE

    def test_empty_flag_ids_raises_error(self):
        with pytest.raises(ValidationError):
            BulkToggleRequest(flag_ids=[], action=BulkToggleAction.ENABLE)

    def test_reason_is_optional(self):
        req = BulkToggleRequest(flag_ids=[str(uuid4())], action=BulkToggleAction.ENABLE)
        assert req.reason is None

    def test_reason_with_value(self):
        req = BulkToggleRequest(
            flag_ids=[str(uuid4())],
            action=BulkToggleAction.ENABLE,
            reason="Planned release",
        )
        assert req.reason == "Planned release"

    def test_reason_max_length_enforced(self):
        with pytest.raises(ValidationError):
            BulkToggleRequest(
                flag_ids=[str(uuid4())],
                action=BulkToggleAction.ENABLE,
                reason="x" * 501,  # Over 500 char limit
            )

    def test_invalid_action_raises_error(self):
        with pytest.raises(ValidationError):
            BulkToggleRequest(flag_ids=[str(uuid4())], action="invalid")

    def test_all_action_types_valid(self):
        for action in BulkToggleAction:
            req = BulkToggleRequest(flag_ids=[str(uuid4())], action=action)
            assert req.action == action


class TestBulkToggleResult:
    def test_success_result(self):
        result = BulkToggleResult(
            flag_id=str(uuid4()),
            flag_key="my-flag",
            success=True,
            old_status="INACTIVE",
            new_status="ACTIVE",
        )
        assert result.success is True
        assert result.error is None

    def test_failure_result(self):
        result = BulkToggleResult(
            flag_id=str(uuid4()),
            flag_key="unknown",
            success=False,
            error="Not found",
        )
        assert result.success is False
        assert result.error == "Not found"


class TestAuditDiff:
    def test_changed_diff(self):
        diff = AuditDiff(
            field="status", old_value="INACTIVE", new_value="ACTIVE", changed=True
        )
        assert diff.changed is True
        assert diff.field == "status"

    def test_diff_with_none_values(self):
        diff = AuditDiff(
            field="description", old_value=None, new_value="New desc", changed=True
        )
        assert diff.old_value is None
        assert diff.new_value == "New desc"
