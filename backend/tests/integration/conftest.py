"""
Integration test fixtures for EP-011.

These fixtures extend the root conftest.py fixtures with
integration-specific helpers: additional user roles, factory
functions for creating test data, and role-specific API clients.
"""
import os
import pytest
import uuid
from typing import Callable, Optional
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from backend.app.main import app
from backend.app.api import deps
from backend.app.api.deps import CacheControl
from backend.app.models.user import User, UserRole
from backend.app.models.experiment import (
    Experiment, ExperimentStatus, ExperimentType, Variant, Metric, MetricType
)
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.event import Event
from backend.app.models.assignment import Assignment

DEFAULT_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/experimentation_test"

HASHED_PASSWORD = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"
DEFAULT_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/experimentation_test"


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Create an admin user for integration tests.

    Uses commit() so the user row is visible to the separate per-request
    DB sessions created by make_client_for_user (NullPool = new connection
    per request, which cannot see uncommitted rows from db_session).
    """
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"admin_int_{suffix}",
        email=f"admin_{suffix}@int.test",
        full_name="Admin Integration User",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=True,
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def developer_user(db_session: Session) -> User:
    """Create a developer user for integration tests."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"dev_int_{suffix}",
        email=f"dev_{suffix}@int.test",
        full_name="Developer Integration User",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def analyst_user(db_session: Session) -> User:
    """Create an analyst user for integration tests."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"analyst_int_{suffix}",
        email=f"analyst_{suffix}@int.test",
        full_name="Analyst Integration User",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=UserRole.ANALYST,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def viewer_user(db_session: Session) -> User:
    """Create a viewer user for integration tests."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"viewer_int_{suffix}",
        email=f"viewer_{suffix}@int.test",
        full_name="Viewer Integration User",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=UserRole.VIEWER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Factory fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_experiment(db_session: Session, admin_user: User) -> Callable:
    """
    Factory fixture for creating Experiment objects.

    Returns a callable that creates and commits an Experiment to db_session.
    Default fields can be overridden via kwargs.
    """
    def _make_experiment(**kwargs) -> Experiment:
        defaults = {
            "name": "Test Experiment",
            "status": ExperimentStatus.DRAFT,
            "owner_id": admin_user.id,
            "description": "Integration test experiment",
            "hypothesis": "Integration hypothesis",
        }
        defaults.update(kwargs)
        experiment = Experiment(**defaults)
        db_session.add(experiment)
        db_session.commit()
        db_session.refresh(experiment)
        return experiment

    return _make_experiment


@pytest.fixture
def make_variant(db_session: Session) -> Callable:
    """
    Factory fixture for creating Variant objects.

    Returns a callable that creates and commits a Variant to db_session.
    """
    def _make_variant(
        experiment: Experiment,
        name: str = "Control",
        is_control: bool = True,
        traffic_allocation: float = 50.0,
        **kwargs,
    ) -> Variant:
        variant = Variant(
            experiment_id=experiment.id,
            name=name,
            is_control=is_control,
            traffic_allocation=traffic_allocation,
            **kwargs,
        )
        db_session.add(variant)
        db_session.commit()
        db_session.refresh(variant)
        return variant

    return _make_variant


@pytest.fixture
def make_metric(db_session: Session) -> Callable:
    """
    Factory fixture for creating Metric objects.

    Returns a callable that creates and commits a Metric to db_session.
    """
    def _make_metric(
        experiment: Experiment,
        name: str = "Conversion",
        event_name: str = "purchase",
        metric_type=MetricType.CONVERSION,
        **kwargs,
    ) -> Metric:
        metric = Metric(
            experiment_id=experiment.id,
            name=name,
            event_name=event_name,
            metric_type=metric_type,
            **kwargs,
        )
        db_session.add(metric)
        db_session.commit()
        db_session.refresh(metric)
        return metric

    return _make_metric


@pytest.fixture
def make_feature_flag(db_session: Session, admin_user: User) -> Callable:
    """
    Factory fixture for creating FeatureFlag objects.

    Returns a callable that creates and commits a FeatureFlag to db_session.
    Default fields can be overridden via kwargs.
    """
    def _make_feature_flag(**kwargs) -> FeatureFlag:
        defaults = {
            "key": f"flag-{uuid.uuid4().hex[:8]}",
            "name": "Test Flag",
            "status": FeatureFlagStatus.INACTIVE,
            "owner_id": admin_user.id,
            "rollout_percentage": 0,
        }
        defaults.update(kwargs)
        flag = FeatureFlag(**defaults)
        db_session.add(flag)
        db_session.commit()
        db_session.refresh(flag)
        return flag

    return _make_feature_flag


