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

The method the analysis uses. Computes a likelihood ratio (`lambda_ratio`) that accumulates evidence for an effect:

- `lambda_ratio >= 1/alpha` → strong evidence for an effect, safe to stop (`stop_for_effect`)
- Otherwise → continue collecting data (`continue`)

The mSPRT has no futility boundary, so the analysis never tells you to stop for
futility. An experiment that is running well past its expected duration is flagged
with the advisory `at_risk`, which is not evidence that there is no effect.

The `always_valid_p_value` can be interpreted like a standard p-value at any point without inflating Type I error.

### Always-Valid Confidence Intervals (Confidence Sequences)

A confidence sequence is a confidence interval that is valid at every sample size simultaneously. The interval shrinks as more data is collected. Use this when you want a continuous view of the effect size range, not just a stop/continue decision.

It is the same mSPRT turned into an interval (the normal-mixture confidence sequence
of Johari et al. 2017 and Howard et al. 2021), on the difference in conversion rates
(treatment minus control), with the same alpha and `tau_squared`:

```text
estimate ± sqrt( V (V + τ²) / τ² · (2 ln(1/α) + ln((V + τ²) / V)) )
```

where V is the variance of the estimated difference. Because the interval and the
stop decision share V, τ² and α, they cannot disagree: 0 is outside the interval
exactly when `can_stop` is `true`. At a 10% conversion rate, α = 0.05 and the default
τ² = 0.001, the half-width is about 0.041 at 1,000 users per arm, 0.0136 at 10,000
and 0.00055 at 10 million. Early on it is wider than a fixed-horizon interval: that
is the price of being valid however often you look. A difference in rates cannot
leave `[-1, 1]`, so the interval is clipped to that range: with 10 users per arm at
a 50% rate the formula gives about ±3.92, and the response reports `[-1, 1]`.
Clipping changes neither the stop decision nor coverage, because 0 and the true
difference always lie inside `[-1, 1]`. While an arm has no users, or
the estimated variance is zero (within each arm every user has the same outcome),
nothing bounds the effect and the interval is `[-1, 1]`, the whole range of a
difference in rates; `can_stop` is then `false`.

### Alpha Spending (not computed yet)

