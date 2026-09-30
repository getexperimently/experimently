"""Experiments: a nullable ``resume_at``, set only on a paused experiment

Adds ``experiments.resume_at`` (``timestamp with time zone``, nullable, no
default) and the check constraint ``ck_experiments_resume_only_when_paused``:
``resume_at IS NULL OR status = 'PAUSED'``.  The status enum is stored by its
member NAME (``DRAFT``, ``ACTIVE``, ``PAUSED``, ...), which is why the literal is
upper case.

Nothing writes the column yet; a follow-up gives it a meaning (#436).  Until
then every row holds NULL and the constraint is satisfied trivially.

Three steps, each only when its object is absent, as ``8fd44fb483a2`` does for
its tables.  A schema built by ``db/bootstrap.py``'s ``create_all`` already has
the column and the constraint (they are on the model), and the transition tests
rewind such a schema's ``alembic_version`` and replay the chain from there:

1. add the column;
2. clear ``resume_at`` on every row whose status is not ``PAUSED``, so that
   adding the constraint cannot fail on a row written while it was absent;
3. add the constraint.

``test_experiment_resume_at_migration.py`` pins that an upgraded database and a
bootstrapped one end with the same column and the same constraint definition.

Core chain, extending the core head ``8fd44fb483a2`` (generated with
``revision --autogenerate --head 8fd44fb483a2``).  Nothing here touches a module
table, so a full checkout still has exactly two heads: this revision and
``modules_0002_warehouse_analysis``.

Revision ID: 271f03a31742
Revises: 8fd44fb483a2
Create Date: 2026-09-29
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "271f03a31742"
down_revision: Union[str, None] = "8fd44fb483a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

_TABLE = "experiments"
_COLUMN = "resume_at"
_CHECK = "ck_experiments_resume_only_when_paused"
_CHECK_SQL = "resume_at IS NULL OR status = 'PAUSED'"


def _has_column() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(_TABLE, schema=_SCHEMA)
    return any(column["name"] == _COLUMN for column in columns)


def _has_check() -> bool:
    checks = sa.inspect(op.get_bind()).get_check_constraints(_TABLE, schema=_SCHEMA)
    return any(check["name"] == _CHECK for check in checks)


def upgrade() -> None:
    if not _has_column():
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True),
            schema=_SCHEMA,
        )
    if not _has_check():
        # Built with SQLAlchemy Core rather than as SQL text: the table and
        # the schema are identifiers, never string-formatted into a statement.
        experiments = sa.table(
            _TABLE, sa.column(_COLUMN), sa.column("status"), schema=_SCHEMA
        )
        op.execute(
            experiments.update()
            .where(
                experiments.c.resume_at.isnot(None),
                experiments.c.status != "PAUSED",
            )
            .values(resume_at=None)
        )
        op.create_check_constraint(_CHECK, _TABLE, _CHECK_SQL, schema=_SCHEMA)


def downgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check", schema=_SCHEMA)
    op.drop_column(_TABLE, _COLUMN, schema=_SCHEMA)