@pytest.fixture
def make_event(db_session: Session) -> Callable:
    """
    Factory fixture for creating Event objects.

    Returns a callable that creates and commits an Event to db_session.
    """
    def _make_event(**kwargs) -> Event:
        defaults = {
            "event_type": "track",
            "event_name": "purchase",
            "user_id": "user-123",
            "value": 1.0,
        }
        defaults.update(kwargs)
        # created_at is required by the Event model (non-nullable string column)
        if "created_at" not in defaults:
            from datetime import datetime, timezone
            defaults["created_at"] = datetime.now(timezone.utc).isoformat()
        event = Event(**defaults)
        db_session.add(event)
        db_session.commit()
        db_session.refresh(event)
        return event

    return _make_event


@pytest.fixture
def make_assignment(db_session: Session) -> Callable:
    """
    Factory fixture for creating Assignment objects.

    Returns a callable that creates and commits an Assignment to db_session.
    """
    def _make_assignment(
        experiment: Experiment,
        variant: Variant,
        user_id: str,
        **kwargs,
    ) -> Assignment:
        assignment = Assignment(
            experiment_id=experiment.id,
            variant_id=variant.id,
            user_id=user_id,
            **kwargs,
        )
        db_session.add(assignment)
        db_session.commit()
        db_session.refresh(assignment)
        return assignment

    return _make_assignment


# ---------------------------------------------------------------------------
# Helper: make_client_for_user
# ---------------------------------------------------------------------------

def make_client_for_user(db_session: Session, user: User) -> TestClient:
    """Create a TestClient authenticated as the given user.

    Each API request gets its own short-lived SQLAlchemy session from the test
    engine.  Using a fresh session per request (rather than the test fixture's
    db_session) prevents state corruption that occurs when the same session is
    shared between the test setup code (which commits via db_session.commit())
    and the endpoint handler (which also commits and then refreshes ORM objects).
    With NullPool, every commit() closes the underlying DBAPI connection; a
    shared session that has been committed many times can end up with expired
    objects that can no longer be refreshed, producing
    "Could not refresh instance" errors.
    """
    # Build a sessionmaker that shares the same NullPool engine as the test DB.
    # We need the engine, not just the session, so we read it from db_session's bind.
    _engine = db_session.get_bind()
    _SessionFactory = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

    def override_get_db():
        """Yield a fresh session per API request."""
        session = _SessionFactory()
        session.execute(text("SET search_path TO test_experimentation"))
        try:
            yield session
        finally:
            try:
                session.close()
            except Exception:
                pass

    async def override_get_current_user():
        return user

    def override_get_current_active_user():
        return user

    def override_get_current_superuser():
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return user

    async def override_get_cache_control():
        return CacheControl(enabled=False, skip=True)

    def override_get_api_key():
        return user

    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user] = override_get_current_user
    app.dependency_overrides[deps.get_current_active_user] = override_get_current_active_user
    app.dependency_overrides[deps.get_current_superuser] = override_get_current_superuser
    app.dependency_overrides[deps.get_cache_control] = override_get_cache_control
    app.dependency_overrides[deps.get_api_key] = override_get_api_key

    return TestClient(app)


# ---------------------------------------------------------------------------
# API client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_client(db_session: Session, admin_user: User, monkeypatch) -> TestClient:
    """Create a TestClient authenticated as the admin_user."""
    test_client = make_client_for_user(db_session, admin_user)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def developer_client(db_session: Session, developer_user: User, monkeypatch) -> TestClient:
    """Create a TestClient authenticated as the developer_user."""
    test_client = make_client_for_user(db_session, developer_user)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def analyst_client(db_session: Session, analyst_user: User, monkeypatch) -> TestClient:
    """Create a TestClient authenticated as the analyst_user."""
    test_client = make_client_for_user(db_session, analyst_user)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def viewer_client(db_session: Session, viewer_user: User, monkeypatch) -> TestClient:
    """Create a TestClient authenticated as the viewer_user."""
    test_client = make_client_for_user(db_session, viewer_user)
    yield test_client
    app.dependency_overrides.clear()
