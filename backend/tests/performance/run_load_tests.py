#!/usr/bin/env python3
"""
CI load test runner for the experimentation platform.

Orchestrates a complete load test cycle:
1. Optionally starts a local test server (uvicorn)
2. Runs Locust in headless mode against the target host
3. Parses the generated CSV output
4. Validates results against PERFORMANCE_TARGETS SLA contracts
5. Generates a human-readable report
6. Exits with code 0 if all SLAs pass, code 1 if any fail

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
    0 — all SLA targets met
    1 — one or more SLA targets violated, or test infrastructure error
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure the repo root is on sys.path so backend.* imports resolve
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.tests.performance.validators import (
    RequestStats,
    ValidationResult,
    parse_locust_csv,
    generate_report,
    validate_against_target,
)
from backend.tests.performance.specs.performance_targets import (
    PERFORMANCE_TARGETS,
    PerformanceTarget,
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
        "--locustfile",
        default=str(_DEFAULT_LOCUSTFILE),
        help="Path to the Locust test file to run",
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
    return parser.parse_args(argv)


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
    import urllib.request
    import urllib.error

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
        "--host", host,
        "--users", str(users),
        "--spawn-rate", str(spawn_rate),
        "--run-time", duration,
        "--locustfile", locustfile,
        "--csv", csv_prefix,
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

    Matching is done by checking whether the stats endpoint name contains the
    target endpoint path (handling path parameters like {key}).

    Args:
        stats_list: Parsed RequestStats from the Locust CSV.

    Returns:
        List of (stats, target) pairs for endpoints that have a defined SLA.
    """
    pairs: list[tuple[RequestStats, PerformanceTarget]] = []
    for stats in stats_list:
        for _key, target in PERFORMANCE_TARGETS.items():
            # Normalise target endpoint — strip path params for matching
            normalised_target = target.endpoint.split("{")[0].rstrip("/")
            if normalised_target in stats.name or stats.name in target.endpoint:
                pairs.append((stats, target))
                break
    return pairs


def _validate_results(
    stats_list: list[RequestStats],
    duration_seconds: float,
) -> list[ValidationResult]:
    """
    Validate all parsed stats against the SLA performance targets.

    Endpoints not covered by a performance target are skipped.

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
        0 if all SLAs pass, 1 if any SLAs fail or an error occurs.
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

        if locust_exit_code != 0:
            print(f"[runner] ERROR: Locust exited with code {locust_exit_code}")
            return 1

        # Parse results
        csv_stats_path = args.csv_prefix + _CSV_STATS_SUFFIX
        print(f"[runner] Parsing results from {csv_stats_path}…")

        try:
            stats_list = parse_locust_csv(csv_stats_path)
        except FileNotFoundError:
            print(f"[runner] ERROR: CSV not found at {csv_stats_path}")
            return 1

        if not stats_list:
            print("[runner] WARNING: No stats parsed from CSV. Nothing to validate.")
            return 0

        # Validate against SLAs
        duration_seconds = _parse_duration_to_seconds(args.duration)
        validation_results = _validate_results(stats_list, duration_seconds)

        # Generate and print report
        report = generate_report(validation_results)
        print("\n" + report)

        # Determine exit code
        all_passed = all(r.passed for r in validation_results)
        if all_passed:
            print("\n[runner] All SLA targets met. Exiting 0.")
            return 0
        else:
            failed = [r.endpoint for r in validation_results if not r.passed]
            print(f"\n[runner] SLA violations for: {', '.join(failed)}")
            print("[runner] Exiting 1.")
            return 1

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
