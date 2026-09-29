"""A warehouse that does not answer cannot take the API down with it.

The real routes, over the real application: the warehouse executor is
saturated by connection tests whose warehouse is held on an Event, forty more
get 429 at once, and an unrelated route that needs a request thread answers
200 while the Event is still unset.  anyio's request thread pool is shrunk to
the executor's size first, so a route that waited for a warehouse on a
request thread would starve it and the watchdog would fail the test.  This
asserts an ordering, not a duration.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import anyio.to_thread
import httpx
import pytest

from backend.app.main import app
from modules.backend.tests.integration.warehouse.conftest import WA
from modules.backend.tests.unit.warehouse.test_executor import _run_with_watchdog

pytestmark = [pytest.mark.integration, pytest.mark.modules]

EXECUTOR_SIZE = 4


def test_unrelated_request_served_while_warehouse_calls_block(wh):
    connection = wh.athena_connection(wh.as_("ADMIN"))
    release = wh.gate = threading.Event()
    helper = ThreadPoolExecutor(1)  # waits on `entered` outside anyio's pool

    async def scenario(outcome: dict) -> None:
        anyio.to_thread.current_default_thread_limiter().total_tokens = EXECUTOR_SIZE
        loop = asyncio.get_running_loop()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            test_url = f"{WA}/connections/{connection['id']}/test"
            saturating = [
                asyncio.create_task(client.post(test_url)) for _ in range(EXECUTOR_SIZE)
            ]
            for _ in range(EXECUTOR_SIZE):
                await loop.run_in_executor(helper, wh.entered.acquire)
            extra = await asyncio.gather(*(client.post(test_url) for _ in range(40)))
            outcome["extra"] = [r.status_code for r in extra]
            outcome["codes"] = {r.json()["detail"]["code"] for r in extra}
            outcome["retry_after"] = {r.headers.get("retry-after") for r in extra}
            unrelated = await client.get(f"{WA}/connectors")
            outcome["unrelated"] = unrelated.status_code
            outcome["released_before_unrelated_answered"] = release.is_set()
            release.set()
            done = await asyncio.gather(*saturating)
            outcome["saturating"] = [r.status_code for r in done]

    outcome, hung = _run_with_watchdog(scenario, release)
    helper.shutdown(wait=False)
    assert not hung, (
        f"a request could not be served while the warehouse held: {outcome}"
    )
    assert "error" not in outcome, outcome
    assert outcome["extra"] == [429] * 40
    assert outcome["codes"] == {"warehouse_busy"}
    assert outcome["retry_after"] == {"30"}
    assert outcome["unrelated"] == 200
    assert outcome["released_before_unrelated_answered"] is False
    assert outcome["saturating"] == [200] * EXECUTOR_SIZE
