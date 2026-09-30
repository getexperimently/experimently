"""One password rule for every place a password is set (#344).

``UserCreate.password``, ``PasswordChange.new_password`` and
``UserUpdate.password`` must accept and refuse exactly the same values. The
three REAL models are validated over a fixed corpus; a rule added to one model
only, a length check that lives only in ``Field(min_length=8)``, or a
validator dropped from ``UserUpdate`` each make the three disagree.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas.user import (
    PasswordChange,
    UserCreate,
    UserUpdate,
    check_password_strength,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

#: value -> accepted?
CORPUS = {
    "": False,
    "a": False,
    "Aa1": False,  # passes every character rule; only the length refuses it
    "Abcdef1": False,  # seven characters
    "Abcdefg1": True,  # eight
    "abcdefgh1": False,  # no upper case
    "ABCDEFGH1": False,  # no lower case
    "Abcdefghi": False,  # no digit
    "Password123": True,
    "Correct-Horse-9": True,
    "A1" + "a" * 70: True,  # 72 bytes
    "A1" + "a" * 71: False,  # 73 bytes
    "A1" + "é" * 35: True,  # 72 bytes in 37 characters
    "A1" + "é" * 35 + "a": False,  # 73 bytes in 38 characters
    "Abcdefg1\ud800": False,  # a lone surrogate: not text
    "\ud800Abcdefg1": False,
    "Été-2026-ok": True,  # non-ASCII letters count as upper/lower
}


def _accepts_create(value: str) -> bool:
    try:
        UserCreate(username="parity", email="parity@example.com", password=value)
    except ValidationError:
        return False
    return True


def _accepts_change(value: str) -> bool:
    try:
        PasswordChange(current_password="Current-1", new_password=value)
    except ValidationError:
        return False
    return True


def _accepts_update(value: str) -> bool:
    try:
        UserUpdate(username="parity", email="parity@example.com", password=value)
    except ValidationError:
        return False
    return True


def _accepts_helper(value: str) -> bool:
    try:
        check_password_strength(value)
    except ValueError:
        return False
    return True


@pytest.mark.parametrize("value", list(CORPUS), ids=[repr(v) for v in CORPUS])
def test_every_model_agrees(value):
    expected = CORPUS[value]
    got = {
        "helper": _accepts_helper(value),
        "UserCreate": _accepts_create(value),
        "PasswordChange": _accepts_change(value),
        "UserUpdate": _accepts_update(value),
    }
    assert got == dict.fromkeys(got, expected), got


def test_the_accepted_count_is_pinned():
    """A corpus edit that silently flips a value shows up here."""
    assert sum(CORPUS.values()) == 6


def test_update_without_a_password_is_valid():
    assert UserUpdate(username="parity", email="parity@example.com").password is None
    assert (
        UserUpdate(
            username="parity", email="parity@example.com", password=None
        ).password
        is None
    )


@pytest.mark.parametrize("value", ["Abcdefg1\ud800", "A1" + "a" * 71, "Aa1"])
def test_no_message_carries_the_value(value):
    for model, kwargs in (
        (UserCreate, {"username": "parity", "email": "p@example.com"}),
        (UserUpdate, {"username": "parity", "email": "p@example.com"}),
    ):
        with pytest.raises(ValidationError) as caught:
            model(password=value, **kwargs)
        for error in caught.value.errors(include_input=False):
            assert value not in str(error.get("msg")), error
            assert value not in str(error.get("ctx")), error


def test_a_lone_surrogate_gets_the_fixed_message():
    with pytest.raises(ValueError) as caught:
        check_password_strength("Abcdefg1\ud800")
    assert str(caught.value) == "Password must be valid text"
