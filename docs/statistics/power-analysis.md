# Statistical Power Analysis

This guide explains how to use the pre-experiment Power Calculator to plan your A/B tests before you launch them.

## What is Statistical Power?

When you run an A/B test, you are trying to detect whether a change (treatment) produces a meaningful difference compared to the baseline (control). Two types of errors can occur:

| Error Type | Description | Probability |
|---|---|---|
| **Type I (false positive)** | You conclude there is an effect when there is none | alpha (significance level) |
| **Type II (false negative)** | You miss a real effect | beta = 1 - power |

**Statistical power** is the probability that your test correctly detects a real effect when one exists. A power of 0.80 means that if the true effect is at least as large as your MDE, you will detect it 80% of the time.

Typical recommended values:
- **Alpha**: 0.05 (5% chance of false positive)
- **Power**: 0.80 (80% chance of detecting a real effect)

---

## The Four Parameters

Every power calculation involves four interdependent parameters. Change one, and the others are affected.

### 1. Baseline Rate

The current performance of your metric before any change. For a conversion rate experiment, this might be 5% (0.05). This must be between 0 and 1 exclusive.

**How to find it**: Use your analytics tool to measure the current metric over the past 4-8 weeks. Use the same time period and user segment you will use in the experiment.

### 2. Minimum Detectable Effect (MDE)

The smallest relative improvement you want to be able to detect. An MDE of 10% on a 5% baseline means you want to detect a lift from 5% to 5.5% (absolute change = 0.5 percentage points).

**How to choose the right MDE**:
- Think about the smallest effect that would be worth launching the feature
- Very small MDEs (< 2%) require extremely large samples
- Very large MDEs (> 30%) are easy to detect but may miss meaningful smaller improvements
- Rule of thumb: start with 10-20% relative MDE for most product experiments

### 3. Significance Level (Alpha)

The acceptable probability of a false positive. The most common value is 0.05 (5%).

- 0.01 → stricter, requires larger sample, fewer false positives
- 0.05 → standard for most product experiments
- 0.10 → more lenient, smaller sample, more false positives

For experiments with multiple variants (A/B/C tests), the platform automatically applies **Bonferroni correction**: alpha is divided by the number of treatment-vs-control comparisons. This keeps the family-wise error rate at the specified alpha level.

### 4. Statistical Power

The probability of detecting a real effect. Standard is 0.80 (80%).

- 0.70 → smaller sample, 30% chance of missing a real effect
- 0.80 → recommended balance
- 0.90 → larger sample, only 10% chance of missing a real effect
- 0.95 → very conservative, requires the largest samples

---

## The Formula

For a two-proportions z-test (the standard for conversion rate experiments), the required sample size per variant is:

```
n = [z_alpha * sqrt(2 * p_bar * (1 - p_bar))
     + z_power * sqrt(p1*(1-p1) + p2*(1-p2))]^2
    / (p2 - p1)^2
```

Where:
- `p1` = baseline rate
- `p2` = baseline rate + (baseline rate * MDE)
- `p_bar` = (p1 + p2) / 2
- `z_alpha` = `norm.ppf(1 - alpha/2)` for two-tailed (e.g. 1.96 for alpha=0.05)
- `z_power` = `norm.ppf(power)` (e.g. 0.842 for power=0.80)

This is the **Fleiss (2003)** formula, which is more accurate than the simpler pooled formula for small proportions.

**Verification example** for `baseline=0.05, MDE=10% relative, alpha=0.05, power=0.80`:
- `p1 = 0.05`, `p2 = 0.055`, `p_bar = 0.0525`
- `z_alpha = 1.9600`, `z_power = 0.8416`
- `n ≈ 31,234 per variant` (31,234 control + 31,234 treatment = 62,468 total)

---

## Runtime Estimation

Once you have the required sample size per variant, you can estimate the runtime:

```
daily_per_variant = daily_traffic * traffic_allocation / n_variants
days = required_sample_size / daily_per_variant
```

**Example**: You need 31,234 per variant, have 10,000 daily users, 50% traffic allocation, 2 variants:
- `daily_per_variant = 10,000 * 0.50 / 2 = 2,500`
- `days = 31,234 / 2,500 = 12.5 days`

---

## Runtime vs. Rigor Trade-off

Longer experiments are more statistically rigorous but slower to reach a decision. Here are practical guidelines:

| Runtime | Assessment | Action |
|---|---|---|
| < 7 days | Excellent | Run the experiment |
| 7–30 days | Acceptable | Standard experimentation window |
| 30–90 days | Long | Consider optimizations (see below) |
| > 90 days | Very long | Reduce scope or use sequential testing |

### How to Reduce Runtime

If your estimated runtime is too long, you have several options:

1. **Increase traffic allocation**: Expose a larger fraction of your users to the experiment.

2. **Increase the MDE**: Accept a larger minimum effect. If a 5% lift is enough to launch, you do not need to detect a 2% lift.

3. **Apply CUPED variance reduction**: Use pre-experiment covariate data to reduce metric variance. This can reduce required sample size by 20-40%. See the [CUPED guide](../api/cuped.md).

4. **Use sequential testing (mSPRT)**: Instead of a fixed sample, check results continuously with a valid stopping rule. You may stop early when significance is reached, potentially cutting runtime in half. See [Statistical Methods](../api/sequential-testing.md).

5. **Focus on a high-volume segment**: Run the experiment on the user segment most likely to exhibit the effect, where you have the most traffic.

---

## Multi-Variant Experiments

When you have more than 2 variants (e.g. A/B/C), the platform applies **Bonferroni correction** to control the family-wise error rate:

```
corrected_alpha = alpha / (n_variants - 1)
```

