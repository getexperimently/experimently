"""
RBAC service — custom role management and effective permissions resolution.
"""

from datetime import datetime
from typing import Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.core.permissions import ROLE_PERMISSIONS, ResourceType
from backend.app.models.user import User, UserRole
from modules.backend.app.models.custom_role import (
    CustomRole,
    DirectPermissionGrant,
    UserCustomRole,
)
from modules.backend.app.schemas.rbac import (
    CustomRoleCreate,
    CustomRoleUpdate,
    EffectivePermissionsResponse,
)


class RBACService:
    @staticmethod
    def create_custom_role(
        db: Session, data: CustomRoleCreate, created_by_id: UUID
    ) -> CustomRole:
        """Create a new custom role. Raises ValueError if name already exists."""
        existing = db.query(CustomRole).filter(CustomRole.name == data.name).first()
        if existing:
            raise ValueError(f"Role '{data.name}' already exists")
        role = CustomRole(
            name=data.name,
            description=data.description,
            permissions=[p.model_dump() for p in data.permissions],
            created_by_id=created_by_id,
        )
        db.add(role)
        db.flush()
        return role

    @staticmethod
    def list_custom_roles(db: Session, include_system: bool = True) -> List[CustomRole]:
        """List all custom roles, optionally including system roles."""
        q = db.query(CustomRole)
        if not include_system:
            q = q.filter(CustomRole.is_system_role == False)
        return q.order_by(CustomRole.name).all()

    @staticmethod
    def get_custom_role(db: Session, role_name: str) -> Optional[CustomRole]:
        return db.query(CustomRole).filter(CustomRole.name == role_name).first()

    @staticmethod
    def update_custom_role(
        db: Session, role_name: str, data: CustomRoleUpdate
    ) -> CustomRole:
        role = db.query(CustomRole).filter(CustomRole.name == role_name).first()
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        if role.is_system_role:
            raise ValueError("Cannot modify system roles")
        if data.description is not None:
            role.description = data.description
        if data.permissions is not None:
            role.permissions = [p.model_dump() for p in data.permissions]
        db.flush()
        return role

    @staticmethod
    def delete_custom_role(db: Session, role_name: str) -> None:
        role = db.query(CustomRole).filter(CustomRole.name == role_name).first()
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        if role.is_system_role:
            raise ValueError("Cannot delete system roles")
        db.delete(role)
        db.flush()

    @staticmethod
    def assign_role(
        db: Session,
        user_id: UUID,
        role_name: str,
        assigned_by_id: UUID,
        reason: Optional[str] = None,
    ) -> UserCustomRole:
        """Assign a custom role to a user. Idempotent — no error if already assigned."""
        role = db.query(CustomRole).filter(CustomRole.name == role_name).first()
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        existing = (
            db.query(UserCustomRole)
            .filter(
                UserCustomRole.user_id == user_id,
                UserCustomRole.role_id == role.id,
            )
            .first()
        )
        if existing:
            return existing
        assignment = UserCustomRole(
            user_id=user_id,
            role_id=role.id,
            assigned_by_id=assigned_by_id,
            reason=reason,
        )
        db.add(assignment)
        db.flush()
        return assignment

    @staticmethod
    def revoke_role(db: Session, user_id: UUID, role_name: str) -> None:
        """Revoke a custom role from a user. No error if not assigned."""
        role = db.query(CustomRole).filter(CustomRole.name == role_name).first()
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        db.query(UserCustomRole).filter(
            UserCustomRole.user_id == user_id,
            UserCustomRole.role_id == role.id,
        ).delete()
        db.flush()

    @staticmethod
    def grant_direct_permission(
        db: Session,
        user_id: UUID,
        resource: str,
        actions: List[str],
        granted_by_id: UUID,
        reason: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> DirectPermissionGrant:
        """Grant a direct permission to a user."""
        grant = DirectPermissionGrant(
            user_id=user_id,
            resource=resource,
            actions=actions,
            granted_by_id=granted_by_id,
            reason=reason,
            expires_at=expires_at,
            is_active=True,
        )
        db.add(grant)
        db.flush()
        return grant

    @staticmethod
    def revoke_direct_permission(db: Session, user_id: UUID, resource: str) -> int:
        """Revoke all direct grants for a user+resource. Returns count deleted."""
        count = (
            db.query(DirectPermissionGrant)
            .filter(
                DirectPermissionGrant.user_id == user_id,
                DirectPermissionGrant.resource == resource,
            )
            .delete()
        )
        db.flush()
        return count

    @staticmethod
    def get_effective_permissions(
        db: Session, user: User
    ) -> EffectivePermissionsResponse:
        """
        Resolve a user's full permission set:
        1. Start with base role permissions (ROLE_PERMISSIONS)
        2. Merge in custom role permissions
        3. Merge in valid direct permission grants
        4. Superusers get all permissions
        """
        perms: Dict[str, Set[str]] = {}

        if user.is_superuser:
            # Superuser: all resources, all actions
            for resource in ResourceType:
                perms[resource.value] = {"create", "read", "update", "delete", "list"}
        else:
            # 1. Base role — safely handle mock objects or missing roles
            try:
                base_role = getattr(user, "role", UserRole.VIEWER)
                base_role_perms = ROLE_PERMISSIONS.get(base_role, {})
            except Exception:
                base_role_perms = {}

            for resource, actions in base_role_perms.items():
                perms.setdefault(resource.value, set()).update(a.value for a in actions)

            # 2. Custom roles
            custom_assignments = (
                db.query(UserCustomRole).filter(UserCustomRole.user_id == user.id).all()
            )
            for assignment in custom_assignments:
                role = assignment.role
                for perm in role.permissions or []:
                    resource_key = perm.get("resource", "")
                    actions_list = perm.get("actions", [])
                    perms.setdefault(resource_key, set()).update(actions_list)

            # 3. Direct grants (valid only)
            direct_grants = (
                db.query(DirectPermissionGrant)
                .filter(
                    DirectPermissionGrant.user_id == user.id,
                    DirectPermissionGrant.is_active == True,
                )
                .all()
            )
            for grant in direct_grants:
                if grant.is_valid:
                    perms.setdefault(grant.resource, set()).update(grant.actions or [])

        # Get custom role names
        custom_role_names = []
        assignments = (
            db.query(UserCustomRole).filter(UserCustomRole.user_id == user.id).all()
        )
        for a in assignments:
            if a.role:
                custom_role_names.append(a.role.name)

        # Build base_role string safely
        user_role = getattr(user, "role", UserRole.VIEWER)
        if hasattr(user_role, "value"):
            base_role_str = user_role.value
        else:
            base_role_str = str(user_role)

        return EffectivePermissionsResponse(
            user_id=str(user.id),
            username=user.username,
            base_role=base_role_str,
            custom_roles=custom_role_names,
            permissions={k: sorted(v) for k, v in perms.items()},
            is_superuser=bool(user.is_superuser),
        )

    @staticmethod
    def check_effective_permission(
        db: Session, user: User, resource: str, action: str
    ) -> bool:
        """
        Check if a user has an effective permission (base + custom + direct).
        Used as a drop-in enhancement for check_permission().
        """
        if user.is_superuser:
            return True
        effective = RBACService.get_effective_permissions(db, user)
        return action in effective.permissions.get(resource, [])
