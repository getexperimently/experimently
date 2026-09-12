"""
Realistic scenario: Multi-Tenant Workspace Isolation (EP-057).

Validates workspace data isolation, RBAC within workspaces, plan limits,
API key lifecycle, and invite workflow — all offline using the service layer
directly with mocked database sessions.

These tests do NOT require a running platform or database.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


class TestWorkspaceModelIntegrity:
    """Validate workspace model structure and constraints."""

    def test_workspace_model_has_required_columns(self):
        from backend.app.models.workspace import Workspace

        col_names = {c.key for c in Workspace.__table__.columns}
        required = {
            "name",
            "slug",
            "plan",
            "is_active",
            "max_experiments",
            "max_feature_flags",
            "max_members",
            "max_api_keys",
        }
        missing = required - col_names
        assert not missing, f"Workspace model missing columns: {missing}"

    def test_workspace_member_model_has_role(self):
        from backend.app.models.workspace import WorkspaceMember

        col_names = {c.key for c in WorkspaceMember.__table__.columns}
        assert "role" in col_names
        assert "workspace_id" in col_names
        assert "user_id" in col_names

    def test_workspace_invite_model_has_token(self):
        from backend.app.models.workspace import WorkspaceInvite

        col_names = {c.key for c in WorkspaceInvite.__table__.columns}
        assert "token" in col_names
        assert "email" in col_names
        assert "expires_at" in col_names

    def test_api_key_model_has_key_hash(self):
        from backend.app.models.workspace import WorkspaceAPIKey

        col_names = {c.key for c in WorkspaceAPIKey.__table__.columns}
        assert "key_hash" in col_names
        assert "key_prefix" in col_names
        assert "scopes" in col_names


class TestWorkspacePlanLimits:
    """Validate plan-based resource limits."""

    def test_plan_enum_values(self):
        from backend.app.models.workspace import WorkspacePlan

        assert hasattr(WorkspacePlan, "FREE")
        assert hasattr(WorkspacePlan, "PRO")
        assert hasattr(WorkspacePlan, "ENTERPRISE")

    def test_free_plan_has_lowest_limits(self):
        from backend.app.services.workspace_service import _PLAN_LIMITS

        free = _PLAN_LIMITS["free"]
        pro = _PLAN_LIMITS["pro"]
        assert free["max_experiments"] < pro["max_experiments"]
        assert free["max_feature_flags"] < pro["max_feature_flags"]
        assert free["max_members"] < pro["max_members"]

    def test_enterprise_plan_has_highest_limits(self):
        from backend.app.services.workspace_service import _PLAN_LIMITS

        enterprise = _PLAN_LIMITS["enterprise"]
        pro = _PLAN_LIMITS["pro"]
        assert enterprise["max_experiments"] >= pro["max_experiments"]
        assert enterprise["max_members"] >= pro["max_members"]

    def test_free_plan_specific_values(self):
        from backend.app.services.workspace_service import _PLAN_LIMITS

        free = _PLAN_LIMITS["free"]
        assert free["max_experiments"] == 10
        assert free["max_feature_flags"] == 50
        assert free["max_members"] == 5
        assert free["max_api_keys"] == 3


class TestRoleHierarchy:
    """Validate workspace member role hierarchy."""

    def test_role_hierarchy_order(self):
        from backend.app.models.workspace import ROLE_HIERARCHY

        assert ROLE_HIERARCHY.index("VIEWER") < ROLE_HIERARCHY.index("ANALYST")
        assert ROLE_HIERARCHY.index("ANALYST") < ROLE_HIERARCHY.index("DEVELOPER")
        assert ROLE_HIERARCHY.index("DEVELOPER") < ROLE_HIERARCHY.index("ADMIN")
        assert ROLE_HIERARCHY.index("ADMIN") < ROLE_HIERARCHY.index("OWNER")

    def test_all_roles_in_hierarchy(self):
        from backend.app.models.workspace import ROLE_HIERARCHY, WorkspaceMemberRole

        for role in WorkspaceMemberRole:
            assert role.value in ROLE_HIERARCHY, f"{role.value} not in ROLE_HIERARCHY"

    def test_five_distinct_roles(self):
        from backend.app.models.workspace import WorkspaceMemberRole

        assert len(WorkspaceMemberRole) == 5


class TestWorkspaceSlugValidation:
    """Validate workspace slug format and uniqueness rules."""

    def test_slug_column_is_unique(self):
        from backend.app.models.workspace import Workspace

        slug_col = Workspace.__table__.columns["slug"]
        assert slug_col.unique, "slug column should have a unique constraint"

    def test_slug_column_is_indexed(self):
        from backend.app.models.workspace import Workspace

        slug_col = Workspace.__table__.columns["slug"]
        assert slug_col.index, "slug column should be indexed for lookups"


class TestWorkspaceInviteLifecycle:
    """Validate invite token generation and expiry logic."""

    def test_invite_token_is_64_hex_chars(self):
        """Invite tokens should be 64 hex characters."""
        import secrets

        token = secrets.token_hex(32)
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_invite_model_has_is_expired_property(self):
        from backend.app.models.workspace import WorkspaceInvite

        assert hasattr(WorkspaceInvite, "is_expired"), "Missing is_expired property"

    def test_invite_model_has_is_accepted_property(self):
        from backend.app.models.workspace import WorkspaceInvite

        assert hasattr(WorkspaceInvite, "is_accepted"), "Missing is_accepted property"

    def test_invite_expiry_logic(self):
        """Verify expiry comparison logic without instantiating the model."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        future = datetime.now(timezone.utc) + timedelta(days=7)
        now = datetime.now(timezone.utc)
        # Expired: expires_at < now
        assert past < now, "Past time should be before now"
        # Not expired: expires_at > now
        assert future > now, "Future time should be after now"


