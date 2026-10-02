"""Feature flags: a ``default_value`` column, false on every row

Adds ``feature_flags.default_value`` (``boolean``, ``NOT NULL``, ``DEFAULT
false``): what a flag serves when it is off.  A boolean flag's
``default_value`` may only be false for now, and nothing reads or writes
the column yet -- the feature-flag create/update contract (#94) does that.

``ADD COLUMN ... NOT NULL DEFAULT false`` fills every existing row with false
in the same statement (PostgreSQL 11 and later store the default in the
catalogue rather than rewriting the table), which is exactly what every flag
serves when it is off today.  There is no separate backfill.

The server default is load-bearing beyond that first fill.  The previous
release's image does not know the column, so its INSERTs do not name it; during
a deploy, and after an image-only rollback (``rollback.yml``), the database
supplies false.  Without the default those INSERTs fail on ``NOT NULL``.

The column is added only when it is absent, as ``271f03a31742`` does: a schema
built by ``db/bootstrap.py``'s ``create_all`` already has it (it is on the
model), and the transition tests rewind such a schema's ``alembic_version`` and
replay the chain from there.

``test_feature_flag_default_value_migration.py`` pins that an upgraded database
and a bootstrapped one end with the same column, and that the previous
release's code still creates, updates and lists flags against it.

Core chain, extending the core head ``d12cbd384bbe`` (generated with
``revision --autogenerate --head d12cbd384bbe``, then edited).  Nothing here
touches a module table, so a full checkout still has exactly two heads: this
revision and ``modules_0002_warehouse_analysis``.

Revision ID: a89544fb1075
Revises: d12cbd384bbe
Create Date: 2026-10-02
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a89544fb1075"
down_revision: Union[str, None] = "d12cbd384bbe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

_TABLE = "feature_flags"
_COLUMN = "default_value"


def _has_column() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(_TABLE, schema=_SCHEMA)
    return any(column["name"] == _COLUMN for column in columns)


def upgrade() -> None:
    if not _has_column():
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            schema=_SCHEMA,
        )


def downgrade() -> None:
    op.drop_column(_TABLE, _COLUMN, schema=_SCHEMA)
