# Monitoring and Observability

The platform integrates with AWS CloudWatch, Prometheus, and structlog to provide comprehensive visibility into API performance, Lambda execution, database health, and application behavior.

---

## CloudWatch Dashboards

### Deploying Dashboards

```bash
cd infrastructure/cloudwatch
./deploy-dashboards.sh
```

This script creates CloudFormation stacks for the pre-built dashboards:

| Dashboard | Contents |
|-----------|---------|
| **API Performance** | Request rate, p50/p95/p99 latency, error rate, active connections |
| **Lambda Functions** | Invocation count, error rate, duration, throttle count (per function) |
| **Database** | Aurora CPU, IOPS, connection count, replica lag |
| **DynamoDB** | Read/write capacity units, throttled requests, system errors |
| **Kinesis** | GetRecords iterator age (processing lag), incoming records rate |

### Creating Log Groups

Log groups must be created before the application starts writing logs:

```bash
aws logs create-log-group --log-group-name /experimentation-platform/api
aws logs create-log-group --log-group-name /experimentation-platform/services
aws logs create-log-group --log-group-name /experimentation-platform/errors
aws logs create-log-group --log-group-name /experimentation-platform/lambda
```

Set retention to 90 days for cost control:

```bash
aws logs put-retention-policy \
  --log-group-name /experimentation-platform/api \
  --retention-in-days 90
```

---

## Prometheus Metrics

The API exposes a Prometheus-compatible metrics endpoint:

```bash
GET /metrics
```

