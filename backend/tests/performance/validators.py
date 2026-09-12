"""
Validators for load test results.

Parses Locust CSV output and validates results against performance SLA targets.
All public functions and classes have comprehensive type annotations.

Percentile calculation uses numpy.percentile with method='lower', which matches
the behaviour expected by the spec tests (integer-valued percentiles for integer
input — no interpolation between adjacent values).
"""

import csv
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from backend.tests.performance.specs.performance_targets import PerformanceTarget


@dataclass
class RequestStats:
    """
    Aggregated statistics for a single endpoint from a load test run.

    Attributes:
        name: The URL path or endpoint name as recorded by Locust
        method: HTTP method (GET, POST, PUT, DELETE)
        num_requests: Total number of requests made during the test
        num_failures: Number of requests that resulted in errors (4xx/5xx)
        response_times: List of individual response times in milliseconds
    """

    name: str
    method: str
    num_requests: int
    num_failures: int
    response_times: List[float]

    # Cached percentile values parsed from Locust CSV (optional — used by parse_locust_csv)
    _p50_cached: float = field(default=0.0, repr=False, compare=False)
    _p95_cached: float = field(default=0.0, repr=False, compare=False)
    _p99_cached: float = field(default=0.0, repr=False, compare=False)
    _use_cached: bool = field(default=False, repr=False, compare=False)

    @property
    def p50(self) -> float:
        """
        50th percentile (median) response time in milliseconds.

        Uses cached value if populated from Locust CSV; otherwise calculates
        from the raw response_times list using numpy.percentile with method='lower'
        (no interpolation — returns the actual observed value at that rank).

        Raises:
            ValueError: If response_times is empty and no cached value is available.
        """
        if self._use_cached:
            return self._p50_cached
        if not self.response_times:
            raise ValueError("Cannot compute p50: response_times is empty")
        return float(np.percentile(self.response_times, 50, method="lower"))

    @property
    def p95(self) -> float:
        """
        95th percentile response time in milliseconds.

        Uses cached value if populated from Locust CSV; otherwise calculates
        from the raw response_times list using numpy.percentile with method='lower'
        (no interpolation — returns the actual observed value at that rank).

        Raises:
            ValueError: If response_times is empty and no cached value is available.
        """
        if self._use_cached:
            return self._p95_cached
        if not self.response_times:
            raise ValueError("Cannot compute p95: response_times is empty")
        return float(np.percentile(self.response_times, 95, method="lower"))

    @property
    def p99(self) -> float:
        """
        99th percentile response time in milliseconds.

        Uses cached value if populated from Locust CSV; otherwise calculates
        from the raw response_times list using numpy.percentile with method='lower'
        (no interpolation — returns the actual observed value at that rank).

        Raises:
            ValueError: If response_times is empty and no cached value is available.
        """
        if self._use_cached:
            return self._p99_cached
        if not self.response_times:
            raise ValueError("Cannot compute p99: response_times is empty")
        return float(np.percentile(self.response_times, 99, method="lower"))

    @property
    def failure_rate(self) -> float:
        """
        Proportion of requests that resulted in failures (0.0 to 1.0).

        Returns 0.0 if num_requests is zero.
        """
        if self.num_requests == 0:
            return 0.0
        return self.num_failures / self.num_requests

    def rps(self, duration_seconds: float) -> float:
        """
        Requests per second achieved during the test.

        Args:
            duration_seconds: Duration of the load test in seconds.

        Returns:
            Requests per second as a float.

        Raises:
            ZeroDivisionError: If duration_seconds is zero.
        """
        if duration_seconds == 0.0:
            raise ZeroDivisionError(
                "duration_seconds must be non-zero to calculate RPS"
            )
        return self.num_requests / duration_seconds


@dataclass
class ValidationResult:
    """
    Result of validating a single endpoint's stats against its SLA target.

    Attributes:
        passed: True if all SLA checks passed; False if any failed.
        endpoint: The URL path of the endpoint being validated.
        failures: List of human-readable failure messages (empty if passed=True).
    """

    passed: bool
    endpoint: str
    failures: List[str]


# Maximum acceptable error rate (1%). Requests above this rate fail the SLA.
MAX_ACCEPTABLE_ERROR_RATE: float = 0.01


