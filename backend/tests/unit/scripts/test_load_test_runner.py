"""The load-test runner fails when it measured nothing.

``backend/tests/performance/run_load_tests.py`` is what the weekly Performance
Tests workflow runs. Run 37279469245 (2026-10-05) spawned 50 users for 60 s,
recorded 0 requests, printed "No stats parsed from CSV. Nothing to validate."
and exited 0: a green check that had measured nothing. Two paths led there,
and each is a case below:

* **no stats.** All 36 request sites in the locustfiles pass
  ``catch_response=True`` without a ``with`` block. Locust records such a
  request only when its context manager exits, so the requests were sent and
  never counted, and the stats CSV held nothing but its ``Aggregated`` row.
* **no matched endpoint.** Requests recorded under names that match no
  ``PERFORMANCE_TARGETS`` entry produce no validation results, and
  ``all([])`` is True.

The third case is the control: a run that records a matched endpoint still
exits 0, so a runner that always exits 1 cannot pass this file.

Each case runs the runner the way the workflow does -- by path, in a
subprocess, which starts Locust in a subprocess of its own -- for a few seconds
against a stub HTTP server started here. Locust is never imported into this
process: importing it monkey-patches the pytest process with gevent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER = REPO_ROOT / "backend" / "tests" / "performance" / "run_load_tests.py"

# Locust records a `catch_response=True` request when the `with` block exits.
# Without the block it is sent, answered and never counted -- the pattern of
# every request site in backend/tests/performance/locustfiles.
UNRECORDED = """
    from locust import HttpUser, constant, task


    class Unrecorded(HttpUser):
        wait_time = constant(0.01)

        @task
        def list_experiments(self):
            self.client.get("/api/v1/experiments", catch_response=True)
"""

# Recorded, but under a name that no PERFORMANCE_TARGETS entry matches.
UNMATCHED = """
    from locust import HttpUser, constant, task


    class Unmatched(HttpUser):
        wait_time = constant(0.01)

        @task
        def not_a_target(self):
            with self.client.get("/stub/not-a-target", catch_response=True):
                pass
"""

# Recorded, and matched: `/api/v1/experiments` is a target, and the loosest one
# a recorded name can reach (p50 150 ms, p95 400 ms, p99 1000 ms, 100 rps).
MEASURED = """
    from locust import HttpUser, constant, task


    class Measured(HttpUser):
        wait_time = constant(0)

        @task
        def list_experiments(self):
            with self.client.get("/api/v1/experiments", catch_response=True):
                pass
"""


class _StubServer(ThreadingHTTPServer):
    daemon_threads = True
    hits = 0

    def handle_error(self, request: object, client_address: object) -> None:
        """A client hanging up mid-request is Locust stopping, not an error."""
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)  # type: ignore[arg-type]


class _Ok(BaseHTTPRequestHandler):
    """Answers every GET and POST with 200 and `{}`, and counts them."""

    protocol_version = "HTTP/1.1"  # keep-alive, so throughput is not connect-bound

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.hits += 1  # type: ignore[attr-defined]

    do_GET = _answer
    do_POST = _answer

    def log_message(self, format: str, *args: object) -> None:
        """Silence the per-request access log."""


@pytest.fixture
def stub() -> Iterator[_StubServer]:
    server = _StubServer(("127.0.0.1", 0), _Ok)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _run(stub: _StubServer, tmp_path: Path, source: str) -> tuple[int, str]:
    """Run the runner by path, as the workflow does; return (exit, output)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    locustfile = tmp_path / "locustfile.py"
    locustfile.write_text(textwrap.dedent(source), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if p
    )
    host, port = stub.server_address[:2]
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--host",
            f"http://{host}:{port}",
            "--users",
            "2",
            "--spawn-rate",
            "2",
            "--duration",
            "3s",
            "--locustfile",
            str(locustfile),
            "--csv-prefix",
            str(tmp_path / "locust"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return result.returncode, result.stdout + result.stderr


@pytest.mark.regression
def test_no_stats_fails(stub: _StubServer, tmp_path: Path) -> None:
    code, output = _run(stub, tmp_path, UNRECORDED)

    # The requests were sent and answered: what is missing is the recording,
    # exactly as in the weekly run, not a server that never answered.
    assert stub.hits > 0, f"the stub was never called, so this proves nothing\n{output}"
    assert "Locust exited with code" not in output, output
    assert code == 1, f"a run that recorded no requests exited {code}\n{output}"
    assert "FAIL: no stats" in output, output


@pytest.mark.regression
def test_no_matched_endpoint_fails(stub: _StubServer, tmp_path: Path) -> None:
    code, output = _run(stub, tmp_path, UNMATCHED)

    assert stub.hits > 0, f"the stub was never called, so this proves nothing\n{output}"
    assert "/stub/not-a-target" in (tmp_path / "locust_stats.csv").read_text(
        encoding="utf-8"
    ), f"the request was not recorded, so this is the no-stats case\n{output}"
    assert code == 1, f"a run that matched no target exited {code}\n{output}"
    assert "FAIL: no matched endpoint" in output, output
    # With no results the report would read "All SLA targets met".
    assert "All SLA targets met" not in output, output


def test_a_measured_run_passes(stub: _StubServer, tmp_path: Path) -> None:
    # The runner's exit here also depends on the target's latency and rate,
    # i.e. on wall-clock time, so the best of three runs counts. On a laptop
    # one run recorded about 8,000 requests in the 3 s (the target needs 300)
    # at 1-2 ms p99 (the target allows 1,000 ms), so a retry should be rare.
    for attempt in range(1, 4):
        code, output = _run(stub, tmp_path / f"attempt-{attempt}", MEASURED)
        if code == 0:
            break

    assert code == 0, f"a run that measured a matched endpoint exited {code}\n{output}"
    assert "[PASS] /api/v1/experiments" in output, output
    assert "All SLA targets met. Exiting 0." in output, output
