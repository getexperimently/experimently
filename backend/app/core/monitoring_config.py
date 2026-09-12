"""
Monitoring configuration — single source of truth for all metrics,
alert thresholds, and dashboard definitions.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class MetricSpec:
    name: str  # e.g., "api_request_duration_seconds"
    description: str
    labels: List[str]  # e.g., ["method", "endpoint", "status_code"]
    alert_threshold: Optional[float] = None
    alert_comparison: str = ">"  # ">" or "<"


# All Prometheus metrics used by the application
METRICS_REGISTRY: Dict[str, MetricSpec] = {
    "http_requests_total": MetricSpec(
        name="http_requests_total",
        description="Total HTTP requests",
        labels=["method", "endpoint", "status_code"],
    ),
    "http_request_duration_seconds": MetricSpec(
        name="http_request_duration_seconds",
        description="HTTP request duration in seconds",
        labels=["method", "endpoint"],
    ),
    "http_request_size_bytes": MetricSpec(
        name="http_request_size_bytes",
        description="HTTP request size in bytes",
        labels=["method", "endpoint"],
    ),
    "db_query_duration_seconds": MetricSpec(
        name="db_query_duration_seconds",
        description="Database query duration in seconds",
        labels=["operation", "table"],
    ),
    "experiment_assignments_total": MetricSpec(
        name="experiment_assignments_total",
        description="Total experiment assignments",
        labels=["experiment_id", "variant_id"],
    ),
    "events_tracked_total": MetricSpec(
        name="events_tracked_total",
        description="Total events tracked",
        labels=["event_type"],
    ),
    "feature_flag_evaluations_total": MetricSpec(
        name="feature_flag_evaluations_total",
        description="Total feature flag evaluations",
        labels=["flag_key", "result"],
    ),
    "cache_hits_total": MetricSpec(
        name="cache_hits_total",
        description="Cache hits",
        labels=["cache_type"],
    ),
    "cache_misses_total": MetricSpec(
        name="cache_misses_total",
        description="Cache misses",
        labels=["cache_type"],
    ),
    "active_experiments_gauge": MetricSpec(
        name="active_experiments_gauge",
        description="Number of currently active experiments",
        labels=[],
        alert_threshold=100,  # Alert if > 100 active experiments
        alert_comparison=">",
    ),
}

# Alert thresholds for CloudWatch alarms
CLOUDWATCH_ALARMS: Dict[str, Dict] = {
    "high_error_rate": {
        "metric": "5XXErrorRate",
        "threshold": 1.0,  # 1% error rate
        "evaluation_periods": 2,
        "period": 60,
        "comparison": "GreaterThanThreshold",
        "alarm_actions": ["${SNS_ALARM_TOPIC_ARN}"],
    },
    "high_latency_p99": {
        "metric": "TargetResponseTime",
        "threshold": 2.0,  # 2 seconds
        "evaluation_periods": 3,
        "period": 60,
        "statistic": "p99",
        "comparison": "GreaterThanThreshold",
    },
    "low_healthy_hosts": {
        "metric": "HealthyHostCount",
        "threshold": 2,
        "evaluation_periods": 1,
        "period": 60,
        "comparison": "LessThanThreshold",
    },
    "high_db_connections": {
        "metric": "DatabaseConnections",
        "threshold": 80,  # 80% of max
        "evaluation_periods": 2,
        "period": 60,
        "comparison": "GreaterThanThreshold",
    },
    "high_cpu": {
        "metric": "CPUUtilization",
        "threshold": 80,
        "evaluation_periods": 3,
        "period": 60,
        "comparison": "GreaterThanThreshold",
    },
}
