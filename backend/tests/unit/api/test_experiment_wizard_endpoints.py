"""
Unit tests for the Experiment Wizard API endpoints.

Uses FastAPI TestClient with dependency overrides.
No real database required — all draft operations use the in-memory store.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api import deps
from backend.app.models.user import User, UserRole
from backend.app.services.experiment_wizard_service import _drafts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: UserRole = UserRole.DEVELOPER, is_superuser: bool = False) -> User:
    """Create a mock user object."""
    user = MagicMock(spec=User)
    user.id = str(uuid.uuid4())
    user.username = "testuser"
    user.email = "test@example.com"
    user.is_active = True
    user.is_superuser = is_superuser
    user.role = role
    return user


def _clear_drafts():
    """Clear in-memory draft store between tests."""
    _drafts.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_draft_store():
    """Clear the in-memory draft store before each test."""
    _clear_drafts()
    yield
    _clear_drafts()


@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_user():
    """Return a mock DEVELOPER user."""
    return _make_user(role=UserRole.DEVELOPER)


@pytest.fixture
def authenticated_client(client, mock_user):
    """Return a TestClient with auth dependency overridden."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: mock_user
    yield client, mock_user
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/v1/wizard/drafts
# ---------------------------------------------------------------------------


class TestCreateDraft:
    """POST /api/v1/wizard/drafts — create a new wizard draft."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_draft_returns_201(self, authenticated_client):
        """POST /wizard/drafts creates a draft and returns 201."""
        client, mock_user = authenticated_client
        response = client.post(
            "/api/v1/wizard/drafts",
            json={"experiment_type": "ab"},
        )
        assert response.status_code == 201

    def test_create_draft_response_has_id(self, authenticated_client):
        """POST /wizard/drafts returns draft with id field."""
        client, mock_user = authenticated_client
        response = client.post(
            "/api/v1/wizard/drafts",
            json={"experiment_type": "ab"},
        )
        data = response.json()
        assert "id" in data
        assert data["id"] is not None

    def test_create_draft_response_has_current_step(self, authenticated_client):
        """POST /wizard/drafts returns draft with current_step field."""
        client, mock_user = authenticated_client
        response = client.post(
            "/api/v1/wizard/drafts",
            json={"experiment_type": "ab"},
        )
        data = response.json()
        assert "current_step" in data
        assert data["current_step"] == "choose_type"

    def test_create_draft_requires_authentication(self, client):
        """POST /wizard/drafts returns 401 without authentication."""
        # No dependency override → auth should fail
        with patch("backend.app.api.deps.get_current_active_user") as mock_dep:
            from fastapi import HTTPException
            mock_dep.side_effect = HTTPException(status_code=401, detail="Not authenticated")
            response = client.post(
                "/api/v1/wizard/drafts",
                json={"experiment_type": "ab"},
            )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/wizard/drafts/{id}
# ---------------------------------------------------------------------------


class TestGetDraft:
    """GET /api/v1/wizard/drafts/{id} — retrieve a wizard draft."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_draft_returns_200(self, authenticated_client):
        """GET /wizard/drafts/{id} returns 200 for existing draft."""
        client, mock_user = authenticated_client
        # Create draft first
        create_resp = client.post(
            "/api/v1/wizard/drafts", json={"experiment_type": "ab"}
        )
        draft_id = create_resp.json()["id"]

        response = client.get(f"/api/v1/wizard/drafts/{draft_id}")
        assert response.status_code == 200

    def test_get_draft_returns_draft_data(self, authenticated_client):
        """GET /wizard/drafts/{id} returns correct draft data."""
        client, mock_user = authenticated_client
        create_resp = client.post(
            "/api/v1/wizard/drafts", json={"experiment_type": "multivariate"}
        )
        draft_id = create_resp.json()["id"]

        response = client.get(f"/api/v1/wizard/drafts/{draft_id}")
        data = response.json()
        assert data["id"] == draft_id
        assert data["experiment_type"] == "multivariate"

    def test_get_draft_returns_404_for_missing_draft(self, authenticated_client):
        """GET /wizard/drafts/{id} returns 404 for non-existent draft."""
        client, mock_user = authenticated_client
        response = client.get(f"/api/v1/wizard/drafts/{uuid.uuid4()}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/v1/wizard/drafts/{id}/step
# ---------------------------------------------------------------------------


class TestUpdateDraftStep:
    """PUT /api/v1/wizard/drafts/{id}/step — update a draft step."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_update_step_returns_200(self, authenticated_client):
        """PUT /wizard/drafts/{id}/step returns 200 for valid update."""
        client, mock_user = authenticated_client
        create_resp = client.post(
            "/api/v1/wizard/drafts", json={"experiment_type": "ab"}
        )
        draft_id = create_resp.json()["id"]

        response = client.put(
            f"/api/v1/wizard/drafts/{draft_id}/step",
            json={"step": "choose_type", "data": {"experiment_type": "ab"}},
        )
        assert response.status_code == 200

    def test_update_step_advances_current_step(self, authenticated_client):
        """PUT /wizard/drafts/{id}/step advances current_step to next step."""
        client, mock_user = authenticated_client
        create_resp = client.post(
            "/api/v1/wizard/drafts", json={"experiment_type": "ab"}
        )
        draft_id = create_resp.json()["id"]

        response = client.put(
            f"/api/v1/wizard/drafts/{draft_id}/step",
            json={"step": "choose_type", "data": {"experiment_type": "ab"}},
        )
        data = response.json()
        assert data["current_step"] == "define_hypothesis"

    def test_update_step_returns_404_for_missing_draft(self, authenticated_client):
        """PUT /wizard/drafts/{id}/step returns 404 for non-existent draft."""
        client, mock_user = authenticated_client
        response = client.put(
            f"/api/v1/wizard/drafts/{uuid.uuid4()}/step",
            json={"step": "choose_type", "data": {"experiment_type": "ab"}},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/wizard/validate
# ---------------------------------------------------------------------------


class TestValidateStep:
    """POST /api/v1/wizard/validate — validate step data without modifying draft."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_validate_endpoint_returns_200(self, authenticated_client):
        """POST /wizard/validate returns 200 for any valid request."""
        client, mock_user = authenticated_client
        response = client.post(
            "/api/v1/wizard/validate",
            json={"step": "choose_type", "data": {"experiment_type": "ab"}},
        )
        assert response.status_code == 200

    def test_validate_choose_type_valid_returns_is_valid_true(self, authenticated_client):
        """POST /wizard/validate with valid choose_type data → is_valid=True."""
        client, mock_user = authenticated_client
        response = client.post(
            "/api/v1/wizard/validate",
            json={"step": "choose_type", "data": {"experiment_type": "ab"}},
        )
        data = response.json()
        assert data["is_valid"] is True
        assert data["errors"] == []

    def test_validate_choose_type_invalid_returns_is_valid_false(self, authenticated_client):
        """POST /wizard/validate with invalid choose_type data → is_valid=False."""
        client, mock_user = authenticated_client
        response = client.post(
            "/api/v1/wizard/validate",
            json={"step": "choose_type", "data": {"experiment_type": "not_a_real_type"}},
        )
        data = response.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) > 0

    def test_validate_define_hypothesis_valid(self, authenticated_client):
        """POST /wizard/validate with valid hypothesis data → is_valid=True."""
        client, mock_user = authenticated_client
        response = client.post(
            "/api/v1/wizard/validate",
            json={
                "step": "define_hypothesis",
                "data": {
                    "hypothesis": "We believe adding a new CTA button will boost conversions.",
                    "primary_metric_id": "metric-001",
                },
            },
        )
        data = response.json()
        assert data["is_valid"] is True

    def test_validate_response_has_errors_list(self, authenticated_client):
        """POST /wizard/validate always returns an errors field as a list."""
        client, mock_user = authenticated_client
        response = client.post(
            "/api/v1/wizard/validate",
            json={"step": "targeting", "data": {}},
        )
        data = response.json()
        assert "errors" in data
        assert isinstance(data["errors"], list)


