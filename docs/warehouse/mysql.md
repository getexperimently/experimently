# MySQL / MariaDB Warehouse Connector

## Overview

The MySQL connector lets you run read-only analytics queries and fetch experiment metrics directly from a MySQL or MariaDB database. It uses `PyMySQL` (pure Python, no native client libraries required) and enforces `DictCursor` so every row is returned as a Python `dict`.

Supported databases:

- MySQL 5.7+ and MySQL 8.0+
- MariaDB 10.3+
- Amazon RDS for MySQL / MariaDB
- Amazon Aurora (MySQL-compatible edition)
- Google Cloud SQL for MySQL
- Azure Database for MySQL

## Installation

`PyMySQL` is already listed in `requirements.txt`:

```bash
# Already included — no manual install needed
pip install PyMySQL==1.1.1
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MYSQL_HOST` | `localhost` | MySQL server hostname |
| `MYSQL_PORT` | `3306` | MySQL server port |
| `MYSQL_DATABASE` | `""` | Database name (required) |
| `MYSQL_USER` | `""` | MySQL username (required) |
| `MYSQL_PASSWORD` | `""` | MySQL password |
| `MYSQL_TIMEOUT_SECONDS` | `30` | Connect/read timeout in seconds |

```bash
export MYSQL_HOST=analytics-mysql.example.com
export MYSQL_PORT=3306
export MYSQL_DATABASE=analytics
export MYSQL_USER=analyst_ro
export MYSQL_PASSWORD=your-password
export MYSQL_TIMEOUT_SECONDS=30
```

## API Endpoints

All endpoints require **DEVELOPER** or **ADMIN** role. Credentials are supplied per-request and never persisted.

### POST /api/v1/warehouse/mysql/test-connection

Test connectivity to a MySQL server.

**Request body:**
```json
{
  "host": "mysql.example.com",
  "port": 3306,
  "database": "analytics",
  "user": "analyst_ro",
  "password": "secret",
  "charset": "utf8mb4",
  "timeout": 30
}
```

**Response (200):**
```json
{ "status": "connected" }
```

**Response (503):** Server unreachable or credentials rejected.

### POST /api/v1/warehouse/mysql/query

Execute a read-only SELECT query. DML/DDL is rejected with HTTP 400.

Uses `%s` placeholders for parameterised queries — never string-format user input into SQL.

**Request body:**
```json
{
  "host": "mysql.example.com",
  "port": 3306,
  "database": "analytics",
  "user": "analyst_ro",
  "password": "secret",
  "sql": "SELECT variant_id, count(*) AS n FROM experiment_assignments WHERE experiment_id = %s GROUP BY variant_id",
  "timeout": 30
}
```

**Response (200):**
```json
{
  "rows": [
    { "variant_id": "control", "n": 10000 },
    { "variant_id": "treatment", "n": 9850 }
  ],
  "row_count": 2
}
```

### GET /api/v1/warehouse/mysql/metrics/experiments/{experiment_id}

Fetch per-variant conversion metrics.

**Query params:** `host`, `port`, `database`, `user`, `password`, `charset`, `timeout`

**Response (200):**
```json
{
  "metrics": {
    "control":   { "mean": 0.12, "count": 10000, "conversions": 1200 },
    "treatment": { "mean": 0.148, "count": 9850, "conversions": 1459 }
  }
}
```

### GET /api/v1/warehouse/mysql/metrics/flags/{flag_id}

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

## Schema Requirements

The `get_experiment_metrics()` helper queries `experiment_assignments`:

```sql
CREATE TABLE experiment_assignments (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    experiment_id VARCHAR(255) NOT NULL,
    user_id       VARCHAR(255) NOT NULL,
    variant_id    VARCHAR(255) NOT NULL,
    converted     TINYINT(1)   NOT NULL DEFAULT 0,
    assigned_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_experiment_id (experiment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

The `get_feature_flag_metrics()` helper queries `feature_flag_events`:

```sql
CREATE TABLE feature_flag_events (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    flag_id       VARCHAR(255)     NOT NULL,
    group_key     VARCHAR(255)     NOT NULL,
    request_count BIGINT UNSIGNED  NOT NULL DEFAULT 0,
    error_count   BIGINT UNSIGNED  NOT NULL DEFAULT 0,
    recorded_at   DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_flag_id (flag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## Connection Pooling Recommendations

For high-throughput workloads, consider using a connection pool. The connector is designed for per-request use (credentials are supplied per-call), but you can integrate it with SQLAlchemy or a standalone pool:

```python
from sqlalchemy import create_engine

engine = create_engine(
    "mysql+pymysql://analyst_ro:secret@mysql.example.com:3306/analytics",
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # Re-validate connections on checkout
    pool_recycle=3600,    # Recycle connections every hour
)
```

For AWS RDS, use `pool_recycle=1800` (30 minutes) to stay inside RDS idle-connection limits.

## SQL Patterns

### Parameterised query (safe pattern)

Always use `%s` placeholders. Never concatenate user input into SQL strings.

```python
from modules.backend.app.services.mysql_connector import MySQLConnector

with MySQLConnector(host="db.example.com", database="analytics",
                   user="analyst", password="secret") as conn:
    rows = conn.execute_query(
        "SELECT variant_id, COUNT(*) AS n "
        "FROM experiment_assignments "
        "WHERE experiment_id = %s GROUP BY variant_id",
        params=("exp-001",),
    )
```

### Conversion rate by variant

```sql
SELECT
    variant_id,
    COUNT(DISTINCT user_id) AS sample_size,
    SUM(converted) AS conversions,
    SUM(converted) / COUNT(DISTINCT user_id) AS conversion_rate
FROM experiment_assignments
WHERE experiment_id = %s
GROUP BY variant_id
```

### Rolling 7-day error rate

```sql
SELECT
    flag_id,
    group_key,
    SUM(request_count) AS requests,
    SUM(error_count) AS errors,
    SUM(error_count) / SUM(request_count) AS error_rate
FROM feature_flag_events
WHERE flag_id = %s
  AND recorded_at >= NOW() - INTERVAL 7 DAY
GROUP BY flag_id, group_key
```

## Troubleshooting

**`Access denied for user 'analyst'@'host'`**
- Verify the username and password match the MySQL user account
- Grant appropriate privileges: `GRANT SELECT ON analytics.* TO 'analyst'@'%';`
- Check the host-based access control — MySQL restricts connections by source IP

**`Can't connect to MySQL server on 'host'`**
- Confirm the MySQL port (3306) is open in the server's firewall
- For RDS/Aurora, check the security group inbound rules

**`Lost connection to MySQL server during query`**
- Increase `MYSQL_TIMEOUT_SECONDS`
- For long-running aggregate queries, consider MySQL's `wait_timeout` and `interactive_timeout` settings

**Character encoding issues (`Incorrect string value`)**
- Ensure the table and connection both use `utf8mb4` (not `utf8`, which only supports up to 3-byte characters and excludes emoji)
- The connector defaults to `charset=utf8mb4`

**`SSL connection error`**
- For RDS with `require_secure_transport=ON`, pass `ssl={'ca': '/path/to/ca.pem'}` through the connector's `pymysql.connect()` call (extend the connector or use a raw PyMySQL connection for SSL-required setups)

**Timezone discrepancies**
- MySQL stores `DATETIME` columns without timezone info. If your server is not in UTC, query results may be offset. Set `SET time_zone = '+00:00'` at connection time or use `CONVERT_TZ()` in your SQL.
