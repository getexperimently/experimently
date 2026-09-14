# backend/app/core/database_config.py
"""
Dynamic schema configuration for database models.

This is **the** source of truth for "which PostgreSQL schema is this process
working on?".  Everything derives its answer from here: the models
(``__table_args__['schema']``, the string ``ForeignKey`` colspecs and the index
names they build), ``db/session.py``'s ``search_path``, ``db/bootstrap.py``,
and alembic's ``migrations/env.py`` (through
:func:`backend.app.db.schema.resolve_schema_name`, which is this function).

It used to be one of two, and they disagreed.  ``POSTGRES_SCHEMA`` was read
directly by ``migrations/env.py`` and by five revision modules, each with its
own ``"experimentation"`` default, while this function looked only at
``APP_ENV``/``TESTING``.  They agree in production and in the test suite and
part company in exactly the shell ``CONTRIBUTING.md`` documents for running anything
by hand (``export APP_ENV=test TESTING=true``, ``POSTGRES_SCHEMA`` unset):
``alembic revision --autogenerate`` then compared a metadata describing one
schema against a reflection of the other and produced a revision that created
all ~50 tables in one and ran ``op.drop_table`` on all ~50 in the other --
``users``, ``experiments``, ``feature_flags``, everything.  ``alembic upgrade
heads`` in the same shell migrated the production schema while the models
pointed at the test one.

Reading ``POSTGRES_SCHEMA`` here rather than translating the metadata
afterwards is what makes the two agree *by construction*: a translation can
move a table and rewrite a foreign key, but the index names the models spell
(``f"{get_schema_name()}_meg_status"``) are literals, frozen when the model
module was imported, and no later repoint can reach them.

Because this now decides the schema for a whole process, the test suite pins
it: ``backend/tests/conftest.py`` sets ``POSTGRES_SCHEMA=test_experimentation``
before it imports anything from ``backend.app``, so a developer shell (or
``scripts/run-backend-tests.sh``, or a CI job) that exports
``POSTGRES_SCHEMA=experimentation`` cannot point a test session at the
application schema.
"""

import logging
import os

logger = logging.getLogger(__name__)


# Add this to backend/app/core/database_config.py
def clear_schema_cache():
    """Clear the cached schema name."""
    # No-op when cache is disabled


# REMOVED @lru_cache for development to avoid caching issues with environment variables
# Re-enable in production with proper configuration management
def get_schema_name() -> str:
    """Get the schema name based on the environment.

    ``POSTGRES_SCHEMA`` wins when set: it is how a deployment, the ECS
    migration task, ``docker-compose``, ``scripts/core_build.sh``'s scratch
    schema and the test conftest all name the schema explicitly, and how every
    alembic revision module names it.  With it unset the name is derived from
    ``APP_ENV``/``TESTING``, as it always was.
    """
    explicit = os.environ.get("POSTGRES_SCHEMA")
    if explicit:
        return explicit

    # Check for truthy values, not just specific strings
    app_env = os.environ.get("APP_ENV", "")
    testing = os.environ.get("TESTING", "")

    # Only use test schema if explicitly set to test values
    if app_env == "test" or testing == "true":
        schema_name = "test_experimentation"
    else:
        schema_name = "experimentation"

    # Log only first time to avoid spam (use a module-level flag)
    if not hasattr(get_schema_name, "_logged"):
        logger.info(
            f"Using schema: {schema_name} (APP_ENV={app_env!r}, TESTING={testing!r})"
        )
        get_schema_name._logged = True

    return schema_name
