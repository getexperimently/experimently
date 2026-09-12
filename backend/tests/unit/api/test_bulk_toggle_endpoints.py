"""
Unit tests for bulk toggle and flag history endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.user import User


def make_mock_user():
    mock_user = MagicMock(spec=User)
    mock_user.id = uuid4()
    mock_user.email = "admin@example.com"
    mock_user.username = "admin"
    mock_user.is_active = True
    mock_user.is_superuser = True
    return mock_user


def make_mock_db():
    return Mock(spec=Session)


def make_mock_flag():
    """Create a MagicMock feature flag without spec constraints on status."""
    flag = MagicMock()
    flag.id = uuid4()
    flag.key = "test-flag"
    flag.name = "Test Flag"
    # Use a real enum value so .value works correctly
    flag.status = FeatureFlagStatus.INACTIVE
    return flag


class TestBulkToggleEndpoint:
    def setup_method(self):
        """Clear overrides before each test."""
        app.dependency_overrides.clear()

    def teardown_method(self):
        """Clear overrides after each test."""
        app.dependency_overrides.clear()

    def test_bulk_toggle_enable_returns_200(self):
        """Bulk enable returns 200 with results."""
        mock_user = make_mock_user()
        mock_db = make_mock_db()
        mock_flag = make_mock_flag()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        mock_db.query.return_value.filter.return_value.first.return_value = mock_flag
        mock_db.flush = Mock()
        mock_db.commit = Mock()

        async def mock_log_toggle(*args, **kwargs):
            return uuid4()

        with patch(
            "backend.app.services.audit_service.AuditService.log_toggle_operation",
            side_effect=mock_log_toggle,
        ):
            client = TestClient(app)
            response = client.post(
                "/api/v1/feature-flags/bulk-toggle",
                json={
                    "flag_ids": [str(uuid4())],
                    "action": "enable",
                    "reason": "Bulk enable for release",
                },
            )

        assert response.status_code == 200

    def test_bulk_toggle_response_has_required_fields(self):
        """Bulk toggle response contains total/succeeded/failed/results."""
        mock_user = make_mock_user()
        mock_db = make_mock_db()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        # Return None so flags are "not found" -> counted as failed
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.commit = Mock()

        client = TestClient(app)
        response = client.post(
            "/api/v1/feature-flags/bulk-toggle",
            json={
                "flag_ids": [str(uuid4())],
                "action": "disable",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "succeeded" in data
        assert "failed" in data
        assert "results" in data

    def test_bulk_toggle_requires_auth(self):
        """Endpoint requires authentication when no override is set."""
        # Clear all overrides so real auth runs
        app.dependency_overrides.clear()

        client = TestClient(app)
        response = client.post(
            "/api/v1/feature-flags/bulk-toggle",
            json={
                "flag_ids": [str(uuid4())],
                "action": "enable",
            },
        )
        assert response.status_code in (401, 403, 422)

    def test_empty_flag_ids_returns_422(self):
        """Empty flag_ids list returns 422 (Pydantic validation)."""
        mock_user = make_mock_user()
        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: make_mock_db()

        client = TestClient(app)
        response = client.post(
            "/api/v1/feature-flags/bulk-toggle",
            json={
                "flag_ids": [],
                "action": "enable",
            },
        )
        assert response.status_code == 422

    def test_invalid_action_returns_422(self):
        """Invalid action value returns 422 (Pydantic validation)."""
        mock_user = make_mock_user()
        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: make_mock_db()

        client = TestClient(app)
        response = client.post(
            "/api/v1/feature-flags/bulk-toggle",
            json={
                "flag_ids": [str(uuid4())],
                "action": "invalid_action",
            },
        )
        assert response.status_code == 422

    def test_not_found_flag_included_in_failed(self):
        """Non-existent flag IDs are reported as failed, not raising 404."""
        mock_user = make_mock_user()
        mock_db = make_mock_db()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.commit = Mock()

        client = TestClient(app)
        response = client.post(
            "/api/v1/feature-flags/bulk-toggle",
            json={
                "flag_ids": [str(uuid4())],
                "action": "enable",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["failed"] == 1
        assert data["succeeded"] == 0


class TestFlagHistoryEndpoint:
    def setup_method(self):
        """Clear overrides before each test."""
        app.dependency_overrides.clear()

    def teardown_method(self):
        """Clear overrides after each test."""
        app.dependency_overrides.clear()

    def test_flag_history_returns_200(self):
        """Flag history endpoint returns 200 for existing flag."""
        mock_user = make_mock_user()
        mock_db = make_mock_db()
        flag_id = uuid4()
        mock_flag = make_mock_flag()
        mock_flag.id = flag_id
        mock_flag.key = "test-flag"
        mock_flag.name = "Test Flag"

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        mock_db.query.return_value.filter.return_value.first.return_value = mock_flag

        with patch(
            "backend.app.services.audit_service.AuditService.get_flag_change_history",
            return_value=([], 0),
        ):
            client = TestClient(app)
            response = client.get(f"/api/v1/feature-flags/{flag_id}/history")

        assert response.status_code == 200

    def test_flag_history_404_for_nonexistent(self):
        """Returns 404 for non-existent flag."""
        mock_user = make_mock_user()
        mock_db = make_mock_db()

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        mock_db.query.return_value.filter.return_value.first.return_value = None

        client = TestClient(app)
        response = client.get(f"/api/v1/feature-flags/{uuid4()}/history")

        assert response.status_code == 404

    def test_flag_history_response_structure(self):
        """Response has flag_id, flag_key, total_changes, history fields."""
        mock_user = make_mock_user()
        mock_db = make_mock_db()
        flag_id = uuid4()
        mock_flag = make_mock_flag()
        mock_flag.id = flag_id
        mock_flag.key = "my-flag"
        mock_flag.name = "My Flag"

        app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
        app.dependency_overrides[deps.get_db] = lambda: mock_db

        mock_db.query.return_value.filter.return_value.first.return_value = mock_flag

        with patch(
            "backend.app.services.audit_service.AuditService.get_flag_change_history",
            return_value=([], 0),
        ):
            client = TestClient(app)
            response = client.get(f"/api/v1/feature-flags/{flag_id}/history")

        assert response.status_code == 200
        data = response.json()
        assert "flag_id" in data
        assert "flag_key" in data
        assert "total_changes" in data
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_flag_history_requires_auth(self):
        """History endpoint requires authentication."""
        app.dependency_overrides.clear()  # Ensure no overrides

        client = TestClient(app)
        response = client.get(f"/api/v1/feature-flags/{uuid4()}/history")

        assert response.status_code in (401, 403)
