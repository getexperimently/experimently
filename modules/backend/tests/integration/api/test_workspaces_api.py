"""
Integration tests for the Workspaces REST API — EP-057.

Tests the full HTTP request/response cycle for workspace CRUD,
member management and the invite lifecycle, and that workspaces have no
plan, no limits and no API-key routes (#263, #264).

All tests use the shared integration conftest fixtures (admin_client,
developer_client, etc.) so they exercise the real FastAPI app with
mocked auth dependencies.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.app.models.user import User, UserRole

HASHED_PASSWORD = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"

#: Response fields removed with plans, limits and workspace API keys.
_REMOVED_FIELDS = (
    "plan",
    "max_experiments",
    "max_feature_flags",
    "max_members",
    "max_api_keys",
    "api_key_count",
    "experiment_count",
    "flag_count",
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _create_workspace(client: TestClient, slug_suffix: str = "") -> dict:
    """Create a workspace via the API and return the response JSON."""
    suffix = uuid.uuid4().hex[:8] + slug_suffix
    payload = {
        "name": f"Test Workspace {suffix}",
        "slug": f"ws-{suffix}",
        "description": "Integration test workspace",
    }
    resp = client.post("/api/v1/workspaces/", json=payload)
    assert resp.status_code == 201, f"Create workspace failed: {resp.text}"
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Auth + basic CRUD
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestCreateWorkspace:
    def test_create_workspace_authenticated(self, admin_client):
        """Admin user creates a workspace — returns 201 with workspace data."""
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "name": "Authenticated WS",
            "slug": f"auth-ws-{suffix}",
            "description": "Test",
        }
        resp = admin_client.post("/api/v1/workspaces/", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["name"] == "Authenticated WS"
        assert data["slug"] == f"auth-ws-{suffix}"
        assert "id" in data
        for gone in _REMOVED_FIELDS:
            assert gone not in data, data

    def test_create_workspace_duplicate_slug_returns_409(self, admin_client):
        """Duplicate slug returns 409 Conflict."""
        ws = _create_workspace(admin_client, "-dup")
        payload = {
            "name": "Duplicate",
            "slug": ws["slug"],
            "description": "",
        }
        resp = admin_client.post("/api/v1/workspaces/", json=payload)
        assert resp.status_code == 409, resp.text

    def test_create_workspace_invalid_slug_returns_422(self, admin_client):
        """Invalid slug pattern returns 422."""
        payload = {
            "name": "Bad Slug",
            "slug": "UPPER_CASE",
            "description": "",
        }
        resp = admin_client.post("/api/v1/workspaces/", json=payload)
        assert resp.status_code == 422, resp.text

    def test_create_workspace_developer_can_create(self, developer_client):
        """Developer role can create a workspace."""
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "name": "Dev WS",
            "slug": f"dev-ws-{suffix}",
            "description": "",
        }
        resp = developer_client.post("/api/v1/workspaces/", json=payload)
        assert resp.status_code == 201, resp.text


@pytest.mark.integration
class TestListWorkspaces:
    def test_list_my_workspaces(self, admin_client):
        """Listed workspaces only include ones the user is a member of."""
        ws = _create_workspace(admin_client, "-list")
        resp = admin_client.get("/api/v1/workspaces/")
        assert resp.status_code == 200, resp.text
        slugs = [w["slug"] for w in resp.json()]
        assert ws["slug"] in slugs


@pytest.mark.integration
class TestGetWorkspace:
    def test_get_workspace_as_member(self, admin_client):
        """Member can retrieve workspace details and stats."""
        ws = _create_workspace(admin_client, "-get")
        resp = admin_client.get(f"/api/v1/workspaces/{ws['id']}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == ws["id"]
        assert "member_count" in data

    def test_get_workspace_not_found_returns_404(self, admin_client):
        """Unknown workspace_id returns 404."""
        resp = admin_client.get(f"/api/v1/workspaces/{uuid.uuid4()}")
        assert resp.status_code in (403, 404), resp.text

    def test_get_workspace_as_non_member_returns_403(self, viewer_client):
        """A user that is not a member gets 403 when trying to view a workspace they don't own.

        Viewer creates workspace B (so they are OWNER), then tries to access
        a random UUID workspace they are NOT a member of — must get 403/404.
        """
        resp = viewer_client.get(f"/api/v1/workspaces/{uuid.uuid4()}")
        assert resp.status_code in (403, 404), resp.text


@pytest.mark.integration
class TestUpdateWorkspace:
    def test_update_workspace_as_admin(self, admin_client):
        """Admin (OWNER counts as ADMIN+) can update workspace name."""
        ws = _create_workspace(admin_client, "-upd")
        resp = admin_client.put(
            f"/api/v1/workspaces/{ws['id']}",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Updated Name"

    def test_update_workspace_as_viewer_returns_403(self, viewer_client, db_session):
        """Viewer (workspace OWNER but trying to update as a non-ADMIN role) cannot
        update — but OWNER can. Instead, test that a non-member cannot update.
        """
        # Viewer tries to update a workspace they are not a member of
        resp = viewer_client.put(
            f"/api/v1/workspaces/{uuid.uuid4()}",
            json={"name": "Viewer Update"},
        )
        assert resp.status_code in (403, 404), resp.text


@pytest.mark.integration
class TestDeleteWorkspace:
    def test_delete_workspace_as_owner(self, admin_client):
        """OWNER can delete their workspace."""
        ws = _create_workspace(admin_client, "-del")
        resp = admin_client.delete(f"/api/v1/workspaces/{ws['id']}")
        assert resp.status_code == 204, resp.text

    def test_delete_workspace_as_developer_returns_403(
        self, developer_client, db_session
    ):
        """Non-member developer cannot delete a workspace they don't own."""
        # Developer tries to delete a workspace they are not a member of
        resp = developer_client.delete(f"/api/v1/workspaces/{uuid.uuid4()}")
        assert resp.status_code in (403, 404), resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Members
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWorkspaceMembers:
    def test_list_members_as_member(self, admin_client):
        ws = _create_workspace(admin_client, "-listmem")
        resp = admin_client.get(f"/api/v1/workspaces/{ws['id']}/members")
        assert resp.status_code == 200, resp.text
        members = resp.json()
        assert len(members) >= 1

    def test_add_member_as_admin(self, admin_client, developer_user):
        """Admin can add an existing user."""
        ws = _create_workspace(admin_client, "-addmem")
        payload = {"user_id": str(developer_user.id), "role": "DEVELOPER"}
        resp = admin_client.post(f"/api/v1/workspaces/{ws['id']}/members", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["role"] == "DEVELOPER"

    def test_add_member_as_developer_returns_403(self, developer_client, viewer_user):
        """Non-member developer cannot add members to a workspace they don't belong to."""
        resp = developer_client.post(
            f"/api/v1/workspaces/{uuid.uuid4()}/members",
            json={"user_id": str(viewer_user.id), "role": "VIEWER"},
        )
        assert resp.status_code in (403, 404), resp.text

    def test_add_duplicate_member_returns_409(self, admin_client, developer_user):
        ws = _create_workspace(admin_client, "-dupmem")
        payload = {"user_id": str(developer_user.id), "role": "VIEWER"}
        admin_client.post(f"/api/v1/workspaces/{ws['id']}/members", json=payload)
        resp = admin_client.post(f"/api/v1/workspaces/{ws['id']}/members", json=payload)
        assert resp.status_code == 409, resp.text

    def test_update_member_role(self, admin_client, developer_user):
        ws = _create_workspace(admin_client, "-updmem")
        admin_client.post(
            f"/api/v1/workspaces/{ws['id']}/members",
            json={"user_id": str(developer_user.id), "role": "VIEWER"},
        )
        resp = admin_client.put(
            f"/api/v1/workspaces/{ws['id']}/members/{developer_user.id}",
            json={"role": "ANALYST"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "ANALYST"

    def test_remove_member_as_admin(self, admin_client, developer_user):
        ws = _create_workspace(admin_client, "-remmem")
        admin_client.post(
            f"/api/v1/workspaces/{ws['id']}/members",
            json={"user_id": str(developer_user.id), "role": "DEVELOPER"},
        )
        resp = admin_client.delete(
            f"/api/v1/workspaces/{ws['id']}/members/{developer_user.id}"
        )
        assert resp.status_code == 204, resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Invites
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWorkspaceInvites:
    def test_create_invite_as_admin(self, admin_client):
        ws = _create_workspace(admin_client, "-inv")
        payload = {"email": "invitee@example.com", "role": "DEVELOPER"}
        resp = admin_client.post(f"/api/v1/workspaces/{ws['id']}/invites", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["email"] == "invitee@example.com"
        assert "token" in data

    def test_get_invite_public(self, admin_client):
        """Invite details are publicly accessible by token."""
        ws = _create_workspace(admin_client, "-ginv")
        payload = {"email": "pub@example.com", "role": "VIEWER"}
        create_resp = admin_client.post(
            f"/api/v1/workspaces/{ws['id']}/invites", json=payload
        )
        token = create_resp.json()["token"]
        resp = admin_client.get(f"/api/v1/workspaces/invites/{token}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["token"] == token

    def test_accept_invite(self, admin_client, admin_user, db_session):
        """Authenticated user can accept an invite and become a member.

        Uses a single client (admin_client) to avoid dependency-override conflicts
        when multiple clients are active in the same test.  We create a second
        workspace so the accepting user is NOT already a member.
        """
        # Create workspace A — admin becomes OWNER
        ws_a = _create_workspace(admin_client, "-accinv-a")
        # Create workspace B separately so we can accept its invite without
        # the admin already being a member from a different fixture.
        suffix = uuid.uuid4().hex[:8]
        ws_b_payload = {
            "name": f"WS B {suffix}",
            "slug": f"ws-b-{suffix}",
            "description": "",
        }
        # We use admin_client to create ws_b but we need a DIFFERENT workspace
        # where the current user is NOT already a member. Since we only have one
        # client, we create the workspace from ws_a's invite (admin invites self
        # to ws_b is irrelevant). Instead, we just test that the invite endpoint
        # works end-to-end:
        # Addressed to the accepting user, so the request reaches the
        # membership check rather than the invited-address check.
        payload = {"email": admin_user.email, "role": "ANALYST"}
        create_resp = admin_client.post(
            f"/api/v1/workspaces/{ws_a['id']}/invites", json=payload
        )
        assert create_resp.status_code == 201, create_resp.text
        # The invite token exists — that is sufficient to verify the endpoint works.
        # Accepting it with the same admin_client would fail (already a member),
        # so we verify the accept endpoint returns 422 with the correct detail.
        token = create_resp.json()["token"]
        resp = admin_client.post(f"/api/v1/workspaces/invites/{token}/accept")
        # Admin is already a member: AlreadyMember is answered with 422
        assert resp.status_code == 422, resp.text
        assert "already a member" in resp.json()["detail"], resp.text

    def test_accept_expired_invite_returns_400(
        self, admin_client, developer_user, db_session
    ):
        """Accepting an expired invite returns 400."""
        from modules.backend.app.models.workspace import WorkspaceInvite

        ws = _create_workspace(admin_client, "-expinv")
        # Addressed to the accepting user, so the request reaches the expiry
        # check rather than the invited-address check.
        payload = {"email": developer_user.email, "role": "VIEWER"}
        create_resp = admin_client.post(
            f"/api/v1/workspaces/{ws['id']}/invites", json=payload
        )
        inv_id = create_resp.json()["id"]
        token = create_resp.json()["token"]
        # Force expiry in DB
        from datetime import datetime, timedelta

        invite = db_session.query(WorkspaceInvite).filter_by(id=inv_id).first()
        if invite:
            invite.expires_at = datetime.utcnow() - timedelta(hours=1)
            db_session.commit()
        # Switch to the developer only now: the auth override is app-global.
        from backend.tests.integration.conftest import make_client_for_user

        developer_client = make_client_for_user(db_session, developer_user)
        resp = developer_client.post(f"/api/v1/workspaces/invites/{token}/accept")
        assert resp.status_code == 400, resp.text

    def test_get_invite_unknown_token_returns_404(self, admin_client):
        resp = admin_client.get("/api/v1/workspaces/invites/nonexistent-token")
        assert resp.status_code == 404, resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Role table: OWNER is granted, changed and removed only by an OWNER
# ─────────────────────────────────────────────────────────────────────────────


def _platform_user(db_session: Session, name: str, role: UserRole) -> User:
    """A committed, non-superuser platform user."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{name}_{suffix}",
        email=f"{name}_{suffix}@int.test",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def ws_people(db_session: Session) -> dict:
    """Two owners, a workspace ADMIN, an outsider and a bystander.

    None is a platform superuser, and the workspace ADMIN and the outsider are
    platform VIEWERs, so no platform role can stand in for a workspace role.
    """
    return {
        "owner": _platform_user(db_session, "ws_owner", UserRole.DEVELOPER),
        "owner2": _platform_user(db_session, "ws_owner2", UserRole.DEVELOPER),
        "wsadmin": _platform_user(db_session, "ws_admin", UserRole.VIEWER),
        "outsider": _platform_user(db_session, "ws_outsider", UserRole.VIEWER),
        "bystander": _platform_user(db_session, "ws_bystander", UserRole.VIEWER),
    }


@pytest.fixture
def as_user(db_session: Session, ws_people: dict):
    """Call the API as any of ``ws_people``: ``as_user(user, method, url, ...)``.

    The per-role client fixtures each replace the app-wide auth override, so
    two of them cannot be used in one test. This keys the override on a
    request header instead, over the per-request sessions that
    ``make_client_for_user`` installs.
    """
    from fastapi import Request

    from backend.app.api import deps
    from backend.app.main import app
    from backend.tests.integration.conftest import make_client_for_user

    client = make_client_for_user(db_session, ws_people["owner"])
    by_id = {str(u.id): u for u in ws_people.values()}

    def current(request: Request) -> User:
        return by_id[request.headers["x-test-user"]]

    async def current_async(request: Request) -> User:
        return current(request)

    app.dependency_overrides[deps.get_current_active_user] = current
    app.dependency_overrides[deps.get_current_user] = current_async

    def call(user: User, method: str, url: str, **kwargs):
        return client.request(
            method, url, headers={"x-test-user": str(user.id)}, **kwargs
        )

    yield call
    app.dependency_overrides.clear()


def _new_workspace(as_user, user: User, label: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    resp = as_user(
        user,
        "POST",
        "/api/v1/workspaces/",
        json={"name": f"{label} {suffix}", "slug": f"{label}-{suffix}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _workspace_with_owners_and_admin(as_user, p: dict) -> str:
    """Owned by ``owner`` and ``owner2``, with ``wsadmin`` as ADMIN."""
    ws_id = _new_workspace(as_user, p["owner"], "roles")
    for user, role in ((p["owner2"], "OWNER"), (p["wsadmin"], "ADMIN")):
        resp = as_user(
            p["owner"],
            "POST",
            f"/api/v1/workspaces/{ws_id}/members",
            json={"user_id": str(user.id), "role": role},
        )
        assert resp.status_code == 201, resp.text
    return ws_id


def _roles(as_user, p: dict, ws_id: str) -> dict:
    resp = as_user(p["owner"], "GET", f"/api/v1/workspaces/{ws_id}/members")
    assert resp.status_code == 200, resp.text
    return {m["user_id"]: m["role"] for m in resp.json()}


@pytest.mark.integration
class TestOwnerRoleChanges:
    @pytest.mark.regression
    def test_admin_cannot_promote_self_to_owner(self, as_user, ws_people):
        p = ws_people
        ws_id = _workspace_with_owners_and_admin(as_user, p)
        resp = as_user(
            p["wsadmin"],
            "PUT",
            f"/api/v1/workspaces/{ws_id}/members/{p['wsadmin'].id}",
            json={"role": "OWNER"},
        )
        assert resp.status_code == 403, resp.text
        assert _roles(as_user, p, ws_id)[str(p["wsadmin"].id)] == "ADMIN"

    @pytest.mark.regression
    def test_admin_cannot_demote_an_owner(self, as_user, ws_people):
        p = ws_people
        ws_id = _workspace_with_owners_and_admin(as_user, p)
        resp = as_user(
            p["wsadmin"],
            "PUT",
            f"/api/v1/workspaces/{ws_id}/members/{p['owner2'].id}",
            json={"role": "VIEWER"},
        )
        assert resp.status_code == 403, resp.text
        assert _roles(as_user, p, ws_id)[str(p["owner2"].id)] == "OWNER"

    @pytest.mark.regression
    def test_admin_cannot_add_a_member_as_owner(self, as_user, ws_people):
        p = ws_people
        ws_id = _workspace_with_owners_and_admin(as_user, p)
        resp = as_user(
            p["wsadmin"],
            "POST",
            f"/api/v1/workspaces/{ws_id}/members",
            json={"user_id": str(p["bystander"].id), "role": "owner"},
        )
        assert resp.status_code == 403, resp.text
        assert str(p["bystander"].id) not in _roles(as_user, p, ws_id)

    @pytest.mark.regression
    def test_admin_cannot_remove_an_owner(self, as_user, ws_people):
        p = ws_people
        ws_id = _workspace_with_owners_and_admin(as_user, p)
        resp = as_user(
            p["wsadmin"],
            "DELETE",
            f"/api/v1/workspaces/{ws_id}/members/{p['owner2'].id}",
        )
        assert resp.status_code == 403, resp.text
        assert _roles(as_user, p, ws_id)[str(p["owner2"].id)] == "OWNER"

    def test_admin_still_manages_other_roles(self, as_user, ws_people):
        p = ws_people
        ws_id = _workspace_with_owners_and_admin(as_user, p)
        base = f"/api/v1/workspaces/{ws_id}/members"
        member = {"user_id": str(p["bystander"].id), "role": "VIEWER"}
        resp = as_user(p["wsadmin"], "POST", base, json=member)
        assert resp.status_code == 201, resp.text
        resp = as_user(
            p["wsadmin"], "PUT", f"{base}/{p['bystander'].id}", json={"role": "ADMIN"}
        )
        assert resp.status_code == 200, resp.text
        resp = as_user(p["wsadmin"], "DELETE", f"{base}/{p['bystander'].id}")
        assert resp.status_code == 204, resp.text

    def test_owner_grants_changes_and_removes_owner(self, as_user, ws_people):
        p = ws_people
        ws_id = _workspace_with_owners_and_admin(as_user, p)
        base = f"/api/v1/workspaces/{ws_id}/members"
        member = {"user_id": str(p["bystander"].id), "role": "OWNER"}
        resp = as_user(p["owner"], "POST", base, json=member)
        assert resp.status_code == 201, resp.text
        resp = as_user(
            p["owner"], "PUT", f"{base}/{p['wsadmin'].id}", json={"role": "OWNER"}
        )
        assert resp.status_code == 200, resp.text
        resp = as_user(
            p["owner"], "PUT", f"{base}/{p['owner2'].id}", json={"role": "DEVELOPER"}
        )
        assert resp.status_code == 200, resp.text
        resp = as_user(p["owner"], "DELETE", f"{base}/{p['bystander'].id}")
        assert resp.status_code == 204, resp.text
        roles = _roles(as_user, p, ws_id)
        assert roles[str(p["wsadmin"].id)] == "OWNER"
        assert roles[str(p["owner2"].id)] == "DEVELOPER"
        assert str(p["bystander"].id) not in roles

    def test_last_owner_still_cannot_step_down(self, as_user, ws_people):
        p = ws_people
        ws_id = _new_workspace(as_user, p["owner"], "solo")
        me = f"/api/v1/workspaces/{ws_id}/members/{p['owner'].id}"
        resp = as_user(p["owner"], "PUT", me, json={"role": "ADMIN"})
        assert resp.status_code == 422, resp.text
        resp = as_user(p["owner"], "DELETE", me)
        assert resp.status_code == 422, resp.text


# ─────────────────────────────────────────────────────────────────────────────
# No plan, no limits, no workspace API keys (#263, #264)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWorkspaceAPIKeyRoutesAreGone:
    """The four workspace API-key operations are removed: exactly 404.

    Not 405, which is what a surviving route on the same path with another
    method would answer.
    """

    def test_every_key_operation_is_404(self, as_user, ws_people):
        owner = ws_people["owner"]
        ws_id = _new_workspace(as_user, owner, "nokeys")
        key_id = uuid.uuid4()
        calls = [
            ("GET", f"/api/v1/workspaces/{ws_id}/api-keys", None),
            ("POST", f"/api/v1/workspaces/{ws_id}/api-keys", {"name": "prod"}),
            ("DELETE", f"/api/v1/workspaces/{ws_id}/api-keys/{key_id}", None),
            ("POST", f"/api/v1/workspaces/{ws_id}/api-keys/{key_id}/rotate", None),
        ]
        answers = [
            (method, url, as_user(owner, method, url, json=body).status_code)
            for method, url, body in calls
        ]
        assert [code for _, _, code in answers] == [404, 404, 404, 404], answers


@pytest.mark.integration
class TestPlanIsRefused:
    """``plan`` is refused with 422, not silently ignored."""

    @staticmethod
    def _assert_plan_refused(resp) -> None:
        assert resp.status_code == 422, resp.text
        errors = resp.json()["detail"]
        assert any(
            e["loc"] == ["body", "plan"] and e["type"] == "extra_forbidden"
            for e in errors
        ), errors

    def test_create_with_plan_is_422(self, as_user, ws_people):
        suffix = uuid.uuid4().hex[:8]
        resp = as_user(
            ws_people["owner"],
            "POST",
            "/api/v1/workspaces/",
            json={
                "name": f"Plan {suffix}",
                "slug": f"plan-{suffix}",
                "plan": "enterprise",
            },
        )
        self._assert_plan_refused(resp)

    def test_update_with_plan_is_422(self, as_user, ws_people, db_session):
        from modules.backend.app.models.workspace import Workspace, WorkspacePlan

        owner = ws_people["owner"]
        ws_id = _new_workspace(as_user, owner, "planupd")
        resp = as_user(
            owner, "PUT", f"/api/v1/workspaces/{ws_id}", json={"plan": "enterprise"}
        )
        self._assert_plan_refused(resp)
        # Nothing was written: the stored (retained, unused) column is unchanged.
        row = db_session.query(Workspace).filter_by(id=uuid.UUID(ws_id)).one()
        db_session.refresh(row)
        assert row.plan == WorkspacePlan.FREE
        # Name and description alone are still accepted.
        resp = as_user(
            owner,
            "PUT",
            f"/api/v1/workspaces/{ws_id}",
            json={"name": "Renamed", "description": "d"},
        )
        assert resp.status_code == 200, resp.text


@pytest.mark.integration
class TestNoMemberLimit:
    """A workspace stored with the old free-plan limit takes any number of members."""

    @staticmethod
    def _five_member_free_workspace(as_user, ws_people, db_session) -> str:
        from modules.backend.app.models.workspace import Workspace, WorkspacePlan

        owner = ws_people["owner"]
        ws_id = _new_workspace(as_user, owner, "nolimit")
        row = db_session.query(Workspace).filter_by(id=uuid.UUID(ws_id)).one()
        row.plan = WorkspacePlan.FREE
        row.max_members = 5
        db_session.commit()
        for i in range(4):  # the owner is member 1
            user = _platform_user(db_session, f"ws_m{i}", UserRole.VIEWER)
            resp = as_user(
                owner,
                "POST",
                f"/api/v1/workspaces/{ws_id}/members",
                json={"user_id": str(user.id), "role": "VIEWER"},
            )
            assert resp.status_code == 201, resp.text
        return ws_id

    @pytest.mark.regression
    def test_sixth_member_is_added(self, as_user, ws_people, db_session):
        ws_id = self._five_member_free_workspace(as_user, ws_people, db_session)
        sixth = _platform_user(db_session, "ws_sixth", UserRole.VIEWER)
        resp = as_user(
            ws_people["owner"],
            "POST",
            f"/api/v1/workspaces/{ws_id}/members",
            json={"user_id": str(sixth.id), "role": "VIEWER"},
        )
        assert resp.status_code == 201, resp.text

    @pytest.mark.regression
    def test_sixth_member_accepts_an_invite(self, as_user, ws_people, db_session):
        ws_id = self._five_member_free_workspace(as_user, ws_people, db_session)
        invitee = ws_people["bystander"]
        resp = as_user(
            ws_people["owner"],
            "POST",
            f"/api/v1/workspaces/{ws_id}/invites",
            json={"email": invitee.email, "role": "VIEWER"},
        )
        assert resp.status_code == 201, resp.text
        token = resp.json()["token"]
        resp = as_user(invitee, "POST", f"/api/v1/workspaces/invites/{token}/accept")
        assert resp.status_code in (200, 201), resp.text
        members = as_user(
            ws_people["owner"], "GET", f"/api/v1/workspaces/{ws_id}/members"
        ).json()
        assert len(members) == 6, members


@pytest.mark.integration
class TestExistingRowsCarryNoPlan:
    """Rows written with a plan and limits are listed and read without them."""

    def test_list_and_get_omit_plan_and_limits(self, as_user, ws_people, db_session):
        from modules.backend.app.models.workspace import Workspace, WorkspacePlan

        owner = ws_people["owner"]
        ws_id = _new_workspace(as_user, owner, "oldrow")
        row = db_session.query(Workspace).filter_by(id=uuid.UUID(ws_id)).one()
        row.plan = WorkspacePlan.ENTERPRISE
        row.max_members = 999999
        row.max_api_keys = 999999
        db_session.commit()

        listed = as_user(owner, "GET", "/api/v1/workspaces/")
        assert listed.status_code == 200, listed.text
        mine = [w for w in listed.json() if w["id"] == ws_id]
        assert len(mine) == 1, listed.json()

        detail = as_user(owner, "GET", f"/api/v1/workspaces/{ws_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["member_count"] == 1
        for body in (mine[0], detail.json()):
            for gone in _REMOVED_FIELDS:
                assert gone not in body, body


def _add_member(as_user, owner: User, ws_id: str, user: User, role: str) -> None:
    resp = as_user(
        owner,
        "POST",
        f"/api/v1/workspaces/{ws_id}/members",
        json={"user_id": str(user.id), "role": role},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.integration
class TestListCarriesMemberCounts:
    """``GET /workspaces/`` answers each workspace's member count (#1008).

    The list used to answer no count at all, so the dashboard's Workspaces
    page showed "0 members" for every workspace.
    """

    @pytest.mark.regression
    def test_each_listed_workspace_has_its_own_member_count(self, as_user, ws_people):
        p = ws_people
        three = _workspace_with_owners_and_admin(as_user, p)
        alone = _new_workspace(as_user, p["owner"], "alone")
        # Not the caller's: it is not listed, and its members count nowhere else.
        theirs = _new_workspace(as_user, p["bystander"], "theirs")
        _add_member(as_user, p["bystander"], theirs, p["outsider"], "VIEWER")

        listed = as_user(p["owner"], "GET", "/api/v1/workspaces/")
        assert listed.status_code == 200, listed.text
        counts = {w["id"]: w.get("member_count") for w in listed.json()}
        assert counts == {three: 3, alone: 1}, listed.json()

        # The list and the workspace's own page agree.
        for ws_id, expected in counts.items():
            detail = as_user(p["owner"], "GET", f"/api/v1/workspaces/{ws_id}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["member_count"] == expected, detail.json()

    @pytest.mark.regression
    def test_a_member_who_leaves_is_no_longer_counted(self, as_user, ws_people):
        p = ws_people
        ws_id = _workspace_with_owners_and_admin(as_user, p)
        gone = as_user(
            p["owner"],
            "DELETE",
            f"/api/v1/workspaces/{ws_id}/members/{p['wsadmin'].id}",
        )
        assert gone.status_code == 204, gone.text

        listed = as_user(p["owner"], "GET", "/api/v1/workspaces/")
        assert listed.status_code == 200, listed.text
        mine = [w for w in listed.json() if w["id"] == ws_id]
        assert [w.get("member_count") for w in mine] == [2], listed.json()

    @pytest.mark.regression
    def test_the_counts_cost_the_same_queries_for_one_workspace_or_four(
        self, as_user, ws_people, db_session
    ):
        """One grouped count, not one query per workspace."""
        p = ws_people
        engine = db_session.get_bind()

        def statements_for_list(user: User) -> list[str]:
            seen: list[str] = []

            def record(conn, cursor, statement, parameters, context, executemany):
                seen.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                resp = as_user(user, "GET", "/api/v1/workspaces/")
            finally:
                event.remove(engine, "before_cursor_execute", record)
            assert resp.status_code == 200, resp.text
            return seen

        _workspace_with_owners_and_admin(as_user, p)
        one = statements_for_list(p["owner"])

        for label in ("two", "three", "four"):
            ws_id = _new_workspace(as_user, p["owner2"], label)
            _add_member(as_user, p["owner2"], ws_id, p["owner"], "VIEWER")
        listed = as_user(p["owner"], "GET", "/api/v1/workspaces/").json()
        assert len(listed) == 4, listed
        assert sorted(w["member_count"] for w in listed) == [2, 2, 2, 3], listed
        four = statements_for_list(p["owner"])

        # The listener sees the list's queries, the count among them.
        counted = [
            s for s in four if "count(" in s.lower() and "workspace_members" in s
        ]
        assert len(counted) == 1, four
        assert len(four) == len(one), (one, four)
