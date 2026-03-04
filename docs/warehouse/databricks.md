# Databricks Warehouse Connector (EP-041)

Connect the experimentation platform directly to your Databricks SQL warehouse
to query experiment assignments, conversion events, and feature flag metrics
without any ETL pipelines.

---

## Installation

The connector uses the `databricks-sql-connector` Python package (v3.x), which
is included in the platform requirements:

```bash
pip install databricks-sql-connector==3.3.0
```

No additional AWS or cloud-provider credentials are required — only a Databricks
personal access token (PAT) or service-principal token.

---

## Configuration Reference

Add the following environment variables to configure a default Databricks
connection (used by background jobs and optional pre-configured endpoints):

| Variable                        | Default     | Description                                               |
|---------------------------------|-------------|-----------------------------------------------------------|
| `DATABRICKS_HOST`               | `""`        | Databricks workspace hostname (e.g. `myws.azuredatabricks.net`) |
| `DATABRICKS_HTTP_PATH`          | `""`        | SQL warehouse HTTP path (e.g. `/sql/1.0/warehouses/abc`) |
| `DATABRICKS_TOKEN`              | `""`        | Personal access token or service-principal token          |
| `DATABRICKS_CATALOG`            | `"main"`    | Unity Catalog catalog name                                |
| `DATABRICKS_SCHEMA`             | `"default"` | Schema inside the catalog                                 |
| `DATABRICKS_TIMEOUT_SECONDS`    | `30`        | Query / socket timeout in seconds                         |

Set them in your `.env` file or export them as shell variables:

```bash
export DATABRICKS_HOST="myworkspace.azuredatabricks.net"
export DATABRICKS_HTTP_PATH="/sql/1.0/warehouses/abc123ef"
export DATABRICKS_TOKEN="dapi_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export DATABRICKS_CATALOG="analytics"
export DATABRICKS_SCHEMA="experiments"
```

---

## Python Usage

### Basic connection and query

```python
from backend.app.services.databricks_connector import DatabricksConnector

with DatabricksConnector(
    host="myworkspace.azuredatabricks.net",
    http_path="/sql/1.0/warehouses/abc123ef",
    access_token="dapi_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    catalog="analytics",
    schema="experiments",
) as conn:
    rows = conn.execute_query(
        "SELECT user_id, variant_id FROM assignments WHERE experiment_id = ?",
        params=["exp-001"],
    )
    for row in rows:
        print(row["user_id"], row["variant_id"])
```

### Test connection

```python
from backend.app.services.databricks_connector import DatabricksConnector

connector = DatabricksConnector(
    host="myworkspace.azuredatabricks.net",
    http_path="/sql/1.0/warehouses/abc123ef",
    access_token="dapi_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
)

if connector.test_connection():
    print("Databricks is reachable.")
else:
    print("Connection failed.")
```

### Fetch experiment metrics

```python
from backend.app.services.databricks_connector import DatabricksConnector

with DatabricksConnector(
    host="myworkspace.azuredatabricks.net",
    http_path="/sql/1.0/warehouses/abc123ef",
    access_token="dapi_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
) as conn:
    metrics = conn.get_experiment_metrics("exp-001")
    for variant_id, stats in metrics.items():
        print(
            f"{variant_id}: mean={stats['mean']:.3f}, "
            f"n={stats['count']}, conversions={stats['conversions']}"
        )
```

**Returns:**
```json
{
  "control":   {"mean": 0.12, "count": 1000, "conversions": 120},
  "treatment": {"mean": 0.148, "count": 980,  "conversions": 145}
}
```

### Fetch feature flag metrics

```python
from backend.app.services.databricks_connector import DatabricksConnector

with DatabricksConnector(
    host="myworkspace.azuredatabricks.net",
    http_path="/sql/1.0/warehouses/abc123ef",
    access_token="dapi_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
) as conn:
    metrics = conn.get_feature_flag_metrics("checkout-v2")
    for group, stats in metrics.items():
        print(
            f"{group}: error_rate={stats['error_rate']:.2%}, "
            f"requests={stats['requests']}"
        )
```

---

## REST API Usage

All endpoints require **DEVELOPER** or **ADMIN** role.
Credentials are supplied per-request and are never persisted server-side.

### POST /api/v1/warehouse/databricks/test-connection

Verify connectivity to a Databricks SQL warehouse.

**Request:**
```json
{
  "host": "myworkspace.azuredatabricks.net",
  "http_path": "/sql/1.0/warehouses/abc123ef",
  "access_token": "dapi_xxxx"
}
```

**Response (200 OK):**
```json
{"status": "connected"}
```

**Response (503 Service Unavailable):**
```json
{"detail": "Databricks connection failed: warehouse unreachable"}
```

---

### POST /api/v1/warehouse/databricks/query

Execute a read-only SQL query.  DML / DDL statements (DROP, DELETE, INSERT,
UPDATE, TRUNCATE, ALTER, CREATE, GRANT, REVOKE, MERGE) are rejected with
HTTP 400.

