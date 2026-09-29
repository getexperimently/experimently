"""The feature-flag routes with the flag cache on, against a real Redis (#100).

``deps.get_cache_control`` hands the routes a ``redis.asyncio`` client. The
routes called it without ``await``: ``get`` returned a coroutine, which is
truthy, so every detail request took the cache-hit branch and ``json.loads``
raised (a 500); ``delete`` and ``scan_iter`` did nothing, so update, delete,
activate and deactivate 500'd and toggle/enable/disable left stale entries
behind. The list read ``settings.CACHE_CONTROL``, whose client is always
``None``.

What would let these pass on the old code, and is avoided:

* a fake or synchronous Redis hides a missing ``await`` -- this is the real
  server and the real client, built by the real dependency;
* the shared client fixtures override ``get_cache_control`` to disabled --
  that override is removed here;
* a ``TestClient`` outside a ``with`` block runs requests on different event
  loops, the pooled client breaks, ``get_cache_control`` swallows the error and
  the cache is silently off -- so the client is a context manager, and every
  test asserts on what is actually in Redis, not only on the status code.

The Redis is ``REDIS_HOST``/``REDIS_PORT`` (the integration-tests job's
``redis`` service). Database 15 is used and flushed, never the default one.
Without a reachable Redis this skips -- core-build and the nightly run have
none -- unless ``EXPERIMENTLY_REQUIRE_REDIS=1``, which the integration-tests
job sets so that losing the service fails instead of skipping.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
import redis as sync_redis
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.tests.integration.conftest import make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.regression]

BASE = "/api/v1/feature-flags"
CACHE_DB = 15


@pytest.fixture
def redis_server(monkeypatch):
    """A synchronous handle on the Redis the application will use, emptied."""
    monkeypatch.setattr(settings, "REDIS_DB", CACHE_DB)
    monkeypatch.setattr(settings, "REDIS_PASSWORD", None)
    monkeypatch.setattr(settings, "REDIS_SSL", False)
    handle = sync_redis.Redis(
        host=str(settings.REDIS_HOST),
        port=int(settings.REDIS_PORT),
        db=CACHE_DB,
        decode_responses=True,
        socket_connect_timeout=2,
    )
    try:
        handle.ping()
    except sync_redis.RedisError as exc:
        message = f"no Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}: {exc}"
        if os.environ.get("EXPERIMENTLY_REQUIRE_REDIS") == "1":
            pytest.fail(message + " but EXPERIMENTLY_REQUIRE_REDIS=1")
        pytest.skip(message)
    handle.flushdb()
    yield handle
    handle.flushdb()
    handle.close()


@pytest.fixture
def cached_client(redis_server, db_session, developer_user, monkeypatch):
    """A developer's client with the real ``get_cache_control`` and the cache on."""
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(deps, "_redis_pool", None)  # built on this client's loop
    make_client_for_user(db_session, developer_user)
    app.dependency_overrides.pop(deps.get_cache_control)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _remove_the_flags_created(db_session):
    yield
    db_session.rollback()
    db_session.query(FeatureFlag).filter(FeatureFlag.key.like("cache100-%")).delete(
        synchronize_session=False
    )
    db_session.commit()


