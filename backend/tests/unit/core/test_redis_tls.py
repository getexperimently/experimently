"""Every Redis client the application builds honours ``REDIS_SSL`` (#147).

The deployed ElastiCache replication group has in-transit encryption on
(``infrastructure/cdk/stacks/elasticache_redis_stack.py``), so it refuses a
plaintext connection. Every client used to be built as
``redis.Redis(host=settings.REDIS_HOST, ...)`` with no TLS, so on AWS the rate
limiter fell back to memory, the readiness probe reported Redis unhealthy and
the caches were silently skipped -- all of it "degrading gracefully", none of
it visible.

The gate has two halves, and each is needed:

* **The scan.** Every call in ``backend/`` and ``modules/`` (tests excluded)
  that builds a Redis client -- ``Redis(``, ``StrictRedis(``, ``RedisCluster(``,
  ``ConnectionPool(``, ``from_url(`` -- is found by walking the AST, and the
  set of sites must equal :data:`SITES` exactly. A sixth constructor fails
  here until it is classified in :data:`SITES` and given a driver below.
* **The drive.** Each site is actually executed with ``REDIS_SSL`` on, against
  a recording stand-in for the client class, and must pass ``ssl=True``. The
  stand-in records the file and line it was called from, and the lines driven
  must be exactly the lines scanned -- so a driver cannot quietly exercise a
  different call than the one the scan found.

``deps.get_redis_pool`` builds ``redis.asyncio.Redis``, a different class from
``redis.Redis``: patching the latter does not intercept it. It is driven on
its own, with only the asyncio class replaced, and the sync class is asserted
untouched.
"""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import redis
import redis.asyncio

from backend.app.core.config import settings

REPO_ROOT = Path(__file__).resolve().parents[4]
SCANNED_ROOTS = ("backend", "modules")

#: The callee names that build a Redis connection.
CONSTRUCTORS = {"Redis", "StrictRedis", "RedisCluster", "ConnectionPool", "from_url"}

#: Every Redis client construction outside the tests, as
#: (path from the repository root, enclosing function). Adding a sixth means
#: adding it here AND a driver in ``DRIVERS``.
SITES = {
    ("backend/app/middleware/rate_limiter.py", "RedisRateLimiter._get_redis"),
    ("backend/app/core/health.py", "check_redis"),
    ("backend/app/api/deps.py", "get_redis_pool"),
    ("backend/app/api/v1/endpoints/results.py", "_get_cache_service"),
    ("backend/app/api/v1/endpoints/results.py", "invalidate_results_cache"),
}


def _is_test_path(relative: Path) -> bool:
    return (
        "tests" in relative.parts
        or relative.name.startswith("test_")
        or relative.name == "conftest.py"
    )


def _callee_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def scan(roots=SCANNED_ROOTS) -> dict[tuple[str, str], int]:
    """``{(path, enclosing function): line}`` for every Redis constructor call."""
    found: dict[tuple[str, str], int] = {}
    for root in roots:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(REPO_ROOT)
            if _is_test_path(relative) or "node_modules" in relative.parts:
                continue
            tree = ast.parse(path.read_text(), filename=str(relative))
            for scope, call in _calls_with_scope(tree):
                if _callee_name(call) in CONSTRUCTORS:
                    key = (relative.as_posix(), scope)
                    assert key not in found, f"two Redis constructors in {key}"
                    found[key] = call.lineno
    return found


def _calls_with_scope(tree: ast.AST):
    """Yield ``(qualified enclosing function, call)`` for every call."""

    def visit(node: ast.AST, scope: list[str]):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                yield from visit(child, scope + [child.name])
            else:
                if isinstance(child, ast.Call):
                    yield ".".join(scope) or "<module>", child
                yield from visit(child, scope)

    yield from visit(tree, [])


# ---------------------------------------------------------------------------
# The recording stand-in
# ---------------------------------------------------------------------------


class Recorder:
    """Stands in for a Redis client class; records every construction."""

    def __init__(self):
        self.calls: list[tuple[tuple[str, int], dict]] = []

    def __call__(self, *args, **kwargs):
        caller = sys._getframe(1)
        filename = Path(caller.f_code.co_filename).resolve()
        try:
            where = filename.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            where = str(filename)
        self.calls.append(((where, caller.f_lineno), kwargs))
        client = MagicMock(name="redis-client")
        client.ping.return_value = True
        return client


def _drive_rate_limiter() -> None:
    from backend.app.middleware.rate_limiter import RateLimitMiddleware

    async def app(scope, receive, send):  # pragma: no cover - never called
        pass

    # Through the middleware, so the REDIS_SSL -> RedisRateLimiter.__init__
    # hand-off is part of what is tested, not just the constructor.
    middleware = RateLimitMiddleware(app, enabled=True)
    middleware._limiter._get_redis()


def _drive_health() -> None:
    from backend.app.core.health import check_redis

    assert check_redis()["status"] == "healthy"


def _drive_deps() -> None:
    from backend.app.api import deps

    deps._redis_pool = None
    try:
        assert asyncio.run(deps.get_redis_pool()) is not None
    finally:
        deps._redis_pool = None


def _drive_results_cache() -> None:
    from backend.app.api.v1.endpoints.results import _get_cache_service

    _get_cache_service()


def _drive_results_invalidate() -> None:
    from backend.app.api.v1.endpoints.results import invalidate_results_cache

    invalidate_results_cache(experiment_id=uuid4(), db=None, current_user=None)


