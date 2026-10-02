"""``UserResponse.email`` is nullable and still required (#342).

The fix for #342 lets ``email`` be ``null`` so that an account stored without
an email address no longer makes the user endpoints answer 500. Clients were
promised the key is always present, so it stays in the schema's ``required``
list: ``Optional[str]`` with no default. ``Optional[str] = None`` would also
fix the 500 but silently drop ``email`` from ``required`` -- that is what this
test refuses, against both the published stable snapshot and the live app.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from backend.app.main import app

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
STABLE_SNAPSHOT = REPO_ROOT / "docs" / "api" / "openapi-v1.stable.json"

NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _user_response(document: Dict[str, Any]) -> Dict[str, Any]:
    return document["components"]["schemas"]["UserResponse"]


def _assert_email_nullable_and_required(schema: Dict[str, Any]) -> None:
    assert "email" in schema["required"], schema["required"]
    email = schema["properties"]["email"]
    assert email.get("anyOf") == NULLABLE_STRING["anyOf"], email
    assert "default" not in email, email


def test_stable_snapshot_keeps_email_required_and_nullable():
    document = json.loads(STABLE_SNAPSHOT.read_text(encoding="utf-8"))
    _assert_email_nullable_and_required(_user_response(document))


def test_live_openapi_keeps_email_required_and_nullable():
    _assert_email_nullable_and_required(_user_response(app.openapi()))
