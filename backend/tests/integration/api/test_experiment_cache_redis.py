"""The experiment routes with the cache on, against a real Redis (#428).

``deps.get_cache_control`` hands the routes a ``redis.asyncio`` client. Most
experiment routes called it without ``await``: ``delete`` returned a coroutine
that never ran, and ``for key in redis.scan_iter(...)`` raised ``TypeError``
(an async generator is not iterable) *after* the change was committed -- so
update, delete, start, pause, schedule, complete, archive and clone answered
500 for a change that had in fact been made. Metadata left the cached detail
behind, and the daily and segmented results were never written to the cache
(``setex`` un-awaited). Create cleared only the caller's own lists. The same
defect #427 fixed for the feature-flag routes (#100).

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
none -- unless ``EXPERIMENTLY_REQUIRE_REDIS=1``, which makes it a failure.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import redis as sync_redis
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.experiment import Experiment
from backend.tests.integration.conftest import make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.regression]

BASE = "/api/v1/experiments"
CACHE_DB = 15
PREFIX = "cache428-"


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


def _cached_client_for(db_session, user, monkeypatch):
    """``user``'s client with the real ``get_cache_control`` and the cache on."""
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(deps, "_redis_pool", None)  # built on this client's loop
    make_client_for_user(db_session, user)
    app.dependency_overrides.pop(deps.get_cache_control)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cached_client(redis_server, db_session, developer_user, monkeypatch):
    """A non-superuser DEVELOPER, who owns every experiment it creates."""
    yield from _cached_client_for(db_session, developer_user, monkeypatch)


@pytest.fixture
def cached_superuser_client(redis_server, db_session, admin_user, monkeypatch):
    """Only for the detail read, which answers 403 to every non-superuser --
    owner included -- whether or not the cache is on (a separate defect)."""
    yield from _cached_client_for(db_session, admin_user, monkeypatch)


@pytest.fixture(autouse=True)
def _remove_the_experiments_created(db_session):
    yield
    db_session.rollback()
    for row in db_session.query(Experiment).filter(Experiment.name.like(f"%{PREFIX}%")):
        db_session.delete(row)  # the ORM cascades to variants and metrics
    db_session.commit()