For a 3-variant experiment with alpha=0.05:
- `corrected_alpha = 0.05 / 2 = 0.025`
- This increases the required sample size per variant

This is the most conservative correction. For large numbers of variants, you may prefer Benjamini-Hochberg (BH) FDR correction — see the [FDR Correction guide](fdr-correction.md).

---

## Minimum Detectable Effect (MDE) Calculator

If you have a fixed sample size available (e.g. 2 weeks of traffic at 50% allocation), you can use the **MDE calculator** to find the smallest effect you can detect:

`POST /api/v1/power/mde`

The service uses binary search to find the relative MDE that requires exactly the given sample size. This is the **inverse** of the sample size calculation and is useful when you have budget constraints.

---

## When to Use Sequential Testing Instead

Consider sequential testing (mSPRT) rather than fixed-sample testing when:
- Your estimated runtime is > 14 days
- You want to make a go/no-go decision as soon as possible
- You have variable traffic (e.g. weekday/weekend patterns)
- The cost of running a harmful experiment outweighs the cost of false positives

See [Statistical Methods](../api/sequential-testing.md) for details on mSPRT and early stopping.

---

## REST API Reference

All endpoints are unauthenticated (no login required). They perform pure computation with no database access.

### POST /api/v1/power/sample-size

Compute the required sample size per variant.

**Request body**:
```json
{
  "baseline_rate": 0.05,
  "minimum_detectable_effect": 0.10,
  "alpha": 0.05,
  "power": 0.80,
  "n_variants": 2,
  "two_tailed": true,
  "metric_type": "proportion",
  "daily_traffic": 10000,
  "traffic_allocation": 0.5
}
```

**Response**:
```json
{
  "per_variant": 31234,
  "total": 62468,
  "alpha": 0.05,
  "power": 0.8,
  "baseline_rate": 0.05,
  "mde_absolute": 0.005,
  "mde_relative": 0.1,
  "confidence_level": 0.95,
  "runtime_days": 12.5,
  "n_variants": 2,
  "two_tailed": true,
  "metric_type": "proportion"
}
```

### POST /api/v1/power/mde

Given a fixed sample size per variant, compute the minimum detectable effect.

**Request body**:
```json
{
  "sample_size_per_variant": 31234,
  "baseline_rate": 0.05,
  "alpha": 0.05,
  "power": 0.80,
  "n_variants": 2,
  "two_tailed": true
}
```

**Response**:
```json
{
  "mde_absolute": 0.005,
  "mde_relative": 0.1,
  "per_variant_sample": 31234,
  "total_sample": 62468,
  "alpha": 0.05,
  "power": 0.8,
  "n_variants": 2,
  "two_tailed": true
}
```

### POST /api/v1/power/runtime

Estimate how many days it will take to collect the required sample size.

**Request body**:
```json
{
  "required_sample_size": 31234,
  "daily_traffic": 10000,
  "traffic_allocation": 0.5,
  "n_variants": 2
}
```

**Response**:
```json
{
  "days_to_significance": 12.49,
  "weeks_to_significance": 1.78,
  "daily_traffic_per_variant": 2500,
  "confidence_interval_days": [6.68, 18.31]
}
```

### GET /api/v1/power/curve

Return the power curve — sample size required per variant for a range of effect sizes.

**Query parameters**: `baseline`, `alpha`, `power`, `mde` (optional, marks a point)

**Example**: `GET /api/v1/power/curve?baseline=0.05&alpha=0.05&power=0.80&mde=0.10`

**Response**:
```json
{
  "points": [
    {"effect_size_relative": 0.01, "sample_size_per_variant": 3122837, "is_current_target": false},
    {"effect_size_relative": 0.10, "sample_size_per_variant": 31234, "is_current_target": true},
    {"effect_size_relative": 0.50, "sample_size_per_variant": 1151, "is_current_target": false}
  ],
  "baseline_rate": 0.05,
  "alpha": 0.05,
  "power_target": 0.80
}
```

### POST /api/v1/power/plan

Generate plain-English planning advice using Claude AI (falls back to built-in templates).

**Request body**:
```json
{
  "experiment_name": "Checkout CTA Button Test",
  "metric_description": "checkout conversion rate from cart page",
  "baseline_rate": 0.05,
  "mde": 0.10,
  "runtime_days": 12.5,
  "business_context": "Q4 launch, mobile-only segment"
}
```

**Response**:
```json
{
  "advice": "Your power analysis for 'Checkout CTA Button Test' targets a 10.0% relative lift...",
  "generated_by": "template",
  "experiment_name": "Checkout CTA Button Test",
  "baseline_rate": 0.05,
  "mde": 0.10,
  "runtime_days": 12.5
}
```

---

## Python SDK Example

```python
import requests

# Compute sample size
response = requests.post(
    "https://api.yourplatform.com/api/v1/power/sample-size",
    json={
        "baseline_rate": 0.05,
        "minimum_detectable_effect": 0.10,
        "alpha": 0.05,
        "power": 0.80,
        "n_variants": 2,
        "daily_traffic": 10000,
        "traffic_allocation": 0.5,
    }
)
result = response.json()
print(f"Need {result['per_variant']:,} users per variant")
print(f"Estimated runtime: {result['runtime_days']:.1f} days")
```

---

## Further Reading

- [CUPED Variance Reduction](../api/cuped.md) — reduce required sample size by 20-40%
- [Sequential Testing](../api/sequential-testing.md) — stop experiments early when significance is reached
- [Post-Stratification](post-stratification.md) — another variance reduction technique
- [Multi-Armed Bandits](../api/multi-armed-bandit.md) — when to use exploration instead of hypothesis testing
- [Interaction Detection](../api/interaction-detection.md) — avoid bias from experiment overlap
