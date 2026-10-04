"""The dashboard's list of audit actions is exactly what the API writes (#221).

``frontend/src/components/admin/audit/action-types.json`` is the list the
dashboard offers in its action filter. ``WRITTEN_ACTION_TYPES`` is every
action something in this profile writes (pinned to the route inventory by
``test_audit_inventory.py``). The rule depends on the profile:

* full (``modules`` loads): the list equals ``WRITTEN_ACTION_TYPES`` plus
  ``MODULES_ONLY_ACTION_TYPES``;
* core (no ``modules``): every written action is in the list, and the list's
  extra entries are all in ``MODULES_ONLY_ACTION_TYPES``.

So an action nothing offers fails, and so does an option nothing writes. The
file is found from this test's own path (no git), so the check runs the same
in core-build's copy of the tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.models.audit_log import ActionType
from backend.app.modules_loader import require_modules_or_absent
from backend.app.services.audit_service import (
    MODULES_ONLY_ACTION_TYPES,
    WRITTEN_ACTION_TYPES,
)

pytestmark = [pytest.mark.smoke]

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_TYPES_JSON = (
    REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "admin"
    / "audit"
    / "action-types.json"
)


def problems(written, offered, modules_only, *, full):
    """What is wrong with ``offered`` (the JSON) against ``written``; [] if nothing."""
    written, offered, modules_only = set(written), set(offered), set(modules_only)
    found = []
    missing = written - offered
    if missing:
        found.append(f"written but not offered: {sorted(missing)}")
    extra = offered - written
    if full:
        if extra:
            found.append(f"offered but not written: {sorted(extra)}")
    else:
        unexplained = extra - modules_only
        if unexplained:
            found.append(
                f"offered but not written by core or modules: {sorted(unexplained)}"
            )
    return found


def _offered():
    return json.loads(ACTION_TYPES_JSON.read_text(encoding="utf-8"))


def test_the_list_is_a_sorted_list_of_known_actions():
    offered = _offered()
    assert isinstance(offered, list)
    assert offered == sorted(set(offered)), "sorted, no duplicates"
    known = {a.value for a in ActionType}
    assert set(offered) <= known, sorted(set(offered) - known)


def test_modules_only_actions_are_not_written_by_core():
    assert not (set(MODULES_ONLY_ACTION_TYPES) & set(WRITTEN_ACTION_TYPES))


def test_the_list_matches_what_this_profile_writes():
    full = require_modules_or_absent()
    written = {a.value for a in WRITTEN_ACTION_TYPES}
    modules_only = {a.value for a in MODULES_ONLY_ACTION_TYPES}
    if full:
        # With the modules loaded, their actions are written too.
        written |= modules_only
    found = problems(written, _offered(), modules_only, full=full)
    assert found == [], f"profile={'full' if full else 'core'}: {found}"


# The rule itself, with each defect planted: both directions fail, in both
# profiles, and the modules-only set excuses an extra option only in core.


@pytest.mark.parametrize("full", [True, False], ids=["full", "core"])
def test_an_action_nobody_offers_fails(full):
    assert problems({"a", "b"}, {"a"}, set(), full=full)


@pytest.mark.parametrize("full", [True, False], ids=["full", "core"])
def test_an_option_nothing_writes_fails(full):
    assert problems({"a"}, {"a", "zzz"}, set(), full=full)


def test_a_modules_only_option_passes_in_core_and_fails_in_full():
    assert problems({"a"}, {"a", "m"}, {"m"}, full=False) == []
    assert problems({"a"}, {"a", "m"}, {"m"}, full=True)