**Request:**
```json
{
  "host": "myworkspace.azuredatabricks.net",
  "http_path": "/sql/1.0/warehouses/abc123ef",
  "access_token": "dapi_xxxx",
  "sql": "SELECT variant_id, COUNT(*) AS users FROM assignments WHERE experiment_id = 'exp-001' GROUP BY variant_id"
}
```

**Response (200 OK):**
```json
{
  "rows": [
    {"variant_id": "control",   "users": 1000},
    {"variant_id": "treatment", "users": 980}
  ],
  "row_count": 2
}
```

**Response (400 Bad Request — unsafe SQL):**
```json
{"detail": "SQL statement not allowed (contains DML/DDL keywords): 'DROP TABLE ...'"}
```

---

### GET /api/v1/warehouse/databricks/metrics/experiments/{experiment_id}

Fetch per-variant conversion metrics for an experiment.

**Query parameters (required):**
- `host` — Databricks workspace hostname
- `http_path` — SQL warehouse HTTP path
- `access_token` — Personal access token

**Response (200 OK):**
```json
{
  "metrics": {
    "control":   {"mean": 0.12,  "count": 1000, "conversions": 120},
    "treatment": {"mean": 0.148, "count": 980,  "conversions": 145}
  }
}
```

---

### GET /api/v1/warehouse/databricks/metrics/flags/{flag_id}

Fetch per-group error-rate metrics for a feature flag.

**Response (200 OK):**
```json
{
  "metrics": {
    "enabled":  {"error_rate": 0.010, "requests": 5000, "errors": 50},
    "disabled": {"error_rate": 0.011, "requests": 4800, "errors": 53}
  }
}
```

---

## SQL Query Patterns for Experiment Metrics

### Assignment distribution query

```sql
SELECT
  variant_id,
  COUNT(DISTINCT user_id) AS sample_size
FROM analytics.experiments.experiment_assignments
WHERE experiment_id = 'exp-001'
GROUP BY variant_id
```

### Conversion funnel query

```sql
WITH assignments AS (
  SELECT user_id, variant_id
  FROM analytics.experiments.experiment_assignments
  WHERE experiment_id = 'exp-001'
),
events AS (
  SELECT user_id, event_type
  FROM analytics.events.user_events
  WHERE event_type = 'purchase'
    AND occurred_at BETWEEN '2026-01-01' AND '2026-01-31'
)
SELECT
  a.variant_id,
  COUNT(DISTINCT a.user_id)                                       AS sample_size,
  SUM(CASE WHEN e.event_type IS NOT NULL THEN 1 ELSE 0 END)       AS conversions,
  SUM(CASE WHEN e.event_type IS NOT NULL THEN 1 ELSE 0 END) * 1.0
    / COUNT(DISTINCT a.user_id)                                   AS conversion_rate
FROM assignments a
LEFT JOIN events e ON a.user_id = e.user_id
GROUP BY a.variant_id
```

### Feature flag error-rate query

```sql
SELECT
  group_key,
  SUM(request_count) AS requests,
  SUM(error_count)   AS errors,
  SUM(error_count) * 1.0 / NULLIF(SUM(request_count), 0) AS error_rate
FROM analytics.feature_flags.flag_events
WHERE flag_id = 'checkout-v2'
  AND event_date >= CURRENT_DATE - INTERVAL 7 DAYS
GROUP BY group_key
```

---

## Security

- **Read-only enforcement:** The connector validates all SQL before execution.
  Any statement containing `DROP`, `DELETE`, `INSERT`, `UPDATE`, `TRUNCATE`,
  `ALTER`, `CREATE`, `GRANT`, `REVOKE`, or `MERGE` is rejected with
  `DatabricksQueryError`.
- **Parameterised queries:** Caller-supplied values (e.g. experiment IDs, flag IDs)
  are always passed as cursor parameters (`?` placeholders), never interpolated
  into the SQL string.
- **No credential persistence:** Access tokens are accepted per-request and are
  never written to the database, logs, or API responses.
- **Role-based access:** All endpoints require `DEVELOPER` or `ADMIN` role.
  `VIEWER` and `ANALYST` roles receive `HTTP 403`.

---

## Troubleshooting

### "Connection refused" / 503

- Verify `host` is correct and includes no protocol prefix (use
  `myws.azuredatabricks.net`, not `https://myws.azuredatabricks.net`).
- Confirm the SQL warehouse is running (not paused or terminated).
- Check that `http_path` matches the warehouse's **Connection Details** in the
  Databricks UI.

### "403 Forbidden / Invalid token" → DatabricksAuthError

- Regenerate the personal access token in **User Settings → Access Tokens**.
- For service principals, ensure the token has been granted the **CAN USE**
  permission on the target SQL warehouse.

### Query timeout (DatabricksTimeoutError)

- Increase `timeout_seconds` in the request body or the
  `DATABRICKS_TIMEOUT_SECONDS` environment variable.
- Check the Databricks query history for long-running queries and add
  appropriate filters (date ranges, LIMIT clauses).

### "SQL statement not allowed" (DatabricksQueryError)

- The `execute_query()` endpoint is read-only. Remove DML / DDL keywords from
  your query.
- To load data into Databricks, use Databricks-native ingestion tools or Spark
  jobs rather than this connector.
