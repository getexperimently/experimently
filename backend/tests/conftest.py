# conftest.py
"""
Test configuration for the experimentation platform.

This module sets up fixtures and configuration for pytest.
"""
import pytest
import os
import logging
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy import event as sa_event
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.orm import configure_mappers
from sqlalchemy.pool import NullPool

from backend.app.main import app
from backend.app.db.session import get_db, Base, init_db
from backend.app.api import deps
from backend.app.models.user import User, UserRole
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.core.database_config import get_schema_name
from backend.app.core.config import settings, TestSettings
from backend.app.models.base import set_schema
from backend.app.api.deps import CacheControl
from unittest.mock import patch, MagicMock, AsyncMock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-process database name
# ---------------------------------------------------------------------------
# Each pytest process gets its own database named
# "experimentation_test_<pid>".  This prevents concurrent test sessions from
# sharing-and trampling-each other's database (each session runs
# DROP DATABASE + CREATE DATABASE in its test_db fixture setup/teardown).
_PID = os.getpid()
_TEST_DB_NAME = f"experimentation_test_{_PID}"
_BASE_DB_URL = "postgresql://postgres:postgres@localhost:5432"
DEFAULT_TEST_DB_URL = f"{_BASE_DB_URL}/{_TEST_DB_NAME}"