@pytest.fixture
def flag(db_session, developer_user):
    row = FeatureFlag(
        key=f"cache100-{uuid.uuid4().hex[:8]}",
        name="Cache flag",
        status=FeatureFlagStatus.INACTIVE,
        owner_id=developer_user.id,
        rollout_percentage=0,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_the_cache_dependency_is_live(cached_client, redis_server):
    """Guards the rest: were the cache silently off, they could not fail."""
    control = cached_client.portal.call(deps.get_cache_control)
    assert control.enabled is True
    assert control.redis is not None


def test_the_flag_detail_is_cached_and_served_from_the_cache(
    cached_client, redis_server, flag
):
    first = cached_client.get(f"{BASE}/{flag.id}")
    assert first.status_code == 200, first.text

    key = f"feature_flag:{flag.id}"
    stored = redis_server.get(key)
    assert stored is not None, "the detail was not written to the cache"
    assert json.loads(stored)["key"] == flag.key

    # A marker only the cache holds: the second answer must come from Redis.
    redis_server.set(key, json.dumps({**json.loads(stored), "name": "from-cache"}))
    second = cached_client.get(f"{BASE}/{flag.id}")
    assert second.status_code == 200, second.text
    assert second.json()["name"] == "from-cache"


def test_the_flag_list_is_cached_and_served_from_the_cache(
    cached_client, redis_server, flag, developer_user
):
    first = cached_client.get(f"{BASE}/")
    assert first.status_code == 200, first.text

    key = f"feature_flags:{developer_user.id}:0:100:None:None"
    stored = redis_server.get(key)
    assert stored is not None, "the list was not written to the cache"
    assert json.loads(stored)["total"] == first.json()["total"]

    redis_server.set(key, json.dumps({**json.loads(stored), "total": 424242}))
    second = cached_client.get(f"{BASE}/")
    assert second.status_code == 200, second.text
    assert second.json()["total"] == 424242


# name -> (method, suffix, json body, status the flag starts in, success code)
MUTATIONS = {
    "update": ("PUT", "", {"description": "changed"}, FeatureFlagStatus.INACTIVE, 200),
    "delete": ("DELETE", "", None, FeatureFlagStatus.INACTIVE, 204),
    "activate": ("POST", "/activate", None, FeatureFlagStatus.INACTIVE, 200),
    "deactivate": ("POST", "/deactivate", None, FeatureFlagStatus.ACTIVE, 200),
    "toggle": ("POST", "/toggle", {"reason": "qa"}, FeatureFlagStatus.INACTIVE, 200),
    "enable": ("POST", "/enable", {"reason": "qa"}, FeatureFlagStatus.INACTIVE, 200),
    "disable": ("POST", "/disable", {"reason": "qa"}, FeatureFlagStatus.ACTIVE, 200),
}


@pytest.mark.parametrize("action", sorted(MUTATIONS))
def test_a_change_drops_the_flag_and_every_cached_list(
    cached_client, redis_server, flag, db_session, developer_user, action
):
    method, suffix, body, start, ok = MUTATIONS[action]
    flag.status = start
    db_session.commit()

    assert cached_client.get(f"{BASE}/{flag.id}").status_code == 200
    assert cached_client.get(f"{BASE}/").status_code == 200
    detail_key = f"feature_flag:{flag.id}"
    own_list = f"feature_flags:{developer_user.id}:0:100:None:None"
    # Every role sees every flag (#83), so another user's list is stale too.
    other_list = f"feature_flags:{uuid.uuid4()}:0:100:None:None"
    redis_server.set(other_list, "{}")
    assert redis_server.exists(detail_key, own_list, other_list) == 3

    resp = cached_client.request(method, f"{BASE}/{flag.id}{suffix}", json=body)
    assert resp.status_code == ok, resp.text

    assert redis_server.exists(detail_key) == 0, "the flag's cached detail survived"
    assert redis_server.exists(own_list, other_list) == 0, "a cached list survived"


def test_creating_a_flag_drops_every_cached_list(
    cached_client, redis_server, developer_user
):
    assert cached_client.get(f"{BASE}/").status_code == 200
    own_list = f"feature_flags:{developer_user.id}:0:100:None:None"
    other_list = f"feature_flags:{uuid.uuid4()}:0:100:None:None"
    redis_server.set(other_list, "{}")
    assert redis_server.exists(own_list, other_list) == 2

    key = f"cache100-{uuid.uuid4().hex[:8]}"
    resp = cached_client.post(
        f"{BASE}/", json={"key": key, "name": key, "rollout_percentage": 0}
    )
    assert resp.status_code == 201, resp.text
    assert redis_server.exists(own_list, other_list) == 0
