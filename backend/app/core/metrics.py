"""
Prometheus metrics registry for the experimentation platform.

All metrics are registered once at module import time. Helper functions
provide a clean, label-safe API for recording measurements throughout
the codebase without callers needing to know the underlying metric type.
"""

from prometheus_client import Counter, Histogram, Gauge

# ---------------------------------------------------------------------------
# HTTP metrics
# ---------------------------------------------------------------------------

http_requests_total: Counter = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds: Histogram = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint", "status_code"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ---------------------------------------------------------------------------
# Business metrics
# ---------------------------------------------------------------------------

experiment_assignments_total: Counter = Counter(
    "experiment_assignments_total",
    "Total experiment assignments",
    ["experiment_id", "variant_id"],
)

events_tracked_total: Counter = Counter(
    "events_tracked_total",
    "Total events tracked",
    ["event_type"],
)

feature_flag_evaluations_total: Counter = Counter(
    "feature_flag_evaluations_total",
    "Total feature flag evaluations",
    ["flag_key", "result"],
)

cache_hits_total: Counter = Counter(
    "cache_hits_total",
    "Cache hits",
    ["cache_type"],
)

cache_misses_total: Counter = Counter(
    "cache_misses_total",
    "Cache misses",
    ["cache_type"],
)

# ---------------------------------------------------------------------------
# Rate limiting metrics
# ---------------------------------------------------------------------------

rate_limit_hits_total: Counter = Counter(
    "rate_limit_hits_total",
    "Total requests checked by the rate limiter",
    ["endpoint"],
)

rate_limit_rejections_total: Counter = Counter(
    "rate_limit_rejections_total",
    "Total requests rejected by the rate limiter (HTTP 429)",
    ["endpoint"],
)

active_experiments_gauge: Gauge = Gauge(
    "active_experiments_gauge",
    "Number of currently active experiments",
)

# ---------------------------------------------------------------------------
# Background scheduler metrics (set by backend.app.core.scheduler_tick)
# ---------------------------------------------------------------------------

scheduler_last_success_timestamp: Gauge = Gauge(
    "scheduler_last_success_timestamp",
    "Unix timestamp of the last successful tick of each background scheduler",
    ["name"],
)

scheduler_tick_duration_seconds: Histogram = Histogram(
    "scheduler_tick_duration_seconds",
    "Wall-clock duration of background scheduler ticks",
    ["name"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 15.0, 60.0, 300.0],
)

scheduler_ticks_total: Counter = Counter(
    "scheduler_ticks_total",
    "Background scheduler ticks by outcome (success, partial, failed, skipped)",
    ["name", "status"],
)

# ---------------------------------------------------------------------------
# Helper recording functions
# ---------------------------------------------------------------------------


def record_request(
    method: str,
    endpoint: str,
    status_code: int,
    duration: float,
) -> None:
    """Record HTTP request counter and duration histogram."""
    http_requests_total.labels(
        method=method,
        endpoint=endpoint,
        status_code=status_code,
    ).inc()
    http_request_duration_seconds.labels(
        method=method,
        endpoint=endpoint,
        status_code=status_code,
    ).observe(duration)


def record_experiment_assignment(experiment_id: str, variant_id: str) -> None:
    """Increment the experiment assignment counter."""
    experiment_assignments_total.labels(
        experiment_id=experiment_id,
        variant_id=variant_id,
    ).inc()


# ``event_type`` on the tracking API is a free-form, client-supplied string
# (``"purchase"``, ``"cta_click"``, ...).  A label must be bounded, so only
# the platform's well-known types are used verbatim; everything else is
# counted as ``custom``.
KNOWN_EVENT_TYPES: frozenset = frozenset(
    {"exposure", "experiment_exposure", "conversion", "click", "page_view", "custom"}
)


def event_type_label(event_type: str) -> str:
    """Map a client-supplied event type to a bounded label value."""
    value = (event_type or "").strip().lower()
    return value if value in KNOWN_EVENT_TYPES else "custom"


def record_event_tracked(event_type: str) -> None:
    """Increment the events-tracked counter (label cardinality is bounded)."""
    events_tracked_total.labels(event_type=event_type_label(event_type)).inc()


def record_flag_evaluation(flag_key: str, result: str) -> None:
    """Increment the feature-flag evaluation counter."""
    feature_flag_evaluations_total.labels(flag_key=flag_key, result=result).inc()


def record_cache_hit(cache_type: str) -> None:
    """Increment the cache-hit counter."""
    cache_hits_total.labels(cache_type=cache_type).inc()


def record_cache_miss(cache_type: str) -> None:
    """Increment the cache-miss counter."""
    cache_misses_total.labels(cache_type=cache_type).inc()


def update_active_experiments(count: int) -> None:
    """Set the active-experiments gauge to the given count."""
    active_experiments_gauge.set(count)


def record_rate_limit_hit(endpoint: str) -> None:
    """Increment the rate-limit hits counter."""
    rate_limit_hits_total.labels(endpoint=endpoint).inc()


def record_rate_limit_rejection(endpoint: str) -> None:
    """Increment the rate-limit rejections counter."""
    rate_limit_rejections_total.labels(endpoint=endpoint).inc()


def record_scheduler_tick(name: str, status: str, duration_seconds: float) -> None:
    """Count a scheduler tick outcome and observe its duration."""
    scheduler_ticks_total.labels(name=name, status=status).inc()
    if status != "skipped":
        scheduler_tick_duration_seconds.labels(name=name).observe(duration_seconds)


def record_scheduler_success(name: str) -> None:
    """Stamp ``scheduler_last_success_timestamp{name}`` with the current time."""
    scheduler_last_success_timestamp.labels(name=name).set_to_current_time()
