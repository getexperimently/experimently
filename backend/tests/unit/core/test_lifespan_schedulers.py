"""
The FastAPI lifespan must not start the background schedulers under the test
profile.

A ``TestClient`` used as a context manager runs the lifespan. If the
schedulers started there, their first tick would run immediately against the
test database, in the middle of whatever test happened to be executing — which
showed up in CI as ``aggregate_metrics`` being called seven times in a test
that patched it and expected one call, and as ticks connecting to and dropping
the test database's connections.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.main import app, lifespan

SCHEDULERS = (
    "experiment_scheduler",
    "rollout_scheduler",
    "metrics_scheduler",
    "safety_scheduler",
    "bandit_scheduler_runner",
)


@pytest.mark.asyncio
async def test_lifespan_starts_nothing_in_the_test_environment(monkeypatch):
    import backend.app.main as main

    started: list[str] = []
    for name in SCHEDULERS:
        scheduler = getattr(main, name)

        async def _start(_name=name):
            started.append(_name)

        async def _stop(_name=name):
            started.append(f"stop:{_name}")

        monkeypatch.setattr(scheduler, "start", _start)
        monkeypatch.setattr(scheduler, "stop", _stop)

    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    async with lifespan(app):
        pass
    assert started == []


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_them_outside_tests(monkeypatch):
    import backend.app.main as main

    started: list[str] = []
    for name in SCHEDULERS:
        scheduler = getattr(main, name)

        async def _start(_name=name):
            started.append(_name)

        async def _stop(_name=name):
            started.append(f"stop:{_name}")

        monkeypatch.setattr(scheduler, "start", _start)
        monkeypatch.setattr(scheduler, "stop", _stop)

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    async with lifespan(app):
        assert set(started) == set(SCHEDULERS)
    assert {entry for entry in started if entry.startswith("stop:")} == {
        f"stop:{name}" for name in SCHEDULERS
    }


def test_test_client_context_manager_does_not_start_schedulers(monkeypatch):
    """The regression itself: entering a TestClient must not tick anything."""
    import backend.app.main as main

    started: list[str] = []
    for name in SCHEDULERS:
        scheduler = getattr(main, name)

        async def _start(_name=name):
            started.append(_name)

        async def _stop(_name=name):
            return None

        monkeypatch.setattr(scheduler, "start", _start)
        monkeypatch.setattr(scheduler, "stop", _stop)

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
    assert started == []
