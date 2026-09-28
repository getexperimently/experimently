"""Fixtures and fakes for the warehouse outbound layer's tests.

Nothing here opens a connection outside this machine: upstreams are either
in-process fake network streams (:class:`FakeBackend`) or a TCP listener on
127.0.0.1 (:class:`Probe`) that only counts the connections it accepts.
"""

from __future__ import annotations

import socket
import threading
from typing import Iterable, List, Optional, Tuple

import httpcore
import pytest


@pytest.fixture(autouse=True)
def mock_logging_handler():
    """Override the unit tree's autouse fixture, which swaps ``logging.getLogger``
    for a mock: these tests assert on real log records (``caplog``)."""
    yield None


class FakeClock:
    """A monotonic clock that moves only when told to."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeStream(httpcore.NetworkStream):
    """Serves canned bytes, ``chunk`` bytes per read, advancing a fake clock."""

    def __init__(
        self,
        payload: bytes,
        *,
        chunk: int = 65536,
        clock: Optional[FakeClock] = None,
        seconds_per_read: float = 0.0,
        log: Optional["FakeBackend"] = None,
    ) -> None:
        self._payload = payload
        self._chunk = chunk
        self._clock = clock
        self._seconds_per_read = seconds_per_read
        self._log = log
        self.written = b""

    def read(self, max_bytes: int, timeout: Optional[float] = None) -> bytes:
        if self._log is not None:
            self._log.read_timeouts.append(timeout)
            self._log.reads += 1
        if self._clock is not None:
            self._clock.advance(self._seconds_per_read)
        size = min(max_bytes, self._chunk)
        data, self._payload = self._payload[:size], self._payload[size:]
        return data

    def write(self, buffer: bytes, timeout: Optional[float] = None) -> None:
        self.written += buffer
        if self._log is not None:
            self._log.requests_written.append(bytes(buffer))

    def close(self) -> None:
        pass

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        if self._log is not None:
            self._log.tls_hostnames.append(server_hostname)
        return self

    def get_extra_info(self, info: str):
        return None


class FakeBackend(httpcore.NetworkBackend):
    """Hands out one FakeStream per connection, from a list of canned answers.

    Records every connect attempt, so a test can assert that none was made.
    """

    def __init__(
        self,
        answers: Iterable[bytes] = (),
        *,
        chunk: int = 65536,
        clock: Optional[FakeClock] = None,
        seconds_per_read: float = 0.0,
    ) -> None:
        self._answers = list(answers)
        self._chunk = chunk
        self._clock = clock
        self._seconds_per_read = seconds_per_read
        self.connects: List[Tuple[str, int]] = []
        self.requests_written: List[bytes] = []
        self.read_timeouts: List[Optional[float]] = []
        self.tls_hostnames: List[Optional[str]] = []
        self.reads = 0

    def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        self.connects.append((host, port))
        if not self._answers:
            raise httpcore.ConnectError("no fake answer left")
        return FakeStream(
            self._answers.pop(0),
            chunk=self._chunk,
            clock=self._clock,
            seconds_per_read=self._seconds_per_read,
            log=self,
        )

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("no unix sockets")

    def sleep(self, seconds: float) -> None:
        pass


def http_answer(
    status: int, body: bytes = b"", headers: Iterable[Tuple[str, str]] = ()
) -> bytes:
    """A complete HTTP/1.1 response with a Content-Length."""
    reason = {200: "OK", 302: "Found", 400: "Bad Request", 500: "Server Error"}.get(
        status, "X"
    )
    lines = [f"HTTP/1.1 {status} {reason}", f"Content-Length: {len(body)}"]
    lines += [f"{name}: {value}" for name, value in headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


def public_resolver(address: str = "93.184.216.34"):
    """A resolver that answers every name with one public address."""

    def resolve(host: str, port: int):
        return [(address, port)]

    return resolve


class Probe:
    """A TCP listener on 127.0.0.1 that counts the connections it accepts."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self.accepted = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            self.accepted += 1
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(2)
        self._sock.close()


@pytest.fixture
def probe():
    listener = Probe()
    try:
        yield listener
    finally:
        listener.close()


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()
