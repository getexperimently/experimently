"""ep033_add_compliance_audit_events

Revision ID: f1a2b3c4d5e6
Revises: e181583b4b24
Create Date: 2026-03-02 18:00:00.000000

SOC 2 Type 2 / ISO 27001 compliance audit event table.
Separate from the existing audit_logs table — this table is append-only,
HMAC-signed, and has configurable retention fields.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e181583b4b24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "experimentation"


def upgrade() -> None:
    # Create enum types first
    audit_action_type = postgresql.ENUM(
        "CREATE",
        "READ",
        "UPDATE",
        "DELETE",
        "LOGIN",
        "LOGOUT",
        "LOGIN_FAILED",
        "ROLE_GRANT",
        "ROLE_REVOKE",
        "KEY_CREATE",
        "KEY_REVOKE",
        "EXPORT",
        "REPORT_GENERATED",
        name="audit_action_type",
        schema=_SCHEMA,
    )
    audit_action_type.create(op.get_bind(), checkfirst=True)

    audit_outcome_type = postgresql.ENUM(
        "SUCCESS",
        "FAILURE",
        "DENIED",
        name="audit_outcome_type",
        schema=_SCHEMA,
    )
    audit_outcome_type.create(op.get_bind(), checkfirst=True)

    # Create the audit_events_v2 table
    op.create_table(
        "audit_events_v2",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_ip", sa.String(length=45), nullable=True),
        sa.Column("actor_user_agent", sa.String(length=512), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "action",
            sa.Enum(
                "CREATE", "READ", "UPDATE", "DELETE",
                "LOGIN", "LOGOUT", "LOGIN_FAILED",
                "ROLE_GRANT", "ROLE_REVOKE",
                "KEY_CREATE", "KEY_REVOKE",
                "EXPORT", "REPORT_GENERATED",
                name="audit_action_type",
                schema=_SCHEMA,
            ),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "SUCCESS", "FAILURE", "DENIED",
                name="audit_outcome_type",
                schema=_SCHEMA,
            ),
            nullable=False,
        ),
        sa.Column("hmac_signature", sa.String(length=64), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )

    # Create indexes
    op.create_index(
        "ix_audit_events_v2_timestamp",
        "audit_events_v2",
        ["timestamp"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_events_v2_actor_id",
        "audit_events_v2",
        ["actor_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_events_v2_resource",
        "audit_events_v2",
        ["resource_type", "resource_id"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_audit_events_v2_resource", table_name="audit_events_v2", schema=_SCHEMA)
    op.drop_index("ix_audit_events_v2_actor_id", table_name="audit_events_v2", schema=_SCHEMA)
    op.drop_index("ix_audit_events_v2_timestamp", table_name="audit_events_v2", schema=_SCHEMA)

    # Drop the table
    op.drop_table("audit_events_v2", schema=_SCHEMA)

    # Drop enum types
    audit_action_type = postgresql.ENUM(name="audit_action_type", schema=_SCHEMA)
    audit_action_type.drop(op.get_bind(), checkfirst=True)

    audit_outcome_type = postgresql.ENUM(name="audit_outcome_type", schema=_SCHEMA)
    audit_outcome_type.drop(op.get_bind(), checkfirst=True)
