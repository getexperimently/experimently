"""A recorded-response Snowflake for the Snowflake connector's tests.

The connector's real client (:class:`~modules.backend.app.warehouse.egress.
OutboundClient` over :class:`~modules.backend.app.warehouse.egress.
GuardedTransport`) is used unchanged: the destination check, the address
check, the deadline and the body limit all run.  Only the network is fake --
the network backend from :mod:`.google_fake`, which reads the HTTP request the
client wrote and answers it from a handler, here with a recorded response from
``recorded/snowflake/``.  Nothing leaves the machine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from modules.backend.app.warehouse.deadlines import Deadline
from modules.backend.app.warehouse.egress import GuardedTransport, OutboundClient
from modules.backend.tests.unit.warehouse.google_fake import (
    PUBLIC_ADDRESS,
    GoogleFake,
    SeenRequest,
)

#: The network fake is not specific to Google; it answers whatever it is sent.
NetworkFake = GoogleFake

RECORDED = Path(__file__).parent / "recorded" / "snowflake"
SENTINEL = "UPSTREAM-SENTINEL-sf-7a2c"
#: The statement handle every recorded answer carries.
HANDLE = "019c06a4-0000-df4f-0000-00100006589e"

Answer = Tuple[int, Any]


def recorded(name: str) -> Answer:
    """``(status, body)`` of a recorded response."""
    data = json.loads((RECORDED / f"{name}.json").read_text(encoding="utf-8"))
    return int(data["status"]), data["body"]


def public_resolver(host: str, port: int):
    return [(PUBLIC_ADDRESS, port)]


def client_factory(fake: GoogleFake) -> Callable[[Deadline], OutboundClient]:
    """Build the connector's real client over the fake network."""

    def make(deadline: Deadline) -> OutboundClient:
        return OutboundClient(
            deadline,
            warehouse="snowflake",
            transport=GuardedTransport(
                deadline, resolver=public_resolver, network_backend=fake
            ),
        )

    return make


class Script:
    """A handler that answers by kind of request from recorded files.

    ``routes`` maps ``submit`` (POST statements), ``status`` (GET a
    statement), ``partition`` (GET with ``?partition=``) and ``cancel`` to a
    list of recorded names or ``(status, body)`` pairs, answered in order;
    the last one repeats.
    """

    def __init__(self, routes: Dict[str, List[Any]]) -> None:
        self._routes = {key: list(value) for key, value in routes.items()}

    @staticmethod
    def key(request: SeenRequest) -> str:
        path = request.path
        if request.method == "POST" and path == "/api/v2/statements":
            return "submit"
        if request.method == "POST" and path.endswith("/cancel"):
            return "cancel"
        if request.method == "GET" and path.startswith("/api/v2/statements/"):
            return "partition" if "partition" in request.query else "status"
        return "other"

    def __call__(self, request: SeenRequest) -> Answer:
        answers = self._routes.get(self.key(request))
        if not answers:
            return 599, {"message": "no scripted answer"}
        answer = answers[0] if len(answers) == 1 else answers.pop(0)
        if isinstance(answer, str):
            return recorded(answer)
        return answer
