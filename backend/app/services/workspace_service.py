"""
WorkspaceService for EP-057: Multi-Tenant Team Workspaces.

Handles all business logic for workspace CRUD, membership management,
invite lifecycle, and workspace-scoped API key management.
"""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.workspace import (
    ROLE_HIERARCHY,
    Workspace,
    WorkspaceAPIKey,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceMemberRole,
    WorkspacePlan,
)

# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class WorkspaceError(Exception):
    """Base exception for workspace service errors."""


class WorkspaceNotFound(WorkspaceError):
    """Raised when a workspace cannot be found."""


class WorkspaceMemberNotFound(WorkspaceError):
    """Raised when a workspace member record cannot be found."""


class WorkspacePermissionError(WorkspaceError):
    """Raised when the caller lacks the required workspace role."""


class WorkspaceSlugTaken(WorkspaceError):
    """Raised when the requested slug is already in use."""


class WorkspaceSlugInvalid(WorkspaceError):
    """Raised when the slug does not match the allowed character pattern."""


class AlreadyMember(WorkspaceError):
    """Raised when a user is already a member of the workspace."""


class CannotRemoveLastOwner(WorkspaceError):
    """Raised when attempting to remove the only owner of a workspace."""


class CannotDemoteLastOwner(WorkspaceError):
    """Raised when an owner attempts to remove their own OWNER role."""


class InviteNotFound(WorkspaceError):
    """Raised when an invite token cannot be found."""


class InviteExpired(WorkspaceError):
    """Raised when attempting to accept an expired invite."""


class InviteAlreadyAccepted(WorkspaceError):
    """Raised when attempting to accept an already-accepted invite."""


class PlanLimitExceeded(WorkspaceError):
    """Raised when a plan resource limit would be exceeded."""


class APIKeyNotFound(WorkspaceError):
    """Raised when a workspace API key cannot be found."""


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WorkspaceStats:
    """Aggregated statistics for a workspace."""

    member_count: int
    experiment_count: int
    flag_count: int
    api_key_count: int


# ─────────────────────────────────────────────────────────────────────────────
# Slug helpers
# ─────────────────────────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,48}[a-z0-9]$")


def _validate_slug(slug: str) -> None:
    """Raise WorkspaceSlugInvalid if slug is not URL-safe."""
    if not _SLUG_RE.match(slug):
        raise WorkspaceSlugInvalid(
            "Slug must be 3–50 characters, lowercase alphanumeric with hyphens, "
            "and must not start or end with a hyphen."
        )


# ─────────────────────────────────────────────────────────────────────────────
# API key helpers
# ─────────────────────────────────────────────────────────────────────────────

_KEY_PREFIX_DISPLAY = "ep_live_"


def _generate_api_key() -> str:
    """Return a random workspace API key with a recognisable prefix."""
    return f"{_KEY_PREFIX_DISPLAY}{secrets.token_hex(24)}"


