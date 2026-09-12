# Add to env.py
import os
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

# Import your models.  Open-core seam: register the Community models, then let
# the Enterprise package register its own through hooks.register_model_module().
# Autogenerate therefore sees exactly the tables the running edition owns — a
# Community build must not generate migrations that create Enterprise tables.
from backend.app.ee_loader import require_enterprise_or_absent
from backend.app.models import register_core_models

Base = register_core_models()
# Strict on purpose: if Enterprise code is present but fails to register,
# target_metadata would hold only the Community tables and autogenerate would
# propose dropping every Enterprise table. Better to refuse than to be quiet.
require_enterprise_or_absent()

# Set target_metadata to your SQLAlchemy models
target_metadata = Base.metadata

# Keep the Enterprise-managed constraints out of this chain's autogenerate
# (see backend/app/db/autogenerate_filters.py for the reasoning).
from backend.app.db.autogenerate_filters import include_object  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Get schema from environment variable
schema = os.environ.get("POSTGRES_SCHEMA", "experimentation")
db_name = os.environ.get("POSTGRES_DB", "experimentation")

# Build sqlalchemy.url from the same POSTGRES_* variables the application,
# the test suite and the CI workflows use.
_db_user = os.environ.get("POSTGRES_USER", "postgres")
_db_password = os.environ.get("POSTGRES_PASSWORD", "postgres")
_db_host = os.environ.get("POSTGRES_SERVER") or os.environ.get("POSTGRES_HOST") or "localhost"
_db_port = os.environ.get("POSTGRES_PORT", "5432")
postgres_url = f"postgresql://{_db_user}:{_db_password}@{_db_host}:{_db_port}/{db_name}"
config.set_main_option("sqlalchemy.url", postgres_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

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
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


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

    with connectable.connect() as connection:
        # Migrations (and the alembic_version table) live inside `schema`;
        # create it on a fresh database so `upgrade head` works from zero.
        connection.execute(CreateSchema(schema, if_not_exists=True))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=schema,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
