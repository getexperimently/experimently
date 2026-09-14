# ClickHouse Warehouse Connector

!!! info "Part of the `warehouse` module"
    Warehouse-native analytics is one of the optional modules -- present in the **full profile**, absent from the core one. A core deployment does not serve these routes. See [Modules and profiles](../getting-started/modules.md) for what each profile includes and how to run the full one.

## Why ClickHouse

ClickHouse is an open-source columnar database management system designed for online analytical processing (OLAP). It excels at experiment analytics workloads because:

- **Columnar storage**: Reads only the columns referenced in a query — not full rows — making aggregations on large event tables extremely fast.
- **Vectorised execution**: Processes data in SIMD-friendly batches, routinely achieving billions-of-rows-per-second throughput on a single node.
- **Native aggregation functions**: `count()`, `countIf()`, `avg()`, `quantile()` are first-class, highly optimised citizens, ideal for variant-level metric computation.
- **ClickHouse Cloud**: Fully managed, serverless, auto-scaling option with a generous free tier — ideal for getting started without infrastructure overhead.
- **HTTP interface**: The `clickhouse-connect` library uses the ClickHouse HTTP API (port 8123 / 8443 for TLS), so no native driver installation is required.

## Installation

The connector is bundled with the platform. No additional setup is required beyond the normal `pip install -r requirements.txt`.

```bash
# clickhouse-connect is already in requirements.txt
pip install clickhouse-connect==0.7.0
```

## Configuration

Add the following environment variables (or set them in your `.env` file):

| Variable | Default | Description |
|---|---|---|
| `CLICKHOUSE_HOST` | `localhost` | ClickHouse server hostname |
| `CLICKHOUSE_PORT` | `8123` | HTTP port (`8443` for HTTPS/TLS) |
| `CLICKHOUSE_DATABASE` | `default` | Database name |
| `CLICKHOUSE_USER` | `default` | Username |
| `CLICKHOUSE_PASSWORD` | `""` | Password (empty for no-auth local dev) |
| `CLICKHOUSE_SECURE` | `false` | Set to `true` to use HTTPS |
| `CLICKHOUSE_TIMEOUT_SECONDS` | `30` | Connect/query timeout in seconds |

## ClickHouse Cloud Setup

1. Create a free account at [clickhouse.cloud](https://clickhouse.cloud).
2. Provision a new service and note the **hostname**, **username**, and **password** from the connection dialog.
3. The default port for ClickHouse Cloud is `8443` (HTTPS). Set `CLICKHOUSE_SECURE=true`.
4. Allowlist the IP address(es) of your application servers in the ClickHouse Cloud firewall settings.

```bash
export CLICKHOUSE_HOST=abc123.us-east-1.aws.clickhouse.cloud
export CLICKHOUSE_PORT=8443
export CLICKHOUSE_DATABASE=default
export CLICKHOUSE_USER=default
export CLICKHOUSE_PASSWORD=your-password-here
export CLICKHOUSE_SECURE=true
```

## API Endpoints

All endpoints require **DEVELOPER** or **ADMIN** role. Credentials are supplied per-request and never persisted.

### POST /api/v1/warehouse/clickhouse/test-connection

Test connectivity to a ClickHouse server.

**Request body:**
```json
{
  "host": "ch.example.com",
  "port": 8123,
  "database": "analytics",
  "user": "default",
  "password": "secret",
  "secure": false,
  "timeout": 30
}
```

**Response (200):**
```json
{ "status": "connected" }
```

**Response (503):** Server unreachable or credentials rejected.

### POST /api/v1/warehouse/clickhouse/query

Execute a read-only SELECT query. DML/DDL is rejected with HTTP 400.

**Request body:**
```json
{
  "host": "ch.example.com",
  "port": 8123,
  "database": "analytics",
  "user": "default",
  "password": "secret",
  "sql": "SELECT variant_name, count() AS n FROM experiment_events WHERE experiment_id = {eid:String} GROUP BY variant_name",
  "timeout": 30
}
```

**Response (200):**
```json
{
  "rows": [
    { "variant_name": "control", "n": 10000 },
    { "variant_name": "treatment", "n": 9850 }
  ],
  "row_count": 2
}
```

### GET /api/v1/warehouse/clickhouse/metrics/experiments/{experiment_id}

Fetch per-variant conversion metrics.

**Query params:** `host`, `port`, `database`, `user`, `password`, `secure`, `timeout`

**Response (200):**
```json
{
  "metrics": {
    "control":   { "mean": 0.12, "count": 10000, "conversions": 1200 },
    "treatment": { "mean": 0.148, "count": 9850, "conversions": 1459 }
  }
}
```

### GET /api/v1/warehouse/clickhouse/metrics/flags/{flag_id}

Fetch per-group error-rate metrics for a feature flag.

**Response (200):**
```json
{
  "metrics": {
    "enabled":  { "error_rate": 0.005, "requests": 50000, "errors": 250 },
    "disabled": { "error_rate": 0.004, "requests": 48000, "errors": 192 }
  }
}
```

## SQL Query Patterns for Experiment Metrics

ClickHouse uses named `{param:Type}` placeholders for parameterised queries, which prevent SQL injection at the protocol level.

### Variant-level conversion metrics

```sql
SELECT
    variant_name,
    count() AS count,
    avg(metric_value) AS mean,
    countIf(converted = 1) AS conversions
FROM experiment_events
WHERE experiment_id = {experiment_id:String}
GROUP BY variant_name
```

### Percentile latency by variant

```sql
SELECT
    variant_name,
    quantile(0.50)(response_ms) AS p50,
    quantile(0.95)(response_ms) AS p95,
    quantile(0.99)(response_ms) AS p99
FROM experiment_events
WHERE experiment_id = {experiment_id:String}
GROUP BY variant_name
```

### Daily conversion trend

```sql
SELECT
    toDate(event_timestamp) AS day,
    variant_name,
    count() AS events,
    sum(converted) AS conversions
FROM experiment_events
WHERE experiment_id = {experiment_id:String}
  AND event_timestamp >= now() - INTERVAL 30 DAY
GROUP BY day, variant_name
ORDER BY day, variant_name
```

## Schema Requirements

The `get_experiment_metrics()` helper expects a table named `experiment_events` with at least:

| Column | Type | Description |
|---|---|---|
| `experiment_id` | String | Experiment identifier |
| `variant_name` | String | Variant label (e.g., `control`, `treatment`) |
| `metric_value` | Float64 | Primary metric observation |
| `converted` | UInt8 | 1 if the user converted, 0 otherwise |

The `get_feature_flag_metrics()` helper expects `feature_flag_events` with:

| Column | Type | Description |
|---|---|---|
| `flag_id` | String | Feature flag identifier |
| `group_key` | String | Group label (e.g., `enabled`, `disabled`) |
| `request_count` | UInt64 | Number of requests in this row |
| `error_count` | UInt64 | Number of errored requests |

## Troubleshooting

**Connection refused on port 8123**
- Confirm ClickHouse is running: `clickhouse-client --query "SELECT 1"`
- Check firewall / security group rules allow port 8123 (or 8443 for TLS)

**Authentication failed**
- Verify username / password in `users.xml` or via ClickHouse Cloud console
- ClickHouse default user has no password in development configs; set one for production

**Query times out**
- Increase `CLICKHOUSE_TIMEOUT_SECONDS` or set a longer `max_execution_time` in ClickHouse settings
- Add indexes (`ORDER BY` / `PARTITION BY`) to your experiment tables

**`Table 'database.experiment_events' doesn't exist`**
- Create the required tables following the schema above before using the metrics endpoints
