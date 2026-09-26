# Gradual Rollouts

A gradual rollout raises a feature flag's rollout percentage over time, in controlled stages.
Instead of flipping a flag from 0% to 100% in one step, you roll out to 10%, watch for
problems, expand to 50%, confirm everything is healthy, then go to 100%.

---

## Why Gradual Rollouts Matter

Deploying a new feature to 100% of users at once is the highest-risk approach. If the feature
has a bug or slows things down, every user is affected at once. Gradual rollouts limit your
**blast radius**:

- A bug at 5% rollout affects only 5% of users.
- You can catch problems in monitoring dashboards before they reach the majority.
- If something goes wrong, you can pause the rollout at the current stage rather than
  scrambling for a full revert.
- You can time stages to coincide with low-traffic periods.

---

## What a Rollout Schedule Is

A rollout schedule is a plan attached to a feature flag. It defines:

- a sequence of **stages**, each with a target rollout percentage;
- a **trigger type** for each stage: time-based (it starts automatically at its
  `start_date`) or manual (it starts only when you advance it);
- optional start and end dates for the whole schedule.

The platform's background scheduler processes active schedules every 15 minutes
(`ROLLOUT_CHECK_INTERVAL_MINUTES`) and starts a time-based stage once its `start_date` has
passed.

---

## Creating a Rollout Schedule via API

Run these in one terminal, in order, against the stack from the
[Quick Start](../getting-started/quick-start.md). Each step uses the shell variables set by
the ones before it.

**URLs.** The collection URL ends with a slash (`/api/v1/rollout-schedules/`). Without it
the API answers `307 Temporary Redirect`, which `curl` doesn't follow, so nothing happens
and nothing is printed.

### Step 1: Log in

Changing a flag's rollout takes a user with the ADMIN or DEVELOPER role:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

It prints `"ADMIN"`.

### Step 2: Create the flag

A schedule belongs to a flag. This creates one, switched on at 0%, and saves its id in
`$FLAG_ID` (see [Creating Feature Flags](create.md) for the details):

```{.bash exec}
FLAG=$(curl -s -X POST localhost:8000/api/v1/feature-flags/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"key": "new-checkout-flow", "name": "New Checkout Flow", "rollout_percentage": 0, "is_active": true}')
FLAG_ID=$(jq -r .id <<<"$FLAG")

jq '{key, status, rollout_percentage}' <<<"$FLAG"
```
<!-- expect: "status": "active" -->
<!-- expect: "rollout_percentage": 0 -->

It prints `"status": "active"` and `"rollout_percentage": 0`.

### Step 3: Create the rollout schedule

This schedule has three stages:

1. **Initial Canary**, 10%, manual: you start it when you're ready.
2. **Expanded Rollout**, 50%, time-based: it starts by itself a week from now.
3. **Full Rollout**, 100%, manual: a human approval gate before everyone gets the feature.

Dates are UTC, in ISO 8601 form. The first two lines work them out from today with `jq`, so
the example always uses dates in the future. In your own schedule you can write them out
(`2027-01-08T00:00:00Z`). The command saves the schedule's id in `$SCHEDULE_ID`, and the
first stage's in `$CANARY_ID`:

```{.bash exec}
WEEK1=$(jq -nr 'now + 7*86400 | todate')
WEEK4=$(jq -nr 'now + 28*86400 | todate')

SCHEDULE=$(curl -s -X POST localhost:8000/api/v1/rollout-schedules/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  --data @- <<EOF
{
  "name": "New Checkout Flow Gradual Rollout",
  "description": "Roll out the new checkout to all users over 4 weeks",
  "feature_flag_id": "$FLAG_ID",
  "end_date": "$WEEK4",
  "max_percentage": 100,
  "min_stage_duration": 24,
  "stages": [
    {
      "name": "Initial Canary",
      "description": "First 10%: watch error rates",
      "stage_order": 1,
      "target_percentage": 10,
      "trigger_type": "manual"
    },
    {
      "name": "Expanded Rollout",
      "description": "Expand to 50%: confirm stability",
      "stage_order": 2,
      "target_percentage": 50,
      "trigger_type": "time_based",
      "start_date": "$WEEK1"
    },
    {
      "name": "Full Rollout",
      "description": "100%: manual gate for final approval",
      "stage_order": 3,
      "target_percentage": 100,
      "trigger_type": "manual"
    }
  ]
}
EOF
)
SCHEDULE_ID=$(jq -r .id <<<"$SCHEDULE")
CANARY_ID=$(jq -r '.stages[] | select(.stage_order == 1) | .id' <<<"$SCHEDULE")

jq -c '{status, stages: [.stages[] | {stage_order, target_percentage, trigger_type, status}]}' <<<"$SCHEDULE"
```
<!-- expect: "status":"draft" -->
<!-- expect: "trigger_type":"manual","status":"pending" -->

The API answers `201 Created`. A new schedule is a `draft`, and every stage is `pending`:

```json
{"status":"draft","stages":[{"stage_order":1,"target_percentage":10,"trigger_type":"manual","status":"pending"},{"stage_order":2,"target_percentage":50,"trigger_type":"time_based","status":"pending"},{"stage_order":3,"target_percentage":100,"trigger_type":"manual","status":"pending"}]}
```

The response also carries the schedule's `id`, `feature_flag_id`, `owner_id`, dates and
settings, and each stage's `id`. A schedule is refused with `422` when its target
percentages decrease, or when its stage orders aren't 1, 2, 3 and so on without gaps.

