"""The Redis clients that ignored ``REDIS_PASSWORD`` now send it (#236).

``deps.get_redis_pool`` and both clients in ``results.py`` were built with
host, port and ssl but no password, so against a Redis that requires AUTH the
result cache and the dependency cache never connected -- silently, because
both degrade to "no cache". These drive the real functions against the
``redis`` package itself, not the helper they now go through, so they state
the defect independently of the fix. The full inventory is
``backend/tests/unit/core/test_redis_connection.py``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import redis
import redis.asyncio

from backend.app.core.config import settings

PASSWORD = "s3cret-236"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "REDIS_DB", 3)


def _get_cache_service() -> None:
    from backend.app.api.v1.endpoints.results import _get_cache_service

    assert _get_cache_service().enabled


def _invalidate_results_cache() -> None:
    from backend.app.api.v1.endpoints.results import invalidate_results_cache

    invalidate_results_cache(experiment_id=uuid4(), db=None, current_user=None)


@pytest.mark.unit
@pytest.mark.regression
def test_get_redis_pool_sends_redis_password(configured, monkeypatch):
    from backend.app.api import deps

    built = MagicMock()
    monkeypatch.setattr(redis.asyncio, "Redis", built)
    monkeypatch.setattr(deps, "_redis_pool", None)
    assert asyncio.run(deps.get_redis_pool()) is not None
    assert built.call_count == 1
    assert built.call_args.kwargs.get("password") == PASSWORD
    assert built.call_args.kwargs.get("db") == 3


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize(
    "driver",
    [_get_cache_service, _invalidate_results_cache],
    ids=["_get_cache_service", "invalidate_results_cache"],
)
def test_results_cache_clients_send_redis_password(driver, configured, monkeypatch):
    built = MagicMock()
    monkeypatch.setattr(redis, "Redis", built)
    driver()
    assert built.call_count == 1
    assert built.call_args.kwargs.get("password") == PASSWORD
    # REDIS_DB too: results.py hard-coded db=0.
    assert built.call_args.kwargs.get("db") == 3
