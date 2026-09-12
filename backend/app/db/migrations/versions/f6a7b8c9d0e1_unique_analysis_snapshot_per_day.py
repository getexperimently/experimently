"""One analysis_snapshots row per experiment, kind and UTC day

``GET /results/{id}`` (and ``/sequential``, ``/cuped``, ``/bayesian``) used to
insert a full-JSON snapshot row on every uncached request, so a results page
polling every five seconds added ~17k rows a day per experiment with no dedup
and no retention.  ``record_snapshot`` now stores ``as_of`` truncated to its
UTC calendar day — the same bucket the RNG seed is derived from — and updates
that day's row in place; this migration makes the database enforce it.

Existing rows are folded into the same shape: ``as_of`` is truncated to the
day and, where that leaves duplicates for one (experiment_id, kind, day), the
most recently created row wins.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-11
"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request; it is the only value interpolated into the statements below (a
# schema name cannot be a bind parameter), which is why they carry `nosec`.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

_UNIQUE_NAME = "uq_analysis_snapshot_experiment_kind_as_of"

# Statement templates. The only interpolated value is the schema name above;
# a schema cannot be a bind parameter, hence the `nosec` where they are
# formatted.
_TRUNCATE_TO_DAY_SQL = """
    UPDATE {schema}.analysis_snapshots
    SET as_of = date_trunc('day', as_of AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
"""

_KEEP_NEWEST_PER_DAY_SQL = """
    DELETE FROM {schema}.analysis_snapshots a
    USING {schema}.analysis_snapshots b
    WHERE a.experiment_id = b.experiment_id
      AND a.kind = b.kind
      AND a.as_of = b.as_of
      AND (a.created_at, a.id) < (b.created_at, b.id)
"""


def upgrade() -> None:
    # 1. Fold every existing timestamp onto its UTC day.  The bandit
    #    scheduler's rows move too: within a day the latest tick survives
    #    step 2, which is the state the weights ended the day in.
    op.execute(sa.text(_TRUNCATE_TO_DAY_SQL.format(schema=_SCHEMA)))  # nosec B608  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text

    # 2. Keep the newest row per (experiment_id, kind, day).
    op.execute(sa.text(_KEEP_NEWEST_PER_DAY_SQL.format(schema=_SCHEMA)))  # nosec B608  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text

    # 3. Enforce it from here on.
    op.create_unique_constraint(
        _UNIQUE_NAME,
        "analysis_snapshots",
        ["experiment_id", "kind", "as_of"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    # The collapsed rows cannot be restored; only the constraint is dropped.
    op.drop_constraint(
        _UNIQUE_NAME,
        "analysis_snapshots",
        schema=_SCHEMA,
        type_="unique",
    )
