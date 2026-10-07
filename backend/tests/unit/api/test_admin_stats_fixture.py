"""The admin dashboard is tested against the shape the stats route answers (#1007).

``frontend/src/tests/fixtures/admin-stats.json`` is the response the admin
dashboard's test renders (``frontend/src/tests/admin/AdminDashboard.test.tsx``).
The page used to read flat keys (``total_experiments``) that
``GET /api/v1/admin/stats`` never sent, so every summary number was empty while
its test, written against the same flat keys, passed. This pins the fixture to
what the route builds: the same keys at every level, a number where the route
answers a number and a string where it answers one. A change to the route's
shape fails here until the fixture, and with it the page, follows.
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import MagicMock

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
FIXTURE = REPO_ROOT / "frontend" / "src" / "tests" / "fixtures" / "admin-stats.json"


def _shape(value: object) -> object:
    """The value's keys, all the way down, with each leaf replaced by its kind."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


async def _route_answer() -> dict:
    from backend.app.api.deps import CacheControl
    from backend.app.api.v1.endpoints import admin

    db = MagicMock()
    db.query.return_value.count.return_value = 7
    db.query.return_value.filter.return_value.count.return_value = 3
    return await admin.get_system_stats(
        db=db, current_user=MagicMock(), cache_control=CacheControl()
    )


@pytest.mark.regression
@pytest.mark.asyncio
async def test_the_dashboard_fixture_has_the_shape_the_route_answers():
    answer = await _route_answer()
    fixture = json.loads(FIXTURE.read_text("utf-8"))
    assert _shape(fixture) == _shape(answer)


@pytest.mark.asyncio
async def test_the_route_answers_nested_counts():
    """The positive control: the comparison above is between two nested shapes."""
    answer = await _route_answer()
    assert answer["experiments"] == {"total": 7, "active": 3}
    assert answer["feature_flags"] == {"total": 7, "active": 3}
    assert answer["users"]["total"] == 7
