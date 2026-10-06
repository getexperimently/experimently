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

Those cases run the runner the way the workflow does -- in a subprocess, which
starts Locust in a subprocess of its own -- for a few seconds against a stub
HTTP server started here. Locust is never imported into this process:
importing it monkey-patches the pytest process with gevent.

The rest decide a finished run from a stats CSV written here (``_judge``), so
nothing in them depends on how fast anything ran:

* **coverage.** Every target a locustfile declares in ``TARGETS`` must have
  been recorded, and a locustfile that declares none fails. One matched
  endpoint used to be enough, so a request site that recorded nothing left
  the rest of the run green.
* **exact matching.** A recorded endpoint matches a target by method and name.
  The old two-way substring match checked ``GET /api/v1/experiments`` against
  create_experiment (POST), and matched a request renamed to
  ``/api/v1/tracking/track-renamed`` to ``track`` (it contains the target).
* **--sla.** ``enforce`` is the default. The weekly workflow passes
  ``report``: latency and throughput are printed, not gated, because one
  run's timings on a shared runner are not a stable statistic (budgets are
  Phase 2, QA L2). The same over-budget CSV exits 1 under one and 0 under the
  other.
* **failed requests.** Locust exits 1 when any request was marked a failure;
  that exit is what fails a run with a failed request, and the runner names
  the endpoint.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import textwrap
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
PERFORMANCE = REPO_ROOT / "backend" / "tests" / "performance"
RUNNER = PERFORMANCE / "run_load_tests.py"
BASELINE = PERFORMANCE / "locustfiles" / "api_load_test.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "performance-tests.yml"

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

# Recorded, and matched to the one target the control's driver installs.
MEASURED = """
    from locust import HttpUser, constant, task

    TARGETS = ("stub",)


    class Measured(HttpUser):
        wait_time = constant(0)

        @task
        def list_experiments(self):
            with self.client.get("/api/v1/experiments", catch_response=True):
                pass
"""

# A request the locustfile marks a failure. Locust exits 1 for it, and that
# exit is what fails the run: the runner returns before reading the stats.
FAILING = """
    from locust import HttpUser, constant, task

    TARGETS = ("health",)


    class Failing(HttpUser):
        wait_time = constant(0.01)

        @task
        def health(self):
            with self.client.get("/fail", name="/health", catch_response=True) as r:
                if r.status_code == 200:
                    r.success()
                else:
                    r.failure(f"HTTP {r.status_code}, expected 200")
"""

# The control runs the runner's own main() with PERFORMANCE_TARGETS replaced
# by one target nothing can miss on time: 60 s at every percentile and 0.1
# requests a second. So its exit depends on the runner's logic, not on how
# fast the machine is.
CONTROL_DRIVER = """
import sys

sys.path.insert(0, {performance!r})
import run_load_tests as r
from backend.tests.performance.specs.performance_targets import PerformanceTarget

r.PERFORMANCE_TARGETS = {{
    "stub": PerformanceTarget(
        endpoint="/api/v1/experiments",
        method="GET",
        p50_ms=60000,
        p95_ms=60000,
        p99_ms=60000,
        min_rps=0.1,
        description="the stub endpoint",
    )
}}
sys.exit(r.main(sys.argv[1:]))
"""


class _StubServer(ThreadingHTTPServer):
    daemon_threads = True
    hits = 0

    def handle_error(self, request: object, client_address: object) -> None:
        """A client hanging up mid-request is Locust stopping, not an error."""
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)  # type: ignore[arg-type]


class _Ok(BaseHTTPRequestHandler):
    """Answers every GET and POST with `{}` and counts them: 503 under /fail, else 200."""

    protocol_version = "HTTP/1.1"  # keep-alive, so throughput is not connect-bound
    # TCP_NODELAY. The headers and the body go out as two writes; with Nagle on,
    # Linux holds the body until the client's delayed ACK, about 40 ms, so in CI
    # every request took 42 ms and two users made 32 requests per second
    # against the target's 100. macOS does not show it.
    disable_nagle_algorithm = True

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = b"{}"
        self.send_response(503 if self.path.startswith("/fail") else 200)
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


