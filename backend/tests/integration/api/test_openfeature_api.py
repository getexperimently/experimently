"""
Integration tests for the OpenFeature-compatible API endpoints (EP-044).

  GET  /api/v1/openfeature/flags         — list flags for local evaluation
  POST /api/v1/openfeature/evaluate      — server-side single flag evaluation
  POST /api/v1/openfeature/bulk-evaluate — server-side bulk evaluation

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

from backend.app.main import app
from backend.app.api import deps
from backend.app.models.user import User, UserRole
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HASHED_PASSWORD = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"
ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_ID   = uuid.UUID("00000000-0000-0000-0000-000000000002")

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
    query_mock.first.return_value = first_flag if first_flag is not None else (flags[0] if flags else None)
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
        from fastapi import HTTPException, status as http_status
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
        from fastapi import HTTPException, status as http_status
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
# POST /api/v1/openfeature/evaluate
# ---------------------------------------------------------------------------


class TestPostOpenFeatureEvaluate:
    """Tests for POST /api/v1/openfeature/evaluate."""

    def test_evaluate_enabled_flag_returns_value(self, client):
        """An enabled boolean flag (no variants) returns value=true."""
        flag = _make_feature_flag("my-feature", enabled=True, rollout_percentage=100.0)
        user = _make_user()
        _setup_overrides(user, [flag], first_flag=flag)

        response = client.post(
            "/api/v1/openfeature/evaluate",
            json={"flagKey": "my-feature", "userId": "user-1"},
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["value"] is True
        assert data["reason"] == "in_rollout"
        assert data["flagKey"] == "my-feature"

    def test_evaluate_disabled_flag_returns_false(self, client):
        """A disabled flag returns value=false with reason=flag_disabled."""
        flag = _make_feature_flag("off-flag", enabled=False)
        user = _make_user()
        _setup_overrides(user, [flag], first_flag=flag)

        response = client.post(
            "/api/v1/openfeature/evaluate",
            json={"flagKey": "off-flag", "userId": "u1"},
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["value"] is False
        assert data["reason"] == "flag_disabled"

    def test_evaluate_unknown_flag_returns_default_reason(self, client):
        """An unknown flagKey returns reason=FLAG_NOT_FOUND and value=null."""
        user = _make_user()
        _setup_overrides(user, [], first_flag=None)

        response = client.post(
            "/api/v1/openfeature/evaluate",
            json={"flagKey": "nonexistent", "userId": "u1"},
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reason"] == "FLAG_NOT_FOUND"
        assert data["value"] is None

    def test_evaluate_variant_flag_returns_variant_value(self, client):
        """A flag with variants returns the assigned variant's value."""
        variants = [
            {"key": "control", "weight": 0.0},   # 0% so this is never picked
            {"key": "treatment", "weight": 1.0, "value": "new-checkout"},
        ]
        flag = _make_feature_flag(
            "checkout-ab", enabled=True, rollout_percentage=100.0, variants=variants
        )
        user = _make_user()
        _setup_overrides(user, [flag], first_flag=flag)

        response = client.post(
            "/api/v1/openfeature/evaluate",
            json={"flagKey": "checkout-ab", "userId": "u1"},
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reason"] == "variant_assigned"
        assert data["variant"] is not None

    def test_evaluate_zero_rollout_returns_false(self, client):
        """A flag with 0% rollout always returns value=false."""
        flag = _make_feature_flag("zero-pct", enabled=True, rollout_percentage=0.0)
        user = _make_user()
        _setup_overrides(user, [flag], first_flag=flag)

        response = client.post(
            "/api/v1/openfeature/evaluate",
            json={"flagKey": "zero-pct", "userId": "user-123"},
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200
        assert response.json()["value"] is False
        assert response.json()["reason"] == "out_of_rollout"

    def test_evaluate_missing_api_key_returns_401(self, client):
        """POST /evaluate without an API key returns 401."""
        from fastapi import HTTPException, status as http_status
        def raise_401():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED)
        app.dependency_overrides[deps.get_api_key] = raise_401
        app.dependency_overrides[deps.get_db] = lambda: MagicMock()

        response = client.post(
            "/api/v1/openfeature/evaluate",
            json={"flagKey": "f", "userId": "u"},
        )
        assert response.status_code == 401

    def test_evaluate_response_includes_flag_key(self, client):
        """The response always echoes back the flagKey."""
        flag = _make_feature_flag("echo-key", enabled=True, rollout_percentage=100.0)
        user = _make_user()
        _setup_overrides(user, [flag], first_flag=flag)

        response = client.post(
            "/api/v1/openfeature/evaluate",
            json={"flagKey": "echo-key", "userId": "u1"},
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200
        assert response.json()["flagKey"] == "echo-key"

    def test_evaluate_with_empty_user_id(self, client):
        """An empty userId is valid (hashes to a consistent value)."""
        flag = _make_feature_flag("f", enabled=True, rollout_percentage=100.0)
        user = _make_user()
        _setup_overrides(user, [flag], first_flag=flag)

        response = client.post(
            "/api/v1/openfeature/evaluate",
            json={"flagKey": "f", "userId": ""},
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200
        assert response.json()["value"] is True

    def test_evaluate_non_owner_user_is_forbidden(self, client):
        """A non-superuser API key owner cannot evaluate flags they don't own."""
        owner_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        flag = _make_feature_flag("private-flag", owner_id=owner_id)
        # api_key_user is NOT the owner.
        requester = _make_user(user_id=DEV_USER_ID, is_superuser=False)
        _setup_overrides(requester, [flag], first_flag=flag)

        response = client.post(
            "/api/v1/openfeature/evaluate",
            json={"flagKey": "private-flag", "userId": "u1"},
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/openfeature/bulk-evaluate
# ---------------------------------------------------------------------------


class TestBulkEvaluate:
    """Tests for POST /api/v1/openfeature/bulk-evaluate."""

    def _setup_multi_flag_db(self, user: User, flags: List[MagicMock]) -> None:
        """Set up DB mock that returns the correct flag for each .first() call."""
        db = MagicMock()
        flag_map = {f.key: f for f in flags}
        call_count = [0]

        def query_side_effect(model_class):
            q = MagicMock()

            def filter_side_effect(*args, **kwargs):
                # Extract key from filter argument if possible.
                fq = MagicMock()
                fq.first.return_value = None
                for f in flags:
                    fq.first.return_value = f  # last one wins — override per-test
                return fq

            q.filter.side_effect = filter_side_effect
            q.all.return_value = flags
            return q

        db.query.side_effect = query_side_effect
        app.dependency_overrides[deps.get_db] = lambda: db
        app.dependency_overrides[deps.get_api_key] = lambda: user

    def test_bulk_evaluate_returns_list(self, client):
        """Bulk evaluate returns a list with one result per request."""
        flag_a = _make_feature_flag("flag-a", enabled=True, rollout_percentage=100)
        flag_b = _make_feature_flag("flag-b", enabled=False)
        user = _make_user()

        # Set up a DB mock that returns the correct flag based on key.
        db = MagicMock()

        def make_query(model_class):
            q = MagicMock()
            def filter_fn(*args, **kwargs):
                fq = MagicMock()
                # We need to inspect the filter argument to return the right flag.
                # For simplicity, alternate between the two flags.
                fq.first.side_effect = [flag_a, flag_b]
                return fq
            q.filter.side_effect = filter_fn
            q.all.return_value = [flag_a, flag_b]
            return q

        db.query.side_effect = make_query
        app.dependency_overrides[deps.get_db] = lambda: db
        app.dependency_overrides[deps.get_api_key] = lambda: user

        response = client.post(
            "/api/v1/openfeature/bulk-evaluate",
            json=[
                {"flagKey": "flag-a", "userId": "u1"},
                {"flagKey": "flag-b", "userId": "u1"},
            ],
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200
        results = response.json()
        assert isinstance(results, list)
        assert len(results) == 2

    def test_bulk_evaluate_missing_flag_returns_flag_not_found(self, client):
        """Each missing flag in the bulk request gets FLAG_NOT_FOUND reason."""
        user = _make_user()

        db = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = None  # all flags missing
        q.all.return_value = []
        db.query.return_value = q
        app.dependency_overrides[deps.get_db] = lambda: db
        app.dependency_overrides[deps.get_api_key] = lambda: user

        response = client.post(
            "/api/v1/openfeature/bulk-evaluate",
            json=[{"flagKey": "missing-1", "userId": "u1"}],
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200
        assert response.json()[0]["reason"] == "FLAG_NOT_FOUND"

    def test_bulk_evaluate_missing_api_key_returns_401(self, client):
        """Bulk evaluate without an API key returns 401."""
        from fastapi import HTTPException, status as http_status
        def raise_401():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED)
        app.dependency_overrides[deps.get_api_key] = raise_401
        app.dependency_overrides[deps.get_db] = lambda: MagicMock()

        response = client.post(
            "/api/v1/openfeature/bulk-evaluate",
            json=[{"flagKey": "f", "userId": "u"}],
        )
        assert response.status_code == 401

    def test_bulk_evaluate_empty_list_returns_empty_result(self, client):
        """An empty request body returns an empty list."""
        user = _make_user()
        _setup_overrides(user, [])

        response = client.post(
            "/api/v1/openfeature/bulk-evaluate",
            json=[],
            headers={"X-API-Key": "k"},
        )
        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# Hash function correctness
# ---------------------------------------------------------------------------


class TestHashFunction:
    """Tests for the server-side _hash_user function used in /evaluate."""

    def test_hash_in_unit_interval(self):
        from backend.app.api.v1.endpoints.openfeature import _hash_user
        h = _hash_user("user-123", "my-flag")
        assert 0.0 <= h < 1.0

    def test_hash_is_deterministic(self):
        from backend.app.api.v1.endpoints.openfeature import _hash_user
        h1 = _hash_user("alice", "dark-mode")
        h2 = _hash_user("alice", "dark-mode")
        assert h1 == h2

    def test_cross_sdk_vector_user123_my_flag(self):
        """
        Cross-SDK test vector:
          MD5("user-123:my-flag") hex = 43bc57b1e81dec71c5242122ac05170f
          First 4 bytes LE → uint32 = 2975317059
          2975317059 / 4294967296 ≈ 0.69274...
        """
        from backend.app.api.v1.endpoints.openfeature import _hash_user
        h = _hash_user("user-123", "my-flag")
        assert abs(h - 0.69274) < 0.0001, f"Expected ~0.69274, got {h}"

    def test_hash_differs_for_different_users(self):
        from backend.app.api.v1.endpoints.openfeature import _hash_user
        assert _hash_user("alice", "flag") != _hash_user("bob", "flag")

    def test_hash_differs_for_different_flags(self):
        from backend.app.api.v1.endpoints.openfeature import _hash_user
        assert _hash_user("alice", "flag-a") != _hash_user("alice", "flag-b")