@pytest.fixture(scope="session", autouse=True)
def configure_all_mappers():
    """Configure all mappers before any tests run."""
    configure_mappers()


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up the test environment before any tests run."""
    # Set environment variables for testing
    os.environ["APP_ENV"] = "test"
    os.environ["TESTING"] = "true"
    os.environ["POSTGRES_DB"] = _TEST_DB_NAME
    os.environ["POSTGRES_SCHEMA"] = "test_experimentation"
    os.environ["POSTGRES_SERVER"] = "localhost"
    os.environ["DATABASE_URI"] = DEFAULT_TEST_DB_URL

    # Initialize test settings
    global settings
    settings = TestSettings()

    # Set schema for all tables
    set_schema()

    yield

    # Clean up
    os.environ.pop("APP_ENV", None)
    os.environ.pop("TESTING", None)
    os.environ.pop("POSTGRES_DB", None)
    os.environ.pop("POSTGRES_SCHEMA", None)
    os.environ.pop("POSTGRES_SERVER", None)
    os.environ.pop("DATABASE_URI", None)


@pytest.fixture(scope="session")
def test_db():
    """Create a per-process test database and schema.

    Using a PID-unique database name (experimentation_test_<pid>) means
    concurrent pytest processes never share or drop each other's database.

    The production engine (session.py) uses a QueuePool(pool_size=20) that
    is created at module-import time.  We dispose it here so that its idle
    connections are closed before pg_terminate_backend() runs in the setup
    block.  Without disposal, those pool connections are killed by
    pg_terminate_backend() and then the pool tries to roll them back on
    return, generating 'server closed the connection unexpectedly' tracebacks
    that cascade through subsequent NullPool checkouts.
    """
    # Dispose the production engine pool to prevent interference.
    try:
        from backend.app.db.session import engine as _prod_engine
        _prod_engine.dispose()
        logger.info("Disposed production engine pool before test_db setup")
    except Exception as _e:
        logger.warning("Could not dispose production engine: %s", _e)

    db_url = DEFAULT_TEST_DB_URL
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            # Use a raw psycopg2 connection with autocommit=True for all
            # database-level DDL (DROP DATABASE / CREATE DATABASE).
            # These statements cannot run inside a transaction block in
            # PostgreSQL, so we must use autocommit mode.
            import psycopg2
            from urllib.parse import urlparse

            parsed = urlparse(db_url)
            admin_conn = psycopg2.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                user=parsed.username,
                password=parsed.password,
                dbname="postgres",
            )
            admin_conn.autocommit = True
            admin_cur = admin_conn.cursor()

            # Kill any existing connections to this process's test database
            # so that DROP DATABASE does not fail with "other users are
            # connected".  This is a no-op when the DB does not exist yet.
            admin_cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s
                  AND pid <> pg_backend_pid()
                """,
                (_TEST_DB_NAME,),
            )

            # Drop and recreate the test database.
            admin_cur.execute(f"DROP DATABASE IF EXISTS {_TEST_DB_NAME}")
            admin_cur.execute(f"CREATE DATABASE {_TEST_DB_NAME}")

            admin_cur.close()
            admin_conn.close()

            # Create engine for test database.
            # NullPool ensures each db_session.connect() gets a brand-new
            # DBAPI connection that is closed (never returned to a pool)
            # when session.close() is called.
            engine = create_engine(db_url, poolclass=NullPool)

            # Register a session-scoped "connect" event so that every new
            # DBAPI connection automatically has search_path set to the test
            # schema.  This fires once per connection checkout (every
            # statement with NullPool).
            @sa_event.listens_for(engine, "connect")
            def set_schema_search_path(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("SET search_path TO test_experimentation")
                cursor.close()

            # Test the connection to the new database
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            # Initialize database with schema and tables
            os.environ["DATABASE_URI"] = db_url
            os.environ["APP_ENV"] = "test"
            os.environ["TESTING"] = "true"

            schema_name = "test_experimentation"

            # Create schema and tables
            with engine.connect() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
                conn.execute(text(f"CREATE SCHEMA {schema_name}"))
                conn.execute(text(f"SET search_path TO {schema_name}"))
                conn.execute(text("COMMIT"))

                # Import ALL models to ensure they are registered with the
                # metadata before create_all runs.  Missing imports cause
                # create_all to fail, which triggers the retry loop.
                import backend.app.models.user  # noqa: F401
                import backend.app.models.experiment  # noqa: F401
                import backend.app.models.feature_flag  # noqa: F401
                import backend.app.models.event  # noqa: F401
                import backend.app.models.assignment  # noqa: F401
                import backend.app.models.safety  # noqa: F401
                import backend.app.models.audit_log  # noqa: F401
                import backend.app.models.segment  # noqa: F401
                import backend.app.models.rollout_schedule  # noqa: F401
                import backend.app.models.report  # noqa: F401
                import backend.app.models.api_key  # noqa: F401
                import backend.app.models.scheduler_run  # noqa: F401
                import backend.app.models.custom_role  # noqa: F401

                # Set schema for all tables
                Base.metadata.schema = schema_name

                # Make sure all tables use the correct schema
                for table in Base.metadata.tables.values():
                    table.schema = schema_name

                # Create tables
                Base.metadata.create_all(bind=engine)

            # If we get here, the database is ready
            break

        except Exception as e:
            retry_count += 1
            logger.error(f"Attempt {retry_count} failed to set up test database: {e}")
            if retry_count == max_retries:
                pytest.fail(
                    f"Failed to set up test database after {max_retries} attempts: {e}"
                )
            import time
            time.sleep(2)  # Wait before retrying

    yield engine

    # Teardown: drop the per-process test database.
    try:
        import psycopg2
        from urllib.parse import urlparse

        parsed = urlparse(db_url)
        cleanup_conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            dbname="postgres",
        )
        cleanup_conn.autocommit = True
        cleanup_cur = cleanup_conn.cursor()

        cleanup_cur.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s
              AND pid <> pg_backend_pid()
            """,
            (_TEST_DB_NAME,),
        )
        cleanup_cur.execute(f"DROP DATABASE IF EXISTS {_TEST_DB_NAME}")
        cleanup_cur.close()
        cleanup_conn.close()

    except Exception as e:
        logger.error(f"Error during test database cleanup: {e}")
        # Don't fail the tests if cleanup fails


@pytest.fixture(scope="function")
def db_session(test_db):
    """Create a fresh database session for a test.

    The session is bound directly to the NullPool engine so that after each
    commit() the session acquires a fresh DBAPI connection on its next DML.

    expire_on_commit=False prevents SQLAlchemy from expiring all loaded
    objects after a commit().  Without this, attributes like
    user.is_superuser trigger a reload SELECT on the next access, which
    opens a new NullPool connection that may fail if the prior commit
    already closed the underlying DBAPI connection.

    We do NOT truncate tables in teardown.  TRUNCATE TABLE ... CASCADE holds
    AccessExclusiveLock on every table in the cascade set.  When pytest
    runs the teardown of one function-scoped fixture while setting up the
    next (which can happen when asyncio test fixtures overlap in the event
    loop), the TRUNCATE and the new test's INSERT deadlock against each
    other.  Since all test data uses UUID primary keys and unique per-test
    suffixes, there is no data contamination between tests.  The entire
    database is dropped and recreated at the start of every pytest session
    (in test_db), so accumulated rows are discarded after each full run.
    """
    Session = sessionmaker(
        bind=test_db,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,  # prevent reload SELECTs after commit()
    )
    session = Session()

    # Set schema search path for the initial connection.
    # The engine-level "connect" event (registered in test_db) re-applies
    # search_path on every new NullPool connection checkout automatically.
    session.execute(text("SET search_path TO test_experimentation"))

    try:
        yield session
    finally:
        # Rollback any uncommitted work left by the test.
        try:
            session.rollback()
        except Exception:
            pass

        try:
            session.close()
        except Exception:
            pass


@pytest.fixture
def client(db_session, monkeypatch):
    """Create a test client for the FastAPI application."""
    # Override the get_db dependency
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    # Mock Cognito auth service
    def mock_get_user_with_groups(*args, **kwargs):
        return {
            "username": "test_user",
            "attributes": {"email": "test@example.com"},
            "groups": ["admin-group"]
        }

    monkeypatch.setattr(
        "backend.app.services.auth_service.CognitoAuthService.get_user_with_groups",
        mock_get_user_with_groups
    )

    # Mock security token decoder
    def mock_decode_token(*args, **kwargs):
        return {
            "sub": "test_user_id",
            "username": "test_user",
            "email": "test@example.com"
        }

    monkeypatch.setattr(
        "backend.app.core.security.decode_token",
        mock_decode_token
    )

    # Create a superuser for authentication
    user = User(
        username="test_user",
        email="test@example.com",
        full_name="Test User",
        hashed_password="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        is_active=True,
        is_superuser=True,
        role=UserRole.ADMIN
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # Create both sync and async return functions for user
    async def override_get_current_user():
        """Override get_current_user to return a test user."""
        return user

    def override_get_current_active_user():
        """Override get_current_active_user to return a test user."""
        return user

    def override_get_current_superuser():
        """Override get_current_superuser to return a superuser."""
        return user

    async def override_get_cache_control():
        """Override cache control to disable caching in tests."""
        return CacheControl(enabled=False, skip=True)

    def override_get_api_key():
        """Override API key authentication to return a test user."""
        return user

    # Set up dependency overrides
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user] = override_get_current_user
    app.dependency_overrides[deps.get_current_active_user] = override_get_current_active_user
    app.dependency_overrides[deps.get_current_superuser] = override_get_current_superuser
    app.dependency_overrides[deps.get_cache_control] = override_get_cache_control
    app.dependency_overrides[deps.get_api_key] = override_get_api_key

    # Create test client
    test_client = TestClient(app)

    yield test_client

    # Clean up
    app.dependency_overrides.clear()


@pytest.fixture
def normal_user(db_session):
    """Create a normal user for testing."""
    user = User(
        username="testuser",
        email="testuser@example.com",
        full_name="Test User",
        hashed_password="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def superuser(db_session):
    """Create a superuser for testing."""
    user = User(
        username="admin",
        email="admin@example.com",
        full_name="Admin User",
        hashed_password="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        is_active=True,
        is_superuser=True,
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def mock_auth(normal_user, monkeypatch):
    """Mock the authentication dependencies."""
    async def override_get_current_user():
        return normal_user

    def override_get_current_active_user():
        return normal_user

    # Mock Cognito auth service
    def mock_get_user_with_groups(*args, **kwargs):
        return {
            "username": normal_user.username,
            "attributes": {"email": normal_user.email},
            "groups": ["developer-group"]
        }

    monkeypatch.setattr(
        "backend.app.services.auth_service.CognitoAuthService.get_user_with_groups",
        mock_get_user_with_groups
    )

    # Mock security token decoder
    def mock_decode_token(*args, **kwargs):
        return {
            "sub": str(normal_user.id),
            "username": normal_user.username,
            "email": normal_user.email
        }

    monkeypatch.setattr(
        "backend.app.core.security.decode_token",
        mock_decode_token
    )

    app.dependency_overrides[deps.get_current_user] = override_get_current_user
    app.dependency_overrides[deps.get_current_active_user] = override_get_current_active_user

    yield

    app.dependency_overrides.pop(deps.get_current_user, None)
    app.dependency_overrides.pop(deps.get_current_active_user, None)


@pytest.fixture
def mock_auth_superuser(superuser, monkeypatch):
    """Mock the authentication dependencies to return a superuser."""
    async def override_get_current_user():
        return superuser

    def override_get_current_active_user():
        return superuser

    def override_get_current_superuser():
        return superuser

    # Mock Cognito auth service
    def mock_get_user_with_groups(*args, **kwargs):
        return {
            "username": superuser.username,
            "attributes": {"email": superuser.email},
            "groups": ["admin-group"]
        }

    monkeypatch.setattr(
        "backend.app.services.auth_service.CognitoAuthService.get_user_with_groups",
        mock_get_user_with_groups
    )

    # Mock security token decoder
    def mock_decode_token(*args, **kwargs):
        return {
            "sub": str(superuser.id),
            "username": superuser.username,
            "email": superuser.email
        }

    monkeypatch.setattr(
        "backend.app.core.security.decode_token",
        mock_decode_token
    )

    # Set up dependency overrides
    app.dependency_overrides[deps.get_current_user] = override_get_current_user
    app.dependency_overrides[deps.get_current_active_user] = override_get_current_active_user
    app.dependency_overrides[deps.get_current_superuser] = override_get_current_superuser

    yield

    # Clean up dependency overrides
    app.dependency_overrides.pop(deps.get_current_user, None)
    app.dependency_overrides.pop(deps.get_current_active_user, None)
    app.dependency_overrides.pop(deps.get_current_superuser, None)


@pytest.fixture
def test_experiment(db_session, normal_user):
    """Create a test experiment for testing."""
    experiment = Experiment(
        name="Test Experiment",
        description="A test experiment",
        hypothesis="Test hypothesis",
        owner_id=normal_user.id,
        status=ExperimentStatus.DRAFT.value,
    )
    db_session.add(experiment)
    db_session.commit()
    db_session.refresh(experiment)
    return experiment


@pytest.fixture
def active_experiment(db_session, normal_user):
    """Create an active test experiment for testing."""
    experiment = Experiment(
        name="Active Experiment",
        description="An active test experiment",
        experiment_type="a_b",
        status=ExperimentStatus.ACTIVE,
        owner_id=normal_user.id,
    )
    db_session.add(experiment)
    db_session.commit()
    db_session.refresh(experiment)
    return experiment


@pytest.fixture
def mock_api_key(monkeypatch):
    """Mock the API key dependency."""
    user = User(
        username="api_user",
        email="api@example.com",
        full_name="API User",
        hashed_password="$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )

    def override_get_api_key(**kwargs):
        return user

    # Set up dependency override
    app.dependency_overrides[deps.get_api_key] = override_get_api_key

    yield

    # Clean up dependency override
    app.dependency_overrides.pop(deps.get_api_key, None)
