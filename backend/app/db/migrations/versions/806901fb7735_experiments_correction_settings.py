"""Experiments: a stored correction method and confidence level (#580)

Adds two NOT NULL columns to ``experiments``, each with a server default and a
check constraint:

* ``correction_method`` ``VARCHAR(32)``, default ``'benjamini_hochberg'``,
  check ``ck_experiments_correction_method``: one of ``none``, ``bonferroni``
  or ``benjamini_hochberg``;
* ``confidence_level`` ``double precision``, default ``0.95``, check
  ``ck_experiments_confidence_level``: between 0.80 and 0.99.

Adding a NOT NULL column with a constant server default fills every existing
row with that default, so every experiment already stored is backfilled to
Benjamini-Hochberg at 0.95. The server default also lets the previous release's
image, which does not know the columns, keep inserting experiments against this
schema after a rollback with ``RUN_MIGRATIONS=false``.

Four steps, each only when its object is absent, as ``271f03a31742`` does: a
schema built by ``db/bootstrap.py``'s ``create_all`` already has the columns and
the checks (they are on the model), and the transition tests rewind such a
schema's ``alembic_version`` and replay the chain from there.

**The downgrade drops both columns, and with them every stored choice.** An
upgrade after it restores the defaults (Benjamini-Hochberg, 0.95), not the
choices that were stored. A downgrade to ``1ab99332f0ba`` or below runs this
downgrade: the self-hosting migrations page and the rollback runbook say so
where they name such a target.

``test_experiment_correction_settings_migration.py`` pins the transitions, and
that an upgraded database and a bootstrapped one end with the same defaults and
the same check definitions (autogenerate compares neither).

Core chain, extending the core head ``1ab99332f0ba`` (generated with
``revision --head 1ab99332f0ba``). Nothing here touches a module table, so a
full checkout still has exactly two heads: this revision and
``modules_0002_warehouse_analysis``.

Revision ID: 806901fb7735
Revises: 1ab99332f0ba
Create Date: 2026-10-03
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "806901fb7735"
down_revision: Union[str, None] = "1ab99332f0ba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

_TABLE = "experiments"

#: (column, its definition, check name, check SQL), in the order they are added.
#: The names and the SQL are the model's (``backend/app/models/experiment.py``).
_STEPS = (
    (
        "correction_method",
        lambda: sa.Column(
            "correction_method",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'benjamini_hochberg'"),
        ),
        "ck_experiments_correction_method",
        "correction_method IN ('none', 'bonferroni', 'benjamini_hochberg')",
    ),
    (
        "confidence_level",
        lambda: sa.Column(
            "confidence_level",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.95"),
        ),
        "ck_experiments_confidence_level",
        "confidence_level >= 0.80 AND confidence_level <= 0.99",
    ),
)


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(_TABLE, schema=_SCHEMA)}


def _checks() -> set:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_check_constraints(_TABLE, schema=_SCHEMA)}


def upgrade() -> None:
    columns = _columns()
    checks = _checks()
    for column, definition, check, check_sql in _STEPS:
        if column not in columns:
            op.add_column(_TABLE, definition(), schema=_SCHEMA)
        if check not in checks:
            op.create_check_constraint(check, _TABLE, check_sql, schema=_SCHEMA)


def downgrade() -> None:
    # Drops every stored correction method and confidence level.
    for column, _definition, check, _check_sql in reversed(_STEPS):
        op.drop_constraint(check, _TABLE, type_="check", schema=_SCHEMA)
        op.drop_column(_TABLE, column, schema=_SCHEMA)
