"""The modules branch, second revision: storage for warehouse analysis (#312).

Creates the three tables warehouse analysis keeps -- ``warehouse_connections``
in its new shape, ``warehouse_sources`` and ``warehouse_analysis_runs`` -- and
removes the earlier ``warehouse_connections`` table, **with every row in it**.

Generated with ``alembic revision --autogenerate --head modules@head`` and
then rewritten by hand, as ``modules_0001_rbac`` was, because the generated
form (an ``ALTER`` of the earlier table) assumes a database that has that
table, and three kinds of database reach this revision:

* **a database a full build migrated** (0.9.x and earlier): the earlier
  ``warehouse_connections`` is there, possibly with rows;
* **a database the core chain built** and a full build now opens: the core
  revision ``e181583b4b24`` created the earlier table, empty;
* **a database a core bootstrap built** and a full build now opens: there is
  no ``warehouse_connections`` at all -- the table belongs to a module model,
  and a core bootstrap creates core tables only.

And a fourth, which never runs this revision: a fresh full bootstrap creates
the three tables from the models and *stamps* the heads.

The earlier table
-----------------
A ``warehouse_connections`` that exists is classified by its full set of
columns, names and types, and only one of three things happens:

* **the new shape** (exactly this revision's columns) -- left alone, rows and
  all.  That is a re-upgrade after a downgrade that did not own the table;
* **the earlier shape** (exactly the columns core revision ``e181583b4b24``
  created, with their types) -- dropped: its rows and both of its indexes.
  Nothing is copied or converted into the new table; connections saved
  through the endpoints removed in 0.9.0 are recreated by an ADMIN;
* **anything else** -- the migration stops with an error naming the table and
  drops nothing.  A table that merely resembles the earlier one is not
  guessed at; the operator renames or removes it and runs the upgrade again.

**Downgrade cannot bring those rows back.**  The supported way back from this
revision is the database snapshot taken before upgrading to it.

Symmetry of downgrade
---------------------
As in ``modules_0001_rbac``: every table this revision creates is tagged with
a COMMENT on its primary-key constraint (:data:`_CREATED_BY`), and downgrade
drops exactly the tagged tables, never the identical ones a fresh bootstrap
created from the models.  When it drops ``warehouse_connections`` it puts back
the earlier shape, empty, so that the previous release's model maps a table
again.

Revision ID: modules_0002_warehouse_analysis
Revises: modules_0001_rbac
Create Date: 2026-09-27
"""

import logging
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "modules_0002_warehouse_analysis"
down_revision: Union[str, None] = "modules_0001_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# The schema name comes from the deployment's own environment, never from a
# request.  It is the only value interpolated into any name below.
_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "experimentation")

#: COMMENT written on the primary key of every table this revision creates.
_CREATED_BY = "created by alembic revision modules_0002_warehouse_analysis"

#: Core tables this revision's foreign keys reference, or its runs describe.
_REQUIRED_CORE_TABLES = ("users", "experiments", "variants")

#: A column only the earlier ``warehouse_connections`` has.
_EARLIER_SHAPE_COLUMN = "encrypted_credentials"

#: The earlier ``warehouse_connections``, column by column, exactly as core
#: revision ``e181583b4b24`` (and the previous release's model) created it:
#: name -> the type as PostgreSQL reflects it.
_EARLIER_SHAPE = {
    "id": "UUID",
    "created_at": "TIMESTAMP",
    "updated_at": "TIMESTAMP",
    "name": "VARCHAR(200)",
    "warehouse_type": "VARCHAR(50)",
    _EARLIER_SHAPE_COLUMN: "TEXT",
    "is_active": "BOOLEAN",
    "owner_id": "UUID",
}

#: The columns of the ``warehouse_connections`` this revision creates.
_NEW_SHAPE_COLUMNS = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "name",
        "warehouse_type",
        "parameters",
        "credentials_ciphertext",
        "pending_credentials_ciphertext",
        "public_key_fingerprint",
        "pending_public_key_fingerprint",
        "external_id",
        "query_timeout_seconds",
        "max_bytes_per_query",
        "max_runs_per_day",
        "created_by",
    }
)

NEW_SHAPE = "new"
EARLIER_SHAPE = "earlier"

CONNECTIONS = "warehouse_connections"
SOURCES = "warehouse_sources"
RUNS = "warehouse_analysis_runs"


