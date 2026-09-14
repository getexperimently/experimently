# Add to env.py
import os
import pathlib
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.schema import CreateSchema

# Add the repository root to sys.path so `import backend...` works no matter
# which directory alembic is invoked from.  This file lives at
# <root>/backend/app/db/migrations/env.py, i.e. four levels below the root.
migrations_dir = os.path.dirname(os.path.abspath(__file__))  # backend/app/db/migrations
project_root = os.path.abspath(os.path.join(migrations_dir, "..", "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Which schema is this process working on?  Resolved FIRST, and published back
# into POSTGRES_SCHEMA, because the revision modules read that variable when
# alembic imports them and five of them carry their own "experimentation"
# default.  backend/app/db/schema.py explains what those two opinions used to
# generate; db/bootstrap.py resolves with the same function.
from backend.app.db.schema import export_schema_name, metadata_for_schema

schema = export_schema_name()

# Import your models.  The seam: register the core models, then let the
# modules package register its own through hooks.register_model_module().
# Autogenerate therefore sees exactly the tables the running profile owns — a
# core build must not generate migrations that create module tables.
from backend.app.models import register_core_models  # noqa: E402
from backend.app.modules_loader import require_modules_or_absent  # noqa: E402

Base = register_core_models()
# Strict on purpose: if the modules package is present but fails to register,
# target_metadata would hold only the core tables and autogenerate would
# propose dropping every module table. Better to refuse than to be quiet.
require_modules_or_absent()

# The models bound their schema from APP_ENV at import time; hand alembic the
# metadata as it reads on the schema resolved above, so that the metadata
# autogenerate compares and the schema it reflects are the same string by
# construction.  Without this, `APP_ENV=test TESTING=true` with POSTGRES_SCHEMA
# left unset — the export sequence CONTRIBUTING.md documents — produced a revision
# that creates all ~50 tables in test_experimentation and drops all ~50 from
# experimentation: users, experiments, feature_flags, everything.
# Base.metadata itself is returned unchanged when the two already agree.
target_metadata = metadata_for_schema(Base, schema)

# Keep the module-managed constraints and the module tables out of the core
# chain's autogenerate, and only that chain's: a revision generated for the
# `modules` branch (`alembic revision --head modules@head ...`) sees
# everything.  See backend/app/db/autogenerate_filters.py for the reasoning.
from backend.app.db.autogenerate_filters import include_object_for  # noqa: E402

# The three behaviours a profile switch needs, shared with db/bootstrap.py so
# that `alembic upgrade heads` and `python -m backend.app.db.bootstrap` do the
# same thing to the same database.  See the docstrings there.
from backend.app.db.bootstrap import (  # noqa: E402
    may_run_alembic,
    prune_redundant_revisions,
    reconcile_with_models,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# The modules' migrations (modules/backend/app/db/migrations/versions, branch
# `modules`) are a second entry in alembic.ini's version_locations.  alembic builds
# the script directory before running this file and skips a listed directory
# that does not exist, so that entry is present exactly when modules/ is -- and
# require_modules_or_absent() above has already refused to continue if modules/
# is present but broken.  Either way the metadata and the revision set agree.
include_object = include_object_for(config.cmd_opts)


def _resolve_version_locations() -> None:
    """Collapse the ``..`` in alembic.ini's version locations.

    The modules' location is spelled ``%(here)s/../../../modules/...`` so that
    it resolves from any working directory (see the comment in alembic.ini).
    alembic only calls ``Path.absolute()`` on a configured location, which keeps
    the ``..`` segments, while a revision's own file path is ``Path.resolve()``d;
    ``ScriptDirectory.generate_revision`` compares the two, so ``alembic
    revision --autogenerate --head modules@head`` would fail with "Path ... is
    not represented in current version locations" and a module's migration could
    not be generated at all.

    Rewriting the locations here fixes that comparison without changing which
    directories are read: the script directory is built before this file runs,
    but ``generate_revision`` is called after it, and a resolved path names the
    same directory.  ``revision --autogenerate`` and every ``upgrade`` /
    ``downgrade`` / ``stamp`` / ``current`` runs this file; ``heads``,
    ``history`` and ``branches`` do not, and do not need to -- they never
    compare paths.
    """
    script = getattr(context, "script", None)
    if script is None or not getattr(script, "version_locations", None):
        return
    script.version_locations = [
        str(pathlib.Path(location).resolve()) for location in script.version_locations
    ]
    # Both are alembic memoized_property caches computed from the above.
    script.__dict__.pop("_version_locations", None)
    script.__dict__.pop("_singular_version_location", None)


_resolve_version_locations()

db_name = os.environ.get("POSTGRES_DB", "experimentation")


#: The connection's default schema, filled in by run_migrations_online() before
#: the comparison runs.  ``None`` offline, where nothing is reflected.
_default_schema: str | None = None


def include_name(name, type_, parent_names):
    """Autogenerate compares the metadata's own schema only.

    Every model declares its schema explicitly, so autogenerate has to reflect
    that schema rather than the connection's default (``public``), which is
    what ``include_schemas=True`` below turns on; this filter then keeps every
    *other* schema out of the comparison, or their tables would be proposed as
    drops.

    Read off ``target_metadata.schema`` rather than off a second variable:
    that is the schema the tables being compared actually declare, so the
    filter and the metadata cannot drift apart even if something later
    repoints the metadata.

    ``None`` is the connection's default schema, not "no schema".  alembic
    replaces the default with ``None`` *before* it runs these filters
    (``autogenerate/compare/schema.py``: ``schemas.discard(default_schema);
    schemas.add(None)``), and ``_compare_tables`` maps the metadata's own
    schema to ``None`` the same way.  So when the two are the same string --
    a role with ``search_path`` set, ``PGOPTIONS``, or simply
    ``POSTGRES_SCHEMA=public`` -- rejecting ``None`` reflected nothing at all
    and autogenerate proposed ``create_table`` for all 37 existing core
    tables (review round 4, finding 5).
    """
    if type_ == "schema":
        if name is None:
            return _default_schema == target_metadata.schema
        return name == target_metadata.schema
    return True

# Build sqlalchemy.url from the same POSTGRES_* variables the application,
# the test suite and the CI workflows use.
_db_user = os.environ.get("POSTGRES_USER", "postgres")
_db_password = os.environ.get("POSTGRES_PASSWORD", "postgres")
_db_host = os.environ.get("POSTGRES_SERVER") or os.environ.get("POSTGRES_HOST") or "localhost"
_db_port = os.environ.get("POSTGRES_PORT", "5432")
postgres_url = f"postgresql://{_db_user}:{_db_password}@{_db_host}:{_db_port}/{db_name}"
config.set_main_option("sqlalchemy.url", postgres_url)

# Interpret the config file for Python logging.
# disable_existing_loggers=False: fileConfig() otherwise switches off every
# logger that already exists and is not named in alembic.ini -- which, when
# alembic is driven from Python (db/bootstrap.py), is the *caller's* logging.
# The bootstrap's own WARNING about a repaired schema was lost exactly that way.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=schema,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


#: Sub-commands that change what the database records, and so may repair an
#: ``alembic_version`` alembic would otherwise refuse to read at all
#: (:func:`prune_redundant_revisions`).  `current`, `history` and `revision`
#: keep alembic's own behaviour: they report, and a report that quietly fixed
#: the thing it was reporting on would be worse than the error.
_STATE_CHANGING_COMMANDS = frozenset({"upgrade", "downgrade", "stamp"})

#: Sub-commands that may be *skipped* on a database from the other profile --
#: "succeed having done nothing".  Only ``upgrade``, because only an upgrade
#: has nothing left to do once this build's own heads are all recorded: that is
#: what :func:`may_run_alembic` tests.  A skipped ``downgrade`` exits 0 with the
#: schema unchanged, and a skipped ``stamp`` is worse still -- ``stamp --purge
#: heads`` is the escape hatch the migration guide and the guard's own message point at,
#: and the guard used to close it.  Both now get alembic's own answer, which
#: names the revision it cannot resolve (review round 4, finding 3).
_SKIPPABLE_COMMANDS = frozenset({"upgrade"})


def _command_name() -> str | None:
    """The alembic sub-command that was typed, or ``None`` when driven from Python.

    ``config.cmd_opts.cmd`` is alembic's ``(function, positional, keyword)``
    tuple for the sub-command; ``config.cmd_opts`` itself is ``None`` under
    ``db/bootstrap.py``, which calls ``command.upgrade``/``command.stamp``
    directly.
    """
    cmd = getattr(config.cmd_opts, "cmd", None)
    if not cmd:
        return None
    return getattr(cmd[0], "__name__", None)


def _changes_state() -> bool:
    """Whether this invocation may repair the version table before running."""
    name = _command_name()
    return name is None or name in _STATE_CHANGING_COMMANDS


def _guard_applies() -> bool:
    """Whether the foreign-revision guard applies to this invocation."""
    name = _command_name()
    return name is None or name in _SKIPPABLE_COMMANDS


def _is_upgrade() -> bool:
    """Whether this alembic invocation is a CLI ``upgrade``.

    Programmatic drives (``cmd_opts is None``) answer False: that is
    ``db/bootstrap.py``, which reconciles itself immediately afterwards and
    must not have it happen twice -- nor at all around ``command.stamp``.

    The distinction matters because :func:`reconcile_with_models` creates
    tables: running it after a ``downgrade`` would put back what was just
    dropped.
    """
    return _command_name() == "upgrade"


def _is_at_head(connection) -> bool:
    """Whether every head this build has is now recorded in *schema*.

    The second half of the reconcile's condition, and it has to be read from
    the database rather than from the command line: ``alembic upgrade
    <revision>`` deliberately stops part way, and creating every table the
    models declare at that point would put the schema ahead of the version
    table and break the next step.  Only a database that is *at* its heads is
    one the models may be reconciled with.

    A head this build does not have (``modules_0001_rbac`` under a core build)
    is not required to be recorded: this asks whether **our** chain is finished,
    which is the same question ``may_run_alembic`` asks above.
    """
    from alembic.runtime.migration import MigrationContext

    recorded = set(
        MigrationContext.configure(
            connection, opts={"version_table_schema": schema}
        ).get_current_heads()
    )
    return set(context.script.revision_map.heads) <= recorded


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # An alembic_version row that another recorded row already descends from
    # makes alembic refuse *every* command -- "Requested revision X overlaps
    # with other requested revisions Y" -- and this release creates exactly
    # that state on any database the previous build recorded at both
    # a7b8c9d0e1f2 and modules_0001_rbac (the branch used to be an alembic
    # base).  db/bootstrap.py has always pruned those rows; the CDK migration
    # task, deploy-prod.yml, db-migrate.yml and docs/self-hosting/migrations.md
    # all run raw `alembic upgrade heads`, which died there.  Ahead of the
    # connection below because everything past it reads the version table; the
    # prune opens (and closes) its own.
    if _changes_state():
        prune_redundant_revisions(connectable, schema, config)

    with connectable.connect() as connection:
        # Migrations (and the alembic_version table) live inside `schema`;
        # create it on a fresh database so `upgrade head` works from zero.
        connection.execute(CreateSchema(schema, if_not_exists=True))
        connection.commit()

        # Which schema alembic's own `None` stands for -- see include_name().
        global _default_schema
        _default_schema = connection.dialect.default_schema_name

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=schema,
            include_schemas=True,
            include_name=include_name,
            include_object=include_object,
        )

        # A database from the *other* profile: one alembic_version row this
        # build has no file for makes every alembic command fail before it
        # applies anything.  db/bootstrap.py has always handled that; raw
        # `alembic upgrade heads` -- what docs/self-hosting/migrations.md,
        # deploy-prod.yml and the CDK migration task run -- died with
        # "Can't locate revision identified by 'modules_0001_rbac'".  Same
        # decision, same message, whichever way alembic was launched.
        # `upgrade` only (_SKIPPABLE_COMMANDS): `downgrade` and `stamp` get
        # alembic's own error instead of exiting 0 having changed nothing.
        if not _guard_applies() or may_run_alembic(
            config, set(context.get_context().get_current_heads()), schema
        ):
            with context.begin_transaction():
                context.run_migrations()
        finished = _is_upgrade() and _is_at_head(connection)

    # Finish a profile switch.  A core-built database has the core chain
    # stamped, which marks the revisions that once created `workspaces`,
    # `sso_configs`, `phi_audit_logs` and six more as applied without creating
    # them; the modules branch owns only the three RBAC tables, so `upgrade
    # heads` alone left a full build answering `profile: full` while
    # /workspaces, /hipaa/* and /auth/sso/* all 500ed on UndefinedTable -- and
    # both revisions stamped, so nothing retried.  The models are the source of
    # truth for the schema here (see db/bootstrap.py); this runs after the
    # migrations, on its own connection, so a pending migration always gets
    # first refusal on its own DDL and nothing takes a DDL lock behind an
    # already-open connection.  It costs one reflection pass when there is
    # nothing to do, which is the normal case.  It creates *module* tables and
    # nothing else: this runs on every `upgrade heads` that reaches head, so an
    # unfiltered create_all would quietly create a core table whose migration
    # was never written, with no revision and no downgrade, and hide the drift
    # from the next --autogenerate (review round 4, finding 2).
    if finished:
        reconcile_with_models(connectable, schema)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
