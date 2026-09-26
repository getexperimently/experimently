# Safety Monitoring

Safety monitoring watches feature flags for signs of trouble — elevated error rates, increased latency — and
rolls a flag back when a configured threshold is breached. It is a safety net for risky rollouts that does not
depend on an engineer watching dashboards.

Implementation: `backend/app/services/safety_service.py` (checks and rollbacks),
`backend/app/core/safety_scheduler.py` (background loop), endpoints under `/api/v1/safety`.

---

## What Safety Monitoring Does

The safety monitor runs every 5 minutes (`SAFETY_CHECK_INTERVAL_MINUTES`; the rollout scheduler's cadence is
`ROLLOUT_CHECK_INTERVAL_MINUTES`, default 15 — demos set both to 1). For every `ACTIVE` flag whose
`rollout_percentage` is above 0 it:

1. Loads the flag's safety configuration (or the platform default when the flag has none) and skips the flag
   if monitoring is not `enabled`.
2. Reads the current value of each configured metric over the last 15 minutes: error metrics come from
   `error_logs` (relative to the flag's evaluations in `raw_metrics`), latency metrics from `raw_metrics`.
3. Compares each value with the metric's `critical_threshold` using its `comparison_type`. A breach marks the
   flag unhealthy; a `warning_threshold` breach is only reported.
4. If the flag is unhealthy **and** the global setting `enable_automatic_rollbacks` is on, rolls the flag back:
   sets `rollout_percentage` to the configuration's `rollback_percentage` (default `0`; the flag stays `ACTIVE`, so its configuration is preserved), records a
   `SafetyRollbackRecord`, and sends the configured Slack/email notification.

You can run the same check on demand with `GET /api/v1/safety/feature-flags/{flag_id}/check`.

---

## Metrics You Can Monitor

| Metric name | Source | Meaning |
|-------------|--------|---------|
| `error_rate` | `error_logs` ÷ flag evaluations | Fraction of evaluations that logged an error (0.0–1.0) |
| `error_count` | `error_logs` | Number of errors in the window |
| `total_evaluations` | `raw_metrics` | Number of flag evaluations in the window |
| `latency`, `avg_latency` | `raw_metrics` (`metric_type = latency`) | Average latency in ms |
| `p95_latency` | `raw_metrics` | 95th percentile latency in ms |
| `max_latency`, `min_latency` | `raw_metrics` | Extremes in ms |

Each metric takes a `MetricThreshold`:

| Field | Type | Description |
|-------|------|-------------|
| `critical_threshold` | float | Breaching it makes the flag unhealthy (rollback candidate) |
| `warning_threshold` | float | Reported in the check details; never triggers a rollback |
| `comparison_type` | `"greater_than"` (default), `"less_than"`, `"equal_to"` | How the current value is compared with the thresholds |

Metric names outside this list are accepted but have no data source; they are reported as healthy.

---

## Configuring Per-Flag Safety

Run the commands on the rest of this page in one terminal, in order, against the stack from
the [Quick Start](../getting-started/quick-start.md). Each uses the shell variables set by
the ones before it.

### Log in and create a flag

Changing safety settings takes a superuser, such as the demo administrator:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .is_superuser
```
<!-- expect: true -->

It prints `true`.

The examples watch a flag that is on for half of all users. This creates it and saves its id
in `$FLAG_ID` (see [Creating Feature Flags](create.md)):

```{.bash exec}
FLAG_ID=$(curl -s -X POST localhost:8000/api/v1/feature-flags/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"key": "new-checkout-flow", "name": "New Checkout Flow", "rollout_percentage": 50, "is_active": true}' \
  | jq -r .id)

curl -s localhost:8000/api/v1/feature-flags/$FLAG_ID \
  -H "Authorization: Bearer $TOKEN" | jq '{status, rollout_percentage}'
```
<!-- expect: "status": "active" -->
<!-- expect: "rollout_percentage": 50 -->

It prints `"status": "active"` and `"rollout_percentage": 50`.

### A flag without a configuration

`GET /api/v1/safety/feature-flags/{flag_id}/config` never answers `404` for a flag without a
configuration. It returns a default built from the global settings, with the nil UUID as
`id`. Nothing is written until you `POST`:

```{.bash exec}
curl -s localhost:8000/api/v1/safety/feature-flags/$FLAG_ID/config \
  -H "Authorization: Bearer $TOKEN" | jq '{id, enabled}'
```
<!-- expect: "id": "00000000-0000-0000-0000-000000000000" -->
<!-- expect: "enabled": true -->

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "enabled": true
}
```

### Create or Update a Flag's Configuration

Requires a superuser. The call creates the configuration, or replaces the fields you send:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/safety/feature-flags/$FLAG_ID/config \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "enabled": true,
    "metrics": {
      "error_rate":  {"warning_threshold": 0.02, "critical_threshold": 0.05, "comparison_type": "greater_than"},
      "p95_latency": {"warning_threshold": 300,  "critical_threshold": 500,  "comparison_type": "greater_than"}
    },
    "rollback_percentage": 0
  }' | jq -c '.metrics'
