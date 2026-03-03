# Gradual Rollouts

A gradual rollout progressively increases a feature flag's rollout percentage over time, in controlled stages. Instead of flipping a flag from 0% to 100% in one step, you roll out to 10%, watch for problems, expand to 50%, confirm everything is healthy, then go to 100%.

---

## Why Gradual Rollouts Matter

Deploying a new feature to 100% of users at once is the highest-risk approach. If the feature has a bug or causes unexpected performance degradation, all users are immediately affected. Gradual rollouts limit your **blast radius**:

- A bug at 5% rollout affects only 5% of users
- You can catch problems in monitoring dashboards before they reach the majority
- If something goes wrong, you can pause the rollout at the current stage rather than scrambling for a full revert
- You can use time-based stages to coincide with low-traffic periods

---

## What a Rollout Schedule Is

A rollout schedule is a plan attached to a feature flag that defines:

- A sequence of **stages**, each with a target rollout percentage
- A **trigger type** for each stage: time-based (advance automatically at a specified date), metric-based, or manual (advance only when you explicitly approve)
- Optional start and end dates for the overall schedule

The platform's background scheduler processes active rollout schedules every 15 minutes and advances time-based stages when their `start_date` has been reached.

---

## Creating a Rollout Schedule via API

### Step 1: Create the Flag (if not already done)

See [Creating Feature Flags](create.md).

### Step 2: Create the Rollout Schedule

```bash
curl -X POST http://localhost:8000/api/v1/rollout-schedules \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "New Checkout Flow Gradual Rollout",
    "description": "Roll out new checkout to all users over 3 weeks",
    "feature_flag_id": "flag-uuid-here",
    "start_date": "2026-04-01T00:00:00Z",
    "end_date": "2026-04-28T23:59:59Z",
    "max_percentage": 100,
    "min_stage_duration": 24,
    "stages": [
      {
        "name": "Initial Canary",
        "description": "First 10% — watch error rates",
        "stage_order": 1,
        "target_percentage": 10,
        "trigger_type": "time_based",
        "start_date": "2026-04-01T00:00:00Z"
      },
      {
        "name": "Expanded Rollout",
        "description": "Expand to 50% — confirm stability",
        "stage_order": 2,
        "target_percentage": 50,
        "trigger_type": "time_based",
        "start_date": "2026-04-08T00:00:00Z"
      },
      {
        "name": "Full Rollout",
        "description": "100% — manual gate for final approval",
        "stage_order": 3,
        "target_percentage": 100,
        "trigger_type": "manual"
      }
    ]
  }'
```

**Response: 201 Created**

```json
{
  "id": "schedule-uuid",
  "name": "New Checkout Flow Gradual Rollout",
  "feature_flag_id": "flag-uuid-here",
  "status": "pending",
  "current_stage": null,
  "stages": [
    { "id": "stage-1-uuid", "stage_order": 1, "target_percentage": 10, "trigger_type": "time_based", "status": "pending" },
    { "id": "stage-2-uuid", "stage_order": 2, "target_percentage": 50, "trigger_type": "time_based", "status": "pending" },
    { "id": "stage-3-uuid", "stage_order": 3, "target_percentage": 100, "trigger_type": "manual", "status": "pending" }
  ]
}
```

### Step 3: Activate the Schedule

```bash
curl -X POST http://localhost:8000/api/v1/rollout-schedules/schedule-uuid/activate \
  -H "Authorization: Bearer $TOKEN"
```

Once activated, the scheduler will advance the schedule at the specified dates.

---

## Rollout Stages

### Target Percentage

Each stage specifies a `target_percentage` — the rollout percentage the flag will be set to when that stage activates. Percentages must be non-decreasing across stages.

Valid: 10 → 50 → 100

Invalid: 10 → 50 → 25 (decreasing is not allowed)

### Trigger Types

| Trigger Type | Description |
|--------------|-------------|
| `time_based` | Stage advances automatically when the current time passes `start_date` |
| `manual` | Stage advances only when you explicitly call the advance endpoint |
| `metric_based` | Stage advances when a defined metric threshold is met (contact your admin for configuration) |

