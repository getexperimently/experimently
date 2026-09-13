"""
Workspace models for EP-057: Multi-Tenant Team Workspaces.

Provides workspace isolation so multiple teams can use the platform
safely within one instance.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

from backend.app.core.database_config import get_schema_name
from backend.app.models.base import Base, BaseModel


class WorkspacePlan(str, enum.Enum):
    """Workspace subscription plan."""

    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class WorkspaceMemberRole(str, enum.Enum):
    """Roles within a workspace."""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    DEVELOPER = "DEVELOPER"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


# Role hierarchy: higher index = more permissions
ROLE_HIERARCHY = ["VIEWER", "ANALYST", "DEVELOPER", "ADMIN", "OWNER"]


class Workspace(Base, BaseModel):
    """Workspace model — top-level isolation boundary for team resources."""

    __tablename__ = "workspaces"

    name = Column(String(200), nullable=False)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    plan = Column(
        SQLAEnum(WorkspacePlan),
        default=WorkspacePlan.FREE,
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)

    # Per-plan resource limits
    max_experiments = Column(Integer, default=10, nullable=False)
    max_feature_flags = Column(Integer, default=50, nullable=False)
    max_members = Column(Integer, default=5, nullable=False)
    max_api_keys = Column(Integer, default=3, nullable=False)

    # Relationships
    members = relationship(
        "WorkspaceMember",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    invites = relationship(
        "WorkspaceInvite",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    api_keys = relationship(
        "WorkspaceAPIKey",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(f"{schema_name}_workspace_slug", "slug", unique=True),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<Workspace {self.slug}>"


class WorkspaceMember(Base, BaseModel):
    """Membership linking a User to a Workspace with a specific role."""

    __tablename__ = "workspace_members"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(
        SQLAEnum(WorkspaceMemberRole),
        default=WorkspaceMemberRole.VIEWER,
        nullable=False,
    )
    invited_by = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    inviter = relationship("User", foreign_keys=[invited_by])

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            UniqueConstraint(
                "workspace_id",
                "user_id",
                name=f"{schema_name}_uq_workspace_member",
            ),
            Index(f"{schema_name}_wm_workspace", "workspace_id"),
            Index(f"{schema_name}_wm_user", "user_id"),
            {"schema": schema_name},
        )

    def __repr__(self):
        return f"<WorkspaceMember workspace={self.workspace_id} user={self.user_id} role={self.role}>"


class WorkspaceInvite(Base, BaseModel):
    """Pending invitation to join a workspace by email."""

    __tablename__ = "workspace_invites"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    email = Column(String(255), nullable=False, index=True)
    role = Column(
        SQLAEnum(WorkspaceMemberRole),
        default=WorkspaceMemberRole.VIEWER,
        nullable=False,
    )
    token = Column(String(64), unique=True, nullable=False, index=True)
    invited_by = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)

    # Relationships
    workspace = relationship("Workspace", back_populates="invites")
    inviter = relationship("User", foreign_keys=[invited_by])

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(f"{schema_name}_wi_workspace", "workspace_id"),
            Index(f"{schema_name}_wi_token", "token", unique=True),
            {"schema": schema_name},
        )

    @property
    def is_expired(self) -> bool:
        """Check whether this invite has passed its expiry time."""
        return datetime.utcnow() > self.expires_at

    @property
    def is_accepted(self) -> bool:
        """Check whether this invite has already been accepted."""
        return self.accepted_at is not None

    def __repr__(self):
        return f"<WorkspaceInvite workspace={self.workspace_id} email={self.email}>"


class WorkspaceAPIKey(Base, BaseModel):
    """Scoped API key attached to a workspace (not a user)."""

    __tablename__ = "workspace_api_keys"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{get_schema_name()}.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    # SHA-256 hex digest — never store the plaintext key
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    # First 8 characters shown to the user for identification
    key_prefix = Column(String(16), nullable=False)
    scopes = Column(JSONB, default=list, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    # Relationships
    workspace = relationship("Workspace", back_populates="api_keys")

    @declared_attr
    def __table_args__(cls):
        schema_name = get_schema_name()
        return (
            Index(f"{schema_name}_wak_workspace", "workspace_id"),
            Index(f"{schema_name}_wak_hash", "key_hash", unique=True),
            {"schema": schema_name},
        )

    @property
    def is_expired(self) -> bool:
        """Return True if an expiry date is set and has passed."""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Return True when the key is both active and not expired."""
        return self.is_active and not self.is_expired

    def __repr__(self):
        return f"<WorkspaceAPIKey {self.name} prefix={self.key_prefix}>"


# ---------------------------------------------------------------------------
# The cross-boundary foreign keys, attached from the module's side
# ---------------------------------------------------------------------------
#
# `experiments.workspace_id` and `feature_flags.workspace_id` are bare indexed
# UUIDs in the core models: a ForeignKey there was the only thing in the core
# ORM that reached across the core/module boundary, and importing those
# models without this one raised NoReferencedTableError. The constraint is
# therefore declared *here*, by the module that owns the referenced table, and
# only exists on a metadata that has loaded the modules' models:
#
# * a fresh full-profile bootstrap (`create_all`) emits it as an ALTER TABLE
#   after both tables exist (`use_alter=True`), with the same ON DELETE SET
#   NULL the original ep057 migration gave it;
# * a core metadata never sees this module, so its schema has no such
#   constraint and no dangling reference;
# * an *existing* full-profile database that ran migration a7b8c9d0e1f2
#   (which dropped the constraint) gets it back from the modules' alembic
#   branch (issue #89). Until then `WorkspaceService.delete_workspace` clears
#   the column itself, so the ON DELETE behaviour holds either way.


def _attach_workspace_foreign_keys() -> None:
    from sqlalchemy import ForeignKeyConstraint

    from backend.app.models.experiment import Experiment
    from backend.app.models.feature_flag import FeatureFlag

    for model, name in (
        (Experiment, "experiments_workspace_id_fkey"),
        (FeatureFlag, "feature_flags_workspace_id_fkey"),
    ):
        table = model.__table__
        if any(getattr(c, "name", None) == name for c in table.constraints):
            continue  # already attached (the module was imported twice)
        table.append_constraint(
            ForeignKeyConstraint(
                ["workspace_id"],
                [Workspace.__table__.c.id],
                name=name,
                ondelete="SET NULL",
                use_alter=True,
            )
        )


_attach_workspace_foreign_keys()