# ---------------------------------------------------------------------------
# POST /api/v1/wizard/drafts/{id}/submit
# ---------------------------------------------------------------------------


class TestSubmitDraft:
    """POST /api/v1/wizard/drafts/{id}/submit — submit a completed draft."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _create_complete_draft(self, client, mock_user):
        """Helper to create a fully-filled draft."""
        create_resp = client.post(
            "/api/v1/wizard/drafts", json={"experiment_type": "ab"}
        )
        draft_id = create_resp.json()["id"]

        # Fill in hypothesis and metric via step update
        client.put(
            f"/api/v1/wizard/drafts/{draft_id}/step",
            json={"step": "choose_type", "data": {"experiment_type": "ab"}},
        )
        client.put(
            f"/api/v1/wizard/drafts/{draft_id}/step",
            json={
                "step": "define_hypothesis",
                "data": {
                    "hypothesis": "We believe adding a new button will increase click-through rates by 20%.",
                    "primary_metric_id": "metric-001",
                },
            },
        )
        return draft_id

    def test_submit_complete_draft_returns_200(self, authenticated_client):
        """POST /wizard/drafts/{id}/submit with complete draft returns 200."""
        client, mock_user = authenticated_client
        draft_id = self._create_complete_draft(client, mock_user)
        response = client.post(f"/api/v1/wizard/drafts/{draft_id}/submit")
        assert response.status_code == 200

    def test_submit_complete_draft_returns_experiment_id(self, authenticated_client):
        """POST /wizard/drafts/{id}/submit returns experiment_id on success."""
        client, mock_user = authenticated_client
        draft_id = self._create_complete_draft(client, mock_user)
        response = client.post(f"/api/v1/wizard/drafts/{draft_id}/submit")
        data = response.json()
        assert data["success"] is True
        assert "experiment_id" in data
        assert data["experiment_id"] is not None

    def test_submit_incomplete_draft_returns_errors(self, authenticated_client):
        """POST /wizard/drafts/{id}/submit with incomplete draft returns errors."""
        client, mock_user = authenticated_client
        # Create draft but don't fill hypothesis or metric
        create_resp = client.post(
            "/api/v1/wizard/drafts", json={"experiment_type": "ab"}
        )
        draft_id = create_resp.json()["id"]

        response = client.post(f"/api/v1/wizard/drafts/{draft_id}/submit")
        data = response.json()
        assert data["success"] is False
        assert isinstance(data["errors"], list)
        assert len(data["errors"]) > 0

    def test_submit_nonexistent_draft_returns_404(self, authenticated_client):
        """POST /wizard/drafts/{id}/submit returns 404 for non-existent draft."""
        client, mock_user = authenticated_client
        response = client.post(f"/api/v1/wizard/drafts/{uuid.uuid4()}/submit")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/wizard/drafts
# ---------------------------------------------------------------------------


class TestListDrafts:
    """GET /api/v1/wizard/drafts — list all drafts for the authenticated user."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_drafts_returns_200(self, authenticated_client):
        """GET /wizard/drafts returns 200."""
        client, mock_user = authenticated_client
        response = client.get("/api/v1/wizard/drafts")
        assert response.status_code == 200

    def test_list_drafts_returns_drafts_list(self, authenticated_client):
        """GET /wizard/drafts returns a list of the user's drafts."""
        client, mock_user = authenticated_client
        # Create two drafts
        client.post("/api/v1/wizard/drafts", json={"experiment_type": "ab"})
        client.post("/api/v1/wizard/drafts", json={"experiment_type": "multivariate"})

        response = client.get("/api/v1/wizard/drafts")
        data = response.json()
        assert "drafts" in data
        assert len(data["drafts"]) == 2

    def test_list_drafts_empty_for_new_user(self, client):
        """GET /wizard/drafts returns empty list for user with no drafts."""
        new_user = _make_user()
        app.dependency_overrides[deps.get_current_active_user] = lambda: new_user
        response = client.get("/api/v1/wizard/drafts")
        data = response.json()
        assert data["drafts"] == []
        app.dependency_overrides.clear()

    def test_list_drafts_requires_authentication(self, client):
        """GET /wizard/drafts returns 401 without authentication."""
        with patch("backend.app.api.deps.get_current_active_user") as mock_dep:
            from fastapi import HTTPException
            mock_dep.side_effect = HTTPException(status_code=401, detail="Not authenticated")
            response = client.get("/api/v1/wizard/drafts")
        assert response.status_code == 401
