"""Every Redis client authenticates to a Redis that requires a password (#236).

The unit tests (``backend/tests/unit/core/test_redis_connection.py``) prove
each client is *built* with ``REDIS_PASSWORD``; this proves the result against
a real server started with ``--requirepass``. The integration-tests workflow
starts one beside its plaintext ``redis`` service (a service container takes
no command) and exports:

``REDIS_AUTH_TEST_PORT``, ``REDIS_AUTH_TEST_PASSWORD``
    where it listens and its password (generated per run);
``REDIS_AUTH_TEST_HOST``
    optional, default ``localhost``;
``EXPERIMENTLY_REQUIRE_REDIS_AUTH=1``
    turns "no server configured" from a skip into a failure, so the job cannot
    silently lose the server and still pass.

Locally::

    docker run -d --rm --name redis-auth -p 6380:6379 redis:7-alpine \\
        redis-server --requirepass local-only
    REDIS_AUTH_TEST_PORT=6380 REDIS_AUTH_TEST_PASSWORD=local-only \\
        python -m pytest backend/tests/integration/test_redis_password_auth.py
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import redis

from backend.app.core.config import settings

pytestmark = [pytest.mark.integration, pytest.mark.regression]


@pytest.fixture
def server() -> dict:
    port = os.environ.get("REDIS_AUTH_TEST_PORT")
    password = os.environ.get("REDIS_AUTH_TEST_PASSWORD")
    if not (port and password):
        message = (
            "no password-protected Redis configured (REDIS_AUTH_TEST_PORT, "
            "REDIS_AUTH_TEST_PASSWORD)"
        )
        if os.environ.get("EXPERIMENTLY_REQUIRE_REDIS_AUTH") == "1":
            pytest.fail(message + " but EXPERIMENTLY_REQUIRE_REDIS_AUTH=1")
        pytest.skip(message)
    return {
        "host": os.environ.get("REDIS_AUTH_TEST_HOST", "localhost"),
        "port": int(port),
        "password": password,
    }


@pytest.fixture
def configured(server, monkeypatch) -> dict:
    """Point the application's settings at the password-protected server."""
    monkeypatch.setattr(settings, "REDIS_HOST", server["host"])
    monkeypatch.setattr(settings, "REDIS_PORT", str(server["port"]))
    monkeypatch.setattr(settings, "REDIS_PASSWORD", server["password"])
    monkeypatch.setattr(settings, "REDIS_DB", 0)
    monkeypatch.setattr(settings, "REDIS_SSL", False)
    return server


def test_the_server_really_requires_the_password(server):
    """Without this the rest could pass against an open server."""
    anonymous = redis.Redis(host=server["host"], port=server["port"])
    with pytest.raises(redis.AuthenticationError):
        anonymous.ping()
    authenticated = redis.Redis(
        host=server["host"], port=server["port"], password=server["password"]
    )
    assert authenticated.ping() is True


def test_the_readiness_probe_authenticates(configured, monkeypatch):
    from backend.app.core.health import check_redis

    assert check_redis()["status"] == "healthy"
    monkeypatch.setattr(settings, "REDIS_PASSWORD", "not-the-password")
    assert check_redis()["status"] == "unhealthy"


def test_the_rate_limiter_uses_redis(configured):
    from backend.app.middleware.rate_limiter import RedisRateLimiter

    limiter = RedisRateLimiter()
    assert limiter._get_redis() is not None
    key = f"s2-{uuid.uuid4().hex}"
    assert limiter.is_allowed(key, limit=5, window_seconds=60) == (True, 4)
    assert limiter._redis_available is True


def test_the_dependency_cache_pool_authenticates(configured, monkeypatch):
    from backend.app.api import deps

    monkeypatch.setattr(deps, "_redis_pool", None)

    async def ping() -> bool:
        pool = await deps.get_redis_pool()
        assert pool is not None
        try:
            return await pool.ping()
        finally:
            await pool.aclose()

    assert asyncio.run(ping()) is True


def test_the_results_cache_authenticates_and_invalidates(configured):
    from backend.app.api.v1.endpoints.results import (
        _get_cache_service,
        invalidate_results_cache,
    )

    cache = _get_cache_service()
    assert cache.enabled, "the results cache could not reach Redis"
    experiment_id = uuid.uuid4()
    key = f"results:{experiment_id}:summary"
    assert cache.set(key, "cached", expire=60)
    assert cache.get(key) == "cached"

    invalidate_results_cache(experiment_id=experiment_id, db=None, current_user=None)
    assert cache.get(key) is None
