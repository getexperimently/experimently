"""Warehouse calls run off the request thread pool, and admission never waits."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import anyio.to_thread
import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode
from modules.backend.app.warehouse.executor import JobKind, WarehouseExecutor

#: Seconds the watchdog waits for a scenario before calling it hung.  The
#: design finishes in well under a second; this only turns a hang into a
#: failure, it is not a performance threshold.
WATCHDOG_SECONDS = 20.0

EXECUTOR_SIZE = 4


def _run_with_watchdog(scenario, release: threading.Event):
    """Run ``scenario`` (a coroutine function) on its own event loop and thread.

    Returns ``(outcome, hung)``.  If the scenario has not finished after
    WATCHDOG_SECONDS it is hung; the blocked jobs are then released so its
    threads can end.  The watchdog is this (the test's) thread, so it works
    even when the scenario blocks its own event loop.
    """
    outcome: dict = {}

    def target() -> None:
        try:
            asyncio.run(scenario(outcome))
        except BaseException as exc:  # reported by the caller
            outcome["error"] = repr(exc)

    thread = threading.Thread(target=target, name="scenario", daemon=True)
    thread.start()
    thread.join(WATCHDOG_SECONDS)
    hung = thread.is_alive()
    release.set()
    if not hung:
        thread.join(WATCHDOG_SECONDS)
    return outcome, hung


def _app(executor: WarehouseExecutor, job) -> FastAPI:
    app = FastAPI()

    @app.post("/warehouse-call")
    async def warehouse_call():
        try:
            result = await executor.run(
                job, total_seconds=60, kind=JobKind.CONNECTION_TEST
            )
        except WarehouseError as err:
            return JSONResponse(
                err.to_body(),
                status_code=err.status_code,
                headers=err.response_headers(),
            )
        return {"result": result}

    @app.get("/unrelated")
    def unrelated():  # a sync route: it needs a thread from anyio's pool
        return {"ok": True}

    return app


def test_unrelated_request_served_while_warehouse_calls_block():
    """The executor is saturated by jobs blocked on an Event.  Forty more calls
    get 429 at once, and an unrelated sync GET returns 200 while the Event is
    still unset.  anyio's request thread pool is shrunk to the executor's size,
    so any design that parks a request thread per warehouse call starves it and
    hangs here (the watchdog turns that into a failure).  This asserts an
    ordering, not a duration."""
    executor = WarehouseExecutor(EXECUTOR_SIZE, per_organisation=EXECUTOR_SIZE)
    release = threading.Event()
    started = threading.Semaphore(0)
    helper = ThreadPoolExecutor(1)  # waits on `started` without using anyio's pool

    def blocked_job(deadline):
        started.release()
        release.wait()
        return "done"

    app = _app(executor, blocked_job)

    async def scenario(outcome: dict) -> None:
        anyio.to_thread.current_default_thread_limiter().total_tokens = EXECUTOR_SIZE
        loop = asyncio.get_running_loop()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            saturating = [
                asyncio.create_task(client.post("/warehouse-call"))
                for _ in range(EXECUTOR_SIZE)
            ]
            for _ in range(EXECUTOR_SIZE):
                await loop.run_in_executor(helper, started.acquire)
            outcome["saturated"] = True

            extra = await asyncio.gather(
                *(client.post("/warehouse-call") for _ in range(40))
            )
            outcome["extra"] = [r.status_code for r in extra]
            outcome["extra_bodies"] = {r.json()["code"] for r in extra}
            outcome["retry_after"] = {r.headers.get("retry-after") for r in extra}

            unrelated = await client.get("/unrelated")
            outcome["unrelated"] = unrelated.status_code
            outcome["released_before_unrelated_answered"] = release.is_set()

            release.set()
            done = await asyncio.gather(*saturating)
            outcome["saturating"] = [r.status_code for r in done]

    outcome, hung = _run_with_watchdog(scenario, release)
    release.set()
    helper.shutdown(wait=False)
    executor.shutdown(wait=not hung)

    assert not hung, (
        "hung: a request could not be served while warehouse calls were blocked "
        f"(progress so far: {outcome})"
    )
    assert "error" not in outcome, outcome
    assert outcome["extra"] == [429] * 40
    assert outcome["extra_bodies"] == {"warehouse_busy"}
    assert outcome["retry_after"] == {"30"}
    assert outcome["unrelated"] == 200
    assert outcome["released_before_unrelated_answered"] is False
    assert outcome["saturating"] == [200] * EXECUTOR_SIZE
    assert executor.admitted == 0


def test_admission_refuses_without_waiting():
    """Full executor, same key, organisation cap: each refused at once, in order."""
    executor = WarehouseExecutor(3, per_organisation=2)
    release = threading.Event()

    def blocked(deadline):
        release.wait()
        return "ok"

    outcome: dict = {}

    def scenario() -> None:
        first = executor.try_submit(
            blocked, total_seconds=60, kind=JobKind.ANALYSIS, key="connection-1"
        )
        try:
            executor.try_submit(
                blocked, total_seconds=60, kind=JobKind.PREVIEW, key="connection-1"
            )
        except WarehouseError as err:
            outcome["same_key"] = err.code
        second = executor.try_submit(
            blocked, total_seconds=60, kind=JobKind.PREVIEW, key="c2"
        )
        try:
            executor.try_submit(
                blocked, total_seconds=60, kind=JobKind.ANALYSIS, key="c3"
            )
        except WarehouseError as err:
            outcome["organisation_cap"] = err.code
        # A connection test is not counted by the organisation cap...
        third = executor.try_submit(
            blocked, total_seconds=60, kind=JobKind.CONNECTION_TEST, key="c4"
        )
        # ...but every thread is now taken.
        try:
            executor.try_submit(blocked, total_seconds=60, kind=JobKind.CONNECTION_TEST)
        except WarehouseError as err:
            outcome["full"] = err.code
        outcome["futures"] = (first, second, third)

    thread = threading.Thread(target=scenario, daemon=True)
    thread.start()
    thread.join(WATCHDOG_SECONDS)
    hung = thread.is_alive()
    release.set()
    if hung:
        executor.shutdown(wait=False)
    thread.join(0 if hung else WATCHDOG_SECONDS)
    try:
        assert not hung, f"admission waited for a slot (progress so far: {outcome})"
        assert outcome["same_key"] is WarehouseErrorCode.RUN_IN_PROGRESS
        assert outcome["organisation_cap"] is WarehouseErrorCode.WAREHOUSE_BUSY
        assert outcome["full"] is WarehouseErrorCode.WAREHOUSE_BUSY
        assert [f.result(timeout=WATCHDOG_SECONDS) for f in outcome["futures"]] == [
            "ok"
        ] * 3
        assert executor.admitted == 0
        # Released slots and keys can be taken again.
        again = executor.try_submit(
            lambda deadline: "again",
            total_seconds=5,
            kind=JobKind.ANALYSIS,
            key="connection-1",
        )
        assert again.result(timeout=WATCHDOG_SECONDS) == "again"
    finally:
        executor.shutdown(wait=not hung)


def test_organisations_are_capped_separately():
    executor = WarehouseExecutor(4, per_organisation=1)
    release = threading.Event()
    try:
        a = executor.try_submit(
            lambda d: release.wait(5),
            total_seconds=10,
            kind=JobKind.ANALYSIS,
            organisation="a",
        )
        b = executor.try_submit(
            lambda d: release.wait(5),
            total_seconds=10,
            kind=JobKind.ANALYSIS,
            organisation="b",
        )
        with pytest.raises(WarehouseError) as err:
            executor.try_submit(
                lambda d: None,
                total_seconds=10,
                kind=JobKind.ANALYSIS,
                organisation="a",
            )
        assert err.value.code is WarehouseErrorCode.WAREHOUSE_BUSY
        release.set()
        a.result(timeout=WATCHDOG_SECONDS)
        b.result(timeout=WATCHDOG_SECONDS)
    finally:
        release.set()
        executor.shutdown(wait=True)


def test_executor_threads_are_not_the_request_pool():
    executor = WarehouseExecutor(1, per_organisation=1)
    try:
        name = executor.try_submit(
            lambda d: threading.current_thread().name,
            total_seconds=5,
            kind=JobKind.CONNECTION_TEST,
        ).result(timeout=WATCHDOG_SECONDS)
    finally:
        executor.shutdown(wait=True)
    assert name.startswith("warehouse")


def test_a_job_cancelled_before_it_starts_gives_its_slot_back():
    """shutdown(cancel_futures=True) cancels a job no thread has picked up; its
    slot, key and organisation count must still be released.  (Slots equal
    threads, so the test occupies the pool's only thread from outside to leave
    the admitted job queued.)"""
    executor = WarehouseExecutor(2, per_organisation=2)
    occupier_release = threading.Event()
    executor._pool.shutdown(wait=False)
    executor._pool = ThreadPoolExecutor(1)
    executor._pool.submit(occupier_release.wait, 10)
    ran = []
    try:
        future = executor.try_submit(
            lambda d: ran.append(1), total_seconds=10, kind=JobKind.ANALYSIS, key="c1"
        )
        assert executor.admitted == 1
        executor.shutdown(wait=False)
        assert future.cancelled()
        assert ran == []
        assert executor.admitted == 0
        assert executor._keys == set()
        assert not executor._by_organisation
    finally:
        occupier_release.set()


def test_executor_needs_a_slot():
    with pytest.raises(ValueError):
        WarehouseExecutor(0, per_organisation=1)


def test_executor_is_sized_from_the_settings():
    from modules.backend.app.settings import ModulesSettings

    settings = ModulesSettings()
    assert settings.WAREHOUSE_MAX_CONCURRENT_JOBS == 4
    assert settings.WAREHOUSE_MAX_CONCURRENT_RUNS == 2
    with pytest.raises(ValueError):
        ModulesSettings(WAREHOUSE_MAX_CONCURRENT_JOBS=0)