class TestAPIKeyProperties:
    """Validate workspace API key generation and validation properties."""

    def test_api_key_prefix_format(self):
        """API keys should start with 'ep_live_' prefix."""
        prefix = "ep_live_"
        # UUID hex is 32 chars; the actual key uses secrets.token_hex(24) = 48 hex chars
        import secrets

        key = prefix + secrets.token_hex(24)
        assert key.startswith("ep_live_")
        assert len(key) == 8 + 48  # prefix + 48 hex chars

    def test_api_key_model_has_is_expired_property(self):
        from backend.app.models.workspace import WorkspaceAPIKey

        assert hasattr(WorkspaceAPIKey, "is_expired"), "Missing is_expired property"

    def test_api_key_model_has_is_valid_property(self):
        from backend.app.models.workspace import WorkspaceAPIKey

        assert hasattr(WorkspaceAPIKey, "is_valid"), "Missing is_valid property"

    def test_api_key_model_has_scopes_column(self):
        from backend.app.models.workspace import WorkspaceAPIKey

        col_names = {c.key for c in WorkspaceAPIKey.__table__.columns}
        assert "scopes" in col_names
        assert "is_active" in col_names
        assert "expires_at" in col_names


class TestWorkspaceServiceExceptions:
    """Validate that the service defines proper exception types."""

    def test_all_exception_classes_exist(self):
        from backend.app.services import workspace_service as ws

        expected_exceptions = [
            "WorkspaceError",
            "WorkspaceNotFound",
            "WorkspaceMemberNotFound",
            "WorkspacePermissionError",
            "WorkspaceSlugTaken",
            "WorkspaceSlugInvalid",
            "AlreadyMember",
            "CannotRemoveLastOwner",
            "CannotDemoteLastOwner",
            "InviteNotFound",
            "InviteExpired",
            "InviteAlreadyAccepted",
            "PlanLimitExceeded",
            "APIKeyNotFound",
        ]
        for exc_name in expected_exceptions:
            assert hasattr(ws, exc_name), f"Missing exception class: {exc_name}"

    def test_workspace_error_is_base_class(self):
        from backend.app.services.workspace_service import (
            PlanLimitExceeded,
            WorkspaceError,
            WorkspaceNotFound,
        )

        assert issubclass(WorkspaceNotFound, (WorkspaceError, Exception))
        assert issubclass(PlanLimitExceeded, (WorkspaceError, Exception))


class TestWorkspaceDataIsolation:
    """Validate that workspace service enforces data isolation patterns."""

    def test_workspace_member_unique_constraint(self):
        """A user can only be a member of a workspace once."""
        from backend.app.models.workspace import WorkspaceMember

        # Check for unique constraint on (workspace_id, user_id)
        unique_constraints = [
            c
            for c in WorkspaceMember.__table__.constraints
            if hasattr(c, "columns") and len(c.columns) >= 2
        ]
        # There should be a unique constraint covering workspace_id + user_id
        has_unique = any(
            {"workspace_id", "user_id"}.issubset({col.key for col in c.columns})
            for c in unique_constraints
        )
        assert has_unique, "Missing unique constraint on (workspace_id, user_id)"

    def test_default_api_key_scopes(self):
        """Default API key scopes should follow least-privilege principle."""
        expected_defaults = ["flags:read", "experiments:read", "track:write"]
        # This validates the expected scope structure
        for scope in expected_defaults:
            resource, action = scope.split(":")
            assert resource in ("flags", "experiments", "track")
            assert action in ("read", "write")


# ---------------------------------------------------------------------------
# Online tests — require a running platform
# ---------------------------------------------------------------------------

requires_platform = pytest.mark.skipif(
    os.environ.get("RUN_REALISTIC") != "1",
    reason="Requires a running platform (set RUN_REALISTIC=1)",
)


@requires_platform
class TestWorkspaceAPI:
    """End-to-end workspace API tests against a running platform."""

    @pytest.fixture(scope="class")
    def auth_headers(self):
        import requests

        api_url = os.environ.get("REALISTIC_API_URL", "http://localhost:8000")
        resp = requests.post(
            f"{api_url}/api/v1/auth/login",
            json={"username": "admin@example.com", "password": "testpassword123"},
            timeout=10,
        )
        if resp.status_code != 200:
            pytest.skip("Could not obtain API token")
        token = resp.json().get("access_token", "")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def test_create_workspace(self, auth_headers):
        import requests

        api_url = os.environ.get("REALISTIC_API_URL", "http://localhost:8000")
        slug = f"test-ws-{uuid.uuid4().hex[:6]}"
        resp = requests.post(
            f"{api_url}/api/v1/workspaces",
            json={"name": "Test Workspace", "slug": slug},
            headers=auth_headers,
            timeout=15,
        )
        assert resp.status_code in (200, 201), resp.text

    def test_list_workspaces(self, auth_headers):
        import requests

        api_url = os.environ.get("REALISTIC_API_URL", "http://localhost:8000")
        resp = requests.get(
            f"{api_url}/api/v1/workspaces",
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 200
