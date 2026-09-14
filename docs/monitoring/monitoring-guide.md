# Monitoring Guide — Experimently (EP-013)

This guide covers all monitoring components introduced by EP-013:
Prometheus metrics, structured logging, request tracing, CloudWatch
dashboards, and alerts.

---

## Table of Contents

1. [Available Prometheus Metrics](#1-available-prometheus-metrics)
2. [Adding New Metrics](#2-adding-new-metrics)
3. [Structured Logging](#3-structured-logging)
4. [Request Tracing (X-Request-ID)](#4-request-tracing-x-request-id)
5. [CloudWatch Dashboard Sections](#5-cloudwatch-dashboard-sections)
6. [Setting Up Alerts](#6-setting-up-alerts)
7. [Log Format and CloudWatch Insights Queries](#7-log-format-and-cloudwatch-insights-queries)
8. [Local Development](#8-local-development)
9. [Health Check Endpoint](#9-health-check-endpoint)

---

## 1. Available Prometheus Metrics

All metrics are defined as a single source of truth in
`backend/app/core/monitoring_config.py` (`METRICS_REGISTRY`) and registered
as Prometheus objects in `backend/app/core/metrics.py`.

| Metric name | Type | Labels | Description |
|---|---|---|---|
| `http_requests_total` | Counter | `method`, `endpoint`, `status_code` | Total HTTP requests received |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint` | Request duration — provides p50/p95/p99 latency |
| `http_request_size_bytes` | Histogram | `method`, `endpoint` | Size of incoming request bodies |
| `db_query_duration_seconds` | Histogram | `operation`, `table` | Database query duration by operation type |
| `experiment_assignments_total` | Counter | `experiment_id`, `variant_id` | Experiment variant assignments |
| `events_tracked_total` | Counter | `event_type` | Tracked conversion / custom events |
| `feature_flag_evaluations_total` | Counter | `flag_key`, `result` | Feature flag evaluation calls and their results |
| `cache_hits_total` | Counter | `cache_type` | Cache hits (Redis, LRU, etc.) |
| `cache_misses_total` | Counter | `cache_type` | Cache misses |
| `active_experiments_gauge` | Gauge | _(none)_ | Number of experiments currently in ACTIVE state |

### Recording metrics from application code

Use the helper functions from `backend/app/core/metrics.py`:

```python
from backend.app.core.metrics import (
    record_request,
    record_experiment_assignment,
    record_event_tracked,
    record_flag_evaluation,
    record_cache_hit,
    record_cache_miss,
    update_active_experiments,
)

# HTTP request (called automatically by PrometheusMetricsMiddleware)
record_request("GET", "/api/v1/experiments", 200, 0.042)

# Business events
record_experiment_assignment("exp-abc", "variant-B")
record_flag_evaluation("dark-mode", "enabled")
record_cache_hit("redis")
update_active_experiments(17)
```

---

## 2. Adding New Metrics

1. **Add a `MetricSpec` entry** to `METRICS_REGISTRY` in
   `backend/app/core/monitoring_config.py`:

   ```python
   "my_new_counter_total": MetricSpec(
       name="my_new_counter_total",
       description="Counts something important",
       labels=["label_one", "label_two"],
   ),
   ```

2. **Register the Prometheus object** in `backend/app/core/metrics.py`:

   ```python
   from prometheus_client import Counter

   my_new_counter_total: Counter = Counter(
       "my_new_counter_total",
       "Counts something important",
       ["label_one", "label_two"],
   )
   ```

3. **Add a helper function** in `backend/app/core/metrics.py`:

   ```python
   def record_my_event(label_one: str, label_two: str) -> None:
       my_new_counter_total.labels(
           label_one=label_one,
           label_two=label_two,
       ).inc()
   ```

4. **Write a test** in `backend/tests/unit/core/test_metrics.py` following
   the existing `test_record_*` pattern.

5. **Optionally add a CloudWatch alarm** for it in `CLOUDWATCH_ALARMS` inside
   `monitoring_config.py` (see section 6).

---

## 3. Structured Logging

The platform uses [structlog](https://www.structlog.org/) for structured,
context-aware logging configured in `backend/app/core/logger.py`.

### Configuration

`configure_logging()` is called once at startup in `backend/app/main.py`.

| Parameter | Default | Description |
|---|---|---|
| `log_level` | `"INFO"` | Python log level name (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `json_logs` | `True` (non-dev) | `True` → JSON output for CloudWatch; `False` → colourised dev output |
| `service_name` | `"experimentation-platform"` | Added to every log event as `service` |

Environment variables that control behaviour at startup:

```bash
LOG_LEVEL=DEBUG      # override log level
APP_ENV=dev          # triggers human-readable console output
```

### Emitting structured log events

```python
from backend.app.core.logger import get_logger

logger = get_logger(__name__)

logger.info("experiment_started", experiment_id="exp-123", user_id="user-456")
logger.error("db_query_failed", table="experiments", error=str(exc))
```

### Binding per-request context

Use `bind_log_context` to add fields that appear on **every** log line
within a request (automatically done by `RequestIDMiddleware`):

```python
from backend.app.core.logger import bind_log_context

bind_log_context(user_id="user-789", tenant_id="acme")
# All subsequent logger.info/error calls in this request will include
# user_id and tenant_id automatically.
```

### JSON log shape (production)

```json
{
  "event": "experiment_started",
  "level": "info",
  "timestamp": "2026-03-01T12:34:56.789+00:00",
  "logger": "backend.app.services.experiment_service",
  "service": "experimentation-platform",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "path": "/api/v1/experiments",
  "method": "POST",
  "experiment_id": "exp-123"
}
```

---

## 4. Request Tracing (X-Request-ID)

`RequestIDMiddleware` (`backend/app/middleware/request_id_middleware.py`)
ensures every request has a unique `X-Request-ID` header.

- If the incoming request contains `X-Request-ID`, that value is reused
  (enables end-to-end tracing from upstream proxies or the frontend).
- Otherwise a new UUID4 is generated.
- The ID is added to the response headers as `X-Request-ID` and bound
  into the structured-logging context for the duration of the request.

**Client usage:**

```bash
curl -H "X-Request-ID: my-trace-id-123" https://api.example.com/api/v1/health
# Response will include: X-Request-ID: my-trace-id-123
```

---

## 5. CloudWatch Dashboard Sections

The `MonitoringStack` CDK construct
(`infrastructure/cdk/stacks/monitoring_stack.py`) provisions two dashboards:

### `experimentation-platform` (infrastructure metrics)

| Widget | Metrics |
|---|---|
| API Gateway | Request count, latency |
| Lambda Functions | Invocations, duration (Assignment, EventProcessor, FeatureFlag) |
| DynamoDB | Read/Write capacity units, throttling |
| Kinesis | Incoming records/bytes, iterator age |
| RDS Aurora | CPU, DB connections, free memory, read/write latency |
| ElastiCache Redis | CPU, current connections, cache hits/misses |

### `experimentation-application-metrics` (application metrics)

| Widget | Source |
|---|---|
| Experiment Metrics | Active experiments, creation rate, flag evaluations, assignments |
| Event Processing | Events processed, latency, errors |
| HTTP Request Rate & Error Rate | `http_requests_total` (Prometheus) |
| Request Latency p50/p95/p99 | `http_request_duration_seconds` (Prometheus) |
| Active Experiments | `active_experiments_gauge` (Prometheus) |
| Cache Hit Ratio | `cache_hits_total` / `cache_misses_total` (Prometheus) |
| Feature Flag Evaluations | `feature_flag_evaluations_total` (Prometheus) |

---

## 6. Setting Up Alerts

### Existing alarms (infrastructure)

| Alarm | Trigger |
|---|---|
| `ExperimentationApi5xxErrors` | API Gateway 5xx count >= 5 in 1 min |
| `AssignmentLambdaErrors` | Lambda errors >= 5 in 5 min |
| `AssignmentsTableThrottling` | DynamoDB throttled requests >= 10 in 5 min |
| `AuroraHighCPU` | Aurora CPU >= 80% for 3 consecutive periods |
| `KinesisProcessingDelay` | Iterator age > 5 min for 3 periods |
| `AssignmentLambdaDuration` | p95 duration > 5 s for 3 periods |
| `RedisHighCPU` | Redis CPU >= 80% for 3 periods |

### EP-013 application alarms

| Alarm | Trigger |
|---|---|
| `AppHighErrorRate` | 5xx requests > 10 per minute for 2 evaluation periods |
| `AppHighLatencyP99` | p99 latency > 2 s for 3 consecutive minutes |
| `AppHighActiveExperiments` | active experiments gauge > 100 |

### Adding a new alarm

1. Add an entry to `CLOUDWATCH_ALARMS` in
   `backend/app/core/monitoring_config.py` (used by documentation and future
   tooling):

   ```python
   "my_new_alarm": {
       "metric": "MyMetricName",
       "threshold": 50,
       "evaluation_periods": 2,
       "period": 60,
       "comparison": "GreaterThanThreshold",
   },
   ```

2. Add the corresponding CDK `cloudwatch.Alarm` resource in
   `infrastructure/cdk/stacks/monitoring_stack.py` following the pattern
   of the existing EP-013 alarms at the bottom of `__init__`.

3. Run `cdk diff` and `cdk deploy ExperimentationMonitoringStack` to apply.

### SNS topic

All alarms send notifications to the `experimentation-alerts` SNS topic.
To add a new subscriber (email, PagerDuty webhook, etc.) update the
`alerts_topic.add_subscription(...)` call in `monitoring_stack.py`.

---

## 7. Log Format and CloudWatch Insights Queries

### Log group

Application logs are written to:
```
/experimentation/application
```

Retention: **2 weeks** (configurable via `retention` in `monitoring_stack.py`).

### Useful CloudWatch Insights queries

**Count errors by endpoint in the last hour:**

```sql
fields @timestamp, path, method, level, event
| filter level = "error"
| stats count() as error_count by path
| sort error_count desc
| limit 20
```

**P99 latency per endpoint (last 15 min):**

```sql
fields @timestamp, path, duration_seconds
| filter ispresent(duration_seconds)
| stats pct(duration_seconds, 99) as p99 by path
| sort p99 desc
```

**All log lines for a specific request_id:**

```sql
fields @timestamp, level, event, @message
| filter request_id = "550e8400-e29b-41d4-a716-446655440000"
| sort @timestamp asc
```

**Feature flag evaluation results:**

```sql
fields @timestamp, flag_key, result, request_id
| filter event = "flag_evaluated"
| stats count() as evals by flag_key, result
| sort evals desc
```

---

## 8. Local Development

### Viewing Prometheus metrics

Start the dev server, then:

```bash
curl http://localhost:8000/metrics
```

Example output:

```text
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{endpoint="/api/v1/experiments",method="GET",status_code="200"} 42.0
http_requests_total{endpoint="/health",method="GET",status_code="200"} 7.0
...
# HELP active_experiments_gauge Number of currently active experiments
# TYPE active_experiments_gauge gauge
active_experiments_gauge 17.0
```

### Viewing structured logs

For human-readable dev output, set `APP_ENV=dev`:

```bash
APP_ENV=dev uvicorn backend.app.main:app --reload
```

For JSON output (mimics production):

```bash
APP_ENV=staging uvicorn backend.app.main:app --reload
```

### Running the monitoring tests

```bash
source venv/bin/activate
export APP_ENV=test TESTING=true

# All monitoring / logging tests
python -m pytest \
  backend/tests/unit/core/test_metrics.py \
  backend/tests/unit/core/test_logger.py \
  backend/tests/unit/middleware/test_metrics_middleware.py \
  backend/tests/unit/middleware/test_request_id_middleware.py \
  -v
```

---

## 9. Health Check Endpoint

`GET /health` returns a detailed JSON payload:

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "production",
  "timestamp": "2026-03-01T12:00:00+00:00",
  "checks": {
    "database": {"status": "healthy", "latency_ms": 2.3},
    "redis":    {"status": "healthy", "latency_ms": 0.8},
    "disk":     {"status": "healthy", "free_gb": 45.2}
  }
}
```

| Field | Values |
|---|---|
| `status` | `healthy` or `unhealthy` |
| `checks[x].status` | `healthy`, `unhealthy`, or `low` (disk < 1 GB free) |

HTTP status: **200** when all checks pass, **503** when any check fails.

This endpoint is suitable for use as:

- **ALB / NLB health-check target** (check for HTTP 200)
- **ECS task health-check**
- **Kubernetes liveness / readiness probe**
