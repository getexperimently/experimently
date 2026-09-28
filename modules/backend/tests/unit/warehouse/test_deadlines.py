"""The total deadline is enforced inside the worker thread, on a monotonic clock."""

from __future__ import annotations

import pytest

from modules.backend.app.warehouse.deadlines import (
    READ_SECONDS,
    Deadline,
    connection_test_total,
    preview_total,
    run_total,
)
from modules.backend.app.warehouse.egress import OutboundClient
from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode
from modules.backend.app.warehouse.executor import JobKind, WarehouseExecutor
from modules.backend.tests.unit.warehouse.conftest import (
    FakeBackend,
    FakeClock,
    http_answer,
    public_resolver,
)


def test_total_deadline_enforced_against_trickling_upstream(fake_clock):
    """An upstream that answers one byte every 20 s never trips a 30 s read limit.

    The connection test's 30 s total must still end it: the worker thread checks
    the deadline before every read, fails with ``time_limit``, and is released.
    Fake clock: each read advances it 20 s; nothing waits in wall time.
    """
    body = b"x" * 4000
    backend = FakeBackend(
        [http_answer(200, body)], chunk=1, clock=fake_clock, seconds_per_read=20.0
    )
    executor = WarehouseExecutor(1, per_organisation=1, clock=fake_clock)
    start = fake_clock.now

    def connection_test(deadline: Deadline):
        with OutboundClient(
            deadline, resolver=public_resolver(), network_backend=backend
        ) as client:
            return client.request(
                "GET", "https://bigquery.googleapis.com/bigquery/v2/projects"
            )

    future = executor.try_submit(
        connection_test,
        total_seconds=connection_test_total(),
        kind=JobKind.CONNECTION_TEST,
    )
    try:
        with pytest.raises(WarehouseError) as err:
            future.result(timeout=30)  # a hang guard only; the fake clock decides
    finally:
        executor.shutdown(wait=True)

    assert err.value.code is WarehouseErrorCode.TIME_LIMIT
    # The worker was released, and it stopped reading long before the answer ended.
    assert executor.admitted == 0
    assert backend.reads < 10
    assert fake_clock.now - start <= connection_test_total() + 20.0
    # Every read was offered at most min(30 s, what was left).
    assert backend.read_timeouts
    assert all(t is not None and 0 < t <= READ_SECONDS for t in backend.read_timeouts)
    assert backend.read_timeouts[-1] <= connection_test_total() - 20.0 + 1e-9


def test_trickle_within_the_total_completes(fake_clock):
    """Positive control: the same trickle, short enough, finishes normally."""
    backend = FakeBackend(
        [http_answer(200, b"ok")], chunk=64, clock=fake_clock, seconds_per_read=1.0
    )
    deadline = Deadline(30, clock=fake_clock)
    with OutboundClient(
        deadline, resolver=public_resolver(), network_backend=backend
    ) as client:
        response = client.request("GET", "https://bigquery.googleapis.com/x")
    assert response.content == b"ok"


def test_poll_loop_stops_at_the_deadline(fake_clock):
    """A poll loop that sleeps through Deadline.sleep ends in time_limit."""
    deadline = Deadline(run_total(10, 0), clock=fake_clock)  # 70 s
    polls = 0

    def sleeper(seconds: float) -> None:
        fake_clock.advance(seconds)

    with pytest.raises(WarehouseError) as err:
        while True:
            polls += 1
            deadline.sleep(10, sleeper=sleeper)
    assert err.value.code is WarehouseErrorCode.TIME_LIMIT
    assert polls == 7


def test_deadline_caps_every_call():
    clock = FakeClock()
    deadline = Deadline(45, clock=clock)
    assert deadline.cap(30) == 30
    assert deadline.cap(None) == READ_SECONDS
    clock.advance(40)
    assert deadline.cap(30) == pytest.approx(5)
    assert deadline.http_timeout().read == pytest.approx(5)
    clock.advance(5)
    with pytest.raises(WarehouseError) as err:
        deadline.cap(30)
    assert err.value.code is WarehouseErrorCode.TIME_LIMIT


def test_fixed_totals():
    assert connection_test_total() == 30
    assert preview_total(300) == 330
    assert run_total(300, 3) == 4 * 300 + 60


def test_deadline_needs_a_positive_total():
    with pytest.raises(ValueError):
        Deadline(0)
