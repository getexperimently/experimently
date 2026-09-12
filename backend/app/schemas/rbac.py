"""
RBAC Post-MVP schemas — API contract for custom roles and permission management.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PermissionAction(str, Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LIST = "list"


class PermissionResource(str, Enum):
    EXPERIMENT = "experiment"
    FEATURE_FLAG = "feature_flag"
    USER = "user"
    ROLE = "role"
    PERMISSION = "permission"
    REPORT = "report"
    AUDIT_LOG = "audit_log"
    EXPORT = "export"


class PermissionGrant(BaseModel):
    resource: PermissionResource
    actions: List[PermissionAction] = Field(..., min_length=1)


class CustomRoleCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    description: Optional[str] = Field(None, max_length=256)
    permissions: List[PermissionGrant] = Field(default_factory=list)


# Rebuild to resolve forward references (PermissionGrant used in CustomRoleCreate)
CustomRoleCreate.model_rebuild()


class CustomRoleUpdate(BaseModel):
    description: Optional[str] = Field(None, max_length=256)
    permissions: Optional[List[PermissionGrant]] = None


class CustomRoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: Optional[str]
    is_system_role: bool  # True for the 4 built-in roles
    permissions: List[PermissionGrant]
    created_at: datetime
    user_count: int = 0  # How many users have this role


class AssignRoleRequest(BaseModel):
    user_id: str
    role_name: str
    reason: Optional[str] = Field(None, max_length=256)


class RevokeRoleRequest(BaseModel):
    user_id: str
    role_name: str
    reason: Optional[str] = Field(None, max_length=256)


class EffectivePermissionsResponse(BaseModel):
    """Complete resolved permission set for a user."""

    user_id: str
    username: str
    base_role: str  # The user.role field (admin/developer/analyst/viewer)
    custom_roles: List[str]  # Names of custom roles assigned to this user
    permissions: Dict[str, List[str]]  # {"experiment": ["read", "list"], ...}
    is_superuser: bool


class DelegatePermissionRequest(BaseModel):
    """Grant a specific permission to a user directly (not via role)."""

    user_id: str
    resource: PermissionResource
    actions: List[PermissionAction] = Field(..., min_length=1)
    reason: Optional[str] = Field(None, max_length=256)
    expires_at: Optional[datetime] = None  # Optional expiry for temporary grants
