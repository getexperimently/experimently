"""Drop the workspace_id foreign keys on experiments and feature_flags

The seam (P2).  ``workspaces`` is the workspaces module's table;
``experiments`` and ``feature_flags`` are core tables.  The two
``workspace_id`` ``ForeignKey`` constraints were the *entire* ORM coupling
between the core and the module — with them in place, importing the core
models without the module's raises ``NoReferencedTableError`` for exactly
these two columns (the coupling report under docs/planning, §2).

The **columns stay**.  Only the constraints go: a core database keeps
``workspace_id`` as a nullable, indexed UUID that nothing reads or writes, so
an existing row's value survives.  No migration *in the core chain* re-adds
the constraint, which is the only guarantee this file can make: it cannot see
the ``modules`` branch, and a core checkout does not have it.  On a core
database that is the end of the story — the ``ON DELETE SET NULL`` it carried
is done explicitly by ``WorkspaceService.delete_workspace``.  On a full one the
modules branch's first revision (``modules_0001_rbac``, issue #89) does
reinstate it, and it is ordered after this revision on purpose: it chains from
here, and ``b8c9d0e1f2a3`` is the core chain's own child of this same
revision.  ``backend/tests/unit/db/test_alembic_branch_order.py`` walks both
version directories and pins both halves of that.  The index is untouched — ``ep057`` created
it separately (``{schema}_exp_workspace`` / ``{schema}_ff_workspace``) and the
model still declares ``index=True``.

Constraint names are discovered by reflection rather than hard-coded: ``ep057``
created both foreign keys unnamed, so their names are whatever PostgreSQL
chose (``experiments_workspace_id_fkey`` in practice), and a database built by
``Base.metadata.create_all`` — the fresh-database path in ``db/bootstrap.py`` —
may differ again.  A database that never had the constraint (any schema
created from the models after this change) is left alone.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-11
"""

import os
from typing import List, Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request.  It is the only value interpolated into any statement below.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

# (table, column) pairs whose foreign key into `workspaces` is dropped.
_TARGETS = (("experiments", "workspace_id"), ("feature_flags", "workspace_id"))


def _workspace_fk_names(inspector, table: str, column: str) -> List[str]:
    """Names of *table*'s foreign keys on *column* that point at ``workspaces``."""
    names = []
    for fk in inspector.get_foreign_keys(table, schema=_SCHEMA):
        if fk.get("constrained_columns") != [column]:
            continue
        if fk.get("referred_table") != "workspaces":
            continue
        if fk.get("name"):
            names.append(fk["name"])
    return names


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names(schema=_SCHEMA))

    for table, column in _TARGETS:
        if table not in existing:
            continue
        for name in _workspace_fk_names(inspector, table, column):
            op.drop_constraint(name, table, schema=_SCHEMA, type_="foreignkey")


def downgrade() -> None:
    """Re-add the constraints, if this database has a ``workspaces`` table.

    A core database has none, so there is nothing to point at and the
    downgrade is a no-op — which is the correct end state for that database.
    """
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names(schema=_SCHEMA))
    if "workspaces" not in existing:
        return

    for table, column in _TARGETS:
        if table not in existing:
            continue
        if _workspace_fk_names(inspector, table, column):
            continue  # already constrained
        op.create_foreign_key(
            f"{table}_{column}_fkey",
            table,
            "workspaces",
            [column],
            ["id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete="SET NULL",
        )
