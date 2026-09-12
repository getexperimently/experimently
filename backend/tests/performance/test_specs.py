"""
Unit tests for performance target specifications.

Tests that the SLA contracts are well-formed, internally consistent,
and cover all required endpoints.
"""

import pytest

from backend.tests.performance.specs.performance_targets import (
    PERFORMANCE_TARGETS,
    TARGET_GROUPS,
    PerformanceTarget,
    TargetGroup,
)


def test_all_required_endpoints_have_targets():
    """All required high-traffic endpoints must have defined performance targets."""
    required = {"assign", "track", "evaluate_flag", "list_experiments", "health"}
    assert required.issubset(set(PERFORMANCE_TARGETS.keys())), (
        f"Missing required endpoint targets: {required - set(PERFORMANCE_TARGETS.keys())}"
    )


def test_sla_values_are_reasonable():
    """Each target must satisfy p50 < p95 < p99 and positive throughput."""
    for name, target in PERFORMANCE_TARGETS.items():
        assert target.p50_ms < target.p95_ms < target.p99_ms, (
            f"{name}: p50 < p95 < p99 must hold, "
            f"got p50={target.p50_ms}, p95={target.p95_ms}, p99={target.p99_ms}"
        )
        assert target.min_rps > 0, (
            f"{name}: min_rps must be positive, got {target.min_rps}"
        )


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


# ---------------------------------------------------------------------------
# New tests for expanded targets and target groups
# ---------------------------------------------------------------------------


def test_crud_endpoints_have_targets():
    """All CRUD endpoints must have defined performance targets."""
    crud_keys = {
        "create_experiment",
        "update_experiment",
        "create_feature_flag",
        "update_feature_flag",
        "delete_experiment",
    }
    assert crud_keys.issubset(set(PERFORMANCE_TARGETS.keys())), (
        f"Missing CRUD targets: {crud_keys - set(PERFORMANCE_TARGETS.keys())}"
    )


def test_crud_endpoints_are_slower_than_evaluation():
    """CRUD operations involve DB writes and should have higher latency targets than flag evaluation."""
    evaluate_flag = PERFORMANCE_TARGETS["evaluate_flag"]
    crud_keys = [
        "create_experiment",
        "update_experiment",
        "create_feature_flag",
        "update_feature_flag",
        "delete_experiment",
    ]
    for key in crud_keys:
        target = PERFORMANCE_TARGETS[key]
        assert target.p95_ms > evaluate_flag.p95_ms, (
            f"{key} p95 ({target.p95_ms}ms) should be > evaluate_flag p95 ({evaluate_flag.p95_ms}ms)"
        )


def test_bulk_operations_have_relaxed_targets():
    """Bulk operations process multiple items and should allow higher latency."""
    bulk_toggle = PERFORMANCE_TARGETS["bulk_flag_toggle"]
    single_update = PERFORMANCE_TARGETS["update_feature_flag"]
    assert bulk_toggle.p95_ms > single_update.p95_ms, (
        f"bulk_flag_toggle p95 ({bulk_toggle.p95_ms}ms) should be > "
        f"update_feature_flag p95 ({single_update.p95_ms}ms)"
    )
    assert bulk_toggle.min_rps <= single_update.min_rps, (
        f"bulk_flag_toggle min_rps ({bulk_toggle.min_rps}) should be <= "
        f"update_feature_flag min_rps ({single_update.min_rps})"
    )


def test_target_groups_cover_all_targets():
    """Every target must appear in at least one target group."""
    grouped_keys: set[str] = set()
    for group in TARGET_GROUPS.values():
        grouped_keys.update(group.target_keys)
    missing = set(PERFORMANCE_TARGETS.keys()) - grouped_keys
    assert not missing, f"Targets not in any group: {missing}"


def test_target_groups_are_non_empty():
    """No target group should be empty."""
    for group_name, group in TARGET_GROUPS.items():
        assert len(group.target_keys) > 0, f"Target group '{group_name}' has no targets"


def test_write_endpoints_use_post_or_put_or_delete():
    """CRUD write targets must use POST, PUT, or DELETE methods."""
    write_keys = [
        "create_experiment",
        "update_experiment",
        "create_feature_flag",
        "update_feature_flag",
        "delete_experiment",
        "bulk_flag_toggle",
    ]
    for key in write_keys:
        target = PERFORMANCE_TARGETS[key]
        assert target.method in {"POST", "PUT", "DELETE"}, (
            f"{key}: write endpoint must use POST/PUT/DELETE, got '{target.method}'"
        )


def test_read_endpoints_use_get():
    """Read-only targets should use the GET method."""
    read_keys = [
        "list_experiments",
        "get_experiment_results",
        "evaluate_flag",
        "health",
    ]
    for key in read_keys:
        target = PERFORMANCE_TARGETS[key]
        assert target.method == "GET", (
            f"{key}: read endpoint must use GET, got '{target.method}'"
        )


def test_all_targets_have_unique_endpoints():
    """No two targets should share the same (endpoint, method) combination."""
    seen: set[tuple[str, str]] = set()
    for name, target in PERFORMANCE_TARGETS.items():
        pair = (target.endpoint, target.method)
        assert pair not in seen, f"{name}: duplicate (endpoint, method) pair: {pair}"
        seen.add(pair)


def test_batch_evaluate_has_higher_latency_than_single():
    """Batch flag evaluation processes multiple flags and must allow higher latency."""
    single = PERFORMANCE_TARGETS["evaluate_flag"]
    batch = PERFORMANCE_TARGETS["batch_evaluate_flags"]
    assert batch.p50_ms > single.p50_ms, (
        f"batch p50 ({batch.p50_ms}ms) should be > single p50 ({single.p50_ms}ms)"
    )
    assert batch.p95_ms > single.p95_ms, (
        f"batch p95 ({batch.p95_ms}ms) should be > single p95 ({single.p95_ms}ms)"
    )
    assert batch.p99_ms > single.p99_ms, (
        f"batch p99 ({batch.p99_ms}ms) should be > single p99 ({single.p99_ms}ms)"
    )
