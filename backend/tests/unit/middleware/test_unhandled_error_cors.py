"""An unhandled route exception is a 500 a cross-origin dashboard can read (#72).

Before the fix Starlette's outermost ServerErrorMiddleware answered it, outside
CORS: no ``Access-Control-Allow-Origin``, so the browser hid the 500 and the
dashboard reported "Can't reach the API". The obvious fix,
``@app.exception_handler(Exception)``, changes nothing -- Starlette hands that
handler to the same outermost layer -- which is why these tests drive the real
app, not a model of it.
"""

from __future__ import annotations

import os
import pathlib
import re
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send

from backend.app.api import deps
from backend.app.main import app
from backend.app.middleware.unhandled_error_middleware import UnhandledErrorMiddleware

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ORIGIN = "http://localhost:3100"  # a dev default in CORS_ORIGINS
SECRET = "SECRET-DETAIL-7f3a"
REPO = pathlib.Path(__file__).resolve().parents[4]


def _boom():
    raise RuntimeError(SECRET)


@pytest.fixture
def failing_db():
    """Any route that needs the database now raises an unhandled exception."""
    app.dependency_overrides[deps.get_db] = _boom
    try:
        yield
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


def _get(client, origin=ORIGIN):
    return client.get(
        "/api/v1/experiments/", headers={"Origin": origin, "Authorization": "Bearer x"}
    )


def test_an_unhandled_exception_is_a_500_the_browser_can_read(failing_db):
    response = _get(TestClient(app, raise_server_exceptions=False))
    assert response.status_code == 500, response.text
    assert response.headers.get("access-control-allow-origin") == ORIGIN, (
        "the 500 has no Access-Control-Allow-Origin, so a cross-origin dashboard "
        f"reports the API as unreachable; headers: {dict(response.headers)}"
    )
    assert response.headers.get("access-control-allow-credentials") == "true"
    assert response.headers.get("x-request-id"), (
        "an operator needs the id to find the log line"
    )
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_the_500_says_nothing_about_the_exception(failing_db):
    response = _get(TestClient(app, raise_server_exceptions=False))
    assert response.text == "Internal Server Error"
    assert response.headers["content-type"].startswith("text/plain")
    assert SECRET not in response.text and "Traceback" not in response.text


def test_a_foreign_origin_gets_no_allow_origin(failing_db):
    response = _get(
        TestClient(app, raise_server_exceptions=False), origin="https://evil.example"
    )
    assert response.status_code == 500
    assert "access-control-allow-origin" not in response.headers, dict(response.headers)


def test_the_exception_still_reaches_the_server(failing_db):
    """Re-raised after the 500 is sent: the server logs it, and tests still see it."""
    with pytest.raises(RuntimeError, match=SECRET):
        _get(TestClient(app, raise_server_exceptions=True))


def test_the_error_layer_is_innermost_and_cors_outermost():
    layers = [m.cls for m in app.user_middleware]
    assert layers[0] is CORSMiddleware, layers
    assert layers[-1] is UnhandledErrorMiddleware, (
        "registered after another middleware, the error layer is no longer innermost "
        f"and that layer's headers are missing from the 500: {layers}"
    )


@pytest.mark.asyncio
async def test_a_response_already_started_is_not_sent_twice():
    """Once the route has begun its response, the layer only re-raises."""

    async def streaming_then_boom(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("after start")

    sent = []

    async def record(message):
        sent.append(message["type"])

    async def receive():
        return {"type": "http.request", "body": b""}

    layer = UnhandledErrorMiddleware(streaming_then_boom)
    with pytest.raises(RuntimeError, match="after start"):
        await layer(
            {"type": "http", "method": "GET", "path": "/", "headers": []},
            receive,
            record,
        )
    assert sent == ["http.response.start"]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_real_server_logs_the_traceback_once_with_the_request_id(tmp_path):
    """Under uvicorn, as deployed: the 500 is readable AND the traceback is logged.

    A catcher that returned the 500 without re-raising would pass every header
    test above and silently drop this log line.
    """
    (tmp_path / "boom_app.py").write_text(
        textwrap.dedent(
            f"""
            from backend.app.main import app

            @app.get("/api/v1/_boom", include_in_schema=False)
            def boom():
                raise RuntimeError({SECRET!r})
            """
        )
    )
    port = _free_port()
    env = dict(os.environ, PYTHONPATH=f"{tmp_path}{os.pathsep}{REPO}")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "boom_app:app",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
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
                    raise AssertionError(
                        f"uvicorn did not start:\n{server.stdout.read() if server.poll() is not None else ''}"
                    ) from None
                time.sleep(0.3)
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/_boom",
            headers={"Origin": ORIGIN, "X-Request-ID": "doc72-probe-id"},
        )
        try:
            urllib.request.urlopen(request, timeout=10)
            raise AssertionError("the route was meant to fail")
        except urllib.error.HTTPError as error:
            status, headers = error.code, dict(error.headers)
    finally:
        server.terminate()
        output, _ = server.communicate(timeout=20)

    assert status == 500
    assert headers.get("access-control-allow-origin") == ORIGIN, headers
    assert headers.get("x-request-id") == "doc72-probe-id", headers
    # One log record, however the console renderer draws it: the dev renderer
    # also prints the logging call's locals (msg = 'Exception in ASGI ...') inside
    # the traceback, so count records by their "[error] <message>" start, and read
    # the record's context from the line after it (the message ends in a newline).
    text = re.sub(r"\x1b\[[0-9;]*m", "", output).splitlines()
    starts = [
        n
        for n, line in enumerate(text)
        if re.search(r"\[\s*error\s*\]\s+Exception in ASGI application", line)
    ]
    assert len(starts) == 1, (
        f"expected the traceback logged exactly once, got {len(starts)}:\n{output[-3000:]}"
    )
    record = "\n".join(text[starts[0] : starts[0] + 2])
    assert "request_id=doc72-probe-id" in record, (
        f"the log record does not carry the request id:\n{record}"
    )
    assert SECRET in output, "the traceback itself is missing from the log"
