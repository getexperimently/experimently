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

## API Reference

### GET /api/v1/results/{experiment_id}/sequential

Returns the full sequential analysis for an experiment.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `method` | `msprt` \| `always_valid` | `msprt` | Sequential testing method |
| `alpha` | float | `0.05` | Significance level |
| `spending_function` | `obrien_fleming` \| `pocock` | `obrien_fleming` | Alpha spending function |
| `num_looks` | int | `5` | Number of planned interim analyses |

**Example Request**

```bash
curl -X GET "http://localhost:8000/api/v1/results/exp-uuid/sequential?method=msprt&alpha=0.05" \
  -H "Authorization: Bearer $TOKEN"
```

**Example Response**

```json
{
  "method": "msprt",
  "msprt_result": {
    "lambda_ratio": 24.3,
    "always_valid_p_value": 0.012,
    "can_stop": true,
    "evidence_strength": "strong_for_effect",
    "boundary": 20.0
  },
  "confidence_sequence": {
    "lower": 0.02,
    "upper": 0.08,
    "width": 0.06,
    "sample_size": 4200
  },
  "evidence_trajectory": [
    {"sample_size": 500, "lambda_ratio": 1.2, "always_valid_p_value": 0.41, "can_stop": false},
    {"sample_size": 2000, "lambda_ratio": 8.1, "always_valid_p_value": 0.09, "can_stop": false},
    {"sample_size": 4200, "lambda_ratio": 24.3, "always_valid_p_value": 0.012, "can_stop": true}
  ],
  "alpha_spending": [
    {"look_number": 1, "cumulative_alpha": 0.001, "boundary_z": 4.88, "boundary_p": 0.001},
    {"look_number": 2, "cumulative_alpha": 0.005, "boundary_z": 3.36, "boundary_p": 0.004}
  ],
  "long_running_risk": {
    "is_at_risk": false,
    "expected_duration_days": 14,
    "actual_duration_days": 10,
    "risk_ratio": 0.71,
    "recommendation": "Experiment is progressing normally."
  },
  "recommended_action": "stop_for_effect"
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

- **VIEWER**: ✅ Read access
- **ANALYST**: ✅ Read access
- **DEVELOPER**: ✅ Read access
- **ADMIN**: ✅ Full access

---

## Common Mistakes

**Don't use sequential testing results as standard p-values in reports.** The `always_valid_p_value` is semantically equivalent but should be labeled as such.

**Don't change the alpha or method mid-experiment.** Fix your parameters before launch.

**Long-running risk is informational only.** An experiment flagged as `is_at_risk` may still be producing valid results — it just indicates the experiment is taking longer than expected given the observed effect size.
