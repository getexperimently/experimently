"""
Unit tests for WorkspaceService — EP-057: Multi-Tenant Team Workspaces.

These tests use the shared conftest db_session fixture (backed by
Postgres via the test DB) so no custom SQLite engine is needed.  This
keeps the mapper registry clean and avoids duplicate-class errors.

Run:
    source venv/bin/activate
    export APP_ENV=test TESTING=true
    python -m pytest modules/backend/tests/unit/services/test_workspace_service.py -v --tb=short
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.app.models.user import User, UserRole
from modules.backend.app.models.workspace import (
    ROLE_HIERARCHY,
    Workspace,
    WorkspaceAPIKey,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceMemberRole,
    WorkspacePlan,
)
from modules.backend.app.services.workspace_service import (
    AlreadyMember,
    APIKeyNotFound,
    CannotDemoteLastOwner,
    CannotRemoveLastOwner,
    InviteAlreadyAccepted,
    InviteExpired,
    InviteNotFound,
    PlanLimitExceeded,
    WorkspaceMemberNotFound,
    WorkspaceNotFound,
    WorkspaceService,
    WorkspaceSlugInvalid,
    WorkspaceSlugTaken,
    _generate_api_key,
    _hash_key,
)

HASHED_PASSWORD = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"


def _make_user(db_session: Session) -> User:
    """Create and persist a minimal User record for FK purposes."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"ws_test_{suffix}",
        email=f"ws_{suffix}@test.com",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def svc():
    return WorkspaceService()


@pytest.fixture
def user_id(db_session: Session) -> uuid.UUID:
    """Return the UUID of a real user record."""
    return _make_user(db_session).id


@pytest.fixture
def other_user_id(db_session: Session) -> uuid.UUID:
    """Return the UUID of a second real user record."""
    return _make_user(db_session).id


