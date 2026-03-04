"""EP-037: Add SSO/SAML & OIDC enterprise authentication tables

Revision ID: ep037_sso_config
Revises: ep036_split_url
Create Date: 2026-03-03 00:00:00.000000

Creates the ``sso_configs`` table for storing SAML 2.0 and OIDC/OAuth2
provider configurations per organization.

Also adds ``sso_provider`` column to the ``users`` table to record which
SSO provider was used for JIT-provisioned accounts (if the column does not
already exist).

``external_id`` already exists in the users table from earlier work
(Cognito integration), so we skip adding it again.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# Revision identifiers, used by Alembic.
revision: str = "ep037_sso_config"
down_revision: Union[str, None] = "ep036_split_url"
branch_labels = None
depends_on = None

_SCHEMA = "experimentation"


def upgrade() -> None:
    """Create sso_configs table and add sso_provider column to users."""

    # Create the sso_provider enum type
    sso_provider_enum = sa.Enum(
        "saml",
        "google",
        "github",
        "microsoft",
        "okta",
        "azure_ad",
        "onelogin",
        name="ssoprovidertype",
        schema=_SCHEMA,
    )
    sso_provider_enum.create(op.get_bind(), checkfirst=True)

    # Create the sso_configs table
    op.create_table(
        "sso_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_name", sa.String(255), nullable=False),
        sa.Column("org_domain", sa.String(255), nullable=False),
        sa.Column(
            "provider_type",
            sa.Enum(
                "saml",
                "google",
                "github",
                "microsoft",
                "okta",
                "azure_ad",
                "onelogin",
                name="ssoprovidertype",
                schema=_SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("entity_id", sa.String(1024), nullable=True),
        sa.Column("sso_url", sa.String(2048), nullable=True),
        sa.Column("x509_certificate", sa.Text, nullable=True),
        sa.Column("client_secret", sa.String(1024), nullable=True),
        sa.Column("role_mapping", JSONB, nullable=True),
        sa.Column("is_enforced", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema=_SCHEMA,
    )

    # Unique constraint on org_domain
    op.create_unique_constraint(
        "uq_sso_configs_org_domain",
        "sso_configs",
        ["org_domain"],
        schema=_SCHEMA,
    )

    # Indexes
    op.create_index(
        "ix_sso_configs_org_domain",
        "sso_configs",
        ["org_domain"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_sso_configs_provider_type",
        "sso_configs",
        ["provider_type"],
        schema=_SCHEMA,
    )

    # Add sso_provider column to users table (may already exist — skip with try/except)
    try:
        op.add_column(
            "users",
            sa.Column("sso_provider", sa.String(50), nullable=True),
            schema=_SCHEMA,
        )
    except Exception:
        pass  # Column already exists


def downgrade() -> None:
    """Drop sso_configs table and remove sso_provider from users."""

    # Remove sso_provider column from users
    try:
        op.drop_column("users", "sso_provider", schema=_SCHEMA)
    except Exception:
        pass

    # Drop indexes and table
    op.drop_index("ix_sso_configs_provider_type", table_name="sso_configs", schema=_SCHEMA)
    op.drop_index("ix_sso_configs_org_domain", table_name="sso_configs", schema=_SCHEMA)
    op.drop_constraint(
        "uq_sso_configs_org_domain", table_name="sso_configs", schema=_SCHEMA
    )
    op.drop_table("sso_configs", schema=_SCHEMA)

    # Drop the enum type
    op.execute(f"DROP TYPE IF EXISTS {_SCHEMA}.ssoprovidertype")
