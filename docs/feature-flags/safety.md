# Safety Monitoring

Safety monitoring automatically watches your feature flags for signs of trouble — elevated error rates, increased latency, unexpected spikes — and rolls back the flag if it detects a problem. This provides a safety net for high-risk deployments without requiring an engineer to monitor dashboards manually.

---

## What Safety Monitoring Does

The safety monitor runs on a background cycle (every 5 minutes by default). For each feature flag with a safety configuration, it:

1. Collects recent error rate and latency metrics from the monitoring pipeline
2. Compares them against the configured thresholds
3. If a threshold is breached, automatically disables the feature flag (sets rollout percentage to 0 and status to `INACTIVE`)
4. Records a rollback event with the timestamp, reason, and metric values at the time of rollback
5. Sends a notification via Slack or email (if alerting is configured)

Rollback is always non-destructive — the flag configuration is preserved. You can re-enable the flag after investigating and resolving the root cause.

---

## Configuring Per-Flag Safety

### Create a Safety Configuration

```bash
curl -X POST http://localhost:8000/api/v1/safety/feature-flags/flag-uuid-here \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "error_rate_threshold": 0.05,
    "latency_p95_threshold_ms": 500,
    "monitoring_window_minutes": 10,
    "rollback_on_breach": true
  }'
```

**Request Fields**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `error_rate_threshold` | float | No | Maximum acceptable error rate (0.0–1.0). Example: `0.05` = 5% errors |
| `latency_p95_threshold_ms` | int | No | Maximum acceptable p95 latency in milliseconds. Example: `500` |
| `monitoring_window_minutes` | int | No | Rolling window for metric aggregation (default: 10 minutes) |
| `rollback_on_breach` | boolean | No | If `true`, automatically disable the flag when a threshold is breached (default: `true`) |

At least one threshold must be specified. You can set only error rate, only latency, or both.

### Example: Checkout Flag with Tight Thresholds

For a feature touching the checkout flow, you might use tight thresholds:

```json
{
  "error_rate_threshold": 0.02,
  "latency_p95_threshold_ms": 300,
  "monitoring_window_minutes": 5,
  "rollback_on_breach": true
}
```

### Example: Non-Critical UI Flag

For a low-risk UI tweak, more relaxed thresholds are appropriate:

```json
{
  "error_rate_threshold": 0.10,
  "latency_p95_threshold_ms": 2000,
  "monitoring_window_minutes": 15,
  "rollback_on_breach": false
}
```

Setting `rollback_on_breach: false` sends alerts but does not automatically disable the flag.

---

## Global Safety Settings

Platform-wide safety defaults apply to all flags that do not have a specific safety configuration.

### View Global Settings

```bash
curl -X GET http://localhost:8000/api/v1/safety/settings \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "global_error_rate_threshold": 0.10,
  "global_latency_p95_threshold_ms": 1000,
  "monitoring_enabled": true,
  "default_monitoring_window_minutes": 10,
  "auto_rollback_enabled": true
}
```

### Update Global Settings

Requires ADMIN role.

```bash
curl -X PUT http://localhost:8000/api/v1/safety/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "global_error_rate_threshold": 0.05,
    "global_latency_p95_threshold_ms": 800,
    "auto_rollback_enabled": true
  }'
```

Per-flag configurations always take precedence over global settings.

---

## Auto-Rollback

When the safety monitor detects a threshold breach and `rollback_on_breach` is `true`, it performs the following actions automatically:

1. Sets the flag's `rollout_percentage` to `0`
2. Sets the flag's `status` to `INACTIVE`
3. Records a `SafetyRollbackRecord` with the breach details
4. Dispatches a notification to configured Slack channels and email addresses

After the rollback, the flag will not be served to any users. Investigate the root cause before re-enabling.

### What Triggers a Rollback

| Condition | Trigger |
|-----------|---------|
| Error rate exceeds `error_rate_threshold` for the monitoring window | Automatic rollback |
| p95 latency exceeds `latency_p95_threshold_ms` for the monitoring window | Automatic rollback |
| Both thresholds breached simultaneously | Single rollback, both reasons recorded |

The monitor uses a rolling window average, not instantaneous values. A single spike that resolves within the window will not trigger a rollback. Sustained elevated metrics will.

---

## Viewing Rollback History

### List All Rollback Records

```bash
curl -X GET http://localhost:8000/api/v1/safety/rollback-records \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "items": [
    {
      "id": "rollback-uuid",
      "feature_flag_id": "flag-uuid",
      "feature_flag_key": "new-checkout-flow",
      "rollback_reason": "error_rate_threshold_exceeded",
      "error_rate_at_rollback": 0.082,
      "latency_p95_at_rollback": 410,
      "rolled_back_at": "2026-03-02T14:32:00Z",
      "was_automatic": true
    }
  ],
  "total": 3
}
```

### Filter by Flag

```bash
curl -X GET "http://localhost:8000/api/v1/safety/rollback-records?feature_flag_id=flag-uuid" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Manual Rollback

You can trigger a rollback manually without waiting for the safety monitor. This is useful when you notice a problem in your own monitoring systems before the safety monitor catches it.

```bash
curl -X POST http://localhost:8000/api/v1/safety/rollback/flag-uuid-here \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Increased checkout error rate observed in Datadog"
  }'
```

The manual rollback has the same effect as an automatic rollback: the flag is immediately disabled and a rollback record is created.

---

## Re-Enabling After Rollback

After investigating and resolving the root cause:

```bash
# Re-enable at a low percentage to confirm the fix
curl -X PUT http://localhost:8000/api/v1/feature-flags/flag-uuid-here \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "rollout_percentage": 5,
    "status": "ACTIVE"
  }'
```

Watch safety metrics for at least one full monitoring window before expanding the rollout further. If thresholds were breached before, the safety monitor will immediately roll back again if the root cause was not fixed.

---

## Best Practices

### Set thresholds relative to baseline

Measure your baseline error rate and latency before enabling safety monitoring. If your API normally returns 2% errors, setting a threshold of 1% would cause false positives.

A reasonable threshold is **2x your baseline**:
- Baseline error rate 2% → threshold `0.04` (4%)
- Baseline p95 latency 200ms → threshold `400`

### Use tight thresholds for critical paths

For features that touch payments, authentication, or core user flows, use tighter thresholds and shorter monitoring windows:
- `error_rate_threshold: 0.02` (2%)
- `latency_p95_threshold_ms: 300`
- `monitoring_window_minutes: 5`

### Combine with gradual rollouts

Safety monitoring is most effective when combined with gradual rollouts. A problem affecting 5% of users is much easier to contain than one affecting 100%.

### Test the rollback path

Before a major launch, deliberately trigger a rollback in a staging environment to confirm that notifications are delivered and the flag disables correctly.
