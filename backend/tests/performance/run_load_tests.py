#!/usr/bin/env python3
"""
CI load test runner for the experimentation platform.

Orchestrates a complete load test cycle:
1. Optionally starts a local test server (uvicorn)
2. Runs Locust in headless mode against the target host
3. Parses the generated CSV output
4. Checks that Locust recorded a request for every target the locustfile
   declares in its ``TARGETS`` tuple
5. Validates results against PERFORMANCE_TARGETS SLA contracts (``--sla
   enforce``), or prints them beside the targets (``--sla report``)
6. Generates a human-readable report
7. Exits 0 or 1 as set out under "Exit codes" below

Usage:
    # Against an already-running server
    python run_load_tests.py --host http://localhost:8000

    # Start a local server automatically
    python run_load_tests.py --start-server --host http://localhost:8001

    # Full options
    python run_load_tests.py \\
        --users 100 \\
        --spawn-rate 10 \\
        --duration 120s \\
        --host http://localhost:8000 \\
        --csv-prefix /tmp/locust_results \\
        --locustfile path/to/api_load_test.py

Exit codes:
    0 — no request failed, every target the locustfile declares in
        ``TARGETS`` was recorded, and (``--sla enforce``, the default) every
        matched endpoint met its latency and throughput targets
    1 — a request failed (Locust exits 1 on any failure, and the runner names
        the endpoints); nothing was measured (Locust recorded no requests, or
        no recorded endpoint matched a target); a declared target was not
        recorded, or the locustfile declares none; with ``--sla enforce``, a
        target was missed; or test infrastructure error

``--sla report`` (what the weekly workflow passes) prints latency and
throughput beside each target and does not gate on them: they come from one
run on a shared CI runner, which is not a stable statistic to fail on, and
budgets are Phase 2 (QA L2). What it gates is that the run measured what the
locustfile is meant to measure, and that nothing failed.

A recorded endpoint matches a target when its method and its Locust name are
the target's ``method`` and ``endpoint`` exactly. Recorded endpoints with no
target (the login, for one) are listed and not checked.

A run that measured nothing is a failure, not a pass. Run 37279469245 spawned
50 users for 60 s, recorded 0 requests and exited 0 -- every request site in
the locustfiles passed ``catch_response=True`` without a ``with`` block, so
Locust never recorded one. ``all([])`` is True, so an empty match did the same.
"""

import argparse
import ast
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure the repo root is on sys.path so backend.* imports resolve.
#
# parents[3], not parents[4]. This file is at
# <root>/backend/tests/performance/run_load_tests.py, so the parents are
# performance(0) tests(1) backend(2) <root>(3) -- and parents[4] is the
# directory ABOVE the repository.
#
# That off-by-one is why this workflow had never passed once in 29 runs since
# 2026-05-11. `_REPO_ROOT` is the `cwd` for both subprocesses this script
# starts, so locust resolved the workflow's relative `--locustfile
# backend/tests/performance/locustfiles/api_load_test.py` against
# `/home/runner/work` and reported "Could not find" for a file that is tracked
# and present. `_repo_root_is_the_repository` in test_run_load_tests.py pins it.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.tests.performance.specs.performance_targets import (
    PERFORMANCE_TARGETS,
    PerformanceTarget,
)
from backend.tests.performance.validators import (
    RequestStats,
    ValidationResult,
    generate_report,
    parse_locust_csv,
    validate_against_target,
)

# Default paths
_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_LOCUSTFILE = _THIS_DIR / "locustfiles" / "api_load_test.py"
_DEFAULT_CSV_PREFIX = "/tmp/locust_results"

# Locust appends _stats.csv to the prefix to produce the stats file
_CSV_STATS_SUFFIX = "_stats.csv"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


