"""``can_act_on_feature_flag`` -- the one decision behind every per-flag route.

Under the shipped scope table every role that may change flags may change any
flag, so the OWN branch and the rule that an unowned flag matches no OWN scope
are unreachable through the API today.  They are the lever for per-flag
restrictions later, so they are pinned here against an injected table.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.core.permissions import (
    FEATURE_FLAG_SCOPE,
    Action,
    Scope,
    can_act_on_feature_flag,
)
from backend.app.models.user import UserRole

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _user(role, is_superuser=False):
    return SimpleNamespace(id=uuid4(), role=role, is_superuser=is_superuser)


OWN_ONLY = {UserRole.DEVELOPER: {Action.UPDATE: Scope.OWN}}


def test_an_own_scope_admits_the_owner():
    dev = _user(UserRole.DEVELOPER)
    assert can_act_on_feature_flag(dev, dev.id, Action.UPDATE, OWN_ONLY) is True


def test_an_own_scope_refuses_another_owner():
    dev = _user(UserRole.DEVELOPER)
    assert can_act_on_feature_flag(dev, uuid4(), Action.UPDATE, OWN_ONLY) is False


def test_an_own_scope_never_matches_a_flag_with_no_owner():
    dev = _user(UserRole.DEVELOPER)
    assert can_act_on_feature_flag(dev, None, Action.UPDATE, OWN_ONLY) is False


def test_a_missing_table_entry_means_own():
    dev = _user(UserRole.DEVELOPER)
    assert can_act_on_feature_flag(dev, uuid4(), Action.UPDATE, {}) is False
    assert can_act_on_feature_flag(dev, dev.id, Action.UPDATE, {}) is True


def test_the_role_matrix_is_checked_before_ownership():
    """Owning a flag never lets a read-only role change it."""
    viewer = _user(UserRole.VIEWER)
    anything = {UserRole.VIEWER: {Action.UPDATE: Scope.ANY}}
    assert can_act_on_feature_flag(viewer, viewer.id, Action.UPDATE, anything) is False


def test_a_superuser_may_always_act():
    su = _user(UserRole.VIEWER, is_superuser=True)
    assert can_act_on_feature_flag(su, None, Action.DELETE, {}) is True


@pytest.mark.parametrize(
    "role, action, allowed",
    [
        (UserRole.ADMIN, Action.UPDATE, True),
        (UserRole.ADMIN, Action.DELETE, True),
        (UserRole.DEVELOPER, Action.UPDATE, True),
        (UserRole.DEVELOPER, Action.DELETE, True),
        (UserRole.ANALYST, Action.READ, True),
        (UserRole.ANALYST, Action.UPDATE, False),
        (UserRole.VIEWER, Action.READ, True),
        (UserRole.VIEWER, Action.DELETE, False),
    ],
)
def test_the_shipped_table_on_someone_elses_flag(role, action, allowed):
    """Access is by role: the answer is the same whoever owns the flag."""
    user = _user(role)
    for owner in (uuid4(), None, user.id):
        assert can_act_on_feature_flag(user, owner, action) is allowed, owner


def test_the_shipped_table_is_all_any():
    scopes = {s for actions in FEATURE_FLAG_SCOPE.values() for s in actions.values()}
    assert scopes == {Scope.ANY}