def _hash_key(plaintext: str) -> str:
    """Return the SHA-256 hex digest of a plaintext API key."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Plan defaults
# ─────────────────────────────────────────────────────────────────────────────

_PLAN_LIMITS = {
    WorkspacePlan.FREE: {
        "max_experiments": 10,
        "max_feature_flags": 50,
        "max_members": 5,
        "max_api_keys": 3,
    },
    WorkspacePlan.PRO: {
        "max_experiments": 1000,
        "max_feature_flags": 5000,
        "max_members": 50,
        "max_api_keys": 20,
    },
    WorkspacePlan.ENTERPRISE: {
        "max_experiments": 999999,
        "max_feature_flags": 999999,
        "max_members": 999999,
        "max_api_keys": 999999,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class WorkspaceService:
    """Business logic layer for workspace management."""

    # ── Workspace CRUD ────────────────────────────────────────────────────────

    def create_workspace(
        self,
        db: Session,
        name: str,
        slug: str,
        owner_id: uuid.UUID,
        plan: str = "free",
        description: str = "",
    ) -> Workspace:
        """Create a new workspace and add the creator as OWNER."""
        _validate_slug(slug)

        # Check slug uniqueness
        existing = db.query(Workspace).filter(Workspace.slug == slug).first()
        if existing:
            raise WorkspaceSlugTaken(f"Slug '{slug}' is already in use.")

        try:
            plan_enum = WorkspacePlan(plan)
        except ValueError:
            plan_enum = WorkspacePlan.FREE

        limits = _PLAN_LIMITS[plan_enum]
        workspace = Workspace(
            name=name,
            slug=slug,
            description=description,
            plan=plan_enum,
            is_active=True,
            **limits,
        )
        db.add(workspace)
        db.flush()  # get workspace.id before adding member

        # Add owner as first member
        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner_id,
            role=WorkspaceMemberRole.OWNER,
            invited_by=None,
            joined_at=datetime.utcnow(),
        )
        db.add(member)
        db.commit()
        db.refresh(workspace)
        return workspace

    def get_workspace(self, db: Session, workspace_id: uuid.UUID) -> Workspace:
        """Return a workspace by ID or raise WorkspaceNotFound."""
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not workspace:
            raise WorkspaceNotFound(f"Workspace {workspace_id} not found.")
        return workspace

    def get_workspace_by_slug(self, db: Session, slug: str) -> Workspace:
        """Return a workspace by slug or raise WorkspaceNotFound."""
        workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
        if not workspace:
            raise WorkspaceNotFound(f"Workspace with slug '{slug}' not found.")
        return workspace

    def list_user_workspaces(
        self, db: Session, user_id: uuid.UUID
    ) -> List[Workspace]:
        """Return all workspaces the user is a member of."""
        members = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user_id)
            .all()
        )
        workspace_ids = [m.workspace_id for m in members]
        if not workspace_ids:
            return []
        return (
            db.query(Workspace)
            .filter(Workspace.id.in_(workspace_ids))
            .all()
        )

    def update_workspace(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        data: dict,
    ) -> Workspace:
        """Update workspace fields. Only name, description, plan are mutable."""
        workspace = self.get_workspace(db, workspace_id)

        allowed = {"name", "description", "plan"}
        for key, value in data.items():
            if key not in allowed:
                continue
            if key == "plan":
                try:
                    value = WorkspacePlan(value)
                    # Update limits when plan changes
                    limits = _PLAN_LIMITS[value]
                    for limit_key, limit_val in limits.items():
                        setattr(workspace, limit_key, limit_val)
                except ValueError:
                    continue
            setattr(workspace, key, value)

        db.commit()
        db.refresh(workspace)
        return workspace

    def delete_workspace(self, db: Session, workspace_id: uuid.UUID) -> None:
        """Delete a workspace and all associated resources (via cascade)."""
        workspace = self.get_workspace(db, workspace_id)
        db.delete(workspace)
        db.commit()

    # ── Members ───────────────────────────────────────────────────────────────

    def add_member(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        invited_by: uuid.UUID,
    ) -> WorkspaceMember:
        """Add an existing user as a member of the workspace."""
        workspace = self.get_workspace(db, workspace_id)

        # Check plan limit
        current_count = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace_id)
            .count()
        )
        if current_count >= workspace.max_members:
            raise PlanLimitExceeded(
                f"Workspace has reached its member limit ({workspace.max_members})."
            )

        # Check for existing membership
        existing = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .first()
        )
        if existing:
            raise AlreadyMember(f"User {user_id} is already a member of this workspace.")

        try:
            role_enum = WorkspaceMemberRole[role.upper()]
        except KeyError:
            role_enum = WorkspaceMemberRole.VIEWER

        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role_enum,
            invited_by=invited_by,
            joined_at=datetime.utcnow(),
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    def remove_member(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Remove a user from the workspace."""
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .first()
        )
        if not member:
            raise WorkspaceMemberNotFound(
                f"User {user_id} is not a member of workspace {workspace_id}."
            )

        # Prevent removing the last owner
        if member.role == WorkspaceMemberRole.OWNER:
            owner_count = (
                db.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == WorkspaceMemberRole.OWNER,
                )
                .count()
            )
            if owner_count <= 1:
                raise CannotRemoveLastOwner(
                    "Cannot remove the last owner of a workspace."
                )

        db.delete(member)
        db.commit()

    def update_member_role(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        new_role: str,
    ) -> WorkspaceMember:
        """Change a member's role within the workspace."""
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .first()
        )
        if not member:
            raise WorkspaceMemberNotFound(
                f"User {user_id} is not a member of workspace {workspace_id}."
            )

        # Prevent an owner from demoting themselves if they are the last owner
        if (
            member.role == WorkspaceMemberRole.OWNER
            and new_role.upper() != "OWNER"
        ):
            owner_count = (
                db.query(WorkspaceMember)
                .filter(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == WorkspaceMemberRole.OWNER,
                )
                .count()
            )
            if owner_count <= 1:
                raise CannotDemoteLastOwner(
                    "Cannot demote the last owner of a workspace."
                )

        try:
            member.role = WorkspaceMemberRole[new_role.upper()]
        except KeyError:
            member.role = WorkspaceMemberRole.VIEWER

        db.commit()
        db.refresh(member)
        return member

    def list_members(
        self, db: Session, workspace_id: uuid.UUID
    ) -> List[WorkspaceMember]:
        """Return all members of a workspace."""
        return (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace_id)
            .all()
        )

    # ── Invites ───────────────────────────────────────────────────────────────

    def create_invite(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        email: str,
        role: str,
        invited_by: uuid.UUID,
    ) -> WorkspaceInvite:
        """Create a 7-day invite token for the given email address."""
        self.get_workspace(db, workspace_id)  # existence check

        try:
            role_enum = WorkspaceMemberRole[role.upper()]
        except KeyError:
            role_enum = WorkspaceMemberRole.VIEWER

        token = secrets.token_hex(32)
        expires_at = datetime.utcnow() + timedelta(days=7)

        invite = WorkspaceInvite(
            workspace_id=workspace_id,
            email=email,
            role=role_enum,
            token=token,
            invited_by=invited_by,
            expires_at=expires_at,
        )
        db.add(invite)
        db.commit()
        db.refresh(invite)
        return invite

    def get_invite_by_token(self, db: Session, token: str) -> WorkspaceInvite:
        """Return an invite by its token or raise InviteNotFound."""
        invite = (
            db.query(WorkspaceInvite)
            .filter(WorkspaceInvite.token == token)
            .first()
        )
        if not invite:
            raise InviteNotFound(f"Invite token not found.")
        return invite

    def accept_invite(
        self,
        db: Session,
        token: str,
        user_id: uuid.UUID,
    ) -> WorkspaceMember:
        """Accept an invite and add the user to the workspace."""
        invite = self.get_invite_by_token(db, token)

        if invite.is_expired:
            raise InviteExpired("This invite has expired.")
        if invite.is_accepted:
            raise InviteAlreadyAccepted("This invite has already been accepted.")

        # Mark accepted
        invite.accepted_at = datetime.utcnow()
        db.flush()

        # Add as member (may raise PlanLimitExceeded or AlreadyMember)
        member = self.add_member(
            db,
            workspace_id=invite.workspace_id,
            user_id=user_id,
            role=invite.role.value,
            invited_by=invite.invited_by,
        )
        return member

    # ── API Keys ──────────────────────────────────────────────────────────────

    def create_api_key(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        name: str,
        scopes: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
    ) -> Tuple[WorkspaceAPIKey, str]:
        """
        Create a new workspace-scoped API key.

        Returns (WorkspaceAPIKey, plaintext_key). The plaintext key is shown
        exactly once — the caller must present it to the user immediately.
        """
        workspace = self.get_workspace(db, workspace_id)

        # Check plan limit
        active_key_count = (
            db.query(WorkspaceAPIKey)
            .filter(
                WorkspaceAPIKey.workspace_id == workspace_id,
                WorkspaceAPIKey.is_active == True,
            )
            .count()
        )
        if active_key_count >= workspace.max_api_keys:
            raise PlanLimitExceeded(
                f"Workspace has reached its API key limit ({workspace.max_api_keys})."
            )

        if scopes is None:
            scopes = ["flags:read", "experiments:read", "track:write"]

        plaintext = _generate_api_key()
        key_hash = _hash_key(plaintext)
        key_prefix = plaintext[:8]

        api_key = WorkspaceAPIKey(
            workspace_id=workspace_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=scopes,
            is_active=True,
            expires_at=expires_at,
        )
        db.add(api_key)
        db.commit()
        db.refresh(api_key)
        return api_key, plaintext

    def revoke_api_key(
        self, db: Session, api_key_id: uuid.UUID
    ) -> None:
        """Deactivate a workspace API key."""
        key = (
            db.query(WorkspaceAPIKey)
            .filter(WorkspaceAPIKey.id == api_key_id)
            .first()
        )
        if not key:
            raise APIKeyNotFound(f"API key {api_key_id} not found.")
        key.is_active = False
        db.commit()

    def rotate_api_key(
        self, db: Session, api_key_id: uuid.UUID
    ) -> Tuple[WorkspaceAPIKey, str]:
        """
        Rotate a workspace API key.

        The old key is deactivated and a new one with the same name/scopes is
        created. Returns (new_WorkspaceAPIKey, new_plaintext_key).
        """
        old_key = (
            db.query(WorkspaceAPIKey)
            .filter(WorkspaceAPIKey.id == api_key_id)
            .first()
        )
        if not old_key:
            raise APIKeyNotFound(f"API key {api_key_id} not found.")

        # Deactivate old key
        old_key.is_active = False
        db.flush()

        # Create replacement key bypassing the limit check (rotation = replace not add)
        plaintext = _generate_api_key()
        key_hash = _hash_key(plaintext)
        key_prefix = plaintext[:8]

        new_key = WorkspaceAPIKey(
            workspace_id=old_key.workspace_id,
            name=old_key.name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=old_key.scopes,
            is_active=True,
            expires_at=old_key.expires_at,
        )
        db.add(new_key)
        db.commit()
        db.refresh(new_key)
        return new_key, plaintext

    def get_api_key_by_hash(
        self, db: Session, plaintext: str
    ) -> Optional[WorkspaceAPIKey]:
        """Look up a workspace API key by its plaintext value (hashed internally)."""
        key_hash = _hash_key(plaintext)
        return (
            db.query(WorkspaceAPIKey)
            .filter(
                WorkspaceAPIKey.key_hash == key_hash,
                WorkspaceAPIKey.is_active == True,
            )
            .first()
        )

    def list_api_keys(
        self, db: Session, workspace_id: uuid.UUID
    ) -> List[WorkspaceAPIKey]:
        """Return all API keys for a workspace (active and inactive)."""
        return (
            db.query(WorkspaceAPIKey)
            .filter(WorkspaceAPIKey.workspace_id == workspace_id)
            .all()
        )

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_workspace_stats(
        self, db: Session, workspace_id: uuid.UUID
    ) -> WorkspaceStats:
        """Return aggregated resource counts for the workspace."""
        self.get_workspace(db, workspace_id)  # existence check

        member_count = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace_id)
            .count()
        )
        api_key_count = (
            db.query(WorkspaceAPIKey)
            .filter(
                WorkspaceAPIKey.workspace_id == workspace_id,
                WorkspaceAPIKey.is_active == True,
            )
            .count()
        )

        # Experiments and flags linked via workspace_id FK (may be NULL for legacy rows)
        try:
            from backend.app.models.experiment import Experiment
            experiment_count = (
                db.query(Experiment)
                .filter(Experiment.workspace_id == workspace_id)
                .count()
            )
        except Exception:
            experiment_count = 0

        try:
            from backend.app.models.feature_flag import FeatureFlag
            flag_count = (
                db.query(FeatureFlag)
                .filter(FeatureFlag.workspace_id == workspace_id)
                .count()
            )
        except Exception:
            flag_count = 0

        return WorkspaceStats(
            member_count=member_count,
            experiment_count=experiment_count,
            flag_count=flag_count,
            api_key_count=api_key_count,
        )

    # ── Permissions ───────────────────────────────────────────────────────────

    def check_member_permission(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        required_role: str,
    ) -> bool:
        """
        Return True if the user holds at least the required_role in the workspace.

        Role hierarchy: VIEWER < ANALYST < DEVELOPER < ADMIN < OWNER
        """
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .first()
        )
        if not member:
            return False

        try:
            member_index = ROLE_HIERARCHY.index(member.role.value)
            required_index = ROLE_HIERARCHY.index(required_role.upper())
        except ValueError:
            return False

        return member_index >= required_index

    def get_member(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Optional[WorkspaceMember]:
        """Return the WorkspaceMember record or None."""
        return (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .first()
        )


# Module-level singleton
workspace_service = WorkspaceService()
