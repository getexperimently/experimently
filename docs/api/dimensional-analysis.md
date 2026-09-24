# Dimensional Analysis & Segment Breakdown (Issue #28)

Dimensional analysis breaks experiment results down by user segments (e.g., by device, country, plan tier, browser) to reveal heterogeneous treatment effects (HTE) — cases where the treatment works differently for different groups.

---

## Overview

When you run an experiment, the top-level result shows the average effect across all users. Dimensional analysis answers: **"Did the effect differ by segment?"**

This is useful for:
- Discovering that a feature performs well for mobile users but poorly for desktop
- Identifying segments where the treatment has a negative effect (safety check)
- Informing rollout decisions (e.g., roll out to the winning segment first)

---

## Statistical Approach

### Bonferroni Correction

When testing multiple segments simultaneously, running standard p-value tests at `α = 0.05` per segment inflates the overall false positive rate. The service applies **Bonferroni correction**:

```
adjusted_alpha = base_alpha / num_segments
```

For example, testing 10 segments at `α = 0.05` gives an adjusted threshold of `α = 0.005` per segment.

All segment results are marked `is_exploratory: true` — they should be treated as hypothesis-generating, not confirmatory. A significant segment finding should be validated with a dedicated follow-up experiment.

### HTE Detection

Heterogeneous treatment effect detection flags cases where the treatment effect differs significantly across segments. This uses a chi-squared test on the segment-level effect estimates.

---

## API Reference

### GET /api/v1/experiments/{experiment_id}/segmented-results/{segment_by}

Returns per-segment breakdowns for the experiment results.

**Query Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `dimension` | string | ✅ | Dimension to break down by (e.g. `device`, `country`, `plan`) |
| `metric_id` | UUID | ❌ | Metric to analyze. Defaults to the experiment's primary metric |
| `base_alpha` | float | ❌ | Base significance threshold before Bonferroni correction. Default: `0.05` |

**Example Request**

```bash
curl -X GET "http://localhost:8000/api/v1/results/exp-uuid/breakdown?dimension=device" \
  -H "Authorization: Bearer $TOKEN"
```

**Example Response**

```json
{
  "experiment_id": "exp-uuid",
  "dimension": "device",
  "base_alpha": 0.05,
  "num_segments": 3,
  "adjusted_alpha": 0.0167,
  "segments": [
    {
      "segment_value": "mobile",
      "sample_size": 8420,
      "adjusted_alpha": 0.0167,
      "is_exploratory": true,
      "variants": [
        {
          "variant_id": "ctrl-uuid",
          "variant_name": "control",
          "is_control": true,
          "sample_size": 4210,
          "conversions": 421,
          "mean": 0.100,
          "confidence_interval": [0.091, 0.109],
          "p_value": null,
          "is_significant": false
        },
        {
          "variant_id": "var-uuid",
          "variant_name": "treatment",
          "is_control": false,
          "sample_size": 4210,
          "conversions": 548,
          "mean": 0.130,
          "confidence_interval": [0.120, 0.140],
          "p_value": 0.0001,
          "is_significant": true
        }
      ]
    },
    {
      "segment_value": "desktop",
      "sample_size": 6200,
      "adjusted_alpha": 0.0167,
      "is_exploratory": true,
      "variants": [...]
    }
  ]
}
```

---

## Reading the Results

1. **`adjusted_alpha`** is the per-segment significance threshold after Bonferroni correction. A segment is `is_significant: true` only if its p-value is below this threshold.

2. **`is_exploratory: true`** on all segments means treat findings as signals, not conclusions. Run a dedicated follow-up experiment to confirm.

3. **Segments with small sample sizes** (< ~200 per variant) will rarely show significance even with large effects. The p-values are still valid but the confidence intervals will be wide.

---

## Common Dimensions

| Dimension Key | Example Values |
|---------------|---------------|
| `device` | `mobile`, `desktop`, `tablet` |
| `country` | `US`, `GB`, `DE` |
| `plan` | `free`, `pro`, `enterprise` |
| `browser` | `chrome`, `safari`, `firefox` |
| `new_user` | `true`, `false` |

Dimension data must be included in the event tracking payload as user properties for the breakdown to be available.

---

## Permissions

- **VIEWER**: ✅ Read access
- **ANALYST**: ✅ Read access
- **DEVELOPER**: ✅ Read access
- **ADMIN**: ✅ Full access