def _create_connections() -> None:
    op.create_table(
        CONNECTIONS,
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("warehouse_type", sa.String(length=20), nullable=False),
        sa.Column("parameters", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("credentials_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("pending_credentials_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("public_key_fingerprint", sa.String(length=100), nullable=True),
        sa.Column(
            "pending_public_key_fingerprint", sa.String(length=100), nullable=True
        ),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("query_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_bytes_per_query", sa.BigInteger(), nullable=True),
        sa.Column("max_runs_per_day", sa.Integer(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "warehouse_type IN ('bigquery', 'snowflake', 'athena')",
            name="ck_warehouse_connections_type",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(parameters) = 'object'",
            name="ck_warehouse_connections_parameters_object",
        ),
        sa.CheckConstraint(
            "query_timeout_seconds >= 10",
            name="ck_warehouse_connections_query_timeout",
        ),
        sa.CheckConstraint(
            "max_runs_per_day >= 1",
            name="ck_warehouse_connections_max_runs_per_day",
        ),
        sa.CheckConstraint(
            "(warehouse_type IN ('bigquery', 'athena')) = "
            "(max_bytes_per_query IS NOT NULL)",
            name="ck_warehouse_connections_byte_cap_type",
        ),
        sa.CheckConstraint(
            "max_bytes_per_query IS NULL OR max_bytes_per_query >= 10000000",
            name="ck_warehouse_connections_byte_cap_min",
        ),
        sa.CheckConstraint(
            "(warehouse_type = 'athena') = (external_id IS NOT NULL)",
            name="ck_warehouse_connections_external_id",
        ),
        sa.CheckConstraint(
            "warehouse_type <> 'athena' OR (credentials_ciphertext IS NULL "
            "AND pending_credentials_ciphertext IS NULL)",
            name="ck_warehouse_connections_athena_no_secret",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], [f"{_SCHEMA}.users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_warehouse_connections_external_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_warehouse_connections_created_at",
        CONNECTIONS,
        ["created_at"],
        schema=_SCHEMA,
    )


def _create_sources() -> None:
    op.create_table(
        SOURCES,
        sa.Column("connection_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("table_reference", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("column_mapping", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("filters", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metric_type", sa.String(length=20), nullable=True),
        sa.Column("conversion_window_hours", sa.Integer(), nullable=True),
        sa.Column("cap_value", sa.Double(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('assignment', 'metric')", name="ck_warehouse_sources_kind"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(table_reference) = 'object'",
            name="ck_warehouse_sources_table_reference_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(column_mapping) = 'object'",
            name="ck_warehouse_sources_column_mapping_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(filters) = 'array'",
            name="ck_warehouse_sources_filters_array",
        ),
        sa.CheckConstraint(
            "metric_type IS NULL OR metric_type IN ('proportion', 'mean')",
            name="ck_warehouse_sources_metric_type",
        ),
        sa.CheckConstraint(
            "(kind = 'metric') = (metric_type IS NOT NULL)",
            name="ck_warehouse_sources_metric_has_type",
        ),
        sa.CheckConstraint(
            "(kind = 'metric') = (conversion_window_hours IS NOT NULL)",
            name="ck_warehouse_sources_metric_has_window",
        ),
        sa.CheckConstraint(
            "conversion_window_hours IS NULL OR conversion_window_hours "
            "BETWEEN 1 AND 8760",
            name="ck_warehouse_sources_window_range",
        ),
        sa.CheckConstraint(
            "cap_value IS NULL OR (cap_value > 0 AND metric_type = 'mean')",
            name="ck_warehouse_sources_cap_value",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            [f"{_SCHEMA}.{CONNECTIONS}.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], [f"{_SCHEMA}.users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "kind",
            "name",
            name="uq_warehouse_sources_connection_kind_name",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_warehouse_sources_created_at",
        SOURCES,
        ["created_at"],
        schema=_SCHEMA,
    )


def _create_runs() -> None:
    op.create_table(
        RUNS,
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("connection_id", UUID(as_uuid=True), nullable=True),
        sa.Column("connection_name", sa.String(length=200), nullable=False),
        sa.Column("warehouse_type", sa.String(length=20), nullable=False),
        sa.Column("experiment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by", UUID(as_uuid=True), nullable=True),
        sa.Column("request", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("statements", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "sufficient_statistics", JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("results", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("job_metadata", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('analysis', 'preview')", name="ck_warehouse_runs_kind"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_warehouse_runs_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(request) = 'object'",
            name="ck_warehouse_runs_request_object",
        ),
        sa.CheckConstraint(
            "kind <> 'analysis' OR experiment_id IS NOT NULL",
            name="ck_warehouse_runs_analysis_has_experiment",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_warehouse_runs_error_code",
        ),
        sa.CheckConstraint(
            "window_start IS NULL OR window_end IS NULL "
            "OR window_start < window_end",
            name="ck_warehouse_runs_window",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            [f"{_SCHEMA}.{CONNECTIONS}.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"], [f"{_SCHEMA}.experiments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], [f"{_SCHEMA}.users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_warehouse_analysis_runs_created_at",
        RUNS,
        ["created_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_warehouse_runs_connection_created",
        RUNS,
        ["connection_id", "created_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_warehouse_runs_experiment_created",
        RUNS,
        ["experiment_id", "created_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "uq_warehouse_runs_one_in_flight",
        RUNS,
        ["connection_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


#: In dependency order: a table's foreign keys point only at tables above it.
_CREATORS = (
    (CONNECTIONS, _create_connections),
    (SOURCES, _create_sources),
    (RUNS, _create_runs),
)


def _create_earlier_connections() -> None:
    """The ``warehouse_connections`` shape of the releases before this one.

    Exactly what the previous release's model builds, so that release maps a
    table again after :func:`downgrade`.  Empty: the rows are not recoverable.
    """
    op.create_table(
        CONNECTIONS,
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("warehouse_type", sa.String(length=50), nullable=False),
        sa.Column(_EARLIER_SHAPE_COLUMN, sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=True),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], [f"{_SCHEMA}.users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_warehouse_conn_active",
        CONNECTIONS,
        ["is_active"],
        schema=_SCHEMA,
    )
    op.create_index(
        f"ix_{_SCHEMA}_warehouse_connections_created_at",
        CONNECTIONS,
        ["created_at"],
        schema=_SCHEMA,
    )


def _connections_shape(inspector) -> str:
    """Which ``warehouse_connections`` this is: :data:`NEW_SHAPE` or
    :data:`EARLIER_SHAPE`.  Anything else raises, and nothing is dropped.
    """
    columns = {
        column["name"]: str(column["type"])
        for column in inspector.get_columns(CONNECTIONS, schema=_SCHEMA)
    }
    if set(columns) == _NEW_SHAPE_COLUMNS:
        return NEW_SHAPE
    if columns == _EARLIER_SHAPE:
        return EARLIER_SHAPE
    raise RuntimeError(
        f"modules_0002_warehouse_analysis: {_SCHEMA}.{CONNECTIONS} exists but "
        "matches neither the table this release creates nor the one earlier "
        "releases created, so the migration will not drop or change it. "
        f"Rename it (ALTER TABLE {_SCHEMA}.{CONNECTIONS} RENAME TO ...) or "
        "remove it yourself, then run the upgrade again. Columns found: "
        f"{', '.join(sorted(columns))}."
    )


def _remove_earlier_connections() -> None:
    """Drop the earlier ``warehouse_connections``: every row, both indexes."""
    bind = op.get_bind()
    # _SCHEMA comes from the deployment's environment and the table name is a
    # module constant; nothing here comes from a request.
    rows = bind.execute(
        sa.text(f'SELECT count(*) FROM "{_SCHEMA}"."{CONNECTIONS}"')
    ).scalar_one()
    logger.warning(
        "modules_0002: removing %d legacy warehouse connection rows", rows
    )
    # No CASCADE: nothing references this table, and if something ever does,
    # the migration should stop rather than take that with it.
    op.execute(f'DROP TABLE "{_SCHEMA}"."{CONNECTIONS}"')


def _tag_table(table: str) -> None:
    """Mark *table*'s primary key as created by this revision."""
    # A fresh inspector: the one upgrade() holds predates the CREATE TABLE.
    pk = sa.inspect(op.get_bind()).get_pk_constraint(table, schema=_SCHEMA)
    name = pk.get("name")
    if name:
        # _SCHEMA comes from the deployment's environment, the other names are
        # module constants or reflected, and the comment is a constant literal.
        op.execute(
            f'COMMENT ON CONSTRAINT "{name}" ON "{_SCHEMA}"."{table}" '
            f"IS '{_CREATED_BY}'"
        )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names(schema=_SCHEMA))

    missing_core = [t for t in _REQUIRED_CORE_TABLES if t not in existing]
    if missing_core:
        raise RuntimeError(
            f"modules_0002_warehouse_analysis needs the core schema in {_SCHEMA!r} "
            f"({', '.join(missing_core)} missing). Apply the core chain first: "
            "`alembic upgrade heads` on a database the core profile built, or "
            "`python -m backend.app.db.bootstrap` on a fresh one."
        )

    if CONNECTIONS in existing and _connections_shape(inspector) == EARLIER_SHAPE:
        _remove_earlier_connections()
        existing.discard(CONNECTIONS)

    for table, create in _CREATORS:
        if table not in existing:
            create()
            _tag_table(table)


def downgrade() -> None:
    """Drop exactly the tables :func:`upgrade` created -- see the docstring."""
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names(schema=_SCHEMA))

    dropped_connections = False
    # Dependents first.
    for table in (RUNS, SOURCES, CONNECTIONS):
        if table not in existing:
            continue
        pk = inspector.get_pk_constraint(table, schema=_SCHEMA)
        if pk.get("comment") == _CREATED_BY:
            op.drop_table(table, schema=_SCHEMA)
            dropped_connections = dropped_connections or table == CONNECTIONS

    if dropped_connections:
        _create_earlier_connections()
