"""
Unit tests for Global Holdout API endpoints (EP-022).

Uses FastAPI TestClient with dependency overrides.
No real database required -- all DB and service calls are mocked.
"""

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.global_holdout import GlobalHoldout
from backend.app.models.user import User, UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role=UserRole.DEVELOPER, is_superuser=False):
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "testuser"
    user.email = "test@example.com"
    user.is_active = True
    user.is_superuser = is_superuser
    user.role = role
    return user


def _make_holdout(
    holdout_id=None,
    name="Test Holdout",
    holdout_percentage=10,
    is_active=True,
    owner_id=None,
):
    ho = MagicMock(spec=GlobalHoldout)
    ho.id = holdout_id or uuid.uuid4()
    ho.name = name
    ho.description = "Test holdout description"
    ho.holdout_percentage = holdout_percentage
    ho.is_active = is_active
    ho.owner_id = owner_id
    ho.created_at = datetime(2025, 1, 1, 12, 0)
    ho.updated_at = datetime(2025, 1, 2, 12, 0)
    return ho


# ---------------------------------------------------------------------------
# Test: Get active holdout
# ---------------------------------------------------------------------------


class TestGetActiveHoldout:
    """GET /api/v1/holdout"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_active_holdout_returns_200(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        ho = _make_holdout()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.get_active_holdout.return_value = ho

            client = TestClient(app)
            response = client.get("/api/v1/holdout")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Holdout"
        assert data["holdout_percentage"] == 10
        assert data["is_active"] is True

    def test_get_active_holdout_returns_200_none_active(self):
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.get_active_holdout.return_value = None

            client = TestClient(app)
            response = client.get("/api/v1/holdout")

        assert response.status_code == 200
        assert response.json() is None

    def test_get_active_holdout_returns_403_for_viewer(self):
        mock_user = _make_user(role=UserRole.VIEWER)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/v1/holdout")

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: List all holdouts
# ---------------------------------------------------------------------------


class TestListAllHoldouts:
    """GET /api/v1/holdout/all"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_holdouts_returns_200_for_admin(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()
        ho = _make_holdout()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.list_holdouts.return_value = [ho]
            instance.count_holdouts.return_value = 1

            client = TestClient(app)
            response = client.get("/api/v1/holdout/all")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_list_holdouts_returns_200_empty(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.list_holdouts.return_value = []
            instance.count_holdouts.return_value = 0

            client = TestClient(app)
            response = client.get("/api/v1/holdout/all")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_holdouts_returns_403_for_viewer(self):
        mock_user = _make_user(role=UserRole.VIEWER)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/v1/holdout/all")

        assert response.status_code == 403

    def test_list_holdouts_returns_403_for_analyst(self):
        mock_user = _make_user(role=UserRole.ANALYST)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/v1/holdout/all")

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: Create holdout
# ---------------------------------------------------------------------------


class TestCreateHoldout:
    """POST /api/v1/holdout"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_holdout_returns_201_for_admin(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()
        ho = _make_holdout(name="New Holdout")

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.create_holdout.return_value = ho

            client = TestClient(app)
            response = client.post(
                "/api/v1/holdout",
                json={"name": "New Holdout", "holdout_percentage": 5},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Holdout"

    def test_create_holdout_returns_422_for_invalid_percentage(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/v1/holdout",
            json={"name": "Bad Holdout", "holdout_percentage": 50},
        )

        assert response.status_code == 422

    def test_create_holdout_returns_422_for_missing_name(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/v1/holdout",
            json={"holdout_percentage": 10},
        )

        assert response.status_code == 422

    def test_create_holdout_returns_403_for_viewer(self):
        mock_user = _make_user(role=UserRole.VIEWER)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/v1/holdout",
            json={"name": "Should Fail", "holdout_percentage": 5},
        )

        assert response.status_code == 403

    def test_create_holdout_returns_403_for_analyst(self):
        mock_user = _make_user(role=UserRole.ANALYST)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/v1/holdout",
            json={"name": "Should Fail", "holdout_percentage": 5},
        )

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: Update holdout
# ---------------------------------------------------------------------------


class TestUpdateHoldout:
    """PUT /api/v1/holdout/{holdout_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_update_holdout_returns_200_for_admin(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()
        ho = _make_holdout(name="Updated Holdout", holdout_percentage=15)

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.update_holdout.return_value = ho

            client = TestClient(app)
            response = client.put(
                f"/api/v1/holdout/{ho.id}",
                json={"name": "Updated Holdout", "holdout_percentage": 15},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Holdout"
        assert data["holdout_percentage"] == 15

    def test_update_holdout_returns_404_when_not_found(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.update_holdout.return_value = None

            client = TestClient(app)
            response = client.put(
                f"/api/v1/holdout/{uuid.uuid4()}",
                json={"name": "Nope"},
            )

        assert response.status_code == 404

    def test_update_holdout_returns_403_for_viewer(self):
        mock_user = _make_user(role=UserRole.VIEWER)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.put(
            f"/api/v1/holdout/{uuid.uuid4()}",
            json={"name": "Fail"},
        )

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: Check user holdout status
# ---------------------------------------------------------------------------


class TestCheckUserHoldout:
    """GET /api/v1/holdout/check/{user_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_check_user_in_holdout(self):
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.is_user_in_holdout.return_value = (True, 10, 5)

            client = TestClient(app)
            response = client.get("/api/v1/holdout/check/user-123")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user-123"
        assert data["is_in_holdout"] is True
        assert data["holdout_percentage"] == 10
        assert data["bucket"] == 5

    def test_check_user_not_in_holdout(self):
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.is_user_in_holdout.return_value = (False, 10, 85)

            client = TestClient(app)
            response = client.get("/api/v1/holdout/check/user-456")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user-456"
        assert data["is_in_holdout"] is False
        assert data["bucket"] == 85

    def test_check_user_no_active_holdout(self):
        """When no holdout is active, returns is_in_holdout=False with 0 percentage."""
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.global_holdout.GlobalHoldoutService"
        ) as MockService:
            instance = MockService.return_value
            instance.is_user_in_holdout.return_value = (False, 0, 0)

            client = TestClient(app)
            response = client.get("/api/v1/holdout/check/user-789")

        assert response.status_code == 200
        data = response.json()
        assert data["is_in_holdout"] is False
        assert data["holdout_percentage"] == 0

    def test_check_user_holdout_returns_403_for_viewer(self):
        mock_user = _make_user(role=UserRole.VIEWER)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/v1/holdout/check/user-123")

        assert response.status_code == 403