def validate_against_target(
    stats: RequestStats,
    target: PerformanceTarget,
    duration_seconds: float,
) -> ValidationResult:
    """
    Validate load test results against a performance SLA target.

    Checks:
    1. p50 response time <= target.p50_ms
    2. p95 response time <= target.p95_ms
    3. p99 response time <= target.p99_ms
    4. Error rate <= MAX_ACCEPTABLE_ERROR_RATE (1%)
    5. Achieved RPS >= target.min_rps

    Args:
        stats: The aggregated request statistics from the load test.
        target: The SLA target to validate against.
        duration_seconds: Duration of the load test in seconds (used for RPS calculation).

    Returns:
        ValidationResult with passed=True if all checks pass, or passed=False with
        a list of human-readable failure messages explaining each violation.
    """
    failures: List[str] = []

    # Check p50
    actual_p50 = stats.p50
    if actual_p50 > target.p50_ms:
        failures.append(f"p50 exceeded: {actual_p50:.1f}ms > {target.p50_ms}ms target")

    # Check p95
    actual_p95 = stats.p95
    if actual_p95 > target.p95_ms:
        failures.append(f"p95 exceeded: {actual_p95:.1f}ms > {target.p95_ms}ms target")

    # Check p99
    actual_p99 = stats.p99
    if actual_p99 > target.p99_ms:
        failures.append(f"p99 exceeded: {actual_p99:.1f}ms > {target.p99_ms}ms target")

    # Check error rate
    actual_error_rate = stats.failure_rate
    if actual_error_rate > MAX_ACCEPTABLE_ERROR_RATE:
        failures.append(
            f"Error rate too high: {actual_error_rate:.2%} > {MAX_ACCEPTABLE_ERROR_RATE:.2%} threshold"
        )

    # Check RPS
    actual_rps = stats.rps(duration_seconds)
    if actual_rps < target.min_rps:
        failures.append(
            f"RPS below target: {actual_rps:.1f} < {target.min_rps} required RPS"
        )

    return ValidationResult(
        passed=len(failures) == 0,
        endpoint=target.endpoint,
        failures=failures,
    )


def parse_locust_csv(csv_path: str) -> List[RequestStats]:
    """
    Parse a Locust stats CSV file and return a list of RequestStats objects.

    Locust generates CSV files with pre-computed percentile columns (50%, 95%, 99%, etc.).
    This function reads those columns and sets the cached percentile values on each
    RequestStats object so that p50/p95/p99 properties return the pre-computed values
    directly without needing raw response_times data.

    The 'Aggregated' summary row (if present) is skipped.

    Args:
        csv_path: Absolute path to the Locust stats CSV file.

    Returns:
        List of RequestStats objects, one per endpoint row in the CSV.

    Raises:
        FileNotFoundError: If the CSV file does not exist at csv_path.
    """
    import os

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Locust CSV file not found: {csv_path}")

    results: List[RequestStats] = []

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Name", "").strip()

            # Skip the Locust aggregated summary row
            if name == "Aggregated":
                continue

            # Skip completely empty rows
            if not name:
                continue

            method = row.get("Type", "GET").strip() or "GET"
            num_requests = int(row.get("Request Count", "0") or "0")
            num_failures = int(row.get("Failure Count", "0") or "0")

            # Read pre-computed percentiles from Locust columns
            p50_val = float(row.get("50%", "0") or "0")
            p95_val = float(row.get("95%", "0") or "0")
            p99_val = float(row.get("99%", "0") or "0")

            stats = RequestStats(
                name=name,
                method=method,
                num_requests=num_requests,
                num_failures=num_failures,
                response_times=[],  # Not available from CSV; percentiles are pre-computed
                _p50_cached=p50_val,
                _p95_cached=p95_val,
                _p99_cached=p99_val,
                _use_cached=True,
            )
            results.append(stats)

    return results


def generate_report(results: List[ValidationResult]) -> str:
    """
    Generate a human-readable performance test report from validation results.

    The report includes:
    - A summary of total passed/failed endpoints
    - Per-endpoint PASS/FAIL status with failure details

    Args:
        results: List of ValidationResult objects to include in the report.

    Returns:
        A formatted multi-line string report.
    """
    total = len(results)
    passed_count = sum(1 for r in results if r.passed)
    failed_count = total - passed_count

    lines: List[str] = [
        "=" * 60,
        "PERFORMANCE TEST REPORT",
        "=" * 60,
        f"Total endpoints: {total}  |  Passed: {passed_count}  |  Failed: {failed_count}",
        "-" * 60,
    ]

    for result in results:
        status_label = "PASS" if result.passed else "FAIL"
        lines.append(f"[{status_label}] {result.endpoint}")
        if result.failures:
            for failure_msg in result.failures:
                lines.append(f"       - {failure_msg}")

    lines.append("=" * 60)
    if failed_count == 0:
        lines.append("All SLA targets met.")
    else:
        lines.append(f"{failed_count} endpoint(s) failed SLA targets.")
    lines.append("=" * 60)

    return "\n".join(lines)


