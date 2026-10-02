"""The one archive rule (#631): ``transition`` and the model's guard.

``transition(current, verb)`` is what every status route consults before it
writes. The ``set`` listener on ``FeatureFlag.status`` is the backstop for any
other ORM writer: it refuses ARCHIVED -> ACTIVE whether the writer assigns the
enum or its string value -- several writers assign the string, so a guard that
compared enums only would be inert exactly where it is needed.

No database: the listener fires on assignment, before any flush.
"""

from __future__ import annotations

import pytest

from backend.app.models.feature_flag import (
    ARCHIVED_FLAG_DETAIL,
    ArchivedFlagError,
    FeatureFlag,
    FeatureFlagStatus,
)
from backend.app.services.feature_flag_service import FlagVerb, transition

pytestmark = [pytest.mark.unit]

ACTIVE = FeatureFlagStatus.ACTIVE
INACTIVE = FeatureFlagStatus.INACTIVE
ARCHIVED = FeatureFlagStatus.ARCHIVED


def _flag(status) -> FeatureFlag:
    return FeatureFlag(key="k", name="n", status=status, rollout_percentage=0)


# --- transition ---------------------------------------------------------------


@pytest.mark.parametrize(
    "current, verb, expected",
    [
        (ACTIVE, FlagVerb.ON, ACTIVE),
        (INACTIVE, FlagVerb.ON, ACTIVE),
        (ACTIVE, FlagVerb.OFF, INACTIVE),
        (INACTIVE, FlagVerb.OFF, INACTIVE),
        (ARCHIVED, FlagVerb.OFF, ARCHIVED),
        (ACTIVE, FlagVerb.ARCHIVE, ARCHIVED),
        (INACTIVE, FlagVerb.ARCHIVE, ARCHIVED),
        (ARCHIVED, FlagVerb.ARCHIVE, ARCHIVED),
        (ARCHIVED, FlagVerb.UNARCHIVE, INACTIVE),
        (ACTIVE, FlagVerb.UNARCHIVE, ACTIVE),
        (INACTIVE, FlagVerb.UNARCHIVE, INACTIVE),
    ],
)
@pytest.mark.parametrize("form", ["enum", "string"])
def test_transition(current, verb, expected, form):
    given = current if form == "enum" else current.value
    assert transition(given, verb) is expected


@pytest.mark.regression
@pytest.mark.parametrize("given", [ARCHIVED, "ARCHIVED", "archived"])
def test_transition_refuses_to_turn_an_archived_flag_on(given):
    with pytest.raises(ArchivedFlagError) as caught:
        transition(given, FlagVerb.ON)
    assert str(caught.value) == ARCHIVED_FLAG_DETAIL


def test_the_refusal_text():
    assert ARCHIVED_FLAG_DETAIL == (
        "This flag is archived. Unarchive it before turning it on."
    )


# --- the model guard ----------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("start", [ARCHIVED, "ARCHIVED"], ids=["from-enum", "from-str"])
@pytest.mark.parametrize("value", [ACTIVE, "ACTIVE"], ids=["to-enum", "to-str"])
def test_the_guard_refuses_archived_to_active(start, value):
    flag = _flag(start)
    with pytest.raises(ArchivedFlagError):
        flag.status = value
    assert flag.status == start


@pytest.mark.parametrize(
    "start, value",
    [
        (ARCHIVED, INACTIVE),  # unarchive
        (ARCHIVED, "INACTIVE"),
        (ARCHIVED, ARCHIVED),
        (ARCHIVED, "ARCHIVED"),
        (INACTIVE, ACTIVE),
        (INACTIVE, "ACTIVE"),
        (ACTIVE, ARCHIVED),
        (ACTIVE, INACTIVE),
    ],
)
def test_the_guard_allows_every_other_change(start, value):
    flag = _flag(start)
    flag.status = value
    assert flag.status == value


@pytest.mark.parametrize("value", [ACTIVE, "ACTIVE", ARCHIVED])
def test_a_new_flag_may_be_constructed_with_any_status(value):
    """The constructor's assignment has no previous value (the seed scripts)."""
    assert _flag(value).status == value


def test_the_percentage_of_an_archived_flag_can_change():
    flag = _flag(ARCHIVED)
    flag.rollout_percentage = 40
    assert (flag.status, flag.rollout_percentage) == (ARCHIVED, 40)
