"""SDK evaluation counters: the per-minute caps behind POST /tracking/evaluations

Two small tables, both keyed by the minute a report was received in:

* ``sdk_evaluation_key_counts`` -- per API key, flag and minute (``requested``:
  every count the key reported, before the per-key cap);
* ``sdk_evaluation_flag_counts`` -- per flag and minute across every key
  (``offered``: what the per-key caps let through, before the per-flag cap).

``backend/app/services/sdk_evaluation_service.py`` updates them with an atomic
``INSERT ... ON CONFLICT DO UPDATE ... RETURNING``, and prunes rows a few
minutes old, so neither table grows with time.

Each table is created only if it is absent.  A schema built by
``db/bootstrap.py``'s ``create_all`` already has both (they are on the models),
and the transition tests rewind such a schema's ``alembic_version`` to an
older revision and replay the chain from there; so does any operator who
restores an ``alembic_version`` row by hand.  A table that exists with a
different shape is not this revision's to repair: the autogenerate tests
(``test_sdk_evaluation_counts_migration.py``) pin that the tables this
revision creates are exactly the models'.

Core chain, extending the core head ``b8c9d0e1f2a3`` (generated with
``revision --autogenerate --head b8c9d0e1f2a3``).  Nothing here touches a
module table, so the ``modules`` branch is unaffected and a full checkout still
has exactly two heads: this revision and ``modules_0001_rbac``.

Revision ID: 8fd44fb483a2
Revises: b8c9d0e1f2a3
Create Date: 2026-09-27
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8fd44fb483a2"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request.  It is the only value interpolated into any name below.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")


def _exists(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table, schema=_SCHEMA)


def upgrade() -> None:
    if not _exists("sdk_evaluation_flag_counts"):
        _create_flag_counts()
    if not _exists("sdk_evaluation_key_counts"):
        _create_key_counts()


def _create_flag_counts() -> None:
    op.create_table(
        "sdk_evaluation_flag_counts",
        sa.Column("flag_key", sa.String(length=100), nullable=False),
        sa.Column("minute", sa.DateTime(), nullable=False),
        sa.Column("offered", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("flag_key", "minute"),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_sdk_evaluation_flag_counts_minute",
        "sdk_evaluation_flag_counts",
        ["minute"],
        unique=False,
        schema=_SCHEMA,
    )


def _create_key_counts() -> None:
    op.create_table(
        "sdk_evaluation_key_counts",
        sa.Column("api_key_id", sa.UUID(), nullable=False),
        sa.Column("flag_key", sa.String(length=100), nullable=False),
        sa.Column("minute", sa.DateTime(), nullable=False),
        sa.Column("requested", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["api_key_id"], [f"{_SCHEMA}.api_keys.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("api_key_id", "flag_key", "minute"),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_sdk_evaluation_key_counts_minute",
        "sdk_evaluation_key_counts",
        ["minute"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        f"ix_{_SCHEMA}_sdk_evaluation_key_counts_minute",
        table_name="sdk_evaluation_key_counts",
        schema=_SCHEMA,
    )
    op.drop_table("sdk_evaluation_key_counts", schema=_SCHEMA)
    op.drop_index(
        f"ix_{_SCHEMA}_sdk_evaluation_flag_counts_minute",
        table_name="sdk_evaluation_flag_counts",
        schema=_SCHEMA,
    )
    op.drop_table("sdk_evaluation_flag_counts", schema=_SCHEMA)