```
<!-- expect: "error_rate":{"warning_threshold":0.02,"critical_threshold":0.05,"comparison_type":"greater_than"} -->
<!-- expect: "p95_latency":{"warning_threshold":300.0,"critical_threshold":500.0,"comparison_type":"greater_than"} -->

It prints the stored thresholds:

```json
{"error_rate":{"warning_threshold":0.02,"critical_threshold":0.05,"comparison_type":"greater_than"},"p95_latency":{"warning_threshold":300.0,"critical_threshold":500.0,"comparison_type":"greater_than"}}
```

**Request Fields**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | No | Whether the monitor checks this flag (default `true`) |
| `metrics` | object | No | Map of metric name → threshold (see above). An empty map means nothing is checked |
| `rollback_percentage` | int | No | Percentage the automatic rollback sets the flag to (default `0`, i.e. fully off). Set it to e.g. `5` to fall back to an internal/canary slice instead of turning the flag off; manual rollbacks take the percentage as a query parameter |

The response (the same shape as `GET .../config`) also carries the configuration's `id`,
`feature_flag_id`, `enabled`, `rollback_percentage`, `created_at` and `updated_at`.

### Example: Checkout Flag with Tight Thresholds

```json
{
  "enabled": true,
  "metrics": {
    "error_rate":  {"critical_threshold": 0.02, "comparison_type": "greater_than"},
    "p95_latency": {"critical_threshold": 300,  "comparison_type": "greater_than"}
  }
}
```

### Example: Non-Critical UI Flag, Alerts Only

Set only `warning_threshold`s (no `critical_threshold`): the check reports warnings but the flag never becomes
unhealthy, so it is never rolled back.

```json
{
  "enabled": true,
  "metrics": {
    "error_rate": {"warning_threshold": 0.10, "comparison_type": "greater_than"}
  }
}
```

---

## Global Safety Settings

Global settings hold the automatic-rollback switch and the default metric thresholds applied to flags that have
no configuration of their own.

### View Global Settings

Any logged-in user can read them:

```{.bash exec}
curl -s localhost:8000/api/v1/safety/settings \
  -H "Authorization: Bearer $TOKEN" | jq .enable_automatic_rollbacks
```
<!-- expect: true -->

It prints `true`: the Quick Start's demo data turns automatic rollbacks on. The response also
carries `default_metrics`, `id`, `created_at` and `updated_at`.

On a database where no settings have been stored, the first read creates them with
`enable_automatic_rollbacks: false` and no defaults. **Automatic rollbacks are then off until
an administrator turns them on.**

### Update Global Settings

Requires a superuser:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/safety/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "enable_automatic_rollbacks": true,
    "default_metrics": {
      "error_rate": {"warning_threshold": 0.05, "critical_threshold": 0.10, "comparison_type": "greater_than"}
    }
  }' | jq -c .default_metrics
```
<!-- expect: {"error_rate":{"warning_threshold":0.05,"critical_threshold":0.1,"comparison_type":"greater_than"}} -->

It prints the stored defaults:

```json
{"error_rate":{"warning_threshold":0.05,"critical_threshold":0.1,"comparison_type":"greater_than"}}
```

Per-flag configurations always take precedence over the defaults.

---

## Running a Check

```{.bash exec}
curl -s localhost:8000/api/v1/safety/feature-flags/$FLAG_ID/check \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{is_healthy, metrics: [.metrics[] | {name, current_value, threshold, is_healthy}]}'
```
<!-- expect: "is_healthy": true -->
<!-- expect: "name": "error_rate" -->

The new flag has no traffic, so every value is `0.0` and the flag is healthy:

```json
{
  "is_healthy": true,
  "metrics": [
    {
      "name": "error_rate",
      "current_value": 0.0,
      "threshold": 0.05,
      "is_healthy": true
    },
    {
      "name": "p95_latency",
      "current_value": 0.0,
      "threshold": 500.0,
      "is_healthy": true
    }
  ]
}
```

