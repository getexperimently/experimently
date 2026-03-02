"""
Performance target specifications for all API endpoints.

These are the SLA contracts. Tests validate actual performance meets these targets.
Each PerformanceTarget defines the acceptable latency percentiles and minimum
throughput for a given endpoint under load.
"""
from dataclasses import dataclass


@dataclass
class PerformanceTarget:
    """
    SLA contract for a single API endpoint.

    Attributes:
        endpoint: The URL path of the endpoint (may contain path params like {key})
        method: HTTP method (GET, POST, PUT, DELETE)
        p50_ms: 50th percentile response time in milliseconds
        p95_ms: 95th percentile response time in milliseconds
        p99_ms: 99th percentile response time in milliseconds
        min_rps: Minimum required requests per second throughput
        description: Human-readable description of what this endpoint does
    """

    endpoint: str
    method: str
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_rps: float
    description: str


# SLA contracts for all performance-critical endpoints.
# These values represent the maximum acceptable response times and minimum throughput.
PERFORMANCE_TARGETS: dict[str, PerformanceTarget] = {
    "assign": PerformanceTarget(
        endpoint="/api/v1/tracking/assign",
        method="POST",
        p50_ms=50,
        p95_ms=200,
        p99_ms=500,
        min_rps=500,
        description="User assignment to experiment variant",
    ),
    "track": PerformanceTarget(
        endpoint="/api/v1/tracking/track",
        method="POST",
        p50_ms=30,
        p95_ms=100,
        p99_ms=300,
        min_rps=1000,
        description="Event tracking",
    ),
    "evaluate_flag": PerformanceTarget(
        endpoint="/api/v1/feature-flags/evaluate/{key}",
        method="GET",
        p50_ms=20,
        p95_ms=80,
        p99_ms=200,
        min_rps=2000,
        description="Single feature flag evaluation",
    ),
    "list_experiments": PerformanceTarget(
        endpoint="/api/v1/experiments",
        method="GET",
        p50_ms=100,
        p95_ms=300,
        p99_ms=800,
        min_rps=200,
        description="List all experiments",
    ),
    "health": PerformanceTarget(
        endpoint="/health",
        method="GET",
        p50_ms=10,
        p95_ms=30,
        p99_ms=100,
        min_rps=5000,
        description="Health check",
    ),
}
