"""The dashboard's experiment and flag role lists equal the server's (#442, #917).

``frontend/src/utils/experimentPermissions.ts`` hand-types which roles the
dashboard offers each experiment and flag control to. ``canCreateExperiment``
gates "+ New Experiment" and Clone; ``canChangeExperiment`` gates the
lifecycle buttons, targeting, "Edit details" and "Delete draft";
``canChangeFeatureFlags`` gates "+ New Flag", the on/off switches, the flag
form and "Save Changes". This file reads those lists as text and compares
them with ``ROLE_PERMISSIONS``, so a role added on one side only fails here
instead of offering a button the API refuses (or hiding one it accepts).
"""

from __future__ import annotations

import pathlib
import re

from backend.app.core.permissions import ROLE_PERMISSIONS, Action, ResourceType

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
HELPER = REPO_ROOT / "frontend" / "src" / "utils" / "experimentPermissions.ts"


def _ts_roles(constant: str) -> set[str]:
    text = HELPER.read_text("utf-8")
    match = re.search(rf"const {constant} = \[([^\]]{{0,200}})\] as const;", text)
    assert match, f"{constant} not found in {HELPER.relative_to(REPO_ROOT)}"
    return set(re.findall(r"'([A-Z_]+)'", match.group(1)))


def _server_roles(
    action: Action, resource: ResourceType = ResourceType.EXPERIMENT
) -> set[str]:
    return {
        role.name
        for role, grants in ROLE_PERMISSIONS.items()
        if action in grants.get(resource, [])
    }


def test_create_roles_match():
    assert _ts_roles("ROLES_THAT_CAN_CREATE") == _server_roles(Action.CREATE)


def test_change_roles_match_update():
    assert _ts_roles("ROLES_THAT_CAN_CHANGE") == _server_roles(Action.UPDATE)


def test_change_roles_match_delete():
    # "Delete draft" is gated by canChangeExperiment, so the roles holding
    # DELETE must be exactly the ones holding UPDATE.
    assert _ts_roles("ROLES_THAT_CAN_CHANGE") == _server_roles(Action.DELETE)


def test_the_lists_are_not_empty():
    # A regex that stopped matching would compare two empty sets.
    assert _ts_roles("ROLES_THAT_CAN_CREATE") == {"ADMIN", "DEVELOPER"}
    assert _ts_roles("ROLES_THAT_CAN_CHANGE") == {"ADMIN", "DEVELOPER"}


# canChangeFeatureFlags answers create, toggle and update with one list, so
# the roles holding FEATURE_FLAG CREATE, UPDATE and DELETE must each be
# exactly that list (`can_act_on_feature_flag` checks the action it is given).
def test_flag_change_roles_match_create():
    assert _ts_roles("FLAG_ROLES_THAT_CAN_CHANGE") == _server_roles(
        Action.CREATE, ResourceType.FEATURE_FLAG
    )


def test_flag_change_roles_match_update():
    assert _ts_roles("FLAG_ROLES_THAT_CAN_CHANGE") == _server_roles(
        Action.UPDATE, ResourceType.FEATURE_FLAG
    )


def test_flag_change_roles_match_delete():
    assert _ts_roles("FLAG_ROLES_THAT_CAN_CHANGE") == _server_roles(
        Action.DELETE, ResourceType.FEATURE_FLAG
    )


def test_the_flag_list_is_not_empty():
    # A regex that stopped matching (a renamed constant) would compare two
    # empty sets above and pass.
    assert _ts_roles("FLAG_ROLES_THAT_CAN_CHANGE") == {"ADMIN", "DEVELOPER"}
