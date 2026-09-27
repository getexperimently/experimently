"""The one scope parser: split on commas, strip, drop empties, exact membership.

Nothing enforces a scope yet; these pin the rule the ruleset endpoint's scope
check and the ``/api/v1/api-keys`` listing share, so the two cannot drift.
The rejected cases are the likely wrong implementations: a case-insensitive
compare, and a substring test (``"sdk:ruleset" in scopes``), which accepts
``xsdk:ruleset`` and ``sdk:ruleset-ro``.
"""

import pytest

from backend.app.core.api_key_scopes import (
    SDK_RULESET_SCOPE,
    format_scopes,
    has_scope,
    normalise_scope_list,
    parse_scopes,
)
from backend.app.schemas.api_key import APIKeyCreate

pytestmark = pytest.mark.unit


def test_scope_name():
    assert SDK_RULESET_SCOPE == "sdk:ruleset"


@pytest.mark.parametrize(
    "stored, granted",
    [
        (None, False),
        ("", False),
        (",", False),
        ("   ", False),
        ("SDK:RULESET", False),
        ("Sdk:Ruleset", False),
        ("xsdk:ruleset", False),
        ("sdk:ruleset-ro", False),
        ("sdk:rules", False),
        ("read,write", False),
        ("sdk:ruleset", True),
        ("read, sdk:ruleset ", True),
        (",,sdk:ruleset,,", True),
        ("xsdk:ruleset,sdk:ruleset", True),
    ],
)
def test_has_scope_is_exact_case_sensitive_membership(stored, granted):
    assert has_scope(stored, SDK_RULESET_SCOPE) is granted


@pytest.mark.parametrize(
    "stored, parsed",
    [
        (None, []),
        ("", []),
        (",,,", []),
        ("read,write", ["read", "write"]),
        ("read, sdk:ruleset ", ["read", "sdk:ruleset"]),
        (",,sdk:ruleset,,", ["sdk:ruleset"]),
        (" SDK:RULESET ", ["SDK:RULESET"]),
    ],
)
def test_parse_scopes(stored, parsed):
    assert parse_scopes(stored) == parsed


def test_format_scopes_round_trips_through_parse():
    assert format_scopes(None) is None
    assert format_scopes([]) is None
    assert format_scopes(["", "  "]) is None
    stored = format_scopes([" read", "sdk:ruleset ", ""])
    assert stored == "read,sdk:ruleset"
    assert parse_scopes(stored) == ["read", "sdk:ruleset"]
    assert has_scope(stored, SDK_RULESET_SCOPE)


def test_normalise_scope_list():
    assert normalise_scope_list([" a ", "", "b"]) == ["a", "b"]


def test_create_schema_uses_the_same_rule():
    assert APIKeyCreate(name="k", scopes="read, sdk:ruleset ,,").scopes == [
        "read",
        "sdk:ruleset",
    ]
    assert APIKeyCreate(name="k", scopes=[" sdk:ruleset ", ""]).scopes == [
        "sdk:ruleset"
    ]
    assert APIKeyCreate(name="k", scopes=None).scopes is None
