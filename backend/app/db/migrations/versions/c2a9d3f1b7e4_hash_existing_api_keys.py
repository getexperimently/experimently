"""Hash existing API keys and enforce hashed storage.

Revision ID: c2a9d3f1b7e4
Revises: b1c2d3e4f5a6
Create Date: 2026-05-02 00:00:00.000000
"""
# pylint: disable=no-member

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c2a9d3f1b7e4"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "experimentation"


def upgrade() -> None:
    # Ensure pgcrypto is available for digest().
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # One-way transform legacy plaintext API keys to SHA-256 hex digests.
    op.execute(
        f"""
        UPDATE {_SCHEMA}.api_keys
        SET key = encode(digest(key, 'sha256'), 'hex')
        WHERE key IS NOT NULL
          AND key !~ '^[0-9a-f]{{64}}$'
        """
    )

    # Narrow type to reflect hashed storage contract.
    op.alter_column(
        "api_keys",
        "key",
        schema=_SCHEMA,
        existing_type=sa.String(length=100),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Cannot recover plaintext keys once hashed; only relax column length.
    op.alter_column(
        "api_keys",
        "key",
        schema=_SCHEMA,
        existing_type=sa.String(length=64),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
