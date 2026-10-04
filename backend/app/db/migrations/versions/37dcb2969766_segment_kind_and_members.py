"""Segments: a kind (rules or id_list), and the members of an id list

Downgrade deletes all id-list members and every segment's kind.

Adds what a segment made from a list of user ids needs (#440):

* ``segments.kind`` (``varchar(16) NOT NULL``, server default ``'rules'``),
  with the check ``ck_segments_kind``: ``kind IN ('rules', 'id_list')``.  Every
  existing segment becomes a rules segment, which is what it was;
* the table ``segment_members (segment_id, member_id)``, primary key
  ``(segment_id, member_id)``, ``segment_id`` referencing ``segments.id`` ON
  DELETE CASCADE, ``member_id`` ``varchar(255)``.  The primary key serves both
  the membership lookup and the count; there is no other index.

No data step: no row is changed.

Each step runs only when its object is absent, as ``271f03a31742`` does: a
schema built by ``db/bootstrap.py``'s ``create_all`` already has them (they are
on the model), and the transition tests rewind such a schema's
``alembic_version`` and replay the chain from there.

The server default exists for an older image after a rollback, which inserts
segments without naming ``kind``; the model sets it too.

**Downgrade** drops, with literal ``op.drop_table`` / ``op.drop_constraint`` /
``op.drop_column``: the table ``segment_members`` -- every id list loses every
member, and nothing can rebuild them -- the check, and ``segments.kind``.  An
id-list segment then comes back from a later upgrade as a rules segment with no
rules.  So the downgrade **refuses** while ``segment_members`` has any row, and
says how many; ``-x allow_member_loss=true`` on the alembic command line runs
it anyway.  Using the override deletes those rows: it needs a person who has
agreed to lose them, at the moment it runs.

Core chain, extending the core head ``d29a479daafe`` (#445).  Nothing here
touches a module table, so a full checkout still has exactly two heads: this
revision and ``modules_0002_warehouse_analysis``.

Revision ID: 37dcb2969766
Revises: d29a479daafe
Create Date: 2026-10-04
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "37dcb2969766"
down_revision: Union[str, None] = "d29a479daafe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

_SEGMENTS = "segments"
_MEMBERS = "segment_members"
_COLUMN = "kind"
_CHECK = "ck_segments_kind"
_CHECK_SQL = "kind IN ('rules', 'id_list')"

#: The ``-x`` argument that lets the downgrade delete stored members.
OVERRIDE = "allow_member_loss"

_OFFLINE_REFUSAL = (
    "37dcb2969766 counts segment_members before it drops the table and cannot "
    "be emitted as SQL; run it online (without --sql)."
)


def _has_column() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(_SEGMENTS, schema=_SCHEMA)
    return any(column["name"] == _COLUMN for column in columns)


def _has_check() -> bool:
    checks = sa.inspect(op.get_bind()).get_check_constraints(_SEGMENTS, schema=_SCHEMA)
    return any(check["name"] == _CHECK for check in checks)


def _has_members_table() -> bool:
    return _MEMBERS in sa.inspect(op.get_bind()).get_table_names(schema=_SCHEMA)


def upgrade() -> None:
    if not _has_column():
        op.add_column(
            _SEGMENTS,
            sa.Column(
                _COLUMN,
                sa.String(length=16),
                server_default=sa.text("'rules'"),
                nullable=False,
            ),
            schema=_SCHEMA,
        )
    if not _has_check():
        op.create_check_constraint(_CHECK, _SEGMENTS, _CHECK_SQL, schema=_SCHEMA)
    if not _has_members_table():
        op.create_table(
            _MEMBERS,
            sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("member_id", sa.String(length=255), nullable=False),
            sa.ForeignKeyConstraint(
                ["segment_id"],
                [f"{_SCHEMA}.{_SEGMENTS}.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("segment_id", "member_id"),
            schema=_SCHEMA,
        )


def _override_given() -> bool:
    value = context.get_x_argument(as_dictionary=True).get(OVERRIDE, "")
    return value.strip().lower() == "true"


def _member_rows() -> int:
    members = sa.table(_MEMBERS, schema=_SCHEMA)
    return int(
        op.get_bind().execute(sa.select(sa.func.count()).select_from(members)).scalar()
    )


def downgrade() -> None:
    """Drops segment_members (every id-list member), the check and segments.kind.

    Refused while ``segment_members`` has rows, unless ``-x
    allow_member_loss=true`` is given.
    """
    if op.get_context().as_sql:
        raise RuntimeError(_OFFLINE_REFUSAL)
    if _has_members_table():
        rows = _member_rows()
        if rows and not _override_given():
            raise RuntimeError(
                f"37dcb2969766: refusing to downgrade: segment_members holds {rows} "
                "row(s), the members of the id-list segments, and this downgrade "
                "deletes them; nothing can rebuild them, and every id-list segment "
                "would come back as a rules segment with no rules. Remove the "
                "members first, or run the downgrade again with "
                f"-x {OVERRIDE}=true once someone has agreed to lose them. Nothing "
                "was changed."
            )
    op.drop_table(_MEMBERS, schema=_SCHEMA)
    op.drop_constraint(_CHECK, _SEGMENTS, type_="check", schema=_SCHEMA)
    op.drop_column(_SEGMENTS, _COLUMN, schema=_SCHEMA)
