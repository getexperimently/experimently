"""EP-057: Add Multi-Tenant Team Workspaces tables

Revision ID: ep057_workspaces
Revises: ep046_llm_experiments
Create Date: 2026-03-07 00:00:00.000000

Creates the following tables:
  workspaces          -- top-level isolation unit
  workspace_members   -- user memberships + roles
  workspace_invites   -- pending email invitations
  workspace_api_keys  -- scoped API keys per workspace

Adds nullable workspace_id foreign-key columns to:
  experiments    -- backwards-compatible; NULL = legacy/unscoped
  feature_flags  -- backwards-compatible; NULL = legacy/unscoped
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Revision identifiers
revision: str = "ep057_workspaces"
down_revision: Union[str, None] = "ep046_llm_experiments"
branch_labels = None
depends_on = None


def _schema() -> str:
    """Return the current Alembic migration schema (falls back to 'public')."""
    from alembic import context as alembic_context

    cfg = alembic_context.config
    try:
        schema = cfg.get_main_option("schema") or "public"
    except Exception:
        schema = "public"

    import os

    return os.environ.get("POSTGRES_SCHEMA", schema)


def upgrade() -> None:
    schema = _schema()

    # ── 1. workspaces ─────────────────────────────────────────────────────────
    op.create_table(
        "workspaces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "plan",
            sa.Enum("free", "pro", "enterprise", name="workspaceplan"),
            nullable=False,
            server_default="free",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_experiments", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("max_feature_flags", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("max_members", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_api_keys", sa.Integer(), nullable=False, server_default="3"),
        schema=schema,
    )
    op.create_index(
        f"{schema}_workspace_slug",
        "workspaces",
        ["slug"],
        unique=True,
        schema=schema,
    )

    # ── 2. workspace_members ──────────────────────────────────────────────────
    op.create_table(
        "workspace_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum(
                "OWNER",
                "ADMIN",
                "DEVELOPER",
                "ANALYST",
                "VIEWER",
                name="workspacememberrole",
            ),
            nullable=False,
            server_default="VIEWER",
        ),
        sa.Column(
            "invited_by",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name=f"{schema}_uq_workspace_member",
        ),
        schema=schema,
    )
    op.create_index(
        f"{schema}_wm_workspace",
        "workspace_members",
        ["workspace_id"],
        schema=schema,
    )
    op.create_index(
        f"{schema}_wm_user",
        "workspace_members",
        ["user_id"],
        schema=schema,
    )

    # ── 3. workspace_invites ──────────────────────────────────────────────────
    op.create_table(
        "workspace_invites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column(
            "role",
            sa.Enum(
                "OWNER",
                "ADMIN",
                "DEVELOPER",
                "ANALYST",
                "VIEWER",
                name="workspacememberrole",
                create_type=False,  # reuse enum created above
            ),
            nullable=False,
            server_default="VIEWER",
        ),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "invited_by",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        schema=schema,
    )
    op.create_index(
        f"{schema}_wi_workspace",
        "workspace_invites",
        ["workspace_id"],
        schema=schema,
    )
    op.create_index(
        f"{schema}_wi_token",
        "workspace_invites",
        ["token"],
        unique=True,
        schema=schema,
    )

    # ── 4. workspace_api_keys ─────────────────────────────────────────────────
    op.create_table(
        "workspace_api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("scopes", JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        schema=schema,
    )
    op.create_index(
        f"{schema}_wak_workspace",
        "workspace_api_keys",
        ["workspace_id"],
        schema=schema,
    )
    op.create_index(
        f"{schema}_wak_hash",
        "workspace_api_keys",
        ["key_hash"],
        unique=True,
        schema=schema,
    )

    # ── 5. Add workspace_id to experiments ────────────────────────────────────
    op.add_column(
        "experiments",
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=schema,
    )
    op.create_index(
        f"{schema}_exp_workspace",
        "experiments",
        ["workspace_id"],
        schema=schema,
    )

    # ── 6. Add workspace_id to feature_flags ──────────────────────────────────
    op.add_column(
        "feature_flags",
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=schema,
    )
    op.create_index(
        f"{schema}_ff_workspace",
        "feature_flags",
        ["workspace_id"],
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()

    # Remove workspace_id FK columns from existing tables
    op.drop_index(f"{schema}_ff_workspace", table_name="feature_flags", schema=schema)
    op.drop_column("feature_flags", "workspace_id", schema=schema)

    op.drop_index(f"{schema}_exp_workspace", table_name="experiments", schema=schema)
    op.drop_column("experiments", "workspace_id", schema=schema)

    # Drop new tables (order respects FK deps)
    op.drop_index(f"{schema}_wak_hash", table_name="workspace_api_keys", schema=schema)
    op.drop_index(f"{schema}_wak_workspace", table_name="workspace_api_keys", schema=schema)
    op.drop_table("workspace_api_keys", schema=schema)

    op.drop_index(f"{schema}_wi_token", table_name="workspace_invites", schema=schema)
    op.drop_index(f"{schema}_wi_workspace", table_name="workspace_invites", schema=schema)
    op.drop_table("workspace_invites", schema=schema)

    op.drop_index(f"{schema}_wm_user", table_name="workspace_members", schema=schema)
    op.drop_index(f"{schema}_wm_workspace", table_name="workspace_members", schema=schema)
    op.drop_table("workspace_members", schema=schema)

    op.drop_index(f"{schema}_workspace_slug", table_name="workspaces", schema=schema)
    op.drop_table("workspaces", schema=schema)

    # Drop custom enum types
    op.execute("DROP TYPE IF EXISTS workspacememberrole")
    op.execute("DROP TYPE IF EXISTS workspaceplan")
