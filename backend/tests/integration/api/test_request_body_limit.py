"""Every request body is held to one size limit, answered 413.

``MAX_REQUEST_BODY_SIZE`` in ``backend/app/main.py`` is 5 MiB. A request that
declares a longer ``Content-Length`` is answered 413 before its body is read;
a body sent without one (chunked) is read up to the limit and then answered
413. The value admits the largest documented request: 10,000 segment member
IDs of 255 characters, 2,590,009 bytes as JSON.

Most tests drive the real app through httpx's ``ASGITransport``, which hands
the app one chunk of the body per ``receive()``, only when the app asks for it.
That is what lets a test count how much of a body was read. The last gate
starts uvicorn itself (h11, as the image runs it), because only a real server
can show the answer arriving while the body has not been sent.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

import httpx
import pytest
from fastapi import params
from fastapi.routing import APIRoute

from backend.app.main import MAX_REQUEST_BODY_SIZE, app
from backend.app.models.segment import Segment

pytestmark = [pytest.mark.integration, pytest.mark.regression]

LIMIT = 5 * 1024 * 1024
CHUNK = 64 * 1024
DETAIL = {"detail": f"Request body larger than {LIMIT} bytes"}
NIL = "00000000-0000-0000-0000-000000000000"
JSON = {"content-type": "application/json"}
FORM = {"content-type": "application/x-www-form-urlencoded"}
TRACK = "/api/v1/tracking/track"
ORIGIN = "http://localhost:3100"  # a development default of CORS_ORIGINS
BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
REPO = pathlib.Path(__file__).resolve().parents[4]

_CHUNK_BYTES = b"x" * CHUNK
#: One form field per chunk. Starlette's own form parser refuses a field over
#: 1 MiB (400) before the limit is reached, so a form body over the limit is
#: made of fields under it.
_FORM_CHUNK_BYTES = b"f=" + b"x" * (CHUNK - 3) + b"&"


class _Offer:
    """A body of ``size`` bytes, handed over in 64 KiB chunks as they are asked for.

    ``pulled`` is how many chunks the app took.
    """

    def __init__(self, size: int, form: bool = False) -> None:
        self.size = size
        self.full = _FORM_CHUNK_BYTES if form else _CHUNK_BYTES
        self.pulled = 0

    async def chunks(self):
        left = self.size
        while left > 0:
            chunk = self.full if left >= CHUNK else b"x" * left
            left -= len(chunk)
            self.pulled += 1
            yield chunk


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _route_contexts():
    """Every HTTP route the app serves, flattened.

    FastAPI >= 0.141 keeps each ``include_router`` as one lazy entry in
    ``app.routes``; its ``effective_route_contexts`` carry the prefixed routes.
    """
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            if isinstance(route, APIRoute):
                yield route
            continue
        yield from contexts() if callable(contexts) else contexts


def _body_routes():
    """``(method, path, url, headers, reads_a_body_field)`` for each route and
    method that can carry a body, read from ``app.routes`` (never a typed list)."""
    seen = set()
    for ctx in _route_contexts():
        for method in sorted(getattr(ctx, "methods", None) or ()):
            if method not in BODY_METHODS or (method, ctx.path) in seen:
                continue
            seen.add((method, ctx.path))
            field = getattr(ctx, "body_field", None)
            form = field is not None and isinstance(field.field_info, params.Form)
            url = re.sub(r"\{[^}]*\}", NIL, ctx.path)
            yield method, ctx.path, url, FORM if form else JSON, field is not None


#: Routes with a body the listing must reach, so that a listing gone empty or
#: partial cannot pass. The floors in ``_assert_listed`` sit well below what the
#: core build lists, so they catch only a listing that finds next to nothing.
EXPECTED_WITH_BODY = {
    ("POST", "/api/v1/tracking/track"),
    ("POST", "/api/v1/tracking/batch"),
    ("POST", "/api/v1/tracking/errors/batch"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/token"),
    ("POST", "/api/v1/segments/{segment_id}/members"),
    ("PUT", "/api/v1/experiments/{experiment_id}"),
}
EXPECTED = EXPECTED_WITH_BODY | {("DELETE", "/api/v1/experiments/{experiment_id}")}


def _assert_listed(routes, expected, floor):
    listed = {(method, path) for method, path, *_ in routes}
    assert expected <= listed, sorted(expected - listed)
    assert len(routes) >= floor, len(routes)


def test_the_limit_is_5_mib():
    """Three pages under docs/ state this value (search for 5,242,880); change
    them with it."""
    assert MAX_REQUEST_BODY_SIZE == LIMIT == 5_242_880


async def test_every_route_answers_413_to_a_declared_length_over_the_limit():
    routes = list(_body_routes())
    _assert_listed(routes, EXPECTED, floor=50)

    body = b"x" * (LIMIT + 1)
    wrong = []
    async with _client() as client:
        for method, path, url, headers, _ in routes:
            response = await client.request(method, url, content=body, headers=headers)
            if (
                response.status_code != 413
                or response.headers.get("connection") != "close"
            ):
                wrong.append((method, path, response.status_code))
    assert not wrong, f"{len(wrong)} of {len(routes)} not refused: {wrong}"


async def test_every_body_route_answers_413_to_a_chunked_body_over_the_limit():
    routes = [r for r in _body_routes() if r[4]]
    _assert_listed(routes, EXPECTED_WITH_BODY, floor=40)

    wrong = []
    async with _client() as client:
        for method, path, url, headers, _ in routes:
            offer = _Offer(LIMIT + 1, form=headers is FORM)
            response = await client.request(
                method, url, content=offer.chunks(), headers=headers
            )
            if (
                response.status_code != 413
                or response.headers.get("connection") != "close"
            ):
                wrong.append((method, path, response.status_code))
    assert not wrong, f"{len(wrong)} of {len(routes)} not refused: {wrong}"


@pytest.mark.parametrize(
    "path", ["/api/v1/tracking/track", "/api/v1/auth/login"], ids=["track", "login"]
)
async def test_a_chunked_body_is_read_no_further_than_the_limit(path):
    """200 MiB offered; the app takes the limit's worth of chunks and stops."""
    offer = _Offer(200 * 1024 * 1024)
    async with _client() as client:
        response = await client.post(path, content=offer.chunks(), headers=JSON)
    assert LIMIT // CHUNK <= offer.pulled <= LIMIT // CHUNK + 2, (
        f"{offer.pulled} chunks of {CHUNK} bytes read; status {response.status_code}"
    )
    assert response.status_code == 413, response.text[:300]