@pytest.fixture
def workspace(db_session: Session, svc: WorkspaceService, user_id: uuid.UUID):
    """A freshly created workspace owned by user_id."""
    suffix = uuid.uuid4().hex[:8]
    return svc.create_workspace(
        db_session,
        name=f"Test Corp {suffix}",
        slug=f"tc-{suffix}",
        owner_id=user_id,
        plan="free",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Workspace CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateWorkspace:
    def test_create_workspace_success(self, db_session: Session, svc: WorkspaceService):
        uid = _make_user(db_session).id
        suffix = uuid.uuid4().hex[:8]
        ws = svc.create_workspace(db_session, "Acme", f"acme-{suffix}", uid)
        assert ws.id is not None
        assert ws.name == "Acme"
        assert ws.plan == WorkspacePlan.FREE

    def test_create_workspace_owner_added_as_member(
        self, db_session: Session, svc: WorkspaceService
    ):
        uid = _make_user(db_session).id
        suffix = uuid.uuid4().hex[:8]
        ws = svc.create_workspace(db_session, "Owner Check", f"owner-{suffix}", uid)
        members = svc.list_members(db_session, ws.id)
        assert len(members) == 1
        assert members[0].role == WorkspaceMemberRole.OWNER

    def test_create_workspace_slug_must_be_unique(
        self, db_session: Session, svc: WorkspaceService
    ):
        uid = _make_user(db_session).id
        suffix = uuid.uuid4().hex[:8]
        svc.create_workspace(db_session, "First", f"slug-{suffix}", uid)
        with pytest.raises(WorkspaceSlugTaken):
            svc.create_workspace(db_session, "Second", f"slug-{suffix}", uid)

    def test_create_workspace_slug_validation_too_short(
        self, db_session: Session, svc: WorkspaceService
    ):
        # slug validation happens before DB hit so we can use a dummy UUID
        with pytest.raises(WorkspaceSlugInvalid):
            svc.create_workspace(db_session, "Bad", "ab", uuid.uuid4())

    def test_create_workspace_slug_validation_uppercase(
        self, db_session: Session, svc: WorkspaceService
    ):
        with pytest.raises(WorkspaceSlugInvalid):
            svc.create_workspace(db_session, "Bad", "My-Slug", uuid.uuid4())

    def test_create_workspace_slug_starts_with_hyphen(
        self, db_session: Session, svc: WorkspaceService
    ):
        with pytest.raises(WorkspaceSlugInvalid):
            svc.create_workspace(db_session, "Bad", "-starts-bad", uuid.uuid4())

    def test_create_workspace_slug_ends_with_hyphen(
        self, db_session: Session, svc: WorkspaceService
    ):
        with pytest.raises(WorkspaceSlugInvalid):
            svc.create_workspace(db_session, "Bad", "ends-bad-", uuid.uuid4())

    def test_create_workspace_pro_plan_limits(
        self, db_session: Session, svc: WorkspaceService
    ):
        uid = _make_user(db_session).id
        suffix = uuid.uuid4().hex[:8]
        ws = svc.create_workspace(
            db_session, "Pro Co", f"pro-{suffix}", uid, plan="pro"
        )
        assert ws.max_members == 50
        assert ws.max_experiments == 1000

    def test_create_workspace_free_plan_limits(
        self, db_session: Session, svc: WorkspaceService
    ):
        uid = _make_user(db_session).id
        suffix = uuid.uuid4().hex[:8]
        ws = svc.create_workspace(
            db_session, "Free Co", f"free-{suffix}", uid, plan="free"
        )
        assert ws.max_members == 5
        assert ws.max_experiments == 10

    def test_create_workspace_description_optional(
        self, db_session: Session, svc: WorkspaceService
    ):
        uid = _make_user(db_session).id
        suffix = uuid.uuid4().hex[:8]
        ws = svc.create_workspace(db_session, "No Desc", f"nodesc-{suffix}", uid)
        assert ws.description == "" or ws.description is None


class TestGetWorkspace:
    def test_get_workspace_success(
        self, db_session: Session, svc: WorkspaceService, workspace: Workspace
    ):
        result = svc.get_workspace(db_session, workspace.id)
        assert result.id == workspace.id

    def test_get_workspace_not_found(self, db_session: Session, svc: WorkspaceService):
        with pytest.raises(WorkspaceNotFound):
            svc.get_workspace(db_session, uuid.uuid4())

    def test_get_workspace_by_slug(
        self, db_session: Session, svc: WorkspaceService, workspace: Workspace
    ):
        result = svc.get_workspace_by_slug(db_session, workspace.slug)
        assert result.id == workspace.id

    def test_get_workspace_by_slug_not_found(
        self, db_session: Session, svc: WorkspaceService
    ):
        with pytest.raises(WorkspaceNotFound):
            svc.get_workspace_by_slug(db_session, "does-not-exist-xyz")


class TestListUserWorkspaces:
    def test_list_user_workspaces_returns_only_their_workspaces(
        self, db_session: Session, svc: WorkspaceService
    ):
        uid_a = _make_user(db_session).id
        uid_b = _make_user(db_session).id
        suf_a = uuid.uuid4().hex[:8]
        suf_b = uuid.uuid4().hex[:8]
        svc.create_workspace(db_session, "A's WS", f"aws-{suf_a}", uid_a)
        svc.create_workspace(db_session, "B's WS", f"bws-{suf_b}", uid_b)
        result = svc.list_user_workspaces(db_session, uid_a)
        slugs = [w.slug for w in result]
        assert f"aws-{suf_a}" in slugs
        assert f"bws-{suf_b}" not in slugs

    def test_list_user_workspaces_empty_when_none(
        self, db_session: Session, svc: WorkspaceService
    ):
        result = svc.list_user_workspaces(db_session, uuid.uuid4())
        assert result == []


class TestUpdateWorkspace:
    def test_update_workspace_name_and_description(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        updated = svc.update_workspace(
            db_session,
            workspace.id,
            {"name": "New Name", "description": "New desc"},
        )
        assert updated.name == "New Name"
        assert updated.description == "New desc"

    def test_update_workspace_plan_changes_limits(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        updated = svc.update_workspace(db_session, workspace.id, {"plan": "pro"})
        assert updated.max_members == 50

    def test_update_workspace_unknown_fields_ignored(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        original_slug = workspace.slug
        updated = svc.update_workspace(
            db_session,
            workspace.id,
            {"slug": "new-slug", "name": "Safe Update"},
        )
        # slug is not in the allowed update list
        assert updated.slug == original_slug
        assert updated.name == "Safe Update"


class TestDeleteWorkspace:
    def test_delete_workspace_removes_workspace(
        self, db_session: Session, svc: WorkspaceService
    ):
        uid = _make_user(db_session).id
        suffix = uuid.uuid4().hex[:8]
        ws = svc.create_workspace(db_session, "Delete Me", f"del-{suffix}", uid)
        ws_id = ws.id
        svc.delete_workspace(db_session, ws_id)
        with pytest.raises(WorkspaceNotFound):
            svc.get_workspace(db_session, ws_id)

    @pytest.mark.regression
    def test_delete_workspace_releases_its_experiments_and_flags(
        self, db_session: Session, svc: WorkspaceService
    ):
        """The seam dropped the ON DELETE SET NULL that used to do this.

        `experiments.workspace_id` and `feature_flags.workspace_id` were the
        only ORM coupling between a core table and a module's, so migration
        a7b8c9d0e1f2 drops both constraints. Without an explicit update here,
        deleting a workspace leaves core rows pointing at an id that no
        longer exists.
        """
        from backend.app.models.experiment import Experiment
        from backend.app.models.feature_flag import FeatureFlag

        owner = _make_user(db_session)
        suffix = uuid.uuid4().hex[:8]
        ws = svc.create_workspace(db_session, "Doomed", f"doomed-{suffix}", owner.id)
        ws_id = ws.id

        experiment = Experiment(
            name=f"exp-{suffix}",
            key=f"exp-{suffix}",
            description="scoped to the workspace",
            owner_id=owner.id,
            workspace_id=ws_id,
        )
        flag = FeatureFlag(
            name=f"flag-{suffix}",
            key=f"flag-{suffix}",
            description="scoped to the workspace",
            owner_id=owner.id,
            workspace_id=ws_id,
        )
        db_session.add_all([experiment, flag])
        db_session.commit()
        experiment_id, flag_id = experiment.id, flag.id

        # The test schema is built from the full-profile metadata, which
        # attaches the ON DELETE SET NULL foreign keys -- so the database would
        # null the columns by itself and the service body under test would be
        # exercised by nothing. Drop them for this test, the state a migrated
        # full-profile database (a7b8c9d0e1f2) is in, and put them back after.
        from sqlalchemy import text

        fks = (
            ("experiments", "experiments_workspace_id_fkey"),
            ("feature_flags", "feature_flags_workspace_id_fkey"),
        )
        for table, name in fks:
            db_session.execute(
                text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
            )
        db_session.commit()
        try:
            svc.delete_workspace(db_session, ws_id)
        finally:
            for table, name in fks:
                db_session.execute(
                    text(
                        f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                        "FOREIGN KEY (workspace_id) REFERENCES workspaces(id) "
                        "ON DELETE SET NULL"
                    )
                )
            db_session.commit()

        db_session.expire_all()
        surviving_experiment = db_session.get(Experiment, experiment_id)
        surviving_flag = db_session.get(FeatureFlag, flag_id)
        # The rows survive -- they are core data, not the workspace's.
        assert surviving_experiment is not None
        assert surviving_flag is not None
        # ...and they are unscoped again, not pointing at a deleted workspace.
        assert surviving_experiment.workspace_id is None
        assert surviving_flag.workspace_id is None


# ─────────────────────────────────────────────────────────────────────────────
# Members
# ─────────────────────────────────────────────────────────────────────────────


class TestAddMember:
    def test_add_member_success(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        member = svc.add_member(
            db_session, workspace.id, other_user_id, "DEVELOPER", user_id
        )
        assert member.role == WorkspaceMemberRole.DEVELOPER
        assert member.user_id == other_user_id

    def test_add_member_already_member_raises_error(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        svc.add_member(db_session, workspace.id, other_user_id, "VIEWER", user_id)
        with pytest.raises(AlreadyMember):
            svc.add_member(db_session, workspace.id, other_user_id, "VIEWER", user_id)

    def test_cannot_exceed_max_members(
        self, db_session: Session, svc: WorkspaceService
    ):
        uid = _make_user(db_session).id
        suffix = uuid.uuid4().hex[:8]
        ws = svc.create_workspace(
            db_session, "Limit Test", f"limit-{suffix}", uid, plan="free"
        )
        # free plan limit is 5 — owner already added → 4 more
        for _ in range(4):
            extra_uid = _make_user(db_session).id
            svc.add_member(db_session, ws.id, extra_uid, "VIEWER", uid)
        # 6th member should fail
        with pytest.raises(PlanLimitExceeded):
            svc.add_member(db_session, ws.id, _make_user(db_session).id, "VIEWER", uid)


class TestRemoveMember:
    def test_remove_member_success(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        svc.add_member(db_session, workspace.id, other_user_id, "VIEWER", user_id)
        svc.remove_member(db_session, workspace.id, other_user_id)
        members = svc.list_members(db_session, workspace.id)
        member_ids = [str(m.user_id) for m in members]
        assert str(other_user_id) not in member_ids

    def test_cannot_remove_last_owner(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        user_id: uuid.UUID,
    ):
        with pytest.raises(CannotRemoveLastOwner):
            svc.remove_member(db_session, workspace.id, user_id)

    def test_remove_member_not_found_raises(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        with pytest.raises(WorkspaceMemberNotFound):
            svc.remove_member(db_session, workspace.id, uuid.uuid4())


class TestUpdateMemberRole:
    def test_update_member_role_success(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        svc.add_member(db_session, workspace.id, other_user_id, "VIEWER", user_id)
        updated = svc.update_member_role(
            db_session, workspace.id, other_user_id, "ANALYST"
        )
        assert updated.role == WorkspaceMemberRole.ANALYST

    def test_owner_cannot_demote_themselves_when_last_owner(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        user_id: uuid.UUID,
    ):
        with pytest.raises(CannotDemoteLastOwner):
            svc.update_member_role(db_session, workspace.id, user_id, "ADMIN")

    def test_owner_can_demote_when_another_owner_exists(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        svc.add_member(db_session, workspace.id, other_user_id, "OWNER", user_id)
        updated = svc.update_member_role(db_session, workspace.id, user_id, "ADMIN")
        assert updated.role == WorkspaceMemberRole.ADMIN


class TestListMembers:
    def test_list_members_returns_all(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        svc.add_member(db_session, workspace.id, other_user_id, "DEVELOPER", user_id)
        members = svc.list_members(db_session, workspace.id)
        assert len(members) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Invites
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateInvite:
    def test_create_invite_generates_unique_token(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        user_id: uuid.UUID,
    ):
        inv1 = svc.create_invite(
            db_session, workspace.id, "a@ex.com", "VIEWER", user_id
        )
        inv2 = svc.create_invite(
            db_session, workspace.id, "b@ex.com", "VIEWER", user_id
        )
        assert inv1.token != inv2.token

    def test_create_invite_expires_in_7_days(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        user_id: uuid.UUID,
    ):
        invite = svc.create_invite(
            db_session, workspace.id, "x@ex.com", "VIEWER", user_id
        )
        delta = invite.expires_at - datetime.utcnow()
        assert 6 < delta.total_seconds() / 86400 <= 7


class TestAcceptInvite:
    def test_accept_invite_creates_membership(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        invite = svc.create_invite(
            db_session, workspace.id, "new@ex.com", "DEVELOPER", user_id
        )
        member = svc.accept_invite(db_session, invite.token, other_user_id)
        assert member.role == WorkspaceMemberRole.DEVELOPER
        assert member.user_id == other_user_id

    def test_accept_expired_invite_raises_error(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        invite = svc.create_invite(
            db_session, workspace.id, "exp@ex.com", "VIEWER", user_id
        )
        # Force expiry
        invite.expires_at = datetime.utcnow() - timedelta(hours=1)
        db_session.commit()
        with pytest.raises(InviteExpired):
            svc.accept_invite(db_session, invite.token, other_user_id)

    def test_accept_already_accepted_invite_raises_error(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        user_id: uuid.UUID,
    ):
        invite = svc.create_invite(
            db_session, workspace.id, "aa@ex.com", "VIEWER", user_id
        )
        uid_a = _make_user(db_session).id
        svc.accept_invite(db_session, invite.token, uid_a)
        with pytest.raises(InviteAlreadyAccepted):
            svc.accept_invite(db_session, invite.token, _make_user(db_session).id)

    def test_get_invite_by_token_not_found(
        self, db_session: Session, svc: WorkspaceService
    ):
        with pytest.raises(InviteNotFound):
            svc.get_invite_by_token(db_session, "nonexistent-token")


# ─────────────────────────────────────────────────────────────────────────────
# API Keys
# ─────────────────────────────────────────────────────────────────────────────


class TestAPIKeyHelpers:
    def test_generate_api_key_has_prefix(self):
        key = _generate_api_key()
        assert key.startswith("ep_live_")

    def test_hash_key_is_sha256_hex(self):
        h = _hash_key("test-key")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_key_is_deterministic(self):
        assert _hash_key("abc") == _hash_key("abc")

    def test_hash_key_differs_for_different_inputs(self):
        assert _hash_key("key1") != _hash_key("key2")


class TestCreateAPIKey:
    def test_create_api_key_returns_plaintext_once(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        key_obj, plaintext = svc.create_api_key(db_session, workspace.id, "My Key")
        assert plaintext.startswith("ep_live_")
        assert len(plaintext) > 8

    def test_create_api_key_stores_hash_not_plaintext(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        key_obj, plaintext = svc.create_api_key(db_session, workspace.id, "Hash Check")
        assert key_obj.key_hash != plaintext
        assert key_obj.key_hash == _hash_key(plaintext)

    def test_api_key_prefix_visible_but_not_full_key(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        key_obj, plaintext = svc.create_api_key(
            db_session, workspace.id, "Prefix Check"
        )
        assert key_obj.key_prefix == plaintext[:8]
        assert key_obj.key_prefix != plaintext

    def test_create_api_key_default_scopes(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        key_obj, _ = svc.create_api_key(db_session, workspace.id, "Scoped Key")
        assert "flags:read" in key_obj.scopes

    def test_cannot_exceed_max_api_keys(
        self, db_session: Session, svc: WorkspaceService
    ):
        uid = _make_user(db_session).id
        suffix = uuid.uuid4().hex[:8]
        ws = svc.create_workspace(
            db_session, "Key Limit", f"keylim-{suffix}", uid, plan="free"
        )
        for i in range(3):  # free plan limit = 3
            svc.create_api_key(db_session, ws.id, f"Key {i}")
        with pytest.raises(PlanLimitExceeded):
            svc.create_api_key(db_session, ws.id, "One too many")


class TestRevokeAPIKey:
    def test_revoke_api_key(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        key_obj, _ = svc.create_api_key(db_session, workspace.id, "Revoke Me")
        svc.revoke_api_key(db_session, key_obj.id)
        db_session.refresh(key_obj)
        assert key_obj.is_active is False

    def test_revoke_nonexistent_key_raises(
        self, db_session: Session, svc: WorkspaceService
    ):
        with pytest.raises(APIKeyNotFound):
            svc.revoke_api_key(db_session, uuid.uuid4())


class TestRotateAPIKey:
    def test_rotate_api_key_invalidates_old_key(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        old_obj, old_plain = svc.create_api_key(db_session, workspace.id, "Rotate Me")
        new_obj, new_plain = svc.rotate_api_key(db_session, old_obj.id)
        db_session.refresh(old_obj)
        assert old_obj.is_active is False
        assert new_plain != old_plain

    def test_rotate_api_key_new_key_is_valid(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        old_obj, _ = svc.create_api_key(db_session, workspace.id, "Rotate Valid")
        new_obj, new_plain = svc.rotate_api_key(db_session, old_obj.id)
        assert new_obj.is_active is True
        assert new_obj.key_hash == _hash_key(new_plain)

    def test_rotate_nonexistent_key_raises(
        self, db_session: Session, svc: WorkspaceService
    ):
        with pytest.raises(APIKeyNotFound):
            svc.rotate_api_key(db_session, uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# Permissions
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckMemberPermission:
    def test_owner_has_all_permissions(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        user_id: uuid.UUID,
    ):
        for role in ROLE_HIERARCHY:
            assert (
                svc.check_member_permission(db_session, workspace.id, user_id, role)
                is True
            )

    def test_admin_can_manage_members(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        svc.add_member(db_session, workspace.id, other_user_id, "ADMIN", user_id)
        assert (
            svc.check_member_permission(
                db_session, workspace.id, other_user_id, "DEVELOPER"
            )
            is True
        )

    def test_developer_cannot_manage_members(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        svc.add_member(db_session, workspace.id, other_user_id, "DEVELOPER", user_id)
        assert (
            svc.check_member_permission(
                db_session, workspace.id, other_user_id, "ADMIN"
            )
            is False
        )

    def test_viewer_is_read_only(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        svc.add_member(db_session, workspace.id, other_user_id, "VIEWER", user_id)
        assert (
            svc.check_member_permission(
                db_session, workspace.id, other_user_id, "VIEWER"
            )
            is True
        )
        assert (
            svc.check_member_permission(
                db_session, workspace.id, other_user_id, "ANALYST"
            )
            is False
        )

    def test_non_member_has_no_access(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        assert (
            svc.check_member_permission(
                db_session, workspace.id, uuid.uuid4(), "VIEWER"
            )
            is False
        )


# ─────────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkspaceStats:
    def test_workspace_stats_member_count(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
        other_user_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        svc.add_member(db_session, workspace.id, other_user_id, "VIEWER", user_id)
        stats = svc.get_workspace_stats(db_session, workspace.id)
        assert stats.member_count == 2

    def test_workspace_stats_api_key_count(
        self,
        db_session: Session,
        svc: WorkspaceService,
        workspace: Workspace,
    ):
        svc.create_api_key(db_session, workspace.id, "K1")
        svc.create_api_key(db_session, workspace.id, "K2")
        stats = svc.get_workspace_stats(db_session, workspace.id)
        assert stats.api_key_count == 2

    def test_workspace_stats_not_found_raises(
        self, db_session: Session, svc: WorkspaceService
    ):
        with pytest.raises(WorkspaceNotFound):
            svc.get_workspace_stats(db_session, uuid.uuid4())
