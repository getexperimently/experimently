"""The modules' alembic branch, first revision: the RBAC tables and the workspace FKs.

This is the first revision of the ``modules`` branch (issue #89), carrying the
schema the optional modules own, so that a core checkout -- which deletes
``modules/`` whole -- sees one head and a full checkout sees two.  It branches
off the core revision ``a7b8c9d0e1f2`` (see "Why the branch point is
a7b8c9d0e1f2" below); core migrations chain on from ``b8c9d0e1f2a3``, the
core's second child of that same revision, and the modules' migrations chain
from this one.  Every upgrade or stamp names ``heads`` (plural).

Two repairs from the boundary audit (issue #88):

* ``custom_roles``, ``user_custom_roles`` and ``direct_permission_grants``
  (``modules/backend/app/models/custom_role.py``) had no migration at all -- they
  existed only on databases built by ``create_all``.  They are created here,
  exactly as the models declare them, when absent.
* the two ``workspace_id`` foreign keys that core migration
  ``a7b8c9d0e1f2`` dropped from ``experiments`` and ``feature_flags`` are
  put back, with the ``ON DELETE SET NULL`` they had, on any database that
  has a ``workspaces`` table (``modules/backend/app/models/workspace.py`` declares
  them ``use_alter`` so a fresh bootstrap gets them from ``create_all``).

Why the branch point is ``a7b8c9d0e1f2`` (review round 2, finding 1)
---------------------------------------------------------------------
The FK step below *undoes* what core revision ``a7b8c9d0e1f2`` does, so the
order the two run in is the whole correctness of the pair, and alembic orders
two revisions only when one is an ancestor of the other.

This revision used to be an independent alembic base (``down_revision = None``,
no ``depends_on``).  Alembic was then free to schedule it anywhere in a plan,
and it scheduled it early: on any database behind ``a7b8c9d0e1f2`` a single
``alembic upgrade heads`` ran this revision *first* (so the guarded FK step
found the constraints already there and skipped), ``a7b8c9d0e1f2`` *second*
(dropping both), and stamped both -- leaving ``ON DELETE SET NULL`` silently
gone with nothing left to re-apply.  ``db/bootstrap.py`` hid it, but the
production paths run raw ``alembic upgrade heads``.

``depends_on = "a7b8c9d0e1f2"`` is not the repair, for two separate reasons.
It removes the depended-on revision from ``_real_heads``, which is what
``heads`` resolves to, so ``alembic stamp heads`` on a fresh full-profile
bootstrap wrote a single row -- this one -- and a core image pointed at that
database died in ``docker-entrypoint.sh`` with "Can't locate revision
identified by 'modules_0001_rbac'".  And from a database recorded at exactly
``a7b8c9d0e1f2`` (the core head as released) it makes alembic re-plan part of
the core chain and re-run migrations that are already applied -- ``upgrade
heads`` fails on ``CREATE TYPE audit_action_type`` from ``ep033``.

So the edge is a plain ``down_revision``, and the core chain grew a second
child of ``a7b8c9d0e1f2`` (``b8c9d0e1f2a3``, a marker revision) so that it
still has a head of its own.  ``a7b8c9d0e1f2`` is a real branch point:
``alembic heads`` prints two, ``stamp heads`` writes two rows, and ancestry --
not luck -- puts the drop before this restoration on every path.

One consequence worth knowing: this revision is no longer an alembic *base*,
so ``alembic downgrade modules@base`` no longer names it.  With a single tree
root alembic cannot filter the branch and downgrades the *whole* core chain
instead.  Unapply this branch with ``alembic downgrade modules@-1``.

``upgrade()`` still refuses to run against a schema that does not have the
core tables it references, and every object it touches is still guarded by
reflection: ``db/bootstrap.py`` is the only thing that builds a database from
zero (the historical core chain cannot be replayed), and it creates the core
tables and *stamps* this revision without ever running it.

Symmetry of downgrade (review round 1, finding 3)
-------------------------------------------------
``upgrade()`` creates each object only when it is absent, because a fresh
full-profile bootstrap creates all of them from the models and then *stamps*
this revision without ever running it.  ``downgrade()`` must therefore drop
only what ``upgrade()`` actually created, or ``alembic downgrade -1`` on a
bootstrapped database would drop three populated tables this revision never
made.  Every object created here is tagged with a PostgreSQL COMMENT
(:data:`_CREATED_BY`) on a *constraint* -- the table's primary key, or the
foreign key itself; the downgrade drops exactly the objects carrying that tag,
which is a fact about the database and so survives a different process, a
different container and a different release.  The mark is not a table comment
because alembic's autogenerate compares those against the models (which carry
none) and would propose dropping it; constraint comments it never looks at.

Revision ID: modules_0001_rbac
Revises: a7b8c9d0e1f2 (the branch point; the core chain goes on at b8c9d0e1f2a3)
Create Date: 2026-09-12
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "modules_0001_rbac"
#: The branch point, not a base -- see "Why the branch point is a7b8c9d0e1f2".
#: This revision must run *after* the core revision that drops the two
#: workspace foreign keys, because it is what puts them back.
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = ("modules",)
#: Deliberately None: a dependency edge would collapse the two heads into one
#: recorded row -- see the docstring.
depends_on: Union[str, Sequence[str], None] = None

# The schema name comes from the deployment's own environment, never from a
# request.  It is the only value interpolated into any name below.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

#: COMMENT written on a constraint of every object this revision creates, so
#: downgrade() can tell them from the identical objects a fresh bootstrap
#: creates from the models.  Reflected back by the ``comment`` key of
#: Inspector.get_pk_constraint() and Inspector.get_foreign_keys().
_CREATED_BY = "created by alembic revision modules_0001_rbac"

#: Core tables this revision's foreign keys reference.  Without a depends_on
#: edge, their absence is what says "the core schema is not there yet".
_REQUIRED_CORE_TABLES = ("users",)

_WORKSPACE_FKS = (
    ("experiments", "experiments_workspace_id_fkey"),
    ("feature_flags", "feature_flags_workspace_id_fkey"),
)


def _create_custom_roles() -> None:
    op.create_table(
        "custom_roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system_role", sa.Boolean(), nullable=False),
        sa.Column("permissions", JSONB(), nullable=False),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"], [f"{_SCHEMA}.users.id"], ondelete="SET NULL"
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_custom_roles_name",
        "custom_roles",
        ["name"],
        unique=True,
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_custom_roles_created_at",
        "custom_roles",
        ["created_at"],
        schema=_SCHEMA,
    )


def _create_user_custom_roles() -> None:
    op.create_table(
        "user_custom_roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{_SCHEMA}.users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], [f"{_SCHEMA}.custom_roles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_id"], [f"{_SCHEMA}.users.id"], ondelete="SET NULL"
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        f"{_SCHEMA}_user_custom_roles_user_idx",
        "user_custom_roles",
        ["user_id"],
        schema=_SCHEMA,
    )
    op.create_index(
        f"{_SCHEMA}_user_custom_roles_role_idx",
        "user_custom_roles",
        ["role_id"],
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_user_custom_roles_created_at",
        "user_custom_roles",
        ["created_at"],
        schema=_SCHEMA,
    )


def _create_direct_permission_grants() -> None:
    op.create_table(
        "direct_permission_grants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("actions", JSONB(), nullable=False),
        sa.Column("granted_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{_SCHEMA}.users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_id"], [f"{_SCHEMA}.users.id"], ondelete="SET NULL"
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_direct_permission_grants_user_id",
        "direct_permission_grants",
        ["user_id"],
        schema=_SCHEMA,
    )
    op.create_index(
        f"{_SCHEMA}_direct_grants_user_resource_idx",
        "direct_permission_grants",
        ["user_id", "resource"],
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_direct_permission_grants_created_at",
        "direct_permission_grants",
        ["created_at"],
        schema=_SCHEMA,
    )


_CREATORS = (
    ("custom_roles", _create_custom_roles),
    ("user_custom_roles", _create_user_custom_roles),
    ("direct_permission_grants", _create_direct_permission_grants),
)


def _workspace_fk(inspector, table: str):
    """The reflected ``workspace_id -> workspaces`` FK of *table*, or None."""
    for fk in inspector.get_foreign_keys(table, schema=_SCHEMA):
        if (
            fk.get("constrained_columns") == ["workspace_id"]
            and fk.get("referred_table") == "workspaces"
            and fk.get("name")
        ):
            return fk
    return None


def _tag_constraint(table: str, name: str) -> None:
    """Mark a constraint as created by this revision (see :data:`_CREATED_BY`)."""
    # _SCHEMA comes from the deployment's environment and the other two names
    # are module-level constants; the comment is a constant literal.
    op.execute(
        f'COMMENT ON CONSTRAINT "{name}" ON "{_SCHEMA}"."{table}" IS \'{_CREATED_BY}\''
    )


def _tag_table(table: str) -> None:
    """Mark *table*'s primary key as created by this revision."""
    # A fresh inspector: the one upgrade() holds predates the CREATE TABLE.
    pk = sa.inspect(op.get_bind()).get_pk_constraint(table, schema=_SCHEMA)
    name = pk.get("name")
    if name:
        _tag_constraint(table, name)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names(schema=_SCHEMA))

    missing_core = [t for t in _REQUIRED_CORE_TABLES if t not in existing]
    if missing_core:
        raise RuntimeError(
            f"modules_0001_rbac needs the core schema in {_SCHEMA!r} "
            f"({', '.join(missing_core)} missing). Apply the core chain first: "
            "`alembic upgrade heads` on a database the core profile built, or "
            "`python -m backend.app.db.bootstrap` on a fresh one."
        )

    for table, create in _CREATORS:
        if table not in existing:
            create()
            _tag_table(table)

    if "workspaces" in existing:
        for table, name in _WORKSPACE_FKS:
            if table in existing and _workspace_fk(inspector, table) is None:
                op.create_foreign_key(
                    name,
                    table,
                    "workspaces",
                    ["workspace_id"],
                    ["id"],
                    source_schema=_SCHEMA,
                    referent_schema=_SCHEMA,
                    ondelete="SET NULL",
                )
                _tag_constraint(table, name)


def downgrade() -> None:
    """Drop exactly the objects :func:`upgrade` created -- see the docstring."""
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names(schema=_SCHEMA))

    for table, _name in _WORKSPACE_FKS:
        if table not in existing:
            continue
        fk = _workspace_fk(inspector, table)
        if fk is not None and fk.get("comment") == _CREATED_BY:
            op.drop_constraint(fk["name"], table, schema=_SCHEMA, type_="foreignkey")

    # Dependents first.
    for table in ("user_custom_roles", "direct_permission_grants", "custom_roles"):
        if table not in existing:
            continue
        pk = inspector.get_pk_constraint(table, schema=_SCHEMA)
        if pk.get("comment") == _CREATED_BY:
            op.drop_table(table, schema=_SCHEMA)
