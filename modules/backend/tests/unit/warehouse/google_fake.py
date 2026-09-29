"""A recorded-response Google for the BigQuery connector's tests.

The connector's real client (:class:`~modules.backend.app.warehouse.egress.
OutboundClient` over :class:`~modules.backend.app.warehouse.egress.
GuardedTransport`) is used unchanged: the destination check, the address
check, the deadline and the body limit all run.  Only the network is fake --
:class:`GoogleFake` is an httpcore network backend whose streams read the
HTTP request the client wrote and answer it from a handler, with a recorded
response from ``recorded/bigquery/``.  Nothing leaves the machine.

Each recorded file is ``{"_provenance": ..., "status": ..., "body": ...}``;
``test_recorded_fixtures_declare_provenance`` requires the provenance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import httpcore

from modules.backend.app.warehouse.deadlines import Deadline
from modules.backend.app.warehouse.egress import GuardedTransport, OutboundClient
from modules.backend.tests.unit.warehouse.conftest import FakeClock

RECORDED = Path(__file__).parent / "recorded" / "bigquery"
SENTINEL = "UPSTREAM-SENTINEL-bq-4d1e"
PUBLIC_ADDRESS = "93.184.216.34"


def recorded(name: str) -> Tuple[int, Any]:
    """``(status, body)`` of a recorded response."""
    data = json.loads((RECORDED / f"{name}.json").read_text(encoding="utf-8"))
    return int(data["status"]), data["body"]


@dataclass
class SeenRequest:
    method: str
    host: str
    path: str
    query: Dict[str, List[str]]
    headers: Dict[str, str]
    body: bytes
    #: The fake clock's time when the request arrived (None without a clock).
    at: Optional[float] = None

    def json(self) -> Any:
        return json.loads(self.body)

    def form(self) -> Dict[str, List[str]]:
        return parse_qs(self.body.decode("ascii"))


Answer = Tuple[int, Any]
Handler = Callable[[SeenRequest], Answer]


def _encode(status: int, body: Any) -> bytes:
    payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    head = [
        f"HTTP/1.1 {status} X",
        "Content-Type: application/json; charset=UTF-8",
        f"Content-Length: {len(payload)}",
        # One request per connection, so no answer is read from a reused one.
        "Connection: close",
    ]
    return ("\r\n".join(head) + "\r\n\r\n").encode("ascii") + payload


def _parse(raw: bytes) -> SeenRequest:
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    method, target, _ = lines[0].split(" ", 2)
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    parts = urlsplit(target)
    return SeenRequest(
        method=method,
        host=headers.get("host", ""),
        path=parts.path,
        query=parse_qs(parts.query),
        headers=headers,
        body=body,
    )


class _Stream(httpcore.NetworkStream):
    def __init__(self, fake: "GoogleFake") -> None:
        self._fake = fake
        self._written = b""
        self._answer: Optional[bytes] = None

    def _complete(self) -> bool:
        head, sep, body = self._written.partition(b"\r\n\r\n")
        if not sep:
            return False
        for line in head.split(b"\r\n")[1:]:
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"content-length":
                return len(body) >= int(value.strip())
        return True

    def write(self, buffer: bytes, timeout: Optional[float] = None) -> None:
        self._written += buffer

    def read(self, max_bytes: int, timeout: Optional[float] = None) -> bytes:
        if self._answer is None:
            assert self._complete(), "the client read before it finished writing"
            request = _parse(self._written)
            self._fake.requests.append(request)
            if self._fake.clock is not None:
                request.at = self._fake.clock()
                self._fake.clock.advance(self._fake.seconds_per_request)
            status, body = self._fake.handler(request)
            self._answer = _encode(status, body)
        data, self._answer = self._answer[:max_bytes], self._answer[max_bytes:]
        return data

    def close(self) -> None:
        pass

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self._fake.tls_hostnames.append(server_hostname)
        return self

    def get_extra_info(self, info: str) -> Any:
        return None


@dataclass
class GoogleFake(httpcore.NetworkBackend):
    """Answers every request from ``handler``; records what was asked."""

    handler: Handler
    clock: Optional[FakeClock] = None
    #: Fake seconds each request takes (advances ``clock``).
    seconds_per_request: float = 0.0
    requests: List[SeenRequest] = field(default_factory=list)
    connects: List[Tuple[str, int]] = field(default_factory=list)
    tls_hostnames: List[Optional[str]] = field(default_factory=list)

    def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        self.connects.append((host, port))
        return _Stream(self)

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("no unix sockets")

    def sleep(self, seconds: float) -> None:
        pass


def public_resolver(host: str, port: int):
    return [(PUBLIC_ADDRESS, port)]


def client_factory(fake: GoogleFake) -> Callable[[Deadline], OutboundClient]:
    """Build the connector's real client over the fake network."""

    def make(deadline: Deadline) -> OutboundClient:
        return OutboundClient(
            deadline,
            warehouse="bigquery",
            transport=GuardedTransport(
                deadline, resolver=public_resolver, network_backend=fake
            ),
        )

    return make


class Script:
    """A handler that answers by (method, path suffix) from recorded files.

    ``routes`` maps a key to a list of recorded names (or ``(status, body)``
    pairs), answered in order; the last one repeats.
    """

    def __init__(self, routes: Dict[str, List[Any]]) -> None:
        self._routes = {key: list(value) for key, value in routes.items()}

    @staticmethod
    def key(request: SeenRequest) -> str:
        if request.host == "oauth2.googleapis.com":
            return "token"
        path = request.path
        if request.method == "POST" and path.endswith("/cancel"):
            return "cancel"
        if request.method == "POST" and path.endswith("/jobs"):
            return (
                "dry_run" if request.json()["configuration"].get("dryRun") else "insert"
            )
        if request.method == "GET" and "/queries/" in path:
            return "results"
        if request.method == "GET" and "/jobs/" in path:
            return "job"
        if request.method == "GET" and "/tables/" in path:
            return "table"
        return "other"

    def __call__(self, request: SeenRequest) -> Answer:
        answers = self._routes.get(self.key(request))
        if not answers:
            return 599, {"error": "no scripted answer"}
        answer = answers[0] if len(answers) == 1 else answers.pop(0)
        if isinstance(answer, str):
            status, body = recorded(answer)
        else:
            status, body = answer
        if (
            isinstance(body, dict)
            and "jobReference" in body
            and request.method == "GET"
        ):
            # Answer with the job id the client asked about, as BigQuery does.
            body = json.loads(json.dumps(body))
            body["jobReference"]["jobId"] = request.path.rsplit("/", 1)[-1]
        if (
            self.key(request) == "insert"
            and isinstance(body, dict)
            and "jobReference" in body
        ):
            body = json.loads(json.dumps(body))
            body["jobReference"]["jobId"] = request.json()["jobReference"]["jobId"]
        return status, body