@dataclass
class BreakpointResult:
    """
    Result of analyzing a breakpoint/capacity limit test.

    Attributes:
        max_users: Maximum concurrent users before degradation
        breaking_rps: RPS at the point of degradation
        breaking_error_rate: Error rate at the breaking point (0.0 to 1.0)
        breaking_p99: P99 latency at the breaking point in milliseconds
        stages_completed: Number of ramp stages completed before breaking
    """

    max_users: int
    breaking_rps: float
    breaking_error_rate: float
    breaking_p99: float
    stages_completed: int


def analyze_breakpoint(
    csv_history_path: str,
    error_rate_threshold: float = 0.05,
    p99_threshold_ms: float = 2000.0,
) -> BreakpointResult:
    """
    Analyze a Locust history CSV to find the system's breaking point.

    The breaking point is defined as the first moment where:
    - Error rate exceeds error_rate_threshold (default 5%), OR
    - P99 latency exceeds p99_threshold_ms (default 2000ms)

    The history CSV has per-second rows with columns: Timestamp, User Count,
    Type, Name, Requests/s, Failures/s, 50%, 95%, 99%, etc.

    Args:
        csv_history_path: Path to the Locust full history CSV.
        error_rate_threshold: Error rate threshold (0.0 to 1.0).
        p99_threshold_ms: P99 latency threshold in milliseconds.

    Returns:
        BreakpointResult with the detected breaking point data.

    Raises:
        FileNotFoundError: If csv_history_path does not exist.
    """
    import os

    if not os.path.exists(csv_history_path):
        raise FileNotFoundError(f"History CSV not found: {csv_history_path}")

    max_users = 0
    breaking_rps = 0.0
    breaking_error_rate = 0.0
    breaking_p99 = 0.0
    stages_completed = 0
    last_user_count = 0

    with open(csv_history_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Name", "").strip()
            # Only look at "Aggregated" rows for overall system metrics
            if name != "Aggregated":
                continue

            user_count = int(row.get("User Count", "0") or "0")
            rps = float(row.get("Requests/s", "0") or "0")
            failures_per_s = float(row.get("Failures/s", "0") or "0")
            p99 = float(row.get("99%", "0") or "0")

            # Calculate error rate for this time window
            error_rate = failures_per_s / rps if rps > 0 else 0.0

            # Track stage transitions (user count increases)
            if user_count > last_user_count:
                stages_completed += 1
                last_user_count = user_count

            # Check for breaking point
            if error_rate > error_rate_threshold or p99 > p99_threshold_ms:
                return BreakpointResult(
                    max_users=user_count,
                    breaking_rps=rps,
                    breaking_error_rate=error_rate,
                    breaking_p99=p99,
                    stages_completed=stages_completed,
                )

            # Track the highest stable values
            if user_count > max_users:
                max_users = user_count
            breaking_rps = max(breaking_rps, rps)
            breaking_p99 = max(breaking_p99, p99)

    # If no breaking point was found, the system handled all stages
    return BreakpointResult(
        max_users=max_users,
        breaking_rps=breaking_rps,
        breaking_error_rate=0.0,
        breaking_p99=breaking_p99,
        stages_completed=stages_completed,
    )


def generate_enhanced_report(
    results: List[ValidationResult],
    breakpoint: Optional[BreakpointResult] = None,
    capacity_report: Optional[str] = None,
) -> str:
    """
    Generate an enhanced performance report with optional breakpoint and capacity data.

    Extends the base generate_report() with additional sections when breakpoint
    analysis or capacity planning data is available.

    Args:
        results: List of ValidationResult objects.
        breakpoint: Optional BreakpointResult from breakpoint analysis.
        capacity_report: Optional pre-formatted capacity planning report string.

    Returns:
        A formatted multi-line string report.
    """
    # Start with the base report
    report = generate_report(results)

    sections: List[str] = [report]

    # Add breakpoint analysis section
    if breakpoint is not None:
        bp_lines: List[str] = [
            "",
            "=" * 60,
            "BREAKPOINT ANALYSIS",
            "=" * 60,
            f"Max stable users    : {breakpoint.max_users}",
            f"Breaking RPS        : {breakpoint.breaking_rps:.1f}",
            f"Breaking error rate : {breakpoint.breaking_error_rate:.2%}",
            f"Breaking p99        : {breakpoint.breaking_p99:.0f}ms",
            f"Stages completed    : {breakpoint.stages_completed}",
        ]
        if breakpoint.breaking_error_rate == 0.0:
            bp_lines.append(
                "Status: System handled all load stages without degradation"
            )
        else:
            bp_lines.append("Status: Degradation detected — consider scaling")
        bp_lines.append("=" * 60)
        sections.append("\n".join(bp_lines))

    # Add capacity planning section
    if capacity_report is not None:
        sections.append("\n" + capacity_report)

    return "\n".join(sections)