async def test_a_body_of_exactly_the_limit_is_read_and_parsed():
    """At the limit, declared or chunked, the route reads the whole body: here
    it is not JSON, so the answer is the route's own 422, not a 413."""
    offer = _Offer(LIMIT)
    async with _client() as client:
        declared = await client.post(TRACK, content=b"x" * LIMIT, headers=JSON)
        chunked = await client.post(TRACK, content=offer.chunks(), headers=JSON)
    for response in (declared, chunked):
        assert response.status_code == 422, response.text[:300]
        assert response.json()["detail"][0]["type"] == "json_invalid"
    assert offer.pulled == LIMIT // CHUNK


@pytest.mark.requires_db
def test_the_largest_documented_segment_request_is_accepted(admin_client, db_session):
    """10,000 IDs of 255 characters (docs/guides/segments.md) reach the route."""
    created = admin_client.post(
        "/api/v1/segments",
        json={"name": f"Body limit {uuid.uuid4().hex[:8]}", "kind": "id_list"},
    )
    assert created.status_code == 201, created.text
    segment_id = created.json()["id"]
    try:
        ids = [f"{i:05d}" + "x" * 250 for i in range(10_000)]
        body = json.dumps({"add": ids}).encode()
        assert len(body) == 2_590_009
        response = admin_client.post(
            f"/api/v1/segments/{segment_id}/members", content=body, headers=JSON
        )
        assert response.status_code == 200, response.text[:300]
        assert response.json() == {
            "added": 10_000,
            "already_members": 0,
            "member_count": 10_000,
        }
    finally:
        db_session.rollback()
        db_session.query(Segment).filter(Segment.id == uuid.UUID(segment_id)).delete(
            synchronize_session=False
        )
        db_session.commit()


@pytest.mark.parametrize(
    "value", ["abc", "-1", "1" * 5000], ids=["letters", "negative", "5000-digits"]
)
async def test_an_unparsable_content_length_goes_on_to_the_counted_check(value):
    """Not a 500: the request is served, and its body is still counted."""
    headers = {**JSON, "content-length": value}
    async with _client() as client:
        small = await client.post(TRACK, content=b"{}", headers=headers)
        large = await client.post(
            TRACK, content=_Offer(LIMIT + 1).chunks(), headers=headers
        )
    assert small.status_code == 401, small.text[:300]  # the route ran: no API key
    assert large.status_code == 413, large.text[:300]


async def test_the_413_carries_the_headers_of_every_other_response():
    """Registered inside CORS, the request id and the response headers layer."""
    headers = {**JSON, "origin": ORIGIN, "x-request-id": "body-limit-probe"}
    async with _client() as client:
        declared = await client.post(TRACK, content=b"x" * (LIMIT + 1), headers=headers)
        chunked = await client.post(
            TRACK, content=_Offer(LIMIT + 1).chunks(), headers=headers
        )
    for response in (declared, chunked):
        assert response.status_code == 413
        assert response.json() == DETAIL
        assert response.headers.get("access-control-allow-origin") == ORIGIN
        assert response.headers.get("x-request-id") == "body-limit-probe"
        assert response.headers.get("x-content-type-options") == "nosniff"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_real_server_answers_413_before_the_body_is_sent(tmp_path):
    """uvicorn with h11, as the image runs it: headers declaring 200 MiB and no
    body. The 413 arrives and the server closes the connection; without the
    limit the server waits for a body that never comes."""
    port = _free_port()
    log = (tmp_path / "uvicorn.log").open("w")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--http",
            "h11",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO,
        env=dict(os.environ),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health/live", timeout=1
                )
                break
            except OSError:
                if server.poll() is not None or time.monotonic() > deadline:
                    pytest.fail(
                        "uvicorn did not start:\n"
                        + (tmp_path / "uvicorn.log").read_text()[-3000:]
                    )
                time.sleep(0.3)

        received = b""
        with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
            sock.sendall(
                b"POST /api/v1/tracking/track HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: 209715200\r\n"
                b"\r\n"
            )
            try:
                while data := sock.recv(65536):
                    received += data
            except TimeoutError:
                pytest.fail(
                    f"no answer and no close within 30 s; got {received[:200]!r}"
                )
    finally:
        server.terminate()
        server.wait(timeout=20)
        log.close()

    assert received.startswith(b"HTTP/1.1 413 "), received[:300]
    assert json.loads(received.split(b"\r\n\r\n", 1)[1]) == DETAIL