No authentication is required (the endpoint should be restricted at the network level in production — allow access only from your Prometheus scraper's IP range).

### Key Metrics Exported

| Metric | Type | Description |
|--------|------|-------------|
| `http_requests_total` | Counter | Total HTTP requests by method, path, and status code |
| `http_request_duration_seconds` | Histogram | Request latency (p50, p95, p99 percentiles) |
| `http_requests_in_progress` | Gauge | Currently active requests |
| `experiment_assignments_total` | Counter | Variant assignments by experiment and variant |
| `feature_flag_evaluations_total` | Counter | Flag evaluations by flag key and result |
| `events_tracked_total` | Counter | Tracked events by type |
| `db_query_duration_seconds` | Histogram | Database query latency |
| `cache_hits_total` | Counter | Redis cache hits |
| `cache_misses_total` | Counter | Redis cache misses |
| `rate_limit_redis_fallback_active` | Gauge | 1 while this process counts rate limits per process because Redis is unavailable; 0 while it counts them in Redis |
| `rate_limit_redis_fallbacks_total` | Counter | Times this process switched rate limiting from Redis to per-process counting |

Each API process exports its own values: with more than one worker per container, a scrape sees
the worker that answered it. While `rate_limit_redis_fallback_active` is 1, per-IP rate limits are
multiplied by the number of API processes; the limiter tries Redis again every 30 s.

### Sample Prometheus Scrape Config

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'experimentation-api'
    static_configs:
      - targets: ['your-api.example.com:8000']
    metrics_path: '/metrics'
    scheme: 'https'
    scrape_interval: 30s
```

---

## Structured Logging (structlog)

The API uses **structlog** for JSON-formatted structured logs. Every log entry includes contextual fields for easy filtering and correlation.

### Log Format

```json
{
  "timestamp": "2026-03-02T14:32:00.123Z",
  "level": "info",
  "logger": "app.api.experiments",
  "request_id": "req-uuid-here",
  "user_id": "user-uuid-here",
  "action": "experiment.create",
  "experiment_id": "exp-uuid-here",
  "duration_ms": 42,
  "status_code": 201
}
```

### Standard Fields

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 UTC timestamp |
| `level` | `debug`, `info`, `warning`, `error`, `critical` |
| `logger` | Module path of the logging component |
| `request_id` | Unique identifier for the HTTP request (correlates all log entries for one request) |
| `user_id` | Authenticated user UUID (if applicable) |
| `action` | Resource and action (e.g., `experiment.start`, `feature_flag.toggle`) |
| `duration_ms` | Time taken for the operation in milliseconds |
| `status_code` | HTTP response status code |

### Querying Logs in CloudWatch Insights

```sql
-- Find slow API requests (> 1000ms)
fields timestamp, request_id, action, duration_ms, status_code
| filter duration_ms > 1000
| sort duration_ms desc
| limit 20

-- Find error requests in the last hour
fields timestamp, request_id, user_id, action, @message
| filter status_code >= 500
| stats count() as error_count by action
| sort error_count desc

-- Trace a specific request
fields @timestamp, level, action, @message
| filter request_id = "req-uuid-here"
| sort @timestamp asc
```

---

## CloudWatch Alarms

Set up alarms to notify you when key thresholds are breached. Requires an SNS topic for notifications:

Create SNS topic:

```bash
aws sns create-topic --name experimentation-alerts
aws sns subscribe --topic-arn arn:aws:sns:us-east-1:123456789:experimentation-alerts \
  --protocol email --notification-endpoint oncall@yourcompany.com
```

### Recommended Alarms

p99 API latency > 1 second:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "ExperimentationAPI-HighLatency" \
  --metric-name "http_request_duration_seconds" \
  --namespace "ExperimentationPlatform" \
  --extended-statistic "p99" \
  --threshold 1.0 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 3 \
  --period 60 \
  --alarm-actions arn:aws:sns:us-east-1:123456789:experimentation-alerts
```

Error rate > 1%:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "ExperimentationAPI-HighErrorRate" \
  --metric-name "http_request_5xx_total" \
  --namespace "ExperimentationPlatform" \
  --statistic "Sum" \
  --threshold 100 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --period 60 \
  --alarm-actions arn:aws:sns:us-east-1:123456789:experimentation-alerts
```

Lambda DLQ messages > 0 (indicates failed events not being processed):

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "EventProcessorDLQ-Messages" \
  --metric-name "ApproximateNumberOfMessagesVisible" \
  --namespace "AWS/SQS" \
  --dimensions Name=QueueName,Value=experimentation-dlq \
  --statistic "Sum" \
  --threshold 0 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1 \
  --period 60 \
  --alarm-actions arn:aws:sns:us-east-1:123456789:experimentation-alerts
```

---

## Distributed Tracing (AWS X-Ray)

The platform integrates with **AWS X-Ray** for distributed tracing across the API, Lambda functions, and DynamoDB calls.

### Enabling X-Ray

Set the environment variable:

```bash
AWS_XRAY_DAEMON_ADDRESS=xray-daemon:2000
```

The ECS task definition includes the X-Ray daemon as a sidecar container. Traces are automatically captured for:

- All incoming HTTP requests
- DynamoDB read and write operations
- Lambda invocations
- External HTTP calls (Slack, SendGrid, GitHub, Salesforce)

### Viewing Traces

1. Open the **AWS X-Ray Console**
2. Navigate to **Traces** and filter by service name: `experimentation-api`
3. Use the Service Map to visualize dependencies
4. Click any trace to see the full execution timeline and identify bottlenecks

---

## Health Check

The API answers `GET /health` without authentication, for load balancers and
monitoring. It is the readiness probe, the same as `GET /health/ready`:

```bash
curl -s localhost:8000/health
```

Outside production it reports each check with its detail:

```json
{
  "status": "healthy",
  "timestamp": "2026-10-07T19:42:43.499684+00:00",
  "profile": "core",
  "version": "0.26.3",
  "environment": "development",
  "checks": {
    "database": {"status": "healthy", "latency_ms": 2.13},
    "redis": {"status": "healthy", "latency_ms": 0.87},
    "disk": {"status": "healthy", "free_gb": 41.7},
    "modules": {"status": "healthy", "profile": "core"}
  }
}
```

With `ENVIRONMENT=production` it leaves out `version`, `environment` and every
detail except each check's `status`:

```json
{
  "status": "healthy",
  "timestamp": "2026-10-07T19:43:19.062038+00:00",
  "profile": "core",
  "checks": {
    "database": {"status": "healthy"},
    "redis": {"status": "healthy"},
    "disk": {"status": "healthy"},
    "modules": {"status": "healthy"}
  }
}
```

It answers `503 Service Unavailable` with `"status": "unhealthy"` when
PostgreSQL does not answer, when Redis does not answer and `REDIS_REQUIRED=true`,
or when the disk check fails. A failed check names the error's type outside
production:

```json
{
  "status": "unhealthy",
  "timestamp": "2026-10-07T19:42:54.171329+00:00",
  "profile": "core",
  "version": "0.26.3",
  "environment": "development",
  "checks": {
    "database": {"status": "unhealthy", "error": "OperationalError"},
    "redis": {"status": "unhealthy", "error": "ConnectionError"},
    "disk": {"status": "healthy", "free_gb": 41.7},
    "modules": {"status": "healthy", "profile": "core"}
  }
}
```

Without `REDIS_REQUIRED=true`, a Redis that does not answer is reported as
`unhealthy` under `checks` while the response stays `200` and `"healthy"`. Free
disk space below 1 GB is reported as `"low"` and does not fail the probe.
`GET /health/live` is the liveness probe: it answers `200` whenever the process
is up and checks neither PostgreSQL nor Redis.

The ALB health check targets `GET /health` with a 5-second timeout and a 2/3 healthy/unhealthy threshold. Tasks that fail health checks are automatically replaced by ECS.

---

## Key Metrics to Watch

These are the most important operational signals:

| Metric | Healthy Range | Action if Breached |
|--------|---------------|-------------------|
| API p99 latency | < 1s | Investigate slow queries, check DynamoDB throttling |
| API error rate (5xx) | < 0.1% | Check application logs for exceptions |
| Database connection pool | < 80% utilized | Increase pool size or scale Aurora |
| Redis cache hit rate | > 85% | Investigate cache key patterns, increase TTL |
| Kinesis iterator age | < 60s | Scale Lambda concurrency, check for processing errors |
| Event Processor DLQ | 0 messages | Process DLQ messages manually, fix poison pill events |
| Lambda cold start rate | < 5% | Keep functions warm with scheduled invocations if needed |
| Safety rollback frequency | < 1/week | Investigate flag quality and error rate thresholds |