### Stage Lifecycle

```
pending → in_progress → completed
```

When a stage activates, it transitions to `in_progress` and the flag's rollout percentage is updated. When the next stage activates, the previous stage transitions to `completed`.

---

## Time-Based Triggers

For `time_based` stages, set a `start_date` in UTC ISO 8601 format:

```json
{
  "trigger_type": "time_based",
  "start_date": "2026-04-08T00:00:00Z"
}
```

The scheduler checks every 15 minutes. A stage set for 09:00 UTC may not advance until 09:15. Plan your schedule with this buffer in mind.

All dates are in UTC. If your business runs on a specific timezone, convert accordingly before setting dates.

---

## Manual Advancement

To advance a manual stage:

```bash
curl -X POST http://localhost:8000/api/v1/rollout-schedules/stages/stage-3-uuid/advance \
  -H "Authorization: Bearer $TOKEN"
```

This immediately sets the flag's rollout percentage to the stage's `target_percentage` and marks the stage as `in_progress`.

Manual stages are recommended for the final rollout to 100% — they serve as a human approval gate before full deployment.

---

## Pausing a Schedule

If you observe problems during a rollout, pause the schedule to stop automatic advancement:

```bash
curl -X POST http://localhost:8000/api/v1/rollout-schedules/schedule-uuid/pause \
  -H "Authorization: Bearer $TOKEN"
```

Pausing does not change the flag's current rollout percentage. It only stops future automatic stage transitions. You can resume the schedule after investigating and resolving the issue.

---

## Cancelling a Schedule

To stop a rollout entirely and clean up the schedule:

```bash
curl -X POST http://localhost:8000/api/v1/rollout-schedules/schedule-uuid/cancel \
  -H "Authorization: Bearer $TOKEN"
```

Cancelling marks the schedule as `cancelled`. The flag's current rollout percentage is not changed — you must update it separately if you want to roll back.

---

## Monitoring Progress

### View Schedule Status

```bash
curl -X GET http://localhost:8000/api/v1/rollout-schedules/schedule-uuid \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "id": "schedule-uuid",
  "status": "active",
  "current_stage": {
    "stage_order": 2,
    "name": "Expanded Rollout",
    "target_percentage": 50,
    "status": "in_progress",
    "activated_at": "2026-04-08T00:12:00Z"
  }
}
```

### Dashboard

In the dashboard, navigate to **Feature Flags → [Your Flag] → Rollout Schedule** to see a visual timeline of stages, current progress, and upcoming dates.

---

## Common Rollout Patterns

### Canary → Stable → Full (3 weeks)

A cautious rollout for high-risk changes like payment flows or authentication:

| Stage | Target % | Trigger | When |
|-------|----------|---------|------|
| Canary | 5% | Time-based | Day 0 |
| Early majority | 25% | Time-based | Day 7 |
| Majority | 75% | Time-based | Day 14 |
| Full rollout | 100% | Manual | Day 21 |

### Fast Rollout (3 days)

For lower-risk UI changes with good monitoring:

| Stage | Target % | Trigger | When |
|-------|----------|---------|------|
| Early adopters | 20% | Time-based | Day 0 |
| Half rollout | 50% | Time-based | Day 1 |
| Full rollout | 100% | Time-based | Day 3 |

### Internal → Beta → General Availability

Roll out first to internal users (using targeting rules), then beta users, then everyone:

| Stage | Target % | Targeting Rule | Trigger |
|-------|----------|---------------|---------|
| Internal | 100% | `email ends_with @yourcompany.com` | Manual |
| Beta | 100% | `plan equals beta` | Manual |
| GA | 100% | No rule (all users) | Manual |

---

## Common Gotchas

- Rollout percentages must be non-decreasing across stages
- You cannot delete stages from an active schedule — cancel the schedule first
- Stage orders must be sequential (1, 2, 3 — no gaps)
- Time-based `start_date` values must be in UTC
- Manual stages must be advanced explicitly — they will not auto-advance even after the `end_date` of the schedule
- The minimum stage duration (`min_stage_duration` in hours) prevents stages from being advanced too quickly, even if manually requested
