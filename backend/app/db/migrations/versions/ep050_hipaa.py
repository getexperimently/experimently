"""EP-050: HIPAA Compliance — create phi_audit_logs and baa_configs tables.

Revision ID: b1c2d3e4f5a6
Revises: a0ce135350af
Create Date: 2026-03-07 12:00:00.000000

Creates:
  experimentation.phi_audit_logs  — HIPAA PHI access audit trail (6-year retention)
  experimentation.baa_configs     — Business Associate Agreement configurations
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic
revision = "b1c2d3e4f5a6"
down_revision = "a0ce135350af"
branch_labels = None
depends_on = None

_SCHEMA = "experimentation"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # phi_audit_logs
    # ------------------------------------------------------------------
    op.create_table(
        "phi_audit_logs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # FK to users.id — nullable so the record is kept even if the user
        # is later deleted (HIPAA audit records must be retained)
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{_SCHEMA}.users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "resource_type",
            sa.String(50),
            nullable=False,
            comment="Type of resource: experiment, feature_flag, user_data",
        ),
        sa.Column(
            "resource_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(20),
            nullable=False,
            comment="Action performed: READ, WRITE, DELETE, EXPORT",
        ),
        sa.Column(
            "phi_fields_accessed",
            JSONB,
            nullable=False,
            server_default="'[]'::jsonb",
            comment="List of PHI field names that were accessed (minimum-necessary)",
        ),
        sa.Column(
            "purpose",
            sa.String(50),
            nullable=False,
            comment="Purpose of access: treatment, operations, research",
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="When the PHI access occurred",
        ),
        sa.Column(
            "retention_years",
            sa.Integer,
            nullable=False,
            server_default="6",
            comment="HIPAA §164.530(j): 6-year retention requirement",
        ),
        # BaseModel common columns
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        schema=_SCHEMA,
    )

    # Indexes for common query patterns
    op.create_index(
        "ix_phi_audit_logs_resource_type",
        "phi_audit_logs",
        ["resource_type"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_phi_audit_logs_resource_id",
        "phi_audit_logs",
        ["resource_id"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_phi_audit_logs_action",
        "phi_audit_logs",
        ["action"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_phi_audit_logs_timestamp",
        "phi_audit_logs",
        ["timestamp"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_phi_audit_logs_created_at",
        "phi_audit_logs",
        ["created_at"],
        schema=_SCHEMA,
    )

    # ------------------------------------------------------------------
    # baa_configs
    # ------------------------------------------------------------------
    op.create_table(
        "baa_configs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_name", sa.String(255), nullable=False),
        sa.Column("signatory_name", sa.String(255), nullable=False),
        sa.Column("signatory_email", sa.String(255), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column(
            "data_residency_region",
            sa.String(50),
            nullable=False,
            comment="AWS region where PHI is stored, e.g. us-east-1",
        ),
        sa.Column(
            "phi_categories",
            JSONB,
            nullable=False,
            server_default="'[]'::jsonb",
            comment="Covered PHI categories: demographics, diagnosis, treatment, billing",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "signed_document_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 hex digest of the signed BAA document",
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{_SCHEMA}.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # BaseModel common columns
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        schema=_SCHEMA,
    )

    # Indexes
    op.create_index(
        "ix_baa_configs_signatory_email",
        "baa_configs",
        ["signatory_email"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_baa_configs_is_active",
        "baa_configs",
        ["is_active"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_baa_configs_created_at",
        "baa_configs",
        ["created_at"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("baa_configs", schema=_SCHEMA)
    op.drop_table("phi_audit_logs", schema=_SCHEMA)
