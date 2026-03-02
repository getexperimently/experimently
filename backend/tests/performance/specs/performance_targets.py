"""
Performance target specifications for all API endpoints.

These are the SLA contracts. Tests validate actual performance meets these targets.
Each PerformanceTarget defines the acceptable latency percentiles and minimum
throughput for a given endpoint under load.
"""
from dataclasses import dataclass, field


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


@dataclass
class TargetGroup:
    """
    A logical grouping of performance targets by operational category.

    Attributes:
        name: Human-readable group name
        description: What this group represents
        target_keys: List of keys into PERFORMANCE_TARGETS
    """

    name: str
    description: str
    target_keys: list[str] = field(default_factory=list)


# SLA contracts for all performance-critical endpoints.
# These values represent the maximum acceptable response times and minimum throughput.
PERFORMANCE_TARGETS: dict[str, PerformanceTarget] = {
    # --- Tracking endpoints (high-frequency SDK calls) ---
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
    # --- Evaluation endpoints ---
    "evaluate_flag": PerformanceTarget(
        endpoint="/api/v1/feature-flags/evaluate/{key}",
        method="GET",
        p50_ms=20,
        p95_ms=80,
        p99_ms=200,
        min_rps=2000,
        description="Single feature flag evaluation",
    ),
    "batch_evaluate_flags": PerformanceTarget(
        endpoint="/api/v1/feature-flags/evaluate-batch",
        method="POST",
        p50_ms=80,
        p95_ms=300,
        p99_ms=800,
        min_rps=500,
        description="Batch evaluation of multiple feature flags",
    ),
    # --- CRUD endpoints (dashboard/management operations) ---
    "create_experiment": PerformanceTarget(
        endpoint="/api/v1/experiments",
        method="POST",
        p50_ms=150,
        p95_ms=400,
        p99_ms=1000,
        min_rps=100,
        description="Create a new experiment",
    ),
    "update_experiment": PerformanceTarget(
        endpoint="/api/v1/experiments/{experiment_id}",
        method="PUT",
        p50_ms=120,
        p95_ms=350,
        p99_ms=900,
        min_rps=100,
        description="Update an existing experiment",
    ),
    "create_feature_flag": PerformanceTarget(
        endpoint="/api/v1/feature-flags",
        method="POST",
        p50_ms=120,
        p95_ms=350,
        p99_ms=900,
        min_rps=150,
        description="Create a new feature flag",
    ),
    "update_feature_flag": PerformanceTarget(
        endpoint="/api/v1/feature-flags/{flag_id}",
        method="PUT",
        p50_ms=100,
        p95_ms=300,
        p99_ms=800,
        min_rps=150,
        description="Update an existing feature flag",
    ),
    "delete_experiment": PerformanceTarget(
        endpoint="/api/v1/experiments/{experiment_id}",
        method="DELETE",
        p50_ms=100,
        p95_ms=300,
        p99_ms=800,
        min_rps=100,
        description="Delete a draft experiment",
    ),
    # --- Analytics/read endpoints ---
    "list_experiments": PerformanceTarget(
        endpoint="/api/v1/experiments",
        method="GET",
        p50_ms=100,
        p95_ms=300,
        p99_ms=800,
        min_rps=200,
        description="List all experiments",
    ),
    "get_experiment_results": PerformanceTarget(
        endpoint="/api/v1/experiments/{experiment_id}/results",
        method="GET",
        p50_ms=200,
        p95_ms=600,
        p99_ms=1500,
        min_rps=50,
        description="Get experiment results with statistical analysis",
    ),
    # --- Bulk operations ---
    "bulk_flag_toggle": PerformanceTarget(
        endpoint="/api/v1/feature-flags/bulk-toggle",
        method="POST",
        p50_ms=200,
        p95_ms=500,
        p99_ms=1200,
        min_rps=50,
        description="Bulk toggle multiple feature flags",
    ),
    # --- Infrastructure ---
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

# Logical groupings of targets by operational category.
TARGET_GROUPS: dict[str, TargetGroup] = {
    "tracking": TargetGroup(
        name="Tracking",
        description="High-frequency SDK tracking calls",
        target_keys=["assign", "track"],
    ),
    "evaluation": TargetGroup(
        name="Evaluation",
        description="Feature flag evaluation endpoints",
        target_keys=["evaluate_flag", "batch_evaluate_flags"],
    ),
    "crud": TargetGroup(
        name="CRUD",
        description="Create/update/delete operations for experiments and feature flags",
        target_keys=[
            "create_experiment",
            "update_experiment",
            "create_feature_flag",
            "update_feature_flag",
            "delete_experiment",
        ],
    ),
    "analytics": TargetGroup(
        name="Analytics",
        description="Read-heavy analytics and listing endpoints",
        target_keys=["list_experiments", "get_experiment_results"],
    ),
    "bulk_operations": TargetGroup(
        name="Bulk Operations",
        description="Batch and bulk operations on multiple resources",
        target_keys=["bulk_flag_toggle"],
    ),
    "infrastructure": TargetGroup(
        name="Infrastructure",
        description="Health checks and infrastructure endpoints",
        target_keys=["health"],
    ),
}
