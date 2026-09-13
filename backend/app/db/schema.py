"""Which PostgreSQL schema is this process working on?

One answer, for every tool that builds or migrates a schema.  Before this
module there were two, and they disagreed:

* ``core.database_config.get_schema_name()`` -- what every **model** declares
  as its ``__table_args__['schema']``.  It reads ``APP_ENV``/``TESTING`` and
  nothing else: ``test_experimentation`` under the test environment,
  ``experimentation`` otherwise.
* ``os.environ.get("POSTGRES_SCHEMA", "experimentation")`` -- what alembic's
  ``migrations/env.py`` reflected and what five revision modules interpolate
  into the names they build, each with its own copy of the literal default.

They agree in production (``POSTGRES_SCHEMA=experimentation``, ``APP_ENV=prod``)
and in the test suite (``conftest.py`` sets both), and they disagreed in exactly
the shell ``CLAUDE.md`` documents for running anything by hand::

    export APP_ENV=test TESTING=true      # POSTGRES_SCHEMA left unset

There ``get_schema_name()`` said ``test_experimentation`` while env.py said
``experimentation``.  ``alembic revision --autogenerate`` then compared a
metadata describing one schema against a reflection of the *other* and
generated a revision that creates all ~50 tables in ``test_experimentation``
and **drops all ~50 from ``experimentation``** -- ``users``, ``experiments``,
``feature_flags``, the lot.  ``alembic upgrade heads`` in the same shell
migrated the production schema while the models pointed at the test one.

The repair is one resolution that everything applies:

1. :func:`resolve_schema_name` *is*
   ``core.database_config.get_schema_name()``, which now reads
   ``POSTGRES_SCHEMA`` first.  One function, so the models, the bootstrap and
   alembic cannot answer differently.  It has to be that function rather than a
   wrapper around it, because the models bake their answer into literals --
   index names such as ``f"{get_schema_name()}_meg_status"`` -- that no later
   translation can reach.
2. :func:`export_schema_name` publishes the answer back into
   ``POSTGRES_SCHEMA``, so the revision modules that read it at *import* time
   (``a7b8c9d0e1f2``, ``ep057_workspaces``, ``modules_0001_rbac``, ...) and
   their ``"experimentation"`` defaults can no longer be a second opinion.
3. :func:`metadata_for_schema` and :func:`point_metadata_at` aim an
   *already-imported* metadata at a schema chosen later -- which is the one
   case (1) cannot cover: ``bootstrap.bootstrap(engine, schema="scratch_1234")``
   called in-process, from a test whose models were imported under a different
   schema.

``backend/tests/unit/db/test_schema_name.py`` pins all of it, and
``backend/tests/integration/database/test_autogenerate_is_empty.py`` checks the
property that matters: a freshly bootstrapped database has nothing left to
autogenerate.
"""

from __future__ import annotations

import os
from typing import Any

#: The environment variable that names the schema explicitly.
SCHEMA_ENV_VAR = "POSTGRES_SCHEMA"


def resolve_schema_name() -> str:
    """The schema this process works on.

    Deliberately nothing but a call to
    :func:`backend.app.core.database_config.get_schema_name` -- the function
    the *models* answer with.  If this had a rule of its own, that rule would
    be the second opinion all over again; the whole point is that there is one
    function and every caller asks it.
    """
    # Imported lazily: this module is imported by alembic's env.py, which runs
    # before anything else has necessarily imported the application.
    from backend.app.core.database_config import get_schema_name

    return get_schema_name()


def export_schema_name(schema: str | None = None) -> str:
    """Resolve the schema and publish it in ``POSTGRES_SCHEMA``; return it.

    Every alembic revision module that needs the schema name reads the
    environment variable when alembic *imports* it, so the variable has to
    carry the resolved answer before a script directory is walked -- not just
    before a migration runs.  ``db/bootstrap.py`` does the same thing with
    :func:`~backend.app.db.bootstrap.alembic_sees_schema` (which restores the
    previous value on the way out, because it may run in-process).
    """
    schema = schema or resolve_schema_name()
    os.environ[SCHEMA_ENV_VAR] = schema
    return schema


def point_metadata_at(base: Any, schema: str) -> None:
    """Point ``base.metadata`` and every table it holds at *schema*, in place.

    What ``db/bootstrap.py`` does before ``create_all``: the models bind their
    schema at import time from ``core.database_config.get_schema_name()``, and
    this moves an already-imported metadata onto the schema
    :func:`resolve_schema_name` chose.

    The edit is deliberately shallow -- ``metadata.tables`` keeps its original
    ``"<old schema>.<table>"`` keys, and so do the string ``ForeignKey``
    colspecs the models spell (``f"{get_schema_name()}.users.id"``).  That is
    *why* it works for DDL: the colspec still resolves through the unchanged
    key to a ``Table`` object whose ``.schema`` is now the new one, so
    ``create_all`` emits ``REFERENCES <new schema>.users``.  It is also why it
    is no good for **autogenerate**, which indexes the metadata by
    ``Table.key`` and looks it up by ``Table.schema``; use
    :func:`metadata_for_schema` there.

    A process-wide edit, like ``models.base.set_schema()``: callers that are
    not one-shot tools restore what they found (see
    ``backend/tests/integration/database/test_profile_migrations.py``'s
    ``_keep_the_models_pointed_where_they_were``).
    """
    base.metadata.schema = schema
    for table in base.metadata.tables.values():
        table.schema = schema


def metadata_for_schema(base: Any, schema: str) -> Any:
    """``base.metadata`` as it would read if the models declared *schema*.

    Returns ``base.metadata`` itself when it already names *schema* (the usual
    case: a deployment where ``POSTGRES_SCHEMA`` and ``APP_ENV`` agree), and
    otherwise a **copy** built with ``Table.to_metadata(..., schema=...)`` --
    SQLAlchemy's supported schema translation, which rewrites each table's
    ``key`` and each foreign key's colspec instead of leaving them pointing at
    the old schema.

    This is what ``migrations/env.py`` hands to alembic as ``target_metadata``.
    Autogenerate needs the *consistent* form: it builds its index from
    ``Table.key`` (frozen when the table was constructed) and looks tables up
    by ``Table.schema``, so the shallow repoint :func:`point_metadata_at` does
    makes it raise ``KeyError: '<old schema>.<table>'`` mid-comparison.

    A copy, not an edit, so that nothing else in the process sees a metadata
    pointed somewhere it did not ask for -- ``env.py`` runs inside the test
    suite's own interpreter in several tests.
    """
    from sqlalchemy import MetaData

    metadata = base.metadata
    if metadata.schema == schema and all(
        table.schema == schema for table in metadata.tables.values()
    ):
        return metadata

    translated = MetaData(schema=schema)
    for table in metadata.tables.values():
        table.to_metadata(translated, schema=schema)
    return translated
