"""EP-034: Add integration_configs table

Revision ID: ep034_integration_configs
Revises: f1a2b3c4d5e6
Create Date: 2026-03-02 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ep034_integration_configs"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    schema = "experimentation"
    op.execute(
        "CREATE TYPE integration_type_enum AS ENUM ('salesforce', 'jira', 'github')"
    )
    op.create_table(
        "integration_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "integration_type",
            sa.Enum("salesforce", "jira", "github", name="integration_type_enum"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("encrypted_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=schema,
    )
    op.create_index(
        "ix_integration_configs_type",
        "integration_configs",
        ["integration_type"],
        schema=schema,
    )
    op.create_unique_constraint(
        "uq_integration_configs_type",
        "integration_configs",
        ["integration_type"],
        schema=schema,
    )


def downgrade() -> None:
    schema = "experimentation"
    op.drop_constraint(
        "uq_integration_configs_type", "integration_configs", schema=schema, type_="unique"
    )
    op.drop_index("ix_integration_configs_type", table_name="integration_configs", schema=schema)
    op.drop_table("integration_configs", schema=schema)
    op.execute("DROP TYPE IF EXISTS integration_type_enum")