def _create(client: TestClient) -> dict:
    name = f"{PREFIX}{uuid.uuid4().hex[:8]}"
    resp = client.post(
        f"{BASE}/",
        json={
            "name": name,
            "description": "cache test",
            "hypothesis": "the cache is dropped",
            "experiment_type": "a_b",
            "variants": [
                {"name": "Control", "is_control": True, "traffic_allocation": 50},
                {"name": "Treatment", "is_control": False, "traffic_allocation": 50},
            ],
            "metrics": [
                {
                    "name": "Conversion",
                    "event_name": "purchase",
                    "metric_type": "conversion",
                    "is_primary": True,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _started(client: TestClient) -> dict:
    exp = _create(client)
    resp = client.post(f"{BASE}/{exp['id']}/start")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _plant_lists(redis_server, owner_id) -> tuple[str, str]:
    """A cached list for the owner and one for someone else, both stale after
    a change: every role sees every experiment (#83)."""
    own_list = f"experiments:{owner_id}:0:100"
    other_list = f"experiments:{uuid.uuid4()}:0:100"
    redis_server.set(own_list, "{}")
    redis_server.set(other_list, "{}")
    return own_list, other_list


def test_the_cache_dependency_is_live(cached_client, redis_server):
    """Guards the rest: were the cache silently off, they could not fail."""
    control = cached_client.portal.call(deps.get_cache_control)
    assert control.enabled is True
    assert control.redis is not None


def test_the_experiment_detail_is_cached_and_served_from_the_cache(
    cached_superuser_client, redis_server
):
    cached_client = cached_superuser_client
    exp = _create(cached_client)
    first = cached_client.get(f"{BASE}/{exp['id']}")
    assert first.status_code == 200, first.text

    key = f"experiment:{exp['id']}"
    stored = redis_server.get(key)
    assert stored is not None, "the detail was not written to the cache"
    assert json.loads(stored)["id"] == exp["id"]

    # A marker only the cache holds: the second answer must come from Redis.
    redis_server.set(key, json.dumps({**json.loads(stored), "name": "from-cache"}))
    second = cached_client.get(f"{BASE}/{exp['id']}")
    assert second.status_code == 200, second.text
    assert second.json()["name"] == "from-cache"


# name -> (path suffix under the experiment, cache key suffix)
RESULTS = {
    "daily": ("/daily-results", "experiment_daily_results:{id}"),
    "segmented": (
        "/segmented-results/country",
        "experiment_segmented_results:{id}:country",
    ),
}


@pytest.mark.parametrize("kind", sorted(RESULTS))
def test_results_are_cached_and_served_from_the_cache(
    cached_client, redis_server, kind
):
    suffix, key_shape = RESULTS[kind]
    exp = _started(cached_client)
    first = cached_client.get(f"{BASE}/{exp['id']}{suffix}")
    assert first.status_code == 200, first.text

    key = key_shape.format(id=exp["id"])
    stored = redis_server.get(key)
    assert stored is not None, f"the {kind} results were not written to the cache"
    assert json.loads(stored) == first.json()

    marker = [{"from": "cache"}] if kind == "daily" else {"from": "cache"}
    redis_server.set(key, json.dumps(marker))
    second = cached_client.get(f"{BASE}/{exp['id']}{suffix}")
    assert second.status_code == 200, second.text
    assert second.json() == marker


def _future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# name -> (method, suffix, json body, query, starts ACTIVE?, success code)
MUTATIONS = {
    "update": ("PUT", "", {"description": "changed"}, None, False, 200),
    "delete": ("DELETE", "", None, "experiment_key", False, 204),
    "start": ("POST", "/start", None, None, False, 200),
    "pause": ("POST", "/pause", None, None, True, 200),
    "schedule": (
        "PUT",
        "/schedule",
        {"start_date": _future(1), "end_date": _future(8), "time_zone": "UTC"},
        None,
        False,
        200,
    ),
    "complete": ("POST", "/complete", None, None, True, 200),
    "archive": ("POST", "/archive", None, None, False, 200),
    "metadata": ("POST", "/metadata", {"note": "cache428"}, None, False, 200),
}


@pytest.mark.parametrize("action", sorted(MUTATIONS))
def test_a_change_drops_the_experiment_and_every_cached_list(
    cached_client, redis_server, developer_user, action
):
    method, suffix, body, query, active, ok = MUTATIONS[action]
    exp = _started(cached_client) if active else _create(cached_client)

    # Planted, not read through the route: the detail read refuses this
    # developer (see ``cached_superuser_client``).
    detail_key = f"experiment:{exp['id']}"
    redis_server.set(detail_key, json.dumps(exp))
    own_list, other_list = _plant_lists(redis_server, developer_user.id)
    assert redis_server.exists(detail_key, own_list, other_list) == 3

    params = {"experiment_key": exp["id"]} if query else None
    resp = cached_client.request(
        method, f"{BASE}/{exp['id']}{suffix}", json=body, params=params
    )
    assert resp.status_code == ok, resp.text

    assert redis_server.exists(detail_key) == 0, "the cached detail survived"
    assert redis_server.exists(own_list, other_list) == 0, "a cached list survived"


@pytest.mark.parametrize("action", ["create", "clone"])
def test_a_new_experiment_drops_every_cached_list(
    cached_client, redis_server, developer_user, action
):
    source = _create(cached_client) if action == "clone" else None
    own_list, other_list = _plant_lists(redis_server, developer_user.id)

    if action == "clone":
        resp = cached_client.post(f"{BASE}/{source['id']}/clone")
        assert resp.status_code == 201, resp.text
    else:
        _create(cached_client)

    assert redis_server.exists(own_list, other_list) == 0, "a cached list survived"


def test_a_redis_error_after_the_change_is_logged_not_raised(
    cached_client, redis_server, monkeypatch, caplog
):
    """The change is committed before the cache is touched: a Redis failure
    then must not turn a change that was made into a 500."""
    exp = _create(cached_client)
    control = cached_client.portal.call(deps.get_cache_control)

    def broken_scan_iter(*args, **kwargs):
        raise sync_redis.ConnectionError("redis went away")

    monkeypatch.setattr(type(control.redis), "scan_iter", broken_scan_iter)
    resp = cached_client.put(f"{BASE}/{exp['id']}", json={"description": "changed"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "changed"
    assert "Experiment cache invalidation failed" in caplog.text