def _run(
    stub: _StubServer, tmp_path: Path, source: str, driver: str | None = None
) -> tuple[int, str]:
    """Run the runner, as the workflow does; return (exit, output).

    By path, or through *driver* (``python -c``) when one is given.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    locustfile = tmp_path / "locustfile.py"
    locustfile.write_text(textwrap.dedent(source), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if p
    )
    host, port = stub.server_address[:2]
    entry = ["-c", driver] if driver is not None else [str(RUNNER)]
    result = subprocess.run(
        [
            sys.executable,
            *entry,
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
    driver = CONTROL_DRIVER.format(performance=str(PERFORMANCE))
    code, output = _run(stub, tmp_path, MEASURED, driver=driver)

    assert stub.hits > 0, f"the stub was never called, so this proves nothing\n{output}"
    assert code == 0, f"a run that measured a matched endpoint exited {code}\n{output}"
    assert "[PASS] /api/v1/experiments" in output, output
    assert "All SLA targets met. Exiting 0." in output, output


@pytest.mark.regression
def test_a_failed_request_fails_the_run(stub: _StubServer, tmp_path: Path) -> None:
    code, output = _run(stub, tmp_path, FAILING)

    assert stub.hits > 0, f"the stub was never called, so this proves nothing\n{output}"
    assert code == 1, f"a run with failed requests exited {code}\n{output}"
    assert "Locust exited with code 1" in output, output
    assert "FAIL: GET /health:" in output, output


# ---------------------------------------------------------------------------
# Deciding a finished run from its stats CSV (no Locust, no timing)
# ---------------------------------------------------------------------------

_HEADER = "Type,Name,Request Count,Failure Count,50%,95%,99%\n"

# The baseline's five targets, every one far over its latency and throughput
# budget: 5 s at every percentile, 10 requests in 60 s.
_OVER_BUDGET = {
    ("POST", "/api/v1/tracking/track"),
    ("POST", "/api/v1/tracking/assign"),
    ("GET", "/api/v1/experiments"),
    ("GET", "/api/v1/feature-flags/evaluate/{key}"),
    ("GET", "/health"),
}


@pytest.fixture(scope="module")
def runner() -> ModuleType:
    """Import `run_load_tests.py` by path (it does not import Locust)."""
    spec = importlib.util.spec_from_file_location("_run_load_tests_unit", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _csv(tmp_path: Path, rows: set[tuple[str, str]] | list[tuple[str, str]]) -> str:
    path = tmp_path / "locust_stats.csv"
    lines = [f"{method},{name},10,0,5000,5000,5000\n" for method, name in sorted(rows)]
    path.write_text(_HEADER + "".join(lines) + "Aggregated,,50,0,5000,5000,5000\n")
    return str(path)


def _locustfile(tmp_path: Path, declaration: str) -> str:
    path = tmp_path / "declared.py"
    path.write_text(declaration + "\n", encoding="utf-8")
    return str(path)


def _judge(runner: ModuleType, capsys: Any, *args: str) -> tuple[int, str]:
    code = runner._judge(*args)
    return code, capsys.readouterr().out


def test_the_default_is_enforce(runner: ModuleType) -> None:
    assert runner._parse_args([]).sla == "enforce"


def test_report_is_the_weekly_workflows_mode_on_its_run_line() -> None:
    """Literally on the run line, not a dispatch input or an environment variable."""
    if not WORKFLOW.is_file():
        pytest.skip("this tree has no .github/workflows")
    import yaml

    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["load-test"][
        "steps"
    ]
    runs = [s["run"] for s in steps if "run_load_tests.py" in s.get("run", "")]
    assert len(runs) == 1, runs
    assert "--sla report" in runs[0], runs[0]
    assert "${{" not in runs[0].split("--sla", 1)[1].split()[0], runs[0]


def test_one_over_budget_csv_fails_under_enforce_and_passes_under_report(
    runner: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    csv = _csv(tmp_path, _OVER_BUDGET)

    code, output = _judge(runner, capsys, csv, str(BASELINE), "60s", "enforce")
    assert code == 1, output
    assert "SLA violations for:" in output, output

    code, output = _judge(runner, capsys, csv, str(BASELINE), "60s", "report")
    assert code == 0, output
    assert "REPORTED, NOT GATED" in output, output
    assert output.count("reported, not gated: ") == 5, output
    assert "All SLA targets met" not in output, output


def test_the_baseline_declares_exactly_its_five_targets(runner: ModuleType) -> None:
    declared = runner._declared_targets(str(BASELINE))
    pairs = {
        (runner.PERFORMANCE_TARGETS[k].method, runner.PERFORMANCE_TARGETS[k].endpoint)
        for k in declared
    }
    assert len(declared) == 5, declared
    assert pairs == _OVER_BUDGET


@pytest.mark.parametrize(
    "profile", ["baseline", "spike", "endurance", "crud", "db-stress", "breakpoint"]
)
def test_every_profile_declares_known_targets(runner: ModuleType, profile: str) -> None:
    declared = runner._declared_targets(runner._PROFILE_LOCUSTFILES[profile])
    assert declared, f"{profile} declares no TARGETS: every run of it would fail"
    unknown = [k for k in declared if k not in runner.PERFORMANCE_TARGETS]
    assert not unknown, unknown


@pytest.mark.regression
@pytest.mark.parametrize("missing", sorted(_OVER_BUDGET))
def test_a_declared_target_that_was_not_recorded_fails(
    runner: ModuleType, tmp_path: Path, capsys: Any, missing: tuple[str, str]
) -> None:
    """The other four were recorded and matched; one missing is enough."""
    csv = _csv(tmp_path, _OVER_BUDGET - {missing})

    code, output = _judge(runner, capsys, csv, str(BASELINE), "60s", "report")
    assert code == 1, output
    assert "FAIL: unmatched target -- " in output, output
    assert f"({missing[0]} {missing[1]})" in output, output


@pytest.mark.regression
@pytest.mark.parametrize(
    "declaration",
    [
        "",
        "TARGETS = ()",
        "TARGETS = []",
        "TARGETS = TUPLE_FROM_ELSEWHERE",
        "TARGETS = ('track', 1)",
    ],
)
def test_a_locustfile_without_a_target_list_fails(
    runner: ModuleType, tmp_path: Path, capsys: Any, declaration: str
) -> None:
    csv = _csv(tmp_path, _OVER_BUDGET)
    locustfile = _locustfile(tmp_path, declaration)

    code, output = _judge(runner, capsys, csv, locustfile, "60s", "report")
    assert code == 1, output
    assert "declares no TARGETS" in output, output


def test_an_unknown_target_name_fails(
    runner: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    csv = _csv(tmp_path, _OVER_BUDGET)
    locustfile = _locustfile(tmp_path, 'TARGETS = ("track", "no_such_target")')

    code, output = _judge(runner, capsys, csv, locustfile, "60s", "report")
    assert code == 1, output
    assert "unknown target(s): no_such_target" in output, output


@pytest.mark.regression
@pytest.mark.parametrize(
    ("method", "name", "expected"),
    [
        ("GET", "/api/v1/experiments", "list_experiments"),
        ("POST", "/api/v1/experiments", "create_experiment"),
        ("PUT", "/api/v1/experiments/{experiment_id}", "update_experiment"),
        ("DELETE", "/api/v1/experiments/{experiment_id}", "delete_experiment"),
        ("GET", "/api/v1/experiments/{experiment_id}", None),
        ("POST", "/api/v1/tracking/track-renamed", None),
        ("POST", "/api/v1/tracking/trac", None),
        ("GET", "/api/v1/tracking/track", None),
        ("POST", "/api/v1/experiments [write]", None),
    ],
)
def test_an_endpoint_matches_a_target_by_method_and_name_exactly(
    runner: ModuleType, method: str, name: str, expected: str | None
) -> None:
    from backend.tests.performance.validators import RequestStats

    stats = RequestStats(
        name=name, method=method, num_requests=1, num_failures=0, response_times=[1.0]
    )
    pairs = runner._map_stats_to_targets([stats])
    keys = [
        k
        for _, target in pairs
        for k, t in runner.PERFORMANCE_TARGETS.items()
        if t is target
    ]
    assert keys == ([expected] if expected else []), (method, name, keys)


def test_every_target_names_one_route_the_api_serves() -> None:
    """A target for a route that does not exist can only ever be unmatched.

    `batch_evaluate_flags` once named POST /api/v1/feature-flags/evaluate-batch,
    which the API has never served. Checked against the committed OpenAPI
    document, whose paths carry the trailing slash on collections.
    """
    import json

    spec = REPO_ROOT / "docs" / "api" / "openapi-v1.full.json"
    if not spec.is_file():
        pytest.skip("this tree has no OpenAPI snapshot")
    from backend.tests.performance.specs.performance_targets import PERFORMANCE_TARGETS

    paths = json.loads(spec.read_text(encoding="utf-8"))["paths"]
    missing = []
    for key, target in PERFORMANCE_TARGETS.items():
        if target.endpoint == "/health":
            continue  # served by the app, outside the /api/v1 document
        path = target.endpoint
        candidates = [path, path + "/"]
        # The locustfiles' templates name parameters by role; the document by field.
        found = any(
            _same_route(c, p) and target.method.lower() in ops
            for c in candidates
            for p, ops in paths.items()
        )
        if not found:
            missing.append(f"{key}: {target.method} {target.endpoint}")
    assert not missing, missing


def _same_route(a: str, b: str) -> bool:
    sa, sb = a.strip("/").split("/"), b.strip("/").split("/")
    return len(sa) == len(sb) and all(
        x == y or (x.startswith("{") and y.startswith("{")) for x, y in zip(sa, sb)
    )


def test_the_locustfiles_use_the_seeds_experiment_and_flag() -> None:
    """common.py's keys are the ones backend/scripts/seed_sdk_contract.py creates.

    Read from the seed's source: importing it sets POSTGRES_* defaults in this
    process's environment.
    """
    from backend.tests.performance.locustfiles import common

    seed = ast.parse(
        (REPO_ROOT / "backend" / "scripts" / "seed_sdk_contract.py").read_text()
    )
    constants = {
        t.id: node.value.value
        for node in seed.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for t in node.targets
        if isinstance(t, ast.Name)
    }
    assert common.EXPERIMENT_KEY == constants["EXPERIMENT_KEY"]
    assert common.FLAG_KEY == constants["FLAG_KEY"]


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.verdict: tuple[str, str] | None = None

    def success(self) -> None:
        self.verdict = ("success", "")

    def failure(self, message: str) -> None:
        self.verdict = ("failure", message)


@pytest.mark.parametrize(
    ("status", "verdict"),
    [
        (200, ("success", "")),
        (201, ("failure", "HTTP 201, expected 200")),
        (401, ("failure", "HTTP 401, expected 200")),
        (0, ("failure", "no response, expected 200")),
    ],
)
def test_expect_decides_every_response(status: int, verdict: tuple[str, str]) -> None:
    from backend.tests.performance.locustfiles.common import expect

    response = _Response(status)
    assert expect(response, 200) is (verdict[0] == "success")
    assert response.verdict == verdict
