"""
Pydantic schemas for EP-057: Multi-Tenant Team Workspaces.
"""

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

# ─────────────────────────────────────────────────────────────────────────────
# Workspace
# ─────────────────────────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,48}[a-z0-9]$")


class CreateWorkspaceRequest(BaseModel):
    """Payload for creating a new workspace."""

    name: str
    slug: str
    description: str = ""
    plan: str = "free"

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "Slug must be 3–50 characters, lowercase alphanumeric with hyphens, "
                "and must not start or end with a hyphen."
            )
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        if len(v) > 200:
            raise ValueError("name must be at most 200 characters")
        return v

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v: str) -> str:
        allowed = {"free", "pro", "enterprise"}
        if v not in allowed:
            raise ValueError(f"plan must be one of {sorted(allowed)}")
        return v


class UpdateWorkspaceRequest(BaseModel):
    """Payload for updating an existing workspace (all fields optional)."""

    name: Optional[str] = None
    description: Optional[str] = None
    plan: Optional[str] = None


class WorkspaceResponse(BaseModel):
    """Response schema for a workspace."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: Optional[str]
    plan: str
    is_active: bool
    max_experiments: int
    max_feature_flags: int
    max_members: int
    max_api_keys: int
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v):
        return str(v)

    @field_validator("plan", mode="before")
    @classmethod
    def coerce_plan(cls, v):
        if hasattr(v, "value"):
            return v.value
        return str(v)


class WorkspaceWithStatsResponse(WorkspaceResponse):
    """Workspace response enriched with live resource counts."""

    member_count: int = 0
    experiment_count: int = 0
    flag_count: int = 0
    api_key_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Members
# ─────────────────────────────────────────────────────────────────────────────


class AddMemberRequest(BaseModel):
    """Payload for adding an existing user to a workspace."""

    user_id: str
    role: str = "VIEWER"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"OWNER", "ADMIN", "DEVELOPER", "ANALYST", "VIEWER"}
        if v.upper() not in allowed:
            raise ValueError(f"role must be one of {sorted(allowed)}")
        return v.upper()


class UpdateMemberRoleRequest(BaseModel):
    """Payload for changing a member's role."""

    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"OWNER", "ADMIN", "DEVELOPER", "ANALYST", "VIEWER"}
        if v.upper() not in allowed:
            raise ValueError(f"role must be one of {sorted(allowed)}")
        return v.upper()


class WorkspaceMemberResponse(BaseModel):
    """Response schema for a workspace member."""

    model_config = ConfigDict(from_attributes=True)

    workspace_id: str
    user_id: str
    role: str
    joined_at: datetime

    # Denormalised user fields (populated manually in endpoints)
    username: Optional[str] = None
    email: Optional[str] = None

    @field_validator("workspace_id", "user_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v):
        return str(v)

    @field_validator("role", mode="before")
    @classmethod
    def coerce_role(cls, v):
        if hasattr(v, "value"):
            return v.value
        return str(v)


# ─────────────────────────────────────────────────────────────────────────────
# Invites
# ─────────────────────────────────────────────────────────────────────────────


class CreateInviteRequest(BaseModel):
    """Payload for sending a workspace invite."""

    email: str
    role: str = "VIEWER"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        # OWNER cannot be granted via invite
        allowed = {"ADMIN", "DEVELOPER", "ANALYST", "VIEWER"}
        if v.upper() not in allowed:
            raise ValueError(
                f"role must be one of {sorted(allowed)} (OWNER cannot be invited)"
            )
        return v.upper()


class WorkspaceInviteResponse(BaseModel):
    """Response schema for a workspace invite."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    email: str
    role: str
    token: str
    expires_at: datetime
    accepted_at: Optional[datetime]

    @field_validator("id", "workspace_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v):
        return str(v)

    @field_validator("role", mode="before")
    @classmethod
    def coerce_role(cls, v):
        if hasattr(v, "value"):
            return v.value
        return str(v)


# ─────────────────────────────────────────────────────────────────────────────
# API Keys
# ─────────────────────────────────────────────────────────────────────────────


class CreateAPIKeyRequest(BaseModel):
    """Payload for creating a new workspace-scoped API key."""

    name: str
    scopes: List[str] = ["flags:read", "experiments:read", "track:write"]
    expires_at: Optional[datetime] = None


class CreateAPIKeyResponse(BaseModel):
    """Response schema returned exactly once when a new API key is created."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    key: str  # plaintext — shown ONCE only
    scopes: List[str]
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v):
        return str(v)


class WorkspaceAPIKeyResponse(BaseModel):
    """Safe response schema for listing API keys (no plaintext)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    scopes: List[str]
    is_active: bool
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v):
        return str(v)
