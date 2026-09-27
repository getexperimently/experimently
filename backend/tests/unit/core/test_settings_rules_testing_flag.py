"""``TESTING`` is read the way pydantic reads a bool, and fails closed.

``settings_rules.testing_flag_is_set`` is standard library only (the
container's start-up check imports it before anything else), so it carries its
own copy of pydantic's False words. This pins that copy against pydantic: a
value pydantic reads as True is on, one it reads as False is off, and one it
cannot read at all is on unless it is empty.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.app.core.settings_rules import (
    HARDENED_ENVIRONMENTS,
    testing_flag_is_set,
    testing_refusal,
)

pytestmark = pytest.mark.unit

_BOOL = TypeAdapter(bool)

#: Every spelling pydantic accepts, in three cases, and values it refuses.
_WORDS = ["1", "0", "true", "false", "on", "off", "t", "f", "y", "n", "yes", "no"]
VALUES = (
    _WORDS
    + [w.upper() for w in _WORDS]
    + [w.capitalize() for w in _WORDS]
    + ["tRuE", "oN", " true", "true ", " 1 ", "2", "1.0", "enabled", " ", "\t"]
)


def _pydantic_reading(value: str):
    try:
        return _BOOL.validate_python(value)
    except ValidationError:
        return None


@pytest.mark.regression
@pytest.mark.parametrize("value", VALUES)
def test_the_flag_agrees_with_pydantic_and_fails_closed(value):
    reading = _pydantic_reading(value)
    expected = True if reading is None else reading  # unreadable: on
    assert testing_flag_is_set(value) is expected, (value, reading)


@pytest.mark.parametrize("value", [None, ""])
def test_unset_or_empty_is_off(value):
    assert testing_flag_is_set(value) is False


@pytest.mark.regression
@pytest.mark.parametrize("environment", HARDENED_ENVIRONMENTS)
@pytest.mark.parametrize("value", ["true", "on", "T", "Y", "enabled"])
def test_the_refusal_names_the_environment(environment, value):
    assert testing_refusal(environment, value) == (
        "TESTING is for the test runner and cannot be combined with "
        f"ENVIRONMENT={environment}. Remove TESTING from this deployment's "
        "configuration."
    )


@pytest.mark.parametrize("environment", ["development", "test", None])
def test_no_refusal_outside_hardened_environments(environment):
    assert testing_refusal(environment, "true") is None


@pytest.mark.parametrize("value", [None, "", "false", "0", "Off", "N"])
def test_no_refusal_when_the_flag_is_off(value):
    assert testing_refusal("production", value) is None
