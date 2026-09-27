# Sequential Testing & Early Stopping

Sequential testing lets you continuously monitor experiment results and stop as soon as you have enough evidence — without inflating your false positive rate. Unlike fixed-horizon A/B tests that require a predetermined sample size, sequential methods maintain valid error rates even when you peek at results repeatedly.

---

## When to Use Sequential Testing

| Situation | Use Sequential Testing |
|-----------|----------------------|
| You need results faster than a fixed-horizon test allows | ✅ Yes |
| Traffic is unpredictable and sample size targets are hard to set | ✅ Yes |
| You want to stop early if a treatment is clearly harmful | ✅ Yes |
| You have a strict predetermined sample size and won't peek | ❌ Use standard A/B |
| You need exact p-values for regulatory reporting | ❌ Use standard A/B |

---

## Methods

### mSPRT (mixture Sequential Probability Ratio Test)

The default method. Computes a likelihood ratio (`lambda_ratio`) that accumulates evidence for or against an effect:

- `lambda_ratio > 1/alpha` → strong evidence for an effect, safe to stop
- `lambda_ratio < alpha` → strong evidence for the null, safe to stop for futility
- Otherwise → continue collecting data

The `always_valid_p_value` can be interpreted like a standard p-value at any point without inflating Type I error.

### Always-Valid Confidence Intervals (Confidence Sequences)

A confidence sequence is a confidence interval that is valid at every sample size simultaneously. The interval shrinks as more data is collected. Use this when you want a continuous view of the effect size range, not just a stop/continue decision.

### Alpha Spending (O'Brien-Fleming / Pocock)

For experiments with planned interim analyses, alpha spending functions control how much of the significance budget is used at each look:

- **O'Brien-Fleming**: Conservative early on, uses most alpha at the end. Recommended for most experiments.
- **Pocock**: Equal boundaries at every look. Easier to explain but requires more total sample size.

---

## Turning it on

Sequential testing is set on the experiment, when you create it
(`POST /api/v1/experiments/`) or change it (`PUT /api/v1/experiments/{id}`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sequential_testing_enabled` | bool | `false` | Turns the analysis on |
| `sequential_testing_config.method` | `msprt` \| `always_valid` | `msprt` | Accepted, but has no effect yet: the analysis is always mSPRT with a confidence sequence ([#222](https://github.com/getexperimently/experimently/issues/222)) |
| `sequential_testing_config.tau_squared` | float | `0.001` | The mSPRT mixing parameter, above 0 and at most 1 |
| `sequential_testing_config.spending_function` | `obrien_fleming` \| `pocock` | `obrien_fleming` | Alpha spending function |
| `sequential_testing_config.planned_looks` | int | `10` | Number of planned interim analyses, 1–100 |

The significance level is 0.05; it can't be changed yet (#222).

Run the commands on this page in one terminal, in order, against the stack from the
[Quick Start](../getting-started/quick-start.md). Each uses the shell variables set by the
ones before it. Log in first:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

It prints `"ADMIN"`. The examples use the demo data's `checkout_button_color` experiment,
which is running and has data. This saves its id in `$EXP_ID` and turns sequential testing
on with five planned looks. The collection URL ends with a slash,
`/api/v1/experiments/`; without it the API answers `307`, which `curl` doesn't follow:

```{.bash exec}
EXP_ID=$(curl -s localhost:8000/api/v1/experiments/ \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r '.items[] | select(.key == "checkout_button_color") | .id')

curl -s -o /dev/null -w '%{http_code}\n' -X PUT localhost:8000/api/v1/experiments/$EXP_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "sequential_testing_enabled": true,
    "sequential_testing_config": {"spending_function": "obrien_fleming", "planned_looks": 5}
  }'
```
<!-- expect: 200 -->

It prints `200`. The experiment's own response reports `sequential_testing_enabled` as
`false` whatever is stored ([#197](https://github.com/getexperimently/experimently/issues/197));
the results endpoint below is the one to read.

---

## API Reference

### GET /api/v1/results/{experiment_id}/sequential

Returns the full sequential analysis for an experiment, on its primary metric. It takes
no query parameters. Any logged-in user can read it. It answers `404` with
`"Sequential testing is not enabled for this experiment"` when it is off, and
`"Experiment not found"` when there is no such experiment.

```{.bash exec}
curl -s localhost:8000/api/v1/results/$EXP_ID/sequential \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{method, boundary: .msprt_result.boundary, evidence_strength: .msprt_result.evidence_strength, recommended_action}'
```
<!-- expect: "method": "msprt" -->
<!-- expect: "boundary": 20 -->
<!-- expect: "evidence_strength": -->
<!-- expect: "recommended_action": -->

It prints `"method": "msprt"`, the boundary `20.0` (that is 1/α), the strength of the
evidence so far and the recommended action. `alpha_spending` gives the boundary for the
first of the `planned_looks`; the endpoint doesn't count looks yet, so every request is
treated as the first. A full response, abridged:

```json
{
  "method": "msprt",
  "msprt_result": {
    "lambda_ratio": 5.59,
    "always_valid_p_value": 0.179,
    "can_stop": false,
    "evidence_strength": "inconclusive",
    "boundary": 20.0
  },
  "confidence_sequence": {
    "lower": -0.0687,
    "upper": 0.0869,
    "width": 0.1556,
    "sample_size": 30000
  },
  "evidence_trajectory": [
    {"sample_size": 30000, "lambda_ratio": 5.59, "always_valid_p_value": 0.179, "can_stop": false}
  ],
  "alpha_spending": [
    {"look_number": 1, "cumulative_alpha": 5.7e-10, "boundary_z": 6.198, "boundary_p": 5.7e-10}
  ],
  "long_running_risk": {
    "is_at_risk": false,
    "expected_duration_days": 30,
    "actual_duration_days": 14,
    "risk_ratio": 0.467,
    "recommendation": "Experiment is on track. No action needed."
  },
  "recommended_action": "continue"
}
```

**Evidence Strength Values**

| Value | Meaning |
|-------|---------|
| `strong_for_effect` | Clear effect detected — safe to stop and ship |
| `moderate_for_effect` | Trending positive — consider continuing for confirmation |
| `inconclusive` | Not enough data yet — continue |
| `moderate_for_null` | Trending toward no effect |
| `strong_for_null` | No effect detected — safe to stop for futility |

**Recommended Actions**

| Value | Meaning |
|-------|---------|
| `stop_for_effect` | Stop the experiment; treatment wins |
| `stop_for_futility` | Stop the experiment; no meaningful effect |
| `continue` | Keep running — not enough evidence yet |

---

## Permissions

Any logged-in user can read the results. Changing an experiment's sequential testing
settings is a change to the experiment: an ADMIN can make it on any experiment, while a
DEVELOPER, ANALYST or VIEWER gets `403` on the demo experiment, which another user
created.

---

## Common Mistakes

**Don't use sequential testing results as standard p-values in reports.** The `always_valid_p_value` is semantically equivalent but should be labeled as such.

**Don't change the configuration mid-experiment.** Fix your parameters before launch.

**Long-running risk is informational only.** An experiment flagged as `is_at_risk` may still be producing valid results — it just indicates the experiment is taking longer than expected given the observed effect size.
