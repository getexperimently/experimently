"""Global holdouts: who each one covered, its own salt, and at most one active

Adds what measuring a global holdout needs (#445):

* ``global_holdouts.activated_at`` and ``deactivated_at`` (``timestamp``,
  naive UTC like ``created_at``, nullable);
* ``global_holdouts.hash_salt`` (``varchar(64) NOT NULL``, server default
  ``'global_holdout_v1'``, the salt every holdout used until now);
* the partial unique index ``uq_global_holdouts_one_active`` on ``is_active``
  ``WHERE is_active``: at most one active holdout;
* the table ``holdout_population (holdout_id, user_id, in_holdout,
  first_seen_at)``, primary key ``(holdout_id, user_id)``, ``holdout_id``
  referencing ``global_holdouts.id`` ON DELETE CASCADE.  ``first_seen_at`` is a
  ``varchar`` holding the canonical UTC string, the type of
  ``events.created_at``, because the results query compares the two directly.

The steps run in this order, each DDL step only when its object is absent (a
schema built by ``db/bootstrap.py``'s ``create_all`` already has them, and the
transition tests rewind such a schema's ``alembic_version``):

1. add ``activated_at`` and ``deactivated_at``;
2. **reduce the active rows to at most one** (data step): the most recently
   updated active row stays active; every other active row gets
   ``is_active = false`` and ``deactivated_at = now()`` (UTC), and their ids
   are printed on one line.  Before this revision ``get_active_holdout()``
   enforced whichever active row ``.first()`` returned, which is not
   necessarily the one kept here.  Under the new rules a deactivated holdout
   has ended and cannot restart, so this step is NOT reverted by
   ``downgrade``;
3. add ``hash_salt`` with the legacy server default, which fills every
   existing row with ``'global_holdout_v1'``;
4. only when step 3 added the column: give every row that is not active after
   step 2 its own salt, ``'holdout:' || id``.  The row active at the upgrade
   keeps the legacy salt, so an old task and a new one bucket its users the
   same way during a blue/green deploy.  That row is never measurable (its
   ``activated_at`` stays NULL and the service never stamps a legacy row);
5. create the partial unique index;
6. create ``holdout_population``.

The server default exists only for an older image after a rollback: the model
gives every new row its own salt with a Python default.

Downgrade drops, with literal ``op.drop_table`` / ``op.drop_index`` /
``op.drop_column``: the table ``holdout_population`` -- **every recorded
membership is deleted and nothing can rebuild it**, so a downgrade across this
revision needs the founder's approval at the moment it runs whenever that
table has rows -- the index, and the three columns.  Step 2 is not reverted.
Rolling back across this revision while a holdout is active invalidates that
holdout's measurement: deactivate it and create a new one after upgrading
again (``docs/deployment/rollback-runbook.md``).

Core chain, extending the core head ``1ab99332f0ba`` (generated with
``revision --autogenerate --head 1ab99332f0ba``).  Nothing here touches a
module table, so a full checkout still has exactly two heads: this revision
and ``modules_0002_warehouse_analysis``.

Revision ID: d29a479daafe
Revises: 1ab99332f0ba
Create Date: 2026-10-03
"""

import os
import sys
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d29a479daafe"
down_revision: Union[str, None] = "1ab99332f0ba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

_HOLDOUTS = "global_holdouts"
_POPULATION = "holdout_population"
_INDEX = "uq_global_holdouts_one_active"
_LEGACY_SALT = "global_holdout_v1"

_OFFLINE_REFUSAL = (
    "d29a479daafe reads global_holdouts to keep one active row and cannot be "
    "emitted as SQL; run it online (without --sql)."
)


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(_HOLDOUTS, schema=_SCHEMA)}


def _has_index() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        index["name"] == _INDEX
        for index in inspector.get_indexes(_HOLDOUTS, schema=_SCHEMA)
    )


def _has_population() -> bool:
    return _POPULATION in sa.inspect(op.get_bind()).get_table_names(schema=_SCHEMA)


