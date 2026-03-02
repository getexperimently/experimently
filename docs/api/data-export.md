# Data Export & Reporting API (EP-020)

This document describes the data export and reporting endpoints available under `/api/v1/export/`.

---

## Authentication

All export endpoints require a valid Bearer token obtained via the `/api/v1/auth/token` endpoint.

```
Authorization: Bearer <access_token>
```

All authenticated roles (ADMIN, DEVELOPER, ANALYST, VIEWER) may access these endpoints.

Unauthenticated requests return `401 Unauthorized`.

---

## Rate Limiting

Export endpoints are subject to the platform-wide rate limiter configured in `RateLimitMiddleware`.
Bursting large CSV exports repeatedly in a short window will trigger `429 Too Many Requests`.
For bulk data pipelines, consider exporting once and caching the result.

---

## Export Endpoints

### GET /api/v1/export/experiments

Download all experiments as a CSV (default) or JSON file.

#### Query Parameters

| Parameter    | Type     | Default     | Description                                                  |
|--------------|----------|-------------|--------------------------------------------------------------|
| `format`     | `string` | `csv`       | Output format. Accepted values: `csv`, `json`                |
| `scope`      | `string` | `summary`   | Data scope. Accepted values: `summary`, `events`, `assignments` |
| `start_date` | `datetime` | `null`    | Inclusive start filter on `created_at` (ISO 8601, UTC)       |
| `end_date`   | `datetime` | `null`    | Inclusive end filter on `created_at` (ISO 8601, UTC)         |

#### CSV Column Names

| Column                  | Type      | Description                              |
|-------------------------|-----------|------------------------------------------|
| `experiment_id`         | string    | UUID of the experiment                   |
| `experiment_name`       | string    | Human-readable experiment name           |
| `status`                | string    | Current status (draft, active, completed, etc.) |
| `experiment_type`       | string    | Type: a_b, mv, split_url, bandit         |
| `start_date`            | string    | ISO 8601 start date, or empty            |
| `end_date`              | string    | ISO 8601 end date, or empty              |
| `duration_days`         | float     | Days between start and end, or empty     |
| `total_assignments`     | integer   | Total user assignments to this experiment |
| `total_events`          | integer   | Total events tracked for this experiment |
| `winner_variant`        | string    | Name of winning variant, or empty        |
| `recommendation`        | string    | SHIP_VARIANT / CONTINUE_TESTING / etc.   |

#### Example curl

```bash
# CSV (default)
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/v1/export/experiments" \
  -o experiments.csv

# JSON with date filter
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/v1/export/experiments?format=json&start_date=2024-01-01T00:00:00Z&end_date=2024-06-30T23:59:59Z" \
  -o experiments.json
```

#### Response Headers

```
Content-Type: text/csv
Content-Disposition: attachment; filename=experiments_20240315_143000.csv
```

---

### GET /api/v1/export/variants

Download per-variant results for all (or filtered) experiments.

Each row represents one variant within one experiment.

#### Query Parameters

Same as `/export/experiments` (`format`, `scope`, `start_date`, `end_date`).

#### CSV Column Names

| Column                      | Type    | Description                                         |
|-----------------------------|---------|-----------------------------------------------------|
| `experiment_id`             | string  | UUID of the parent experiment                       |
| `experiment_name`           | string  | Human-readable experiment name                      |
| `variant_id`                | string  | UUID of the variant                                 |
| `variant_name`              | string  | Variant name                                        |
| `is_control`                | boolean | Whether this is the control variant                 |
| `assignments`               | integer | Number of users assigned to this variant            |
| `conversions`               | integer | Number of conversion events, or empty               |
| `conversion_rate`           | float   | Conversion rate [0, 1], or empty                    |
| `p_value`                   | float   | Statistical p-value vs control, or empty            |
| `is_significant`            | boolean | Whether result is statistically significant         |
| `relative_improvement_pct`  | float   | Relative improvement over control (%), or empty     |

#### Example curl

```bash
# All variants as CSV
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/v1/export/variants" \
  -o variants.csv

# Specific date range as JSON
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/v1/export/variants?format=json&start_date=2024-01-01T00:00:00Z" \
  -o variants.json
```

---

### GET /api/v1/export/feature-flags

Download feature flag usage data.

#### Query Parameters

| Parameter    | Type     | Default | Description                                                    |
|--------------|----------|---------|----------------------------------------------------------------|
| `format`     | `string` | `csv`   | Output format. Accepted values: `csv`, `json`                  |
| `start_date` | `datetime` | `null` | Inclusive start filter on `created_at` (ISO 8601, UTC)        |
| `end_date`   | `datetime` | `null` | Inclusive end filter on `created_at` (ISO 8601, UTC)          |

#### CSV Column Names

| Column                | Type    | Description                                          |
|-----------------------|---------|------------------------------------------------------|
| `flag_id`             | string  | UUID of the feature flag                             |
| `flag_key`            | string  | Machine-readable key (e.g. `checkout_v2`)            |
| `flag_name`           | string  | Human-readable name                                  |
| `status`              | string  | INACTIVE, ACTIVE, or ARCHIVED                        |
| `rollout_percentage`  | integer | Configured rollout percentage (0-100)                |
| `total_evaluations`   | integer | Total number of times the flag was evaluated         |
| `enabled_evaluations` | integer | Number of evaluations where the flag was enabled     |
| `enabled_rate`        | float   | Ratio of enabled evaluations to total [0, 1]         |
| `created_at`          | string  | ISO 8601 creation timestamp                          |
| `updated_at`          | string  | ISO 8601 last-updated timestamp                      |