Each metric's `details` holds its `warning_threshold`, `critical_threshold`, `comparison_type`
and `warning` (whether the warning threshold is breached). The response also carries
`feature_flag_id` and `last_checked`. When a metric breaches its critical threshold, that
metric and the whole response read `"is_healthy": false`.

---

## Auto-Rollback

When the monitor finds a flag unhealthy and `enable_automatic_rollbacks` is on, it:

1. Locks the flag row and sets `rollout_percentage` to the flag's configured `rollback_percentage` (default `0`; status stays `ACTIVE`)
2. Records a `SafetyRollbackRecord` with trigger type `automatic`, the
   metric value and threshold, the previous and target percentages, and the reason
3. Dispatches a notification to the configured Slack channels and email addresses

Users outside the rollback percentage no longer receive the flag after the rollback. Investigate the root cause
before re-enabling.

Error metrics count both server-side evaluation failures and errors reported by clients through
`POST /api/v1/tracking/errors` (see [Creating Feature Flags](create.md#reporting-client-side-errors)), so a crash
behind a flag in a mobile app can trigger the same rollback.

### What Triggers a Rollback

| Condition | Trigger |
|-----------|---------|
| Any metric's current value breaches its `critical_threshold` | Automatic rollback (first breaching metric is named in the reason) |
| Only `warning_threshold`s are breached | Reported in the check; no rollback |
| `enable_automatic_rollbacks` is off | Check reports unhealthy; no rollback |

Values are computed over a 15-minute window, so a short spike that resolves quickly is unlikely to trigger a
rollback while sustained elevated metrics will.

---

## Rollback History

Every rollback (automatic or manual) is stored in the `safety_rollback_records` table
(`feature_flag_id`, `safety_config_id`, `trigger_type`, `trigger_reason`, `previous_percentage`,
`target_percentage`, `success`, `executed_by_user_id`, `created_at`). The rollback response includes the
record's id as `rollback_record_id`. There is no list endpoint yet; query the table or use the dashboard.

---

## Manual Rollback

Requires a superuser. Roll a flag down to a percentage (default `0`), with a reason. The
reason is a query parameter, so its spaces are written `%20`:

```{.bash exec}
curl -s -X POST "localhost:8000/api/v1/safety/feature-flags/$FLAG_ID/rollback?percentage=0&reason=Checkout%20errors%20observed%20in%20Datadog" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{success, message, previous_percentage, new_percentage}'
```
<!-- expect: "success": true -->
<!-- expect: "message": "Feature flag 'new-checkout-flow' rolled back from 50% to 0%" -->

```json
{
  "success": true,
  "message": "Feature flag 'new-checkout-flow' rolled back from 50% to 0%",
  "previous_percentage": 50,
  "new_percentage": 0
}
```

The response also carries `feature_flag_id`, `trigger_type` (`manual`), `rollback_record_id`,
`timestamp` and `details` (the reason). A flag that is not `ACTIVE`, or is already at `0%`,
returns `success: false` with an explanatory message.

---

## Re-Enabling After Rollback

After investigating and resolving the root cause, raise the rollout again. The flag is still
`ACTIVE`, so only the percentage changes:

```{.bash exec}
curl -s -X PUT localhost:8000/api/v1/feature-flags/$FLAG_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"rollout_percentage": 5}' | jq '{status, rollout_percentage}'
```
<!-- expect: "status": "active" -->
<!-- expect: "rollout_percentage": 5 -->

It prints `"status": "active"` and `"rollout_percentage": 5`.

Watch the safety check for at least one full 15-minute window before expanding further. If the root cause was
not fixed, the monitor will roll the flag back again on its next pass.

---

## Best Practices

### Set thresholds relative to baseline

Measure your baseline error rate and latency before enabling safety monitoring. If your API normally returns
2% errors, a 1% threshold causes false positives. A reasonable critical threshold is **2× your baseline**:
baseline error rate 2% → `critical_threshold: 0.04`; baseline p95 latency 200 ms → `critical_threshold: 400`.

### Use a warning threshold as an early signal

Pair a lower `warning_threshold` with the critical one; warnings show up in the check details and in the
dashboard without touching traffic.

### Use tight thresholds for critical paths

For features that touch payments, authentication or core user flows: `error_rate` critical `0.02`,
`p95_latency` critical `300`.

### Combine with gradual rollouts

Safety monitoring is most effective with gradual rollouts. A problem affecting 5% of users is much easier to
contain than one affecting 100%. See [Rollout Schedules](rollouts.md).

### Test the rollback path

Before a major launch, trigger a manual rollback in staging to confirm that notifications are delivered and
the flag drops to 0% as expected.