A group-sequential design with planned interim analyses (O'Brien-Fleming or Pocock
alpha spending) is not implemented. The boundaries the analysis used to report did
not hold their stated significance level
([#232](https://github.com/getexperimently/experimently/issues/232)), and nothing
counted the looks they were indexed by, so they were removed: `alpha_spending` is
always an empty list. `spending_function` and `planned_looks` are still accepted and
stored. The mSPRT above stays valid however often you read the results, so no
planned-looks table is needed to use it.

---

## Turning it on

Sequential testing is set on the experiment, when you create it
(`POST /api/v1/experiments/`) or change it (`PUT /api/v1/experiments/{id}`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sequential_testing_enabled` | bool | `false` | Turns the analysis on |
| `sequential_testing_config.method` | `msprt` \| `always_valid` | `msprt` | `always_valid` is an alias of `msprt`: the analysis is mSPRT with a confidence sequence, reports `"method": "msprt"`, and says so in `analysis_notice` |
| `sequential_testing_config.alpha` | float | `0.05` | The significance level, above 0 and at most 0.2. The stopping boundary is 1/alpha. A value outside the range is refused with `422` |
| `sequential_testing_config.tau_squared` | float | `0.001` | The mSPRT mixing parameter, above 0 and at most 1 |
| `sequential_testing_config.spending_function` | `obrien_fleming` \| `pocock` | `obrien_fleming` | Accepted and stored; no alpha-spending table is computed yet |
| `sequential_testing_config.planned_looks` | int | `10` | Accepted and stored (1–100); no alpha-spending table is computed yet |

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
one optional query parameter, `alpha`: the significance level for this request, above 0
and at most 0.2, which overrides the stored `sequential_testing_config.alpha` (default
`0.05`); a value outside the range answers `422`. Any logged-in user can read it. It answers `404` with
`"Sequential testing is not enabled for this experiment"` when it is off, and
`"Experiment not found"` when there is no such experiment.

```{.bash exec}
curl -s localhost:8000/api/v1/results/$EXP_ID/sequential \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{method, boundary: .msprt_result.boundary, evidence_strength: .msprt_result.evidence_strength, recommended_action, at_risk, alpha_spending, analysis_status}'

curl -s "localhost:8000/api/v1/results/$EXP_ID/sequential?alpha=0.01" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{boundary_at_alpha_001: .msprt_result.boundary}'
```
<!-- expect: "method": "msprt" -->
<!-- expect: "boundary": 20 -->
<!-- expect: "evidence_strength": -->
<!-- expect: "recommended_action": -->
<!-- expect: "at_risk": -->
<!-- expect: "alpha_spending": [] -->
<!-- expect: "analysis_status": "beta" -->
<!-- expect: "boundary_at_alpha_001": 100 -->

It prints `"method": "msprt"`, the boundary `20.0` (that is 1/α at the default α of
0.05), the strength of the evidence so far, the recommended action, the advisory
`at_risk`, an empty `alpha_spending` and `"analysis_status": "beta"`. The second request
asks for α = 0.01, so its boundary is `100.0`. A full response, abridged:

```json
{
  "method": "msprt",
  "msprt_result": {
    "lambda_ratio": 5.73,
    "always_valid_p_value": 0.174,
    "can_stop": false,
    "evidence_strength": "inconclusive",
    "boundary": 20.0
  },
  "confidence_sequence": {
    "lower": -0.0015,
    "upper": 0.0215,
    "width": 0.0230,
    "sample_size": 30000
  },
  "evidence_trajectory": [
    {"sample_size": 30000, "lambda_ratio": 5.73, "always_valid_p_value": 0.174, "can_stop": false}
  ],
  "alpha_spending": [],
  "long_running_risk": {
    "is_at_risk": false,
    "expected_duration_days": 30,
    "actual_duration_days": 14,
    "risk_ratio": 0.467,
    "recommendation": "Experiment is on track. No action needed."
  },
  "recommended_action": "continue",
  "at_risk": false,
  "analysis_status": "beta",
  "analysis_notice": "Beta: the stop/continue decision is mSPRT alone, at the significance level shown by the boundary (1/alpha). alpha_spending is always empty: the planned-looks (alpha-spending) table is not computed yet. https://github.com/getexperimently/experimently/issues/232"
}
```

`analysis_status` is `"beta"` while part of the analysis is not computed yet (here the
alpha-spending table), and
`analysis_notice` then says what; when the status is `"ga"` the notice is `null`. If the
experiment's method is stored as `always_valid`, the notice adds that it is an alias of
`msprt`.

**Evidence Strength Values**

| Value | Meaning |
|-------|---------|
| `strong_for_effect` | Clear effect detected — safe to stop and ship |
| `moderate_for_effect` | Trending positive — consider continuing for confirmation |
| `inconclusive` | Not enough data yet — continue |
| `moderate_for_null` | Trending toward no effect |
| `strong_for_null` | Evidence leans strongly toward no effect. Not a stopping rule |

**Recommended Actions**

| Value | Meaning |
|-------|---------|
| `stop_for_effect` | The mSPRT crossed its boundary (1/alpha): stop, there is an effect |
| `continue` | Keep running — not enough evidence yet |
| `stop_for_futility` | Kept in the value set, but not returned by the current analysis: the mSPRT has no futility boundary. A long-running experiment is flagged with `at_risk` instead |

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

**Long-running risk is informational only.** An experiment flagged `at_risk` (the same value as `long_running_risk.is_at_risk`) may still be producing valid results. It means the experiment is running well past its expected duration or collecting samples slowly, not that there is no effect.
