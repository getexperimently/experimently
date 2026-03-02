"""Unit tests for RBAC Pydantic schemas."""
import pytest
from pydantic import ValidationError
from backend.app.schemas.rbac import (
    CustomRoleCreate, CustomRoleUpdate, PermissionGrant,
    PermissionAction, PermissionResource, AssignRoleRequest,
    DelegatePermissionRequest,
)


class TestCustomRoleCreate:
    def test_valid_role_name(self):
        role = CustomRoleCreate(name="data-scientist", permissions=[])
        assert role.name == "data-scientist"

    def test_name_must_start_with_letter(self):
        with pytest.raises(ValidationError):
            CustomRoleCreate(name="1invalid", permissions=[])

    def test_name_uppercase_rejected(self):
        with pytest.raises(ValidationError):
            CustomRoleCreate(name="MyRole", permissions=[])

    def test_name_too_short_rejected(self):
        with pytest.raises(ValidationError):
            CustomRoleCreate(name="a", permissions=[])

    def test_name_with_underscores_valid(self):
        role = CustomRoleCreate(name="read_only_experiments", permissions=[])
        assert role.name == "read_only_experiments"

    def test_permissions_default_empty(self):
        role = CustomRoleCreate(name="empty-role", permissions=[])
        assert role.permissions == []

    def test_description_optional(self):
        role = CustomRoleCreate(name="my-role", permissions=[])
        assert role.description is None


class TestPermissionGrant:
    def test_valid_grant(self):
        grant = PermissionGrant(resource=PermissionResource.EXPERIMENT, actions=[PermissionAction.READ])
        assert grant.resource == PermissionResource.EXPERIMENT

    def test_empty_actions_rejected(self):
        with pytest.raises(ValidationError):
            PermissionGrant(resource=PermissionResource.EXPERIMENT, actions=[])

    def test_multiple_actions(self):
        grant = PermissionGrant(
            resource=PermissionResource.FEATURE_FLAG,
            actions=[PermissionAction.READ, PermissionAction.LIST],
        )
        assert len(grant.actions) == 2


class TestAssignRoleRequest:
    def test_valid_request(self):
        req = AssignRoleRequest(user_id="some-uuid", role_name="analyst-plus")
        assert req.role_name == "analyst-plus"

    def test_reason_optional(self):
        req = AssignRoleRequest(user_id="uid", role_name="role")
        assert req.reason is None


class TestDelegatePermissionRequest:
    def test_valid_delegation(self):
        req = DelegatePermissionRequest(
            user_id="uid",
            resource=PermissionResource.REPORT,
            actions=[PermissionAction.CREATE],
        )
        assert req.resource == PermissionResource.REPORT

    def test_expires_at_optional(self):
        req = DelegatePermissionRequest(
            user_id="uid",
            resource=PermissionResource.EXPORT,
            actions=[PermissionAction.READ],
        )
        assert req.expires_at is None
