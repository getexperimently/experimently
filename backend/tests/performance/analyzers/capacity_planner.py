"""
Capacity planner for the experimentation platform.

Extrapolates load test results to estimate production capacity requirements
including recommended instance counts, per-instance throughput, and headroom buffers.
"""

import math
from dataclasses import dataclass

# Default headroom buffer — 50% over peak projected load (per EP-012 ticket)
DEFAULT_HEADROOM_PCT: float = 50.0

# Assumed RPS capacity per compute instance (t3.medium equivalent)
DEFAULT_RPS_PER_INSTANCE: float = 500.0


@dataclass
class CapacityEstimate:
    """
    Capacity estimate for a single endpoint or service.

    Attributes:
        endpoint: The API endpoint path
        measured_rps: RPS achieved during the load test
        max_rps: Estimated maximum RPS before degradation
        recommended_instances: Recommended instance count for the target RPS
        headroom_pct: Safety headroom percentage applied
        target_rps: The target RPS used for the estimate
    """

    endpoint: str
    measured_rps: float
    max_rps: float
    recommended_instances: int
    headroom_pct: float
    target_rps: float


def estimate_capacity(
    endpoint_rps: list[tuple[str, float]],
    target_rps: float,
    rps_per_instance: float = DEFAULT_RPS_PER_INSTANCE,
    headroom_pct: float = DEFAULT_HEADROOM_PCT,
) -> list[CapacityEstimate]:
    """
    Estimate capacity requirements based on load test throughput data.

    For each endpoint, calculates the number of instances needed to serve the
    target RPS with the specified headroom buffer.

    The formula:
        effective_target = target_rps * (1 + headroom_pct / 100)
        instances = ceil(effective_target / rps_per_instance)

    Args:
        endpoint_rps: List of (endpoint_path, measured_rps) tuples from load tests.
        target_rps: The production target RPS to plan for.
        rps_per_instance: Assumed RPS capacity per compute instance.
        headroom_pct: Safety headroom percentage (default 50%).

    Returns:
        List of CapacityEstimate objects, one per endpoint.
    """
    estimates: list[CapacityEstimate] = []

    effective_target = target_rps * (1.0 + headroom_pct / 100.0)

    for endpoint, measured_rps in endpoint_rps:
        # Estimate max RPS by extrapolating from measured data
        # If measured at 80% utilization, max ≈ measured / 0.8
        max_rps = measured_rps / 0.8 if measured_rps > 0 else 0.0

        # Calculate instances needed for the effective target
        if rps_per_instance > 0:
            instances_needed = math.ceil(effective_target / rps_per_instance)
        else:
            instances_needed = 1

        estimates.append(
            CapacityEstimate(
                endpoint=endpoint,
                measured_rps=measured_rps,
                max_rps=round(max_rps, 1),
                recommended_instances=max(1, instances_needed),
                headroom_pct=headroom_pct,
                target_rps=target_rps,
            )
        )

    return estimates


def generate_capacity_report(
    estimates: list[CapacityEstimate],
    service_name: str = "experimentation-platform",
) -> str:
    """
    Generate a human-readable capacity planning report.

    Args:
        estimates: List of CapacityEstimate objects.
        service_name: Name of the service for the report header.

    Returns:
        Formatted multi-line report string.
    """
    if not estimates:
        return "No capacity data available."

    lines: list[str] = [
        "=" * 70,
        f"CAPACITY PLANNING REPORT — {service_name}",
        "=" * 70,
    ]

    # Summary
    max_instances = max(e.recommended_instances for e in estimates)
    target_rps = estimates[0].target_rps if estimates else 0
    headroom = estimates[0].headroom_pct if estimates else DEFAULT_HEADROOM_PCT

    lines.append(f"Target RPS: {target_rps:,.0f}  |  Headroom: {headroom:.0f}%")
    lines.append(f"Max recommended instances: {max_instances}")
    lines.append("-" * 70)

    # Per-endpoint details
    lines.append(f"{'Endpoint':<45} {'Measured':>10} {'Max':>10} {'Instances':>10}")
    lines.append("-" * 70)

    for est in estimates:
        endpoint_display = (
            est.endpoint[:42] + "..." if len(est.endpoint) > 45 else est.endpoint
        )
        lines.append(
            f"{endpoint_display:<45} "
            f"{est.measured_rps:>9.1f} "
            f"{est.max_rps:>9.1f} "
            f"{est.recommended_instances:>10d}"
        )

    lines.append("=" * 70)

    # Recommendations
    lines.append("\nRECOMMENDATIONS:")
    lines.append(
        f"  - Deploy at least {max_instances} instances for {target_rps:,.0f} RPS target"
    )
    lines.append(f"  - Includes {headroom:.0f}% headroom buffer for traffic spikes")
    lines.append(
        f"  - Consider auto-scaling with min={max(1, max_instances // 2)} max={max_instances * 2} instances"
    )
    lines.append("=" * 70)

    return "\n".join(lines)
