"""#93: feature-flag ownership and the role x ownership x action matrix.

Access to a flag is by role: ADMIN and DEVELOPER act on any flag, ANALYST and
VIEWER read any flag and change none, not even one they own.  The creator is
recorded as the owner, but ownership is not an access rule.

Two defects, pinned separately so a fix to one cannot hide the other:

1. ``create_feature_flag`` dropped ``owner_id`` (rebuilt ``FeatureFlagCreate``,
   which has no such field), so every flag was stored ownerless.
   -> ``TestCreatePersistsOwner`` creates THROUGH THE API. The matrix below
   inserts rows directly and cannot see this defect.
2. Every per-flag check was ``is_superuser or owner``, never the role, so only
   the bootstrap superuser could manage a flag, and a read-only role that owned
   one could change it.
   -> ``test_flag_access_matrix`` over every per-flag endpoint.

Why the existing suite missed both: ``admin_user`` is ``is_superuser=True``,
so "admin" in every test meant the superuser bypass; and ``make_feature_flag``
writes ``owner_id=admin_user.id`` directly, so no test ever met a flag the
create endpoint had actually produced.

Users are switched per request with ``make_client_for_user``: the overrides
are global, so the most recent call wins (see the note in
test_feature_flags_api.py about requesting two ``*_client`` fixtures).
"""

import uuid
from typing import Dict

import pytest

from backend.app.main import app
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.rollout_schedule import RolloutSchedule, RolloutStage
from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

BASE = "/api/v1/feature-flags"

# name -> (method, suffix, json body, status the flag starts in, success code)
ACTIONS = {
    "get": ("GET", "", None, FeatureFlagStatus.INACTIVE, 200),
    "put": ("PUT", "", {"name": "renamed by qa"}, FeatureFlagStatus.INACTIVE, 200),
    "delete": ("DELETE", "", None, FeatureFlagStatus.INACTIVE, 204),
    "activate": ("POST", "/activate", None, FeatureFlagStatus.INACTIVE, 200),
    "deactivate": ("POST", "/deactivate", None, FeatureFlagStatus.ACTIVE, 200),
    "toggle": ("POST", "/toggle", {"reason": "qa"}, FeatureFlagStatus.INACTIVE, 200),
    "enable": ("POST", "/enable", {"reason": "qa"}, FeatureFlagStatus.INACTIVE, 200),
    "disable": ("POST", "/disable", {"reason": "qa"}, FeatureFlagStatus.ACTIVE, 200),
}
MUTATIONS = [a for a in ACTIONS if a != "get"]

# actor -> (role, is_superuser)
ACTORS = {
    "superuser": (UserRole.ADMIN, True),
    "admin": (UserRole.ADMIN, False),  # an Admin -> Users account: NOT superuser
    "developer": (UserRole.DEVELOPER, False),
    "analyst": (UserRole.ANALYST, False),
    "viewer": (UserRole.VIEWER, False),
}
# own: owner_id = the actor. other: owned by a different DEVELOPER.
# null: owner_id IS NULL -- every flag created before the fix, and every flag
# whose owner is deleted afterwards (the FK is ON DELETE SET NULL).
OWNERSHIP = ["own", "other", "null"]


def expected_status(actor: str, ownership: str, action: str) -> int:
    """Ownership never changes the answer: the parameter is here to prove it."""
    ok = ACTIONS[action][4]
    if action == "get":  # every role reads every flag
        return ok
    if actor in ("analyst", "viewer"):  # read-only, even on their own flag
        return 403
    return ok  # superuser, ADMIN, DEVELOPER: any flag


CASES = [
    pytest.param(actor, own, action, id=f"{actor}-{own}-{action}")
    for actor in ACTORS
    for own in OWNERSHIP
    for action in ACTIONS
]
assert len(CASES) == 5 * 3 * 8 == 120, len(CASES)


@pytest.fixture(autouse=True)
def _remove_what_the_test_created(db_session):
    """Leave the shared test database as it was: the list tests page at 100."""
    yield
    db_session.rollback()
    flags = db_session.query(FeatureFlag.id).filter(FeatureFlag.key.like("ff93-%"))
    flag_ids = [row.id for row in flags]
    if flag_ids:
        schedules = db_session.query(RolloutSchedule.id).filter(
            RolloutSchedule.feature_flag_id.in_(flag_ids)
        )
        schedule_ids = [row.id for row in schedules]
        if schedule_ids:
            db_session.query(RolloutStage).filter(
                RolloutStage.rollout_schedule_id.in_(schedule_ids)
            ).delete(synchronize_session=False)
            db_session.query(RolloutSchedule).filter(
                RolloutSchedule.id.in_(schedule_ids)
            ).delete(synchronize_session=False)
        db_session.query(FeatureFlag).filter(FeatureFlag.id.in_(flag_ids)).delete(
            synchronize_session=False
        )
    db_session.commit()


