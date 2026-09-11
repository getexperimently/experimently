"""Add experiments.key and experiments.experiment_metadata

The SDK-facing tracking API (POST /tracking/assign, /tracking/track,
/tracking/batch) and the experiment delete dependency look experiments up
by ``Experiment.key``, but the column never existed.  ``experiment_metadata``
backs POST /experiments/{id}/metadata, which previously had no storage.

Revision ID: d4e5f6a7b8c9
Revises: c2a9d3f1b7e4
Create Date: 2026-09-11
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c2a9d3f1b7e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column("key", sa.String(length=100), nullable=True),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_experiments_key",
        "experiments",
        ["key"],
        unique=True,
        schema=_SCHEMA,
    )
    op.add_column(
        "experiments",
        sa.Column("experiment_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("experiments", "experiment_metadata", schema=_SCHEMA)
    # Databases bootstrapped from the models (backend/app/db/bootstrap.py)
    # carry the index under the model's naming convention, which is prefixed
    # with the schema the app derived at import time; drop whichever exists.
    for index_name in {
        f"ix_{_SCHEMA}_experiments_key",
        "ix_experimentation_experiments_key",
        "ix_test_experimentation_experiments_key",
    }:
        op.execute(f'DROP INDEX IF EXISTS "{_SCHEMA}"."{index_name}"')
    op.drop_column("experiments", "key", schema=_SCHEMA)
