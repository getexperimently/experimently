"""
Integration tests for the OpenFeature flag listing (EP-044).

  GET  /api/v1/openfeature/flags         — deprecated, behaviour unchanged

POST /api/v1/openfeature/evaluate and /bulk-evaluate were removed (#241);
``TestRemovedEvaluateRoutes`` pins that they answer 404, and
``backend/tests/smoke/test_openfeature_routes.py`` pins the exact route set.

Tests use dependency_overrides to bypass database and authentication, making
them fast unit-style tests that validate the HTTP layer and business logic
without requiring a live PostgreSQL server.

Pattern adapted from test_feature_flags.py and test_split_url_api.py.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.user import User, UserRole

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HASHED_PASSWORD = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"
ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_user(
    user_id: uuid.UUID = ADMIN_USER_ID,
    role: UserRole = UserRole.ADMIN,
    is_superuser: bool = True,
) -> User:
    """Return an in-memory User object (not persisted to DB)."""
    user = MagicMock(spec=User)
    user.id = user_id
    user.username = f"user_{user_id.hex[:8]}"
    user.email = f"user_{user_id.hex[:8]}@test.com"
    user.is_active = True
    user.is_superuser = is_superuser
    user.role = role
    user.hashed_password = HASHED_PASSWORD
    return user


def _make_feature_flag(
    key: str = "test-flag",
    enabled: bool = True,
    rollout_percentage: float = 100.0,
    variants: Optional[List[Dict]] = None,
    owner_id: uuid.UUID = ADMIN_USER_ID,
    status: FeatureFlagStatus = FeatureFlagStatus.ACTIVE,
) -> MagicMock:
    """Return a mock FeatureFlag SQLAlchemy model instance."""
    flag = MagicMock(spec=FeatureFlag)
    flag.id = uuid.uuid4()
    flag.key = key
    flag.name = f"Flag {key}"
    flag.enabled = enabled
    flag.status = status
    flag.rollout_percentage = rollout_percentage
    flag.variants = variants or []
    flag.targeting_rules = []
    flag.owner_id = owner_id
    return flag


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """TestClient with a clean dependency override context."""
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def clear_overrides():
    """Ensure dependency overrides are cleaned up after each test."""
    yield
    app.dependency_overrides.clear()


def _override_get_db(query_results: List[MagicMock]):
    """Build a get_db override whose .query().all() returns `query_results`."""
    db = MagicMock()
    query_mock = MagicMock()
    query_mock.all.return_value = query_results
    query_mock.filter.return_value = query_mock
    query_mock.first.return_value = query_results[0] if query_results else None
    db.query.return_value = query_mock
    return db


def _setup_overrides(
    user: User,
    flags: List[MagicMock],
    first_flag: Optional[MagicMock] = None,
) -> None:
    """Install dependency overrides for db and api_key_user."""
    db = MagicMock()
    query_mock = MagicMock()
    query_mock.all.return_value = flags
    query_mock.filter.return_value = query_mock
    query_mock.first.return_value = (
        first_flag if first_flag is not None else (flags[0] if flags else None)
    )
    db.query.return_value = query_mock

    app.dependency_overrides[deps.get_db] = lambda: db
    app.dependency_overrides[deps.get_api_key] = lambda: user


# ---------------------------------------------------------------------------
# GET /api/v1/openfeature/flags
# ---------------------------------------------------------------------------


class TestGetOpenFeatureFlags:
    """Tests for GET /api/v1/openfeature/flags."""

    def test_returns_200_with_flags_list(self, client):
        """Returns 200 and a list of flag definitions for an API key."""
        flag = _make_feature_flag("dark-mode", enabled=True, rollout_percentage=100.0)
        user = _make_user()
        _setup_overrides(user, [flag])

        response = client.get(
            "/api/v1/openfeature/flags",
            headers={"X-API-Key": "test-key"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "flags" in data
        assert isinstance(data["flags"], list)
        assert len(data["flags"]) == 1

    def test_flag_definition_has_required_fields(self, client):
        """Each flag definition contains key, enabled, rollout_percentage."""
        flag = _make_feature_flag(
            "checkout-exp",
            enabled=True,
            rollout_percentage=75.0,
        )
        user = _make_user()
        _setup_overrides(user, [flag])

        response = client.get("/api/v1/openfeature/flags", headers={"X-API-Key": "k"})
        assert response.status_code == 200
        flag_def = response.json()["flags"][0]
        assert flag_def["key"] == "checkout-exp"
        assert flag_def["enabled"] is True
        assert flag_def["rollout_percentage"] == 75.0

    def test_empty_flag_list_returns_200_with_empty_array(self, client):
        """When no flags exist the response has an empty flags array."""
        user = _make_user()
        _setup_overrides(user, [])

        response = client.get("/api/v1/openfeature/flags", headers={"X-API-Key": "k"})
        assert response.status_code == 200
        assert response.json()["flags"] == []

    def test_multiple_flags_returned(self, client):
        """Multiple flags are all included in the response."""
        flags = [
            _make_feature_flag("flag-a", enabled=True),
            _make_feature_flag("flag-b", enabled=False),
            _make_feature_flag("flag-c", enabled=True, rollout_percentage=50.0),
        ]
        user = _make_user()
        _setup_overrides(user, flags)

        response = client.get("/api/v1/openfeature/flags", headers={"X-API-Key": "k"})
        assert response.status_code == 200
        assert len(response.json()["flags"]) == 3

    def test_flag_with_variants_includes_variant_list(self, client):
        """Flags with variants include the variants array in the response."""
        variants = [
            {"key": "control", "weight": 0.5, "value": "A"},
            {"key": "treatment", "weight": 0.5, "value": "B"},
        ]
        flag = _make_feature_flag("ab-test", variants=variants)
        user = _make_user()
        _setup_overrides(user, [flag])

        response = client.get("/api/v1/openfeature/flags", headers={"X-API-Key": "k"})
        assert response.status_code == 200
        flag_def = response.json()["flags"][0]
        assert "variants" in flag_def
        assert len(flag_def["variants"]) == 2

    def test_missing_api_key_returns_401(self, client):
        """Requests without X-API-Key header should return 401."""
        # Override get_api_key to simulate the key being missing.
        from fastapi import HTTPException
        from fastapi import status as http_status

        def raise_401():
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="API key missing",
            )

        app.dependency_overrides[deps.get_api_key] = raise_401
        app.dependency_overrides[deps.get_db] = lambda: MagicMock()

        response = client.get("/api/v1/openfeature/flags")
        assert response.status_code == 401

    def test_invalid_api_key_returns_401(self, client):
        """An invalid API key returns 401."""
        from fastapi import HTTPException
        from fastapi import status as http_status

        def raise_401():
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API Key",
            )

        app.dependency_overrides[deps.get_api_key] = raise_401
        app.dependency_overrides[deps.get_db] = lambda: MagicMock()

        response = client.get(
            "/api/v1/openfeature/flags",
            headers={"X-API-Key": "invalid-key"},
        )
        assert response.status_code == 401

    def test_disabled_flag_is_included_in_list(self, client):
        """Disabled flags are included in the list so clients can evaluate locally."""
        flag = _make_feature_flag("off-flag", enabled=False)
        user = _make_user()
        _setup_overrides(user, [flag])

        response = client.get("/api/v1/openfeature/flags", headers={"X-API-Key": "k"})
        assert response.status_code == 200
        flag_def = response.json()["flags"][0]
        assert flag_def["enabled"] is False

    def test_rollout_percentage_is_float(self, client):
        """rollout_percentage is returned as a float."""
        flag = _make_feature_flag("pct-flag", rollout_percentage=42.5)
        user = _make_user()
        _setup_overrides(user, [flag])

        response = client.get("/api/v1/openfeature/flags", headers={"X-API-Key": "k"})
        assert response.status_code == 200
        pct = response.json()["flags"][0]["rollout_percentage"]
        assert isinstance(pct, (int, float))
        assert abs(pct - 42.5) < 0.01


# ---------------------------------------------------------------------------
# The removed evaluate routes (#241)
# ---------------------------------------------------------------------------


@pytest.mark.regression
class TestRemovedEvaluateRoutes:
    """POST /openfeature/evaluate and /bulk-evaluate are gone, not failing.

    On the old code both answered 500 for any existing flag (they read
    ``FeatureFlag.enabled``, which the model does not have). Now there is no
    route, so the answer is exactly 404 -- not 405, which would mean a route
    still matches the path.
    """

    @pytest.mark.parametrize(
        "path, body",
        [
            ("/api/v1/openfeature/evaluate", {"flagKey": "any", "userId": "u"}),
            ("/api/v1/openfeature/bulk-evaluate", [{"flagKey": "any", "userId": "u"}]),
        ],
    )
    def test_answers_404(self, client, path, body):
        _setup_overrides(_make_user(), [_make_feature_flag("any")])
        response = client.post(path, json=body, headers={"X-API-Key": "k"})
        assert response.status_code == 404, response.text

    def test_flags_listing_still_answers(self, client):
        """Positive control: the deprecated listing is still mounted."""
        _setup_overrides(_make_user(), [_make_feature_flag("kept")])
        response = client.get("/api/v1/openfeature/flags", headers={"X-API-Key": "k"})
        assert response.status_code == 200, response.text
        assert [f["key"] for f in response.json()["flags"]] == ["kept"]