#: site -> (driver, which client class it builds)
DRIVERS: dict[tuple[str, str], tuple[Callable[[], None], str]] = {
    ("backend/app/middleware/rate_limiter.py", "RedisRateLimiter._get_redis"): (
        _drive_rate_limiter,
        "sync",
    ),
    ("backend/app/core/health.py", "check_redis"): (_drive_health, "sync"),
    ("backend/app/api/deps.py", "get_redis_pool"): (_drive_deps, "asyncio"),
    ("backend/app/api/v1/endpoints/results.py", "_get_cache_service"): (
        _drive_results_cache,
        "sync",
    ),
    ("backend/app/api/v1/endpoints/results.py", "invalidate_results_cache"): (
        _drive_results_invalidate,
        "sync",
    ),
}


def _drive(site, monkeypatch, *, ssl: bool) -> tuple[Recorder, Recorder]:
    """Run ``site`` with REDIS_SSL=``ssl``; return (sync, asyncio) recorders."""
    monkeypatch.setattr(settings, "REDIS_SSL", ssl)
    sync, asyncio_ = Recorder(), Recorder()
    monkeypatch.setattr(redis, "Redis", sync)
    monkeypatch.setattr(redis.asyncio, "Redis", asyncio_)
    driver, _ = DRIVERS[site]
    driver()
    return sync, asyncio_


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.regression
def test_the_scan_finds_exactly_the_classified_sites():
    """Five constructors, no more: a sixth fails until it is classified."""
    found = scan()
    assert set(found) == SITES, (
        "The Redis constructors in backend/ and modules/ are not the classified "
        "set. New (classify in SITES, add a driver, pass ssl=settings.REDIS_SSL): "
        f"{sorted(set(found) - SITES)}; gone: {sorted(SITES - set(found))}"
    )
    assert len(found) == 5
    assert set(DRIVERS) == SITES


@pytest.mark.unit
def test_the_scan_is_not_blind(tmp_path, monkeypatch):
    """A planted constructor of each spelling is found; a test file is not."""
    planted = tmp_path / "backend" / "app" / "planted.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        "import redis\n"
        "def a():\n    redis.Redis(host='h')\n"
        "def b():\n    redis.StrictRedis(host='h')\n"
        "def c():\n    redis.from_url('redis://h')\n"
        "def d():\n    redis.ConnectionPool(host='h')\n"
        "class K:\n    def e(self):\n        Redis()\n"
    )
    ignored = tmp_path / "backend" / "tests" / "test_x.py"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("import redis\nredis.Redis()\n")
    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
    assert set(scan()) == {
        ("backend/app/planted.py", "a"),
        ("backend/app/planted.py", "b"),
        ("backend/app/planted.py", "c"),
        ("backend/app/planted.py", "d"),
        ("backend/app/planted.py", "K.e"),
    }


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("site", sorted(SITES), ids=lambda s: f"{s[0]}:{s[1]}")
def test_with_redis_ssl_every_constructor_passes_ssl_true(site, monkeypatch):
    """Drive the site with REDIS_SSL on; the client must be built with ssl=True."""
    line = scan()[site]
    sync, asyncio_ = _drive(site, monkeypatch, ssl=True)
    _, flavour = DRIVERS[site]
    built, other = (sync, asyncio_) if flavour == "sync" else (asyncio_, sync)

    assert other.calls == [], (
        f"{site} built a {'redis.Redis' if flavour == 'asyncio' else 'redis.asyncio.Redis'}"
        f", not the class it was classified as: {other.calls}"
    )
    assert [where for where, _ in built.calls] == [(site[0], line)], (
        f"driving {site} did not construct the client at the scanned line "
        f"{site[0]}:{line}; constructions seen: {built.calls}"
    )
    ((_, kwargs),) = built.calls
    assert kwargs.get("ssl") is True, (
        f"{site[0]}:{line} builds its Redis client without ssl=True while "
        f"REDIS_SSL is set (kwargs: {sorted(kwargs)}); the deployed ElastiCache "
        "refuses plaintext (#147)"
    )


@pytest.mark.unit
@pytest.mark.parametrize("site", sorted(SITES), ids=lambda s: f"{s[0]}:{s[1]}")
def test_without_redis_ssl_every_constructor_speaks_plaintext(site, monkeypatch):
    """The default stays plaintext: the local and CI redis:7 have no TLS."""
    sync, asyncio_ = _drive(site, monkeypatch, ssl=False)
    ((_, kwargs),) = sync.calls + asyncio_.calls
    assert kwargs.get("ssl") is False, kwargs


@pytest.mark.unit
@pytest.mark.regression
def test_the_asyncio_pool_is_not_intercepted_by_patching_redis_redis(monkeypatch):
    """Why deps.py is driven on its own: the sync patch never sees it."""
    monkeypatch.setattr(settings, "REDIS_SSL", True)
    sync = Recorder()
    monkeypatch.setattr(redis, "Redis", sync)
    asyncio_ = Recorder()
    monkeypatch.setattr(redis.asyncio, "Redis", asyncio_)
    _drive_deps()
    assert sync.calls == []
    ((_, kwargs),) = asyncio_.calls
    assert kwargs["ssl"] is True


@pytest.mark.unit
def test_redis_ssl_defaults_off_and_reads_the_environment(monkeypatch):
    from backend.app.core.config import Settings

    monkeypatch.delenv("REDIS_SSL", raising=False)
    assert Settings.model_fields["REDIS_SSL"].default is False
    monkeypatch.setenv("REDIS_SSL", "true")
    assert Settings().REDIS_SSL is True
