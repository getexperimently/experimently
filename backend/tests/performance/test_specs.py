"""
Unit tests for performance target specifications.

Tests that the SLA contracts are well-formed, internally consistent,
and cover all required endpoints.
"""
import pytest

from backend.tests.performance.specs.performance_targets import (
    PERFORMANCE_TARGETS,
    PerformanceTarget,
)


def test_all_required_endpoints_have_targets():
    """All required high-traffic endpoints must have defined performance targets."""
    required = {"assign", "track", "evaluate_flag", "list_experiments", "health"}
    assert required.issubset(
        set(PERFORMANCE_TARGETS.keys())
    ), f"Missing required endpoint targets: {required - set(PERFORMANCE_TARGETS.keys())}"


def test_sla_values_are_reasonable():
    """Each target must satisfy p50 < p95 < p99 and positive throughput."""
    for name, target in PERFORMANCE_TARGETS.items():
        assert target.p50_ms < target.p95_ms < target.p99_ms, (
            f"{name}: p50 < p95 < p99 must hold, "
            f"got p50={target.p50_ms}, p95={target.p95_ms}, p99={target.p99_ms}"
        )
        assert target.min_rps > 0, f"{name}: min_rps must be positive, got {target.min_rps}"


def test_tracking_endpoints_are_faster_than_list_experiments():
    """Tracking endpoints should be faster than list-experiments (read-heavy DB scan)."""
    track = PERFORMANCE_TARGETS["track"]
    assign = PERFORMANCE_TARGETS["assign"]
    experiments = PERFORMANCE_TARGETS["list_experiments"]

    assert track.p95_ms < experiments.p95_ms, (
        f"track p95 ({track.p95_ms}ms) should be < list_experiments p95 ({experiments.p95_ms}ms)"
    )
    assert assign.p95_ms < experiments.p95_ms, (
        f"assign p95 ({assign.p95_ms}ms) should be < list_experiments p95 ({experiments.p95_ms}ms)"
    )


def test_health_check_is_fastest_endpoint():
    """Health check must be the fastest endpoint (no business logic)."""
    health = PERFORMANCE_TARGETS["health"]
    for name, target in PERFORMANCE_TARGETS.items():
        if name != "health":
            assert health.p95_ms <= target.p95_ms, (
                f"health p95 ({health.p95_ms}ms) should be <= {name} p95 ({target.p95_ms}ms)"
            )


def test_health_check_has_highest_throughput():
    """Health check must support the highest RPS (simple no-op endpoint)."""
    health = PERFORMANCE_TARGETS["health"]
    for name, target in PERFORMANCE_TARGETS.items():
        if name != "health":
            assert health.min_rps >= target.min_rps, (
                f"health min_rps ({health.min_rps}) should be >= {name} min_rps ({target.min_rps})"
            )


def test_performance_target_has_all_required_fields():
    """Every PerformanceTarget must have all required SLA fields populated."""
    for name, target in PERFORMANCE_TARGETS.items():
        assert target.endpoint, f"{name}: endpoint must not be empty"
        assert target.method in {"GET", "POST", "PUT", "DELETE", "PATCH"}, (
            f"{name}: method must be a valid HTTP verb, got '{target.method}'"
        )
        assert target.p50_ms > 0, f"{name}: p50_ms must be positive"
        assert target.p95_ms > 0, f"{name}: p95_ms must be positive"
        assert target.p99_ms > 0, f"{name}: p99_ms must be positive"
        assert target.min_rps > 0, f"{name}: min_rps must be positive"
        assert target.description, f"{name}: description must not be empty"


def test_performance_target_is_dataclass():
    """PerformanceTarget should be instantiatable as a plain dataclass."""
    target = PerformanceTarget(
        endpoint="/test",
        method="GET",
        p50_ms=5.0,
        p95_ms=20.0,
        p99_ms=50.0,
        min_rps=100.0,
        description="Test endpoint",
    )
    assert target.endpoint == "/test"
    assert target.p50_ms == 5.0
    assert target.min_rps == 100.0


def test_evaluate_flag_has_highest_throughput_among_business_endpoints():
    """Feature flag evaluation is called most frequently — must have highest RPS among business endpoints."""
    evaluate_flag = PERFORMANCE_TARGETS["evaluate_flag"]
    track = PERFORMANCE_TARGETS["track"]
    assign = PERFORMANCE_TARGETS["assign"]
    list_exp = PERFORMANCE_TARGETS["list_experiments"]

    assert evaluate_flag.min_rps >= track.min_rps, (
        f"evaluate_flag min_rps ({evaluate_flag.min_rps}) should be >= track min_rps ({track.min_rps})"
    )
    assert evaluate_flag.min_rps >= assign.min_rps, (
        f"evaluate_flag min_rps ({evaluate_flag.min_rps}) should be >= assign min_rps ({assign.min_rps})"
    )
    assert evaluate_flag.min_rps >= list_exp.min_rps, (
        f"evaluate_flag min_rps ({evaluate_flag.min_rps}) should be >= list_experiments min_rps ({list_exp.min_rps})"
    )


def test_all_targets_use_api_v1_prefix_or_root():
    """Endpoints should use /api/v1 prefix or root paths like /health."""
    for name, target in PERFORMANCE_TARGETS.items():
        assert target.endpoint.startswith("/"), (
            f"{name}: endpoint must start with '/', got '{target.endpoint}'"
        )
        if name != "health":
            assert target.endpoint.startswith("/api/v1/"), (
                f"{name}: business endpoints must use /api/v1/ prefix, got '{target.endpoint}'"
            )
