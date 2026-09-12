"""
RBAC management endpoints (P2-A).

GET    /api/v1/rbac/roles                    — list all custom roles
POST   /api/v1/rbac/roles                    — create custom role (ADMIN only)
GET    /api/v1/rbac/roles/{name}             — get role details
PUT    /api/v1/rbac/roles/{name}             — update role (ADMIN only)
DELETE /api/v1/rbac/roles/{name}             — delete role (ADMIN only)
POST   /api/v1/rbac/roles/assign             — assign role to user (ADMIN only)
POST   /api/v1/rbac/roles/revoke             — revoke role from user (ADMIN only)
GET    /api/v1/rbac/users/{user_id}/permissions — get effective permissions
POST   /api/v1/rbac/users/{user_id}/grant    — grant direct permission (ADMIN only)
DELETE /api/v1/rbac/users/{user_id}/grant/{resource} — revoke direct permission
"""

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.api.deps import get_db
from backend.app.models.user import User, UserRole
from backend.app.schemas.rbac import (
    AssignRoleRequest,
    CustomRoleCreate,
    CustomRoleResponse,
    CustomRoleUpdate,
    DelegatePermissionRequest,
    EffectivePermissionsResponse,
    RevokeRoleRequest,
)
from backend.app.services.rbac_service import RBACService

if TYPE_CHECKING:
    from backend.app.models.custom_role import CustomRole

router = APIRouter()


def _require_admin(current_user: User) -> None:
    """Raise 403 if user is not ADMIN or superuser."""
    role = getattr(current_user, "role", None)
    if not current_user.is_superuser and role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")


@router.get("/roles", response_model=list[CustomRoleResponse])
def list_roles(
    include_system: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """List all custom roles, optionally including system roles."""
    roles = RBACService.list_custom_roles(db, include_system=include_system)
    return [_role_to_response(r, db) for r in roles]


@router.post("/roles", response_model=CustomRoleResponse, status_code=201)
def create_role(
    data: CustomRoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Create a new custom role. ADMIN only."""
    _require_admin(current_user)
    try:
        role = RBACService.create_custom_role(db, data, current_user.id)
        db.commit()
        return _role_to_response(role, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/roles/{role_name}", response_model=CustomRoleResponse)
def get_role(
    role_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Get details of a specific custom role."""
    role = RBACService.get_custom_role(db, role_name)
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")
    return _role_to_response(role, db)


@router.put("/roles/{role_name}", response_model=CustomRoleResponse)
def update_role(
    role_name: str,
    data: CustomRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Update a custom role. ADMIN only."""
    _require_admin(current_user)
    try:
        role = RBACService.update_custom_role(db, role_name, data)
        db.commit()
        return _role_to_response(role, db)
    except ValueError as e:
        error_str = str(e)
        status_code = 404 if "not found" in error_str else 400
        raise HTTPException(status_code=status_code, detail=error_str)


@router.delete("/roles/{role_name}", status_code=204)
def delete_role(
    role_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Delete a custom role. ADMIN only. System roles cannot be deleted."""
    _require_admin(current_user)
    try:
        RBACService.delete_custom_role(db, role_name)
        db.commit()
    except ValueError as e:
        error_str = str(e)
        status_code = 404 if "not found" in error_str else 400
        raise HTTPException(status_code=status_code, detail=error_str)


@router.post("/roles/assign", status_code=200)
def assign_role(
    data: AssignRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Assign a custom role to a user. ADMIN only. Idempotent."""
    _require_admin(current_user)
    try:
        RBACService.assign_role(
            db, UUID(data.user_id), data.role_name, current_user.id, data.reason
        )
        db.commit()
        return {"status": "assigned", "user_id": data.user_id, "role": data.role_name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/roles/revoke", status_code=200)
def revoke_role(
    data: RevokeRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Revoke a custom role from a user. ADMIN only."""
    _require_admin(current_user)
    try:
        RBACService.revoke_role(db, UUID(data.user_id), data.role_name)
        db.commit()
        return {"status": "revoked", "user_id": data.user_id, "role": data.role_name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/users/{user_id}/permissions", response_model=EffectivePermissionsResponse)
def get_effective_permissions(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    Get effective permissions for a user.
    Users can view their own permissions; admins can view anyone's.
    """
    # Users can view their own permissions; admins can view anyone's
    if str(user_id) != str(current_user.id):
        _require_admin(current_user)
    from backend.app.models.user import User as UserModel

    target_user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    return RBACService.get_effective_permissions(db, target_user)


@router.post("/users/{user_id}/grant", status_code=201)
def grant_permission(
    user_id: UUID,
    data: DelegatePermissionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Grant a direct permission to a user. ADMIN only. Supports expiry."""
    _require_admin(current_user)
    RBACService.grant_direct_permission(
        db,
        user_id=user_id,
        resource=data.resource.value,
        actions=[a.value for a in data.actions],
        granted_by_id=current_user.id,
        reason=data.reason,
        expires_at=data.expires_at,
    )
    db.commit()
    return {
        "status": "granted",
        "user_id": str(user_id),
        "resource": data.resource,
        "actions": data.actions,
    }


@router.delete("/users/{user_id}/grant/{resource}", status_code=200)
def revoke_permission(
    user_id: UUID,
    resource: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Revoke all direct grants for a user+resource. ADMIN only."""
    _require_admin(current_user)
    count = RBACService.revoke_direct_permission(db, user_id, resource)
    db.commit()
    return {"status": "revoked", "count": count}


def _role_to_response(role: "CustomRole", db: Session) -> CustomRoleResponse:
    """Convert a CustomRole model instance to a CustomRoleResponse schema."""
    from backend.app.models.custom_role import UserCustomRole

    user_count = (
        db.query(UserCustomRole).filter(UserCustomRole.role_id == role.id).count()
    )
    return CustomRoleResponse(
        id=str(role.id),
        name=role.name,
        description=role.description,
        is_system_role=role.is_system_role,
        permissions=[
            {"resource": p["resource"], "actions": p["actions"]}
            for p in (role.permissions or [])
        ],
        created_at=role.created_at,
        user_count=user_count,
    )
