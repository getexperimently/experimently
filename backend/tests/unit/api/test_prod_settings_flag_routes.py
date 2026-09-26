"""The feature-flag list and detail answer under production settings (B5, T22).

ProdSettings -- what staging and production select, from ENVIRONMENT or
APP_ENV -- turned the response cache on. The list then called `.get` on
`CACHE_CONTROL["redis"]`, which is None: a 500 on every request, before the
database is touched. The detail 500'd whenever a Redis answered, because the
async client it builds is never awaited (#100).

Three things make a test of this pass on the old code, so each is avoided:
the routes bind `settings` at import (patching `backend.app.core.config.settings`
reaches neither); the shared `client` fixture overrides `get_cache_control`
to disabled; and a synchronous fake Redis hides the missing `await`.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.api.v1.endpoints import feature_flags as ff
from backend.app.core.config import ProdSettings
from backend.app.main import app
from backend.app.models.user import UserRole

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def prod_settings(monkeypatch):
    # The defaults under test: nothing in the environment may set them.
    for name in ("CACHE_ENABLED", "CACHE_CONTROL"):
        monkeypatch.delenv(name, raising=False)
    return ProdSettings(ENVIRONMENT="staging", _env_file=None)


@pytest.fixture
def client(prod_settings):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superuser = False
    user.role = UserRole.ADMIN
    user.is_active = True
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock(
        owner_id=user.id
    )

    # A Redis that answers, with async methods, as the real client has.
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()

    async def pool():
        return redis

    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()  # no get_cache_control override
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    app.dependency_overrides[deps.get_db] = lambda: db
    try:
        with (
            patch.object(ff, "settings", prod_settings),
            patch.object(deps, "settings", prod_settings),
            patch.object(deps, "get_redis_pool", pool),
            patch.object(ff.crud_feature_flag, "get_multi", return_value=[]),
            patch.object(ff.crud_feature_flag, "count", return_value=0),
            patch.object(
                ff.FeatureFlagService,
                "get_feature_flag",
                return_value={"id": "x", "key": "k"},
            ),
        ):
            yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def test_production_defaults_leave_the_cache_off(prod_settings):
    assert prod_settings.CACHE_ENABLED is False
    assert prod_settings.CACHE_CONTROL["enabled"] is False


def test_the_flag_list_answers_under_production_settings(client):
    resp = client.get("/api/v1/feature-flags/")
    assert resp.status_code == 200, resp.text


def test_a_flag_answers_under_production_settings_with_redis_reachable(client):
    resp = client.get(f"/api/v1/feature-flags/{uuid.uuid4()}")
    assert resp.status_code == 200, resp.text
