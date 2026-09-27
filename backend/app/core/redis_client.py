"""The one place a Redis client is built (#147, #236).

Every Redis client in ``backend/`` and ``modules/`` is created by
:func:`create_redis_client` or :func:`create_async_redis_client`, and both take
the connection parameters -- ``REDIS_HOST``, ``REDIS_PORT``,
``REDIS_PASSWORD``, ``REDIS_DB`` and ``REDIS_SSL`` -- from
:func:`redis_connection_kwargs`. A caller passes only client options (socket
timeouts, ``decode_responses``); a connection parameter is refused, so no call
site can drift from the settings again.

``backend/tests/unit/core/test_redis_connection.py`` scans the tree and fails
on a Redis constructor anywhere but here, and on a call site of these helpers
that it has not classified and driven.
"""

from __future__ import annotations

from typing import Any, Dict

from backend.app.core.config import settings

#: The keys that come from the settings and nowhere else.
CONNECTION_KEYS = frozenset({"host", "port", "password", "db", "ssl"})


def redis_connection_kwargs() -> Dict[str, Any]:
    """The connection parameters every Redis client uses, read from settings now.

    Read at call time, not import time, so a changed setting (and a test's
    ``monkeypatch.setattr(settings, ...)``) is honoured. An empty
    ``REDIS_PASSWORD`` means no password.
    """
    return {
        "host": str(settings.REDIS_HOST),
        "port": int(settings.REDIS_PORT),
        "password": settings.REDIS_PASSWORD or None,
        "db": int(settings.REDIS_DB or 0),
        "ssl": bool(settings.REDIS_SSL),
    }


def _client_kwargs(options: Dict[str, Any]) -> Dict[str, Any]:
    overridden = CONNECTION_KEYS.intersection(options)
    if overridden:
        raise ValueError(
            "Redis connection parameters come from the settings "
            f"(REDIS_HOST/PORT/PASSWORD/DB/SSL); do not pass {sorted(overridden)}"
        )
    return {**redis_connection_kwargs(), **options}


def create_redis_client(**options: Any) -> Any:
    """A synchronous ``redis.Redis`` connected per the settings.

    ``options`` are client options only (``socket_timeout``,
    ``decode_responses``, ...). Constructing the client does not connect; the
    first command does.
    """
    import redis

    return redis.Redis(**_client_kwargs(options))


def create_async_redis_client(**options: Any) -> Any:
    """A ``redis.asyncio.Redis`` connected per the settings; see above."""
    import redis.asyncio

    return redis.asyncio.Redis(**_client_kwargs(options))
