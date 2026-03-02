"""
Unit tests for Mutual Exclusion Group API endpoints (EP-022).

Uses FastAPI TestClient with dependency overrides.
No real database required -- all DB and service calls are mocked.
"""

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api import deps
from backend.app.models.user import User, UserRole
from backend.app.models.mutual_exclusion_group import (
    MutualExclusionGroup,
    MutualExclusionGroupStatus,
)


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


def _make_group(
    group_id=None,
    name="Test Group",
    status=MutualExclusionGroupStatus.ACTIVE,
    traffic_allocation=1.0,
    owner_id=None,
):
    grp = MagicMock(spec=MutualExclusionGroup)
    grp.id = group_id or uuid.uuid4()
    grp.name = name
    grp.description = "Test description"
    grp.traffic_allocation = traffic_allocation
    grp.status = status
    grp.owner_id = owner_id
    grp.experiments = []
    grp.created_at = datetime(2025, 1, 1, 12, 0)
    grp.updated_at = datetime(2025, 1, 2, 12, 0)
    return grp


# ---------------------------------------------------------------------------
# Test: List groups
# ---------------------------------------------------------------------------

class TestListGroups:
    """GET /api/v1/mutual-exclusion-groups"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_groups_returns_200_with_items(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        grp = _make_group()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.list_groups.return_value = [grp]
            instance.count_groups.return_value = 1

            client = TestClient(app)
            response = client.get("/api/v1/mutual-exclusion-groups")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_list_groups_returns_200_empty(self):
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.list_groups.return_value = []
            instance.count_groups.return_value = 0

            client = TestClient(app)
            response = client.get("/api/v1/mutual-exclusion-groups")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_groups_with_status_filter(self):
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.list_groups.return_value = []
            instance.count_groups.return_value = 0

            client = TestClient(app)
            response = client.get("/api/v1/mutual-exclusion-groups?status=active")

        assert response.status_code == 200

    def test_list_groups_returns_403_for_viewer(self):
        mock_user = _make_user(role=UserRole.VIEWER)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/v1/mutual-exclusion-groups")

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: Create group
# ---------------------------------------------------------------------------

class TestCreateGroup:
    """POST /api/v1/mutual-exclusion-groups"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_group_returns_201(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        grp = _make_group(name="New Group")

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.create_group.return_value = grp

            client = TestClient(app)
            response = client.post(
                "/api/v1/mutual-exclusion-groups",
                json={"name": "New Group", "traffic_allocation": 0.8},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Group"

    def test_create_group_returns_201_for_admin(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()
        grp = _make_group(name="Admin Group")

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.create_group.return_value = grp

            client = TestClient(app)
            response = client.post(
                "/api/v1/mutual-exclusion-groups",
                json={"name": "Admin Group"},
            )

        assert response.status_code == 201

    def test_create_group_returns_422_for_invalid_traffic_allocation(self):
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/v1/mutual-exclusion-groups",
            json={"name": "Bad Group", "traffic_allocation": 2.0},
        )

        assert response.status_code == 422

    def test_create_group_returns_422_for_missing_name(self):
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/v1/mutual-exclusion-groups",
            json={"traffic_allocation": 0.5},
        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test: Get group
# ---------------------------------------------------------------------------

class TestGetGroup:
    """GET /api/v1/mutual-exclusion-groups/{group_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_group_returns_200(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        grp = _make_group()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.get_group.return_value = grp

            client = TestClient(app)
            response = client.get(f"/api/v1/mutual-exclusion-groups/{grp.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Group"

    def test_get_group_returns_404(self):
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.get_group.return_value = None

            client = TestClient(app)
            response = client.get(f"/api/v1/mutual-exclusion-groups/{uuid.uuid4()}")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test: Update group
# ---------------------------------------------------------------------------

class TestUpdateGroup:
    """PUT /api/v1/mutual-exclusion-groups/{group_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_update_group_returns_200(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        grp = _make_group(name="Updated Group")

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.update_group.return_value = grp

            client = TestClient(app)
            response = client.put(
                f"/api/v1/mutual-exclusion-groups/{grp.id}",
                json={"name": "Updated Group"},
            )

        assert response.status_code == 200
        assert response.json()["name"] == "Updated Group"

    def test_update_group_returns_404(self):
        mock_user = _make_user()
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.update_group.return_value = None

            client = TestClient(app)
            response = client.put(
                f"/api/v1/mutual-exclusion-groups/{uuid.uuid4()}",
                json={"name": "Nope"},
            )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test: Archive group
# ---------------------------------------------------------------------------

class TestArchiveGroup:
    """DELETE /api/v1/mutual-exclusion-groups/{group_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_archive_group_returns_200_for_admin(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()
        grp = _make_group(status=MutualExclusionGroupStatus.ARCHIVED)

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.archive_group.return_value = grp

            client = TestClient(app)
            response = client.delete(f"/api/v1/mutual-exclusion-groups/{grp.id}")

        assert response.status_code == 200

    def test_archive_group_returns_404_when_not_found(self):
        mock_user = _make_user(role=UserRole.ADMIN, is_superuser=True)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.archive_group.return_value = None

            client = TestClient(app)
            response = client.delete(f"/api/v1/mutual-exclusion-groups/{uuid.uuid4()}")

        assert response.status_code == 404

    def test_archive_group_returns_403_for_viewer(self):
        mock_user = _make_user(role=UserRole.VIEWER)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.delete(f"/api/v1/mutual-exclusion-groups/{uuid.uuid4()}")

        assert response.status_code == 403

    def test_archive_group_returns_403_for_analyst(self):
        """ANALYST cannot delete / archive groups."""
        mock_user = _make_user(role=UserRole.ANALYST)
        mock_db = MagicMock()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.delete(f"/api/v1/mutual-exclusion-groups/{uuid.uuid4()}")

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: Add experiment to group
# ---------------------------------------------------------------------------

class TestAddExperimentToGroup:
    """POST /api/v1/mutual-exclusion-groups/{group_id}/experiments"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_add_experiment_returns_200(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        group_id = uuid.uuid4()
        experiment_id = uuid.uuid4()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.add_experiment_to_group.return_value = MagicMock()

            client = TestClient(app)
            response = client.post(
                f"/api/v1/mutual-exclusion-groups/{group_id}/experiments",
                json={"experiment_id": str(experiment_id)},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_add_experiment_returns_400_already_in_another_group(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        group_id = uuid.uuid4()
        experiment_id = uuid.uuid4()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.add_experiment_to_group.side_effect = ValueError(
                "Experiment is already in another group"
            )

            client = TestClient(app)
            response = client.post(
                f"/api/v1/mutual-exclusion-groups/{group_id}/experiments",
                json={"experiment_id": str(experiment_id)},
            )

        assert response.status_code == 400

    def test_add_experiment_returns_400_group_not_found(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        group_id = uuid.uuid4()
        experiment_id = uuid.uuid4()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.add_experiment_to_group.side_effect = ValueError(
                f"Group {group_id} not found"
            )

            client = TestClient(app)
            response = client.post(
                f"/api/v1/mutual-exclusion-groups/{group_id}/experiments",
                json={"experiment_id": str(experiment_id)},
            )

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Test: Remove experiment from group
# ---------------------------------------------------------------------------

class TestRemoveExperimentFromGroup:
    """DELETE /api/v1/mutual-exclusion-groups/{group_id}/experiments/{experiment_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_remove_experiment_returns_200(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        group_id = uuid.uuid4()
        experiment_id = uuid.uuid4()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.remove_experiment_from_group.return_value = MagicMock()

            client = TestClient(app)
            response = client.delete(
                f"/api/v1/mutual-exclusion-groups/{group_id}/experiments/{experiment_id}"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_remove_experiment_returns_400_not_found(self):
        mock_user = _make_user()
        mock_db = MagicMock()
        group_id = uuid.uuid4()
        experiment_id = uuid.uuid4()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        with patch(
            "backend.app.api.v1.endpoints.mutual_exclusion_groups.MutualExclusionService"
        ) as MockService:
            instance = MockService.return_value
            instance.remove_experiment_from_group.side_effect = ValueError(
                f"Experiment {experiment_id} not found in group {group_id}"
            )

            client = TestClient(app)
            response = client.delete(
                f"/api/v1/mutual-exclusion-groups/{group_id}/experiments/{experiment_id}"
            )

        assert response.status_code == 400