def _user(db_session, role: UserRole, is_superuser: bool) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"ff93_{role.value}_{suffix}",
        email=f"ff93_{suffix}@int.test",
        full_name="ff93",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=is_superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _call(db_session, user: User, action: str, flag_id) -> "object":
    method, suffix, body, _, _ = ACTIONS[action]
    client = make_client_for_user(db_session, user)  # re-installs overrides
    return client.request(method, f"{BASE}/{flag_id}{suffix}", json=body)


@pytest.fixture
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.regression
@pytest.mark.parametrize("actor,ownership,action", CASES)
def test_flag_access_matrix(db_session, cleanup_overrides, actor, ownership, action):
    role, su = ACTORS[actor]
    user = _user(db_session, role, su)
    other = _user(db_session, UserRole.DEVELOPER, False)
    owner_id = {"own": user.id, "other": other.id, "null": None}[ownership]

    flag = FeatureFlag(
        key=f"ff93-{uuid.uuid4().hex[:10]}",
        name="ff93",
        status=ACTIONS[action][3],
        owner_id=owner_id,
        rollout_percentage=0,
    )
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)

    response = _call(db_session, user, action, flag.id)
    want = expected_status(actor, ownership, action)
    assert response.status_code == want, (
        f"{actor} ({role.value}, superuser={su}) {action} on a flag owned by "
        f"{ownership}: want {want}, got {response.status_code}: {response.text}"
    )


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.regression
class TestCreatePersistsOwner:
    """Create through the API, then drive the flag the endpoint produced."""

    @pytest.mark.parametrize("actor", ["superuser", "admin", "developer"])
    def test_creator_is_recorded_as_owner_and_manages_the_flag(
        self, db_session, cleanup_overrides, actor
    ):
        role, su = ACTORS[actor]
        user = _user(db_session, role, su)
        client = make_client_for_user(db_session, user)
        key = f"ff93-create-{uuid.uuid4().hex[:8]}"

        created = client.post(
            f"{BASE}/", json={"key": key, "name": "ff93", "is_active": False}
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["owner_id"] == str(user.id), body  # the dropped field

        row = db_session.query(FeatureFlag).filter(FeatureFlag.key == key).one()
        db_session.refresh(row)
        assert row.owner_id == user.id, "owner_id must be persisted, not just echoed"

        # The whole lifecycle, in an order where each step's precondition holds.
        steps: Dict[str, int] = {
            "get": 200,
            "put": 200,
            "activate": 200,
            "deactivate": 200,
            "toggle": 200,  # inactive -> active
            "disable": 200,
            "enable": 200,
            "delete": 204,
        }
        got = {a: _call(db_session, user, a, body["id"]).status_code for a in steps}
        assert got == steps, got
        gone = _call(db_session, user, "get", body["id"])
        assert gone.status_code == 404, gone.text

    @pytest.mark.parametrize("actor", ["analyst", "viewer"])
    def test_read_only_roles_cannot_create(self, db_session, cleanup_overrides, actor):
        role, su = ACTORS[actor]
        user = _user(db_session, role, su)
        client = make_client_for_user(db_session, user)
        response = client.post(
            f"{BASE}/", json={"key": f"ff93-ro-{uuid.uuid4().hex[:8]}", "name": "x"}
        )
        assert response.status_code == 403, response.text

    def test_a_second_developer_manages_the_first_ones_flag(
        self, db_session, cleanup_overrides
    ):
        first = _user(db_session, UserRole.DEVELOPER, False)
        second = _user(db_session, UserRole.DEVELOPER, False)
        created = make_client_for_user(db_session, first).post(
            f"{BASE}/",
            json={
                "key": f"ff93-2d-{uuid.uuid4().hex[:8]}",
                "name": "x",
                "is_active": False,
            },
        )
        assert created.status_code == 201, created.text
        fid = created.json()["id"]

        # e.g. switching off a teammate's flag during an incident
        steps = {"get": 200, "put": 200, "activate": 200, "deactivate": 200}
        got = {a: _call(db_session, second, a, fid).status_code for a in steps}
        assert got == steps, got
        row = db_session.query(FeatureFlag).filter(FeatureFlag.id == fid).one()
        db_session.refresh(row)
        assert row.owner_id == first.id, "acting on a flag must not change its owner"


def test_matrix_case_count_is_exact():
    """Collected count, not just list length: guards a filter/skip creeping in."""
    assert len(CASES) == 120
    assert sum(1 for c in CASES if expected_status(*c.values) == 403) == 2 * 3 * 7