#### Example curl

```bash
# Feature flags as CSV
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/v1/export/feature-flags" \
  -o feature_flags.csv

# Active flags only — use start_date to narrow results in combination with your own filtering
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/v1/export/feature-flags?format=json" \
  -o feature_flags.json
```

---

## Report Endpoints

### GET /api/v1/export/reports/overview

Returns a JSON summary of platform-wide activity. Always returns `application/json`.

#### Query Parameters

| Parameter    | Type     | Default | Description                                              |
|--------------|----------|---------|----------------------------------------------------------|
| `start_date` | `datetime` | `null` | Report period start (inclusive, ISO 8601 UTC)           |
| `end_date`   | `datetime` | `null` | Report period end (inclusive, ISO 8601 UTC)             |

#### JSON Response Schema

```json
{
  "generated_at": "2024-03-15T14:30:00+00:00",
  "period_start": "2024-01-01T00:00:00+00:00",
  "period_end": "2024-03-15T23:59:59+00:00",
  "total_experiments": 42,
  "active_experiments": 7,
  "completed_experiments": 30,
  "total_feature_flags": 15,
  "active_feature_flags": 8,
  "total_assignments": 125000,
  "total_events": 340000,
  "experiments_with_winners": 12,
  "average_experiment_duration_days": 21.4
}
```

| Field                              | Type    | Description                                              |
|------------------------------------|---------|----------------------------------------------------------|
| `generated_at`                     | string  | ISO 8601 timestamp when the report was generated         |
| `period_start`                     | string  | Report period start, or null if no filter applied        |
| `period_end`                       | string  | Report period end, or null if no filter applied          |
| `total_experiments`                | integer | Total experiments in the platform (filtered by period)   |
| `active_experiments`               | integer | Experiments currently in ACTIVE status                   |
| `completed_experiments`            | integer | Experiments in COMPLETED status                          |
| `total_feature_flags`              | integer | Total feature flags                                      |
| `active_feature_flags`             | integer | Feature flags in ACTIVE status                           |
| `total_assignments`                | integer | Total user-experiment assignments                        |
| `total_events`                     | integer | Total tracking events                                    |
| `experiments_with_winners`         | integer | Experiments that have a winner identified                |
| `average_experiment_duration_days` | float   | Average duration (days) of completed experiments, or null |

#### Example curl

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/v1/export/reports/overview" | jq .

# With date filter
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/v1/export/reports/overview?start_date=2024-01-01T00:00:00Z&end_date=2024-03-31T23:59:59Z" | jq .
```

---

### GET /api/v1/export/reports/experiments/{experiment_id}

Returns a combined JSON report for a single experiment, including experiment metadata and per-variant breakdown.

#### Path Parameters

| Parameter       | Type   | Description                    |
|-----------------|--------|--------------------------------|
| `experiment_id` | string | UUID of the experiment         |

#### Query Parameters

| Parameter | Type     | Default | Description                   |
|-----------|----------|---------|-------------------------------|
| `format`  | `string` | `json`  | Output format (`csv` or `json`) |

#### JSON Response Schema

```json
{
  "experiment_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  "experiments": [
    {
      "experiment_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      "experiment_name": "Checkout Button Colour Test",
      "status": "completed",
      "experiment_type": "a_b",
      "start_date": "2024-01-01T00:00:00+00:00",
      "end_date": "2024-01-31T00:00:00+00:00",
      "duration_days": 30.0,
      "total_assignments": 10000,
      "total_events": 1100,
      "winner_variant": "Treatment",
      "recommendation": "SHIP_VARIANT"
    }
  ],
  "variants": [
    {
      "experiment_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      "experiment_name": "Checkout Button Colour Test",
      "variant_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      "variant_name": "Control",
      "is_control": true,
      "assignments": 5000,
      "conversions": 500,
      "conversion_rate": 0.10,
      "p_value": null,
      "is_significant": false,
      "relative_improvement_pct": null
    }
  ]
}
```

#### Example curl

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/v1/export/reports/experiments/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" | jq .
```

---

## Error Responses

| Status Code | Description                                              |
|-------------|----------------------------------------------------------|
| `401`       | Missing or invalid Bearer token                          |
| `403`       | Authenticated but insufficient permissions               |
| `422`       | Invalid query parameter (e.g. `format=xml`)              |
| `429`       | Rate limit exceeded                                      |
| `500`       | Internal server error (check application logs)           |

### Example 422 Error

```json
{
  "detail": [
    {
      "loc": ["query", "format"],
      "msg": "value is not a valid enumeration member; permitted: 'csv', 'json'",
      "type": "type_error.enum"
    }
  ]
}
```

---

## Notes

- All date/time values in export files are in ISO 8601 format with UTC offset.
- UUIDs are included in exports as plain strings (not resolved to names where the ID is already paired with a human-readable name in an adjacent column).
- Date filtering is **inclusive on both ends** (`created_at >= start_date AND created_at <= end_date`).
- CSV exports use Python's `csv.DictWriter` with `\r\n` line endings (RFC 4180).
- For large datasets, exports are **streamed** (`StreamingResponse`) to keep memory usage constant.
- The `scope` parameter is accepted for all experiment/variant endpoints but is not currently used to change the column set — it is reserved for future expansion (e.g. `events` scope will include raw event columns).