def _keep_one_active() -> list:
    """Step 2: deactivate every active row but the most recently updated one.

    Built with SQLAlchemy Core: the table and the schema are identifiers,
    never string-formatted into a statement.  Returns the deactivated ids.
    """
    holdouts = sa.table(
        _HOLDOUTS,
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("is_active", sa.Boolean),
        sa.column("updated_at", sa.DateTime),
        sa.column("deactivated_at", sa.DateTime),
        schema=_SCHEMA,
    )
    kept = (
        sa.select(holdouts.c.id)
        .where(holdouts.c.is_active.is_(True))
        .order_by(holdouts.c.updated_at.desc(), holdouts.c.id)
        .limit(1)
        .scalar_subquery()
    )
    result = op.get_bind().execute(
        holdouts.update()
        .where(holdouts.c.is_active.is_(True), holdouts.c.id != kept)
        .values(is_active=False, deactivated_at=sa.func.timezone("utc", sa.func.now()))
        .returning(holdouts.c.id)
    )
    return sorted(str(row.id) for row in result)


def _salt_the_inactive_rows() -> None:
    """Step 4: every row not active after step 2 gets ``'holdout:' || id``."""
    holdouts = sa.table(
        _HOLDOUTS,
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("is_active", sa.Boolean),
        sa.column("hash_salt", sa.String),
        schema=_SCHEMA,
    )
    op.execute(
        holdouts.update()
        .where(holdouts.c.is_active.is_(False))
        .values(
            hash_salt=sa.literal("holdout:") + sa.cast(holdouts.c.id, sa.String)
        )
    )


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(_OFFLINE_REFUSAL)

    # 1. activated_at, deactivated_at
    present = _columns()
    if "activated_at" not in present:
        op.add_column(
            _HOLDOUTS,
            sa.Column("activated_at", sa.DateTime(), nullable=True),
            schema=_SCHEMA,
        )
    if "deactivated_at" not in present:
        op.add_column(
            _HOLDOUTS,
            sa.Column("deactivated_at", sa.DateTime(), nullable=True),
            schema=_SCHEMA,
        )

    # 2. at most one active row (data step, not reverted)
    deactivated = _keep_one_active()
    # On stdout, one line: alembic.ini's root logger is at WARN, so a logger
    # at INFO would be dropped outside alembic's own loggers.
    sys.stdout.write(
        f"d29a479daafe: deactivated {len(deactivated)} global holdout(s) to keep "
        f"one active: {', '.join(deactivated) or 'none'}\n"
    )
    sys.stdout.flush()

    # 3. hash_salt, filled with the legacy salt by the server default
    added_salt = "hash_salt" not in present
    if added_salt:
        op.add_column(
            _HOLDOUTS,
            sa.Column(
                "hash_salt",
                sa.String(length=64),
                server_default=_LEGACY_SALT,
                nullable=False,
            ),
            schema=_SCHEMA,
        )
        # 4. only the row active at the upgrade keeps the legacy salt
        _salt_the_inactive_rows()

    # 5. at most one active holdout, enforced by the database
    if not _has_index():
        op.create_index(
            _INDEX,
            _HOLDOUTS,
            ["is_active"],
            unique=True,
            schema=_SCHEMA,
            postgresql_where=sa.text("is_active"),
        )

    # 6. who each holdout covered
    if not _has_population():
        op.create_table(
            _POPULATION,
            sa.Column("holdout_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("in_holdout", sa.Boolean(), nullable=False),
            sa.Column("first_seen_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(
                ["holdout_id"],
                [f"{_SCHEMA}.{_HOLDOUTS}.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("holdout_id", "user_id"),
            schema=_SCHEMA,
        )


def downgrade() -> None:
    """Drops holdout_population (all recorded memberships), the index and three columns.

    Every row of ``holdout_population`` is deleted and nothing rebuilds it:
    a downgrade across this revision needs the founder's approval at the
    moment it runs whenever that table has rows.  The data step (one active
    holdout) is not reverted.
    """
    op.drop_table(_POPULATION, schema=_SCHEMA)
    op.drop_index(_INDEX, table_name=_HOLDOUTS, schema=_SCHEMA)
    op.drop_column(_HOLDOUTS, "hash_salt", schema=_SCHEMA)
    op.drop_column(_HOLDOUTS, "deactivated_at", schema=_SCHEMA)
    op.drop_column(_HOLDOUTS, "activated_at", schema=_SCHEMA)