### Step 4: Activate the schedule

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/rollout-schedules/$SCHEDULE_ID/activate \
  -H "Authorization: Bearer $TOKEN" | jq .status
```
<!-- expect: "active" -->

It prints `"active"`. From now on the scheduler starts each time-based stage once its
`start_date` has passed. Activating a schedule doesn't change the flag: it is still at 0%.

---

## Rollout Stages

### Target Percentage

Each stage has a `target_percentage`: the rollout percentage the flag is set to when that
stage starts. Percentages must not decrease from one stage to the next.

- Valid: 10 → 50 → 100.
- Invalid: 10 → 50 → 25.

### Trigger Types

| Trigger Type | Description |
|--------------|-------------|
| `time_based` | The stage starts automatically once the current time passes its `start_date`. A time-based stage with no `start_date` starts on the scheduler's next pass. |
| `manual` | The stage starts only when you advance it. |
| `metric_based` | Accepted, but not implemented in this release: such a stage never starts by itself. |

### Stage Lifecycle

```text
pending → in_progress → completed
```

When a stage starts, it becomes `in_progress` and the flag's rollout percentage is set to
the stage's target. When the scheduler starts the next stage, the previous one becomes
`completed`.

---

## Time-Based Triggers

For `time_based` stages, set a `start_date` in UTC, in ISO 8601 form:

```json
{
  "trigger_type": "time_based",
  "start_date": "2027-01-08T00:00:00Z"
}
```

The scheduler checks every 15 minutes, so a stage set for 09:00 UTC may not start until
09:15. Plan your schedule with this buffer in mind.

All dates are in UTC. If your business runs on a specific timezone, convert before setting
dates.

---

## Manual Advancement

Advance a manual stage to start it. This starts the canary:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/rollout-schedules/stages/$CANARY_ID/advance \
  -H "Authorization: Bearer $TOKEN" | jq '{name, status}'

curl -s localhost:8000/api/v1/feature-flags/$FLAG_ID \
  -H "Authorization: Bearer $TOKEN" | jq .rollout_percentage
```
<!-- expect: "status": "in_progress" -->
<!-- expect: 10 -->

The stage is `in_progress`, and the flag is now at `10`%.

The advance takes effect at once, and the schedule must be active. Only a manual stage can
be advanced; advancing a time-based one answers `400`. A manual advance is not held back by
the earlier stages or by `min_stage_duration`: advancing the 100% stage first would put the
flag at 100% at once. `min_stage_duration` (in hours) applies only to the stages the
scheduler starts.

Manual stages are recommended for the final rollout to 100%: they serve as a human approval
gate before full deployment.

---

## Pausing a Schedule

If you observe problems during a rollout, pause the schedule to stop the automatic stages:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/rollout-schedules/$SCHEDULE_ID/pause \
  -H "Authorization: Bearer $TOKEN" | jq .status
```
<!-- expect: "paused" -->

It prints `"paused"`. Pausing does not change the flag's current rollout percentage; it only
stops future stage transitions. When you have investigated and resolved the issue, resume the
schedule by activating it again:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/rollout-schedules/$SCHEDULE_ID/activate \
  -H "Authorization: Bearer $TOKEN" | jq .status
```
<!-- expect: "active" -->

It prints `"active"`.

---

## Monitoring Progress

### View Schedule Status

```{.bash exec}
curl -s localhost:8000/api/v1/rollout-schedules/$SCHEDULE_ID \
  -H "Authorization: Bearer $TOKEN" \
  | jq -c '{status, stages: [.stages[] | {name, target_percentage, status}]}'
```
<!-- expect: "name":"Initial Canary","target_percentage":10,"status":"in_progress" -->

```json
{"status":"active","stages":[{"name":"Initial Canary","target_percentage":10,"status":"in_progress"},{"name":"Expanded Rollout","target_percentage":50,"status":"pending"},{"name":"Full Rollout","target_percentage":100,"status":"pending"}]}
```

To list every schedule for a flag, filter the collection by `feature_flag_id`:

```{.bash exec}
curl -s "localhost:8000/api/v1/rollout-schedules/?feature_flag_id=$FLAG_ID" \
  -H "Authorization: Bearer $TOKEN" | jq .total
```
<!-- expect: 1 -->

It prints `1`. The response is `{"items": [...], "total", "skip", "limit"}`.

---

## Cancelling a Schedule

To stop a rollout entirely:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/rollout-schedules/$SCHEDULE_ID/cancel \
  -H "Authorization: Bearer $TOKEN" | jq .status
```
<!-- expect: "cancelled" -->

It prints `"cancelled"`. The flag's current rollout percentage is not changed. To roll back,
change the flag itself (see [Creating Feature Flags](create.md)).

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

Roll out first to internal users (with targeting rules), then to beta users, then to
everyone. Change the flag's targeting rules between the stages:

| Stage | Target % | Targeting Rule | Trigger |
|-------|----------|---------------|---------|
| Internal | 100% | `email ends_with @yourcompany.com` | Manual |
| Beta | 100% | `plan equals beta` | Manual |
| GA | 100% | No rule (all users) | Manual |

---

## Common Gotchas

- Rollout percentages must not decrease across stages.
- You cannot delete stages from an active schedule: cancel the schedule first.
- Stage orders must be sequential (1, 2, 3, with no gaps).
- Time-based `start_date` values are in UTC.
- Manual stages must be advanced explicitly: they never start by themselves, even after the
  schedule's `end_date`.
- A manual advance takes effect at once, whatever the earlier stages and
  `min_stage_duration` say.