# Convenience mapping from profile name to locustfile
_PROFILE_LOCUSTFILES: dict[str, str] = {
    "baseline": str(_THIS_DIR / "locustfiles" / "api_load_test.py"),
    "spike": str(_THIS_DIR / "locustfiles" / "spike_test.py"),
    "endurance": str(_THIS_DIR / "locustfiles" / "endurance_test.py"),
    "crud": str(_THIS_DIR / "locustfiles" / "crud_load_test.py"),
    "db-stress": str(_THIS_DIR / "locustfiles" / "db_stress_test.py"),
    "breakpoint": str(_THIS_DIR / "locustfiles" / "breakpoint_test.py"),
}


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the load test runner."""
    parser = argparse.ArgumentParser(
        description="CI load test runner — runs Locust and validates SLAs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default="http://localhost:8000",
        help="Target API host URL",
    )
    parser.add_argument(
        "--users",
        type=int,
        default=50,
        help="Number of concurrent Locust users",
    )
    parser.add_argument(
        "--spawn-rate",
        type=int,
        default=10,
        help="Users to spawn per second during ramp-up",
    )
    parser.add_argument(
        "--duration",
        default="60s",
        help="Test duration (e.g. 60s, 2m, 5m)",
    )
    parser.add_argument(
        "--profile",
        choices=list(_PROFILE_LOCUSTFILES.keys()),
        default=None,
        help="Test profile (convenience alias for --locustfile): "
        + ", ".join(_PROFILE_LOCUSTFILES.keys()),
    )
    parser.add_argument(
        "--locustfile",
        default=str(_DEFAULT_LOCUSTFILE),
        help="Path to the Locust test file to run (overridden by --profile if set)",
    )
    parser.add_argument(
        "--csv-prefix",
        default=_DEFAULT_CSV_PREFIX,
        help="Prefix for Locust CSV output files",
    )
    parser.add_argument(
        "--start-server",
        action="store_true",
        default=False,
        help="Start a local uvicorn server before running the test",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=8001,
        help="Port for the local test server (used with --start-server)",
    )
    parser.add_argument(
        "--sla",
        choices=["enforce", "report"],
        default="enforce",
        help="enforce: every matched endpoint must meet its latency and "
        "throughput targets. report: they are printed beside the targets and "
        "not checked (the weekly workflow's mode: one run's timings are not a "
        "stable statistic; budgets are Phase 2, QA L2)",
    )
    args = parser.parse_args(argv)

    # Resolve --profile to a locustfile path (profile takes precedence)
    if args.profile is not None:
        args.locustfile = _PROFILE_LOCUSTFILES[args.profile]

    return args


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------


def _start_server(port: int) -> subprocess.Popen:
    """
    Start a local uvicorn server for the FastAPI application.

    Args:
        port: TCP port to listen on.

    Returns:
        The Popen object for the running server process.
    """
    backend_dir = _REPO_ROOT / "backend"
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "test",
            "TESTING": "true",
            "PYTHONPATH": str(_REPO_ROOT),
        }
    )
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    print(f"[runner] Starting local server on port {port}…")
    proc = subprocess.Popen(cmd, env=env, cwd=str(_REPO_ROOT))
    return proc


def _wait_for_server(host: str, timeout_seconds: int = 30) -> bool:
    """
    Poll the server health endpoint until it responds or the timeout expires.

    Args:
        host: Base URL of the server (e.g. http://localhost:8001)
        timeout_seconds: Maximum seconds to wait for the server to become ready.

    Returns:
        True if the server became ready within the timeout; False otherwise.
    """
    import urllib.error
    import urllib.request

    health_url = f"{host}/health"
    deadline = time.monotonic() + timeout_seconds
    print(f"[runner] Waiting for server at {health_url}…")
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as resp:
                if resp.status == 200:
                    print("[runner] Server is ready.")
                    return True
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            pass
        time.sleep(1)
    print(f"[runner] ERROR: Server did not become ready within {timeout_seconds}s")
    return False


# ---------------------------------------------------------------------------
# Locust execution
# ---------------------------------------------------------------------------


def _run_locust(
    host: str,
    users: int,
    spawn_rate: int,
    duration: str,
    locustfile: str,
    csv_prefix: str,
) -> int:
    """
    Execute Locust in headless mode.

    Args:
        host: Target API host URL.
        users: Number of concurrent virtual users.
        spawn_rate: Users per second to spawn during ramp-up.
        duration: Test duration string (e.g. "60s", "2m").
        locustfile: Path to the Locust test file.
        csv_prefix: Prefix for CSV output files (Locust appends _stats.csv etc.)

    Returns:
        Locust's exit code (0 = success, non-zero = failure or error).
    """
    cmd = [
        sys.executable,
        "-m",
        "locust",
        "--headless",
        "--host",
        host,
        "--users",
        str(users),
        "--spawn-rate",
        str(spawn_rate),
        "--run-time",
        duration,
        "--locustfile",
        locustfile,
        "--csv",
        csv_prefix,
        "--csv-full-history",
        "--only-summary",
    ]
    print(f"[runner] Running Locust: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(_REPO_ROOT))
    return result.returncode


# ---------------------------------------------------------------------------
# SLA validation
# ---------------------------------------------------------------------------


def _map_stats_to_targets(
    stats_list: list[RequestStats],
) -> list[tuple[RequestStats, PerformanceTarget]]:
    """
    Match parsed RequestStats objects to their corresponding PERFORMANCE_TARGETS entries.

    A row matches a target when its method and name are the target's method
    and endpoint, exactly. Locustfiles name templated paths the way the
    targets spell them (``name="/api/v1/feature-flags/evaluate/{key}"``).

    The match was once a substring test in both directions with no method,
    so ``GET /api/v1/experiments`` was checked against create_experiment
    (POST, the first target in the dict), and a request renamed to
    ``/api/v1/tracking/track-renamed`` (or cut to ``/api/v1/tracking/trac``)
    still matched ``track``.

    Args:
        stats_list: Parsed RequestStats from the Locust CSV.

    Returns:
        List of (stats, target) pairs for endpoints that have a defined SLA.
    """
    pairs: list[tuple[RequestStats, PerformanceTarget]] = []
    for stats in stats_list:
        for _key, target in PERFORMANCE_TARGETS.items():
            if (stats.method, stats.name) == (target.method, target.endpoint):
                pairs.append((stats, target))
                break
    return pairs


def _declared_targets(locustfile: str) -> Optional[list[str]]:
    """
    Read the ``TARGETS`` tuple a locustfile declares, without importing it.

    Importing a locustfile imports Locust, which patches this process with
    gevent; the runner only reads the module-level literal.

    Args:
        locustfile: Path to the Locust test file.

    Returns:
        The declared target keys, or None when the file declares no
        ``TARGETS`` as a literal tuple or list of strings.
    """
    tree = ast.parse(Path(locustfile).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        if "TARGETS" not in names or node.value is None:
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            return None
        if isinstance(value, (tuple, list)) and all(isinstance(v, str) for v in value):
            return list(value)
        return None
    return None


def _coverage_failures(locustfile: str, stats_list: list[RequestStats]) -> list[str]:
    """
    The reasons a run did not record every target its locustfile declares.

    Args:
        locustfile: Path to the Locust test file.
        stats_list: Parsed RequestStats from the Locust CSV.

    Returns:
        One line per problem; empty when every declared target was recorded.
    """
    declared = _declared_targets(locustfile)
    if not declared:
        return [
            f"{locustfile} declares no TARGETS, so there is no list of targets "
            "the run must record (add a module-level TARGETS tuple of "
            "PERFORMANCE_TARGETS keys)"
        ]
    unknown = [key for key in declared if key not in PERFORMANCE_TARGETS]
    if unknown:
        return [f"TARGETS names unknown target(s): {', '.join(unknown)}"]
    recorded = {(s.method, s.name) for s in stats_list if s.num_requests > 0}
    problems: list[str] = []
    for key in declared:
        target = PERFORMANCE_TARGETS[key]
        if (target.method, target.endpoint) not in recorded:
            problems.append(
                f"{key} ({target.method} {target.endpoint}): declared in "
                "TARGETS, but Locust recorded no request under that method and name"
            )
    return problems


def _validate_results(
    stats_list: list[RequestStats],
    duration_seconds: float,
) -> list[ValidationResult]:
    """
    Validate all parsed stats against the SLA performance targets.

    Endpoints not covered by a performance target are listed and skipped.

    Args:
        stats_list: Parsed RequestStats from the Locust CSV.
        duration_seconds: Total test duration used for RPS calculation.

    Returns:
        List of ValidationResult objects.
    """
    pairs = _map_stats_to_targets(stats_list)

    if not pairs:
        print("[runner] WARNING: No endpoints matched performance targets.")
        print("[runner] Endpoints in CSV:", [s.name for s in stats_list])
        print("[runner] Defined targets:", list(PERFORMANCE_TARGETS.keys()))

    results: list[ValidationResult] = []
    for stats, target in pairs:
        result = validate_against_target(stats, target, duration_seconds)
        results.append(result)

    return results


def _report_measurements(
    stats_list: list[RequestStats],
    duration_seconds: float,
) -> None:
    """
    Print each matched endpoint's latency and throughput beside its target.

    Used with ``--sla report``: nothing here can fail the run. The numbers
    come from one run on a shared CI runner, which is not a stable statistic
    to fail on; latency and throughput budgets are Phase 2 (QA L2).
    """
    print(
        "[runner] --sla report: latency and throughput are REPORTED, NOT GATED "
        "(one run's timings on a shared runner are not a stable statistic; "
        "budgets are Phase 2, QA L2)."
    )
    for stats, target in _map_stats_to_targets(stats_list):
        print(
            f"[runner] reported, not gated: {target.method} {target.endpoint}: "
            f"{stats.num_requests} requests, "
            f"p50 {stats.p50:.0f} ms (target {target.p50_ms:g}), "
            f"p95 {stats.p95:.0f} ms (target {target.p95_ms:g}), "
            f"p99 {stats.p99:.0f} ms (target {target.p99_ms:g}), "
            f"{stats.rps(duration_seconds):.1f} rps (target {target.min_rps:g})"
        )


def _judge(csv_stats_path: str, locustfile: str, duration: str, sla: str) -> int:
    """
    Decide a run Locust finished with exit 0, from its stats CSV.

    Locust has already failed the run if any request was marked a failure
    (it exits 1, and ``main`` returns before this). What is left to decide:

    * something was recorded (``no stats``);
    * something recorded matches a target (``no matched endpoint``);
    * every target the locustfile declares in ``TARGETS`` was recorded,
      and the locustfile declares a non-empty ``TARGETS`` at all;
    * with ``sla == "enforce"``, every matched endpoint met its target.
      With ``"report"``, latency and throughput are printed, not checked.

    Args:
        csv_stats_path: Locust's ``<prefix>_stats.csv``.
        locustfile: The locustfile the run used (read, never imported).
        duration: The run's duration string, for throughput.
        sla: "enforce" or "report".

    Returns:
        0 or 1, the runner's exit status.
    """
    try:
        stats_list = parse_locust_csv(csv_stats_path)
    except FileNotFoundError:
        print(f"[runner] ERROR: CSV not found at {csv_stats_path}")
        return 1

    if not stats_list:
        print(
            f"[runner] FAIL: no stats -- {csv_stats_path} has no endpoint "
            "rows, so Locust recorded no requests and nothing was measured. "
            "Exiting 1."
        )
        return 1

    pairs = _map_stats_to_targets(stats_list)
    # Before the report: with no results it would read "All SLA targets
    # met", and `all([])` is True.
    if not pairs:
        print("[runner] Endpoints in CSV:", [s.name for s in stats_list])
        print("[runner] Defined targets:", list(PERFORMANCE_TARGETS.keys()))
        print(
            f"[runner] FAIL: no matched endpoint -- none of the "
            f"{len(stats_list)} endpoint(s) Locust recorded matches a "
            "PERFORMANCE_TARGETS entry, so no target was checked. Exiting 1."
        )
        return 1

    matched = {id(stats) for stats, _ in pairs}
    untargeted = [f"{s.method} {s.name}" for s in stats_list if id(s) not in matched]
    if untargeted:
        print(
            f"[runner] Recorded with no target (not checked): {', '.join(untargeted)}"
        )

    # Every target the locustfile is meant to exercise must have been
    # recorded: one matched endpoint is not enough, because a request site
    # that records nothing (or a target renamed out from under it) leaves the
    # rest of the run green.
    coverage = _coverage_failures(locustfile, stats_list)
    if coverage:
        for line in coverage:
            print(f"[runner] FAIL: unmatched target -- {line}.")
        print("[runner] Exiting 1.")
        return 1

    duration_seconds = _parse_duration_to_seconds(duration)
    if sla == "report":
        _report_measurements(stats_list, duration_seconds)
        print(
            "\n[runner] Every declared target recorded and no request failed; "
            "latency and throughput reported, not gated. Exiting 0."
        )
        return 0

    validation_results = _validate_results(stats_list, duration_seconds)
    report = generate_report(validation_results)
    print("\n" + report)

    if all(r.passed for r in validation_results):
        print("\n[runner] All SLA targets met. Exiting 0.")
        return 0
    failed = [r.endpoint for r in validation_results if not r.passed]
    print(f"\n[runner] SLA violations for: {', '.join(failed)}")
    print("[runner] Exiting 1.")
    return 1


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------


def _parse_duration_to_seconds(duration: str) -> float:
    """
    Convert a Locust-style duration string to seconds.

    Args:
        duration: Duration string (e.g. "60s", "2m", "1h", "90").

    Returns:
        Duration in seconds as a float.

    Raises:
        ValueError: If the duration string cannot be parsed.
    """
    duration = duration.strip().lower()
    if duration.endswith("h"):
        return float(duration[:-1]) * 3600
    if duration.endswith("m"):
        return float(duration[:-1]) * 60
    if duration.endswith("s"):
        return float(duration[:-1])
    # Bare number — assume seconds
    try:
        return float(duration)
    except ValueError as exc:
        raise ValueError(f"Cannot parse duration: '{duration}'") from exc


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """
    Main entry point for the CI load test runner.

    Returns:
        0 if every declared target was recorded and every matched endpoint
        met its target; 1 if any target was missed, nothing was measured (no
        stats, or no matched endpoint), a declared target was not recorded,
        or an error occurred.
    """
    args = _parse_args(argv)

    server_proc: Optional[subprocess.Popen] = None

    try:
        # Optionally start a local server
        if args.start_server:
            server_host = f"http://localhost:{args.server_port}"
            server_proc = _start_server(args.server_port)
            if not _wait_for_server(server_host):
                print("[runner] FATAL: Could not start local server.")
                return 1
            host = server_host
        else:
            host = args.host

        # Run Locust
        locust_exit_code = _run_locust(
            host=host,
            users=args.users,
            spawn_rate=args.spawn_rate,
            duration=args.duration,
            locustfile=args.locustfile,
            csv_prefix=args.csv_prefix,
        )

        csv_stats_path = args.csv_prefix + _CSV_STATS_SUFFIX
        if locust_exit_code != 0:
            # Locust exits 1 when any request was marked a failure: this is
            # where failed requests fail the run. Name the endpoints, so the
            # red run says where without opening the CSV.
            print(f"[runner] ERROR: Locust exited with code {locust_exit_code}")
            try:
                for stats in parse_locust_csv(csv_stats_path):
                    if stats.num_failures:
                        print(
                            f"[runner] FAIL: {stats.method} {stats.name}: "
                            f"{stats.num_failures} of {stats.num_requests} "
                            "requests failed"
                        )
            except FileNotFoundError:
                pass
            return 1

        print(f"[runner] Parsing results from {csv_stats_path}…")
        return _judge(csv_stats_path, args.locustfile, args.duration, args.sla)

    except KeyboardInterrupt:
        print("\n[runner] Interrupted.")
        return 1
    except Exception as exc:
        print(f"[runner] FATAL: {exc}")
        return 1
    finally:
        if server_proc is not None:
            print("[runner] Stopping local server…")
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
