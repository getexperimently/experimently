"""Unit tests for RBACService — all using MagicMock DB."""
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from backend.app.schemas.rbac import (
    CustomRoleCreate, CustomRoleUpdate, PermissionGrant,
    PermissionAction, PermissionResource,
)
from backend.app.services.rbac_service import RBACService
from backend.app.models.user import UserRole


class TestCreateCustomRole:
    def test_creates_role_with_name(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        data = CustomRoleCreate(name="data-scientist", permissions=[])
        role = RBACService.create_custom_role(db, data, uuid4())
        db.add.assert_called_once()
        db.flush.assert_called_once()

    def test_raises_if_name_exists(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock()
        data = CustomRoleCreate(name="existing-role", permissions=[])
        with pytest.raises(ValueError, match="already exists"):
            RBACService.create_custom_role(db, data, uuid4())

    def test_persists_permissions(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        perms = [PermissionGrant(resource=PermissionResource.EXPERIMENT, actions=[PermissionAction.READ])]
        data = CustomRoleCreate(name="readonly-experiments", permissions=perms)
        RBACService.create_custom_role(db, data, uuid4())
        added = db.add.call_args[0][0]
        assert len(added.permissions) == 1
        assert added.permissions[0]["resource"] == "experiment"


class TestUpdateCustomRole:
    def test_raises_on_system_role(self):
        db = MagicMock()
        mock_role = MagicMock()
        mock_role.is_system_role = True
        db.query.return_value.filter.return_value.first.return_value = mock_role
        with pytest.raises(ValueError, match="Cannot modify system roles"):
            RBACService.update_custom_role(db, "admin", CustomRoleUpdate(description="new"))

    def test_raises_if_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found"):
            RBACService.update_custom_role(db, "ghost", CustomRoleUpdate())

    def test_updates_description(self):
        db = MagicMock()
        mock_role = MagicMock()
        mock_role.is_system_role = False
        db.query.return_value.filter.return_value.first.return_value = mock_role
        RBACService.update_custom_role(db, "myrole", CustomRoleUpdate(description="updated"))
        assert mock_role.description == "updated"


class TestDeleteCustomRole:
    def test_raises_on_system_role(self):
        db = MagicMock()
        mock_role = MagicMock()
        mock_role.is_system_role = True
        db.query.return_value.filter.return_value.first.return_value = mock_role
        with pytest.raises(ValueError, match="Cannot delete system roles"):
            RBACService.delete_custom_role(db, "admin")

    def test_deletes_role(self):
        db = MagicMock()
        mock_role = MagicMock()
        mock_role.is_system_role = False
        db.query.return_value.filter.return_value.first.return_value = mock_role
        RBACService.delete_custom_role(db, "myrole")
        db.delete.assert_called_with(mock_role)


class TestAssignRevoke:
    def test_assign_creates_assignment(self):
        db = MagicMock()
        mock_role = MagicMock()
        mock_role.id = uuid4()
        db.query.return_value.filter.return_value.first.side_effect = [mock_role, None]
        RBACService.assign_role(db, uuid4(), "myrole", uuid4())
        db.add.assert_called_once()

    def test_assign_idempotent(self):
        db = MagicMock()
        mock_role = MagicMock()
        mock_role.id = uuid4()
        mock_existing = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [mock_role, mock_existing]
        result = RBACService.assign_role(db, uuid4(), "myrole", uuid4())
        db.add.assert_not_called()
        assert result == mock_existing

    def test_assign_raises_if_role_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found"):
            RBACService.assign_role(db, uuid4(), "ghost", uuid4())

    def test_revoke_calls_delete(self):
        db = MagicMock()
        mock_role = MagicMock()
        mock_role.id = uuid4()
        db.query.return_value.filter.return_value.first.return_value = mock_role
        RBACService.revoke_role(db, uuid4(), "myrole")
        db.query.return_value.filter.return_value.delete.assert_called_once()


class TestGetEffectivePermissions:
    def test_superuser_gets_all_permissions(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        user = MagicMock()
        user.is_superuser = True
        user.id = uuid4()
        user.username = "admin"
        user.role = UserRole.ADMIN
        result = RBACService.get_effective_permissions(db, user)
        assert result.is_superuser is True
        assert "create" in result.permissions.get("experiment", [])

    def test_viewer_gets_read_only(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        user = MagicMock()
        user.is_superuser = False
        user.id = uuid4()
        user.username = "viewer1"
        user.role = UserRole.VIEWER
        result = RBACService.get_effective_permissions(db, user)
        assert "read" in result.permissions.get("experiment", [])
        assert "create" not in result.permissions.get("experiment", [])

    def test_custom_role_permissions_merged(self):
        db = MagicMock()
        mock_role = MagicMock()
        mock_role.permissions = [{"resource": "export", "actions": ["read", "list"]}]
        mock_assignment = MagicMock()
        mock_assignment.role = mock_role
        mock_assignment.role.name = "exporter"
        db.query.return_value.filter.return_value.all.side_effect = [
            [mock_assignment],  # UserCustomRole query
            [],                 # DirectPermissionGrant query
            [mock_assignment],  # second UserCustomRole query for names
        ]
        user = MagicMock()
        user.is_superuser = False
        user.id = uuid4()
        user.username = "dev1"
        user.role = UserRole.DEVELOPER
        result = RBACService.get_effective_permissions(db, user)
        assert "read" in result.permissions.get("export", [])

    def test_expired_direct_grant_not_included(self):
        db = MagicMock()
        expired_grant = MagicMock()
        expired_grant.is_valid = False
        expired_grant.resource = "report"
        expired_grant.actions = ["delete"]
        db.query.return_value.filter.return_value.all.side_effect = [
            [],               # UserCustomRole
            [expired_grant],  # DirectPermissionGrant
            [],               # for custom_role_names
        ]
        user = MagicMock()
        user.is_superuser = False
        user.id = uuid4()
        user.username = "user1"
        user.role = UserRole.VIEWER
        result = RBACService.get_effective_permissions(db, user)
        assert "delete" not in result.permissions.get("report", [])

    def test_valid_direct_grant_included(self):
        db = MagicMock()
        valid_grant = MagicMock()
        valid_grant.is_valid = True
        valid_grant.resource = "report"
        valid_grant.actions = ["create"]
        db.query.return_value.filter.return_value.all.side_effect = [
            [],              # UserCustomRole
            [valid_grant],   # DirectPermissionGrant
            [],              # custom_role_names
        ]
        user = MagicMock()
        user.is_superuser = False
        user.id = uuid4()
        user.username = "user1"
        user.role = UserRole.VIEWER
        result = RBACService.get_effective_permissions(db, user)
        assert "create" in result.permissions.get("report", [])


class TestCheckEffectivePermission:
    def test_superuser_always_true(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        user = MagicMock()
        user.is_superuser = True
        user.id = uuid4()
        user.username = "su"
        user.role = UserRole.ADMIN
        assert RBACService.check_effective_permission(db, user, "experiment", "delete") is True

    def test_viewer_cannot_create(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        user = MagicMock()
        user.is_superuser = False
        user.id = uuid4()
        user.username = "viewer"
        user.role = UserRole.VIEWER
        assert RBACService.check_effective_permission(db, user, "experiment", "create") is False
