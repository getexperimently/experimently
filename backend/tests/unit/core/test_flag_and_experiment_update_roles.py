"""Who can change feature flags is who can change experiments, for every role.

``require_sdk_ruleset_key`` (``backend/app/api/sdk_scope.py``) admits a scoped
key only while its owner holds ``UPDATE`` on feature flags. Batch assignment
(``POST /api/v1/tracking/assign/batch``) writes experiment assignments behind
that same check, so it relies on the two role sets being equal. This pins
them equal, role by role, for non-superusers (a superuser passes every check).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.core.permissions import Action, ResourceType, check_permission
from backend.app.models.user import UserRole

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("role", list(UserRole), ids=lambda r: r.value)
def test_flag_update_equals_experiment_update(role):
    user = SimpleNamespace(role=role, is_superuser=False)
    assert check_permission(user, ResourceType.FEATURE_FLAG, Action.UPDATE) == (
        check_permission(user, ResourceType.EXPERIMENT, Action.UPDATE)
    )


def test_the_roles_that_pass_are_admin_and_developer():
    """Guard the guard: equal because both are True for these two, and False
    for the others, not because the check answers the same thing for all."""
    passing = {
        role
        for role in UserRole
        if check_permission(
            SimpleNamespace(role=role, is_superuser=False),
            ResourceType.FEATURE_FLAG,
            Action.UPDATE,
        )
    }
    assert passing == {UserRole.ADMIN, UserRole.DEVELOPER}
