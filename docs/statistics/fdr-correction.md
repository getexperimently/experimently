# Benjamini-Hochberg FDR Correction

The Benjamini-Hochberg (BH) procedure controls the **False Discovery Rate (FDR)** — the
expected proportion of false positives among all rejected hypotheses — when testing
multiple metrics simultaneously. It is less conservative than Bonferroni while still
providing strong statistical guarantees.

## Why FDR is Better Than Bonferroni for Many Metrics

When an experiment measures 10 or more metrics, Bonferroni correction becomes extremely
conservative: it controls the **Family-Wise Error Rate (FWER)** — the probability of
even *one* false positive — at the cost of almost never detecting true effects.

| Property | Bonferroni | BH FDR |
|---|---|---|
| Controls | FWER (any false positive) | FDR (proportion of false positives) |
| Threshold per metric | $\alpha / m$ | $k/m \times \alpha$ (rank-dependent) |
| Recommended for | 1–4 metrics | 5+ metrics |
| Power (sensitivity) | Low for many tests | Higher |
| False positives | Nearly zero | At most $\alpha$ proportion |

**Rule of thumb**: Use Bonferroni for $\leq 4$ metrics; use BH FDR for $\geq 5$ metrics.

## The BH Procedure

Given $m$ raw p-values $p_1, p_2, \ldots, p_m$ and a desired FDR threshold $\alpha$:

1. **Sort** p-values ascending: $p_{(1)} \leq p_{(2)} \leq \cdots \leq p_{(m)}$.
2. **Compute** the BH threshold for rank $k$: $T_k = \frac{k}{m} \times \alpha$.
3. **Find** the largest rank $k^*$ such that $p_{(k^*)} \leq T_{k^*}$.
4. **Reject** all hypotheses with rank $\leq k^*$ (declare significant).

### Example

10 p-values with $\alpha = 0.10$:

| Rank | p-value | BH threshold $k/10 \times 0.10$ | Reject? |
|---|---|---|---|
| 1 | 0.001 | 0.010 | Yes |
| 2 | 0.008 | 0.020 | Yes |
| 3 | 0.039 | 0.030 | No |
| 4 | 0.041 | 0.040 | No |
| 5 | 0.042 | 0.050 | Yes |
| 6 | **0.060** | **0.060** | **Yes** ← largest k* |
| 7 | 0.074 | 0.070 | No |
| 8 | 0.205 | 0.080 | No |
| 9 | 0.212 | 0.090 | No |
| 10 | 0.391 | 0.100 | No |

Result: Reject 6 hypotheses (all with rank $\leq 6$), even though ranks 3–5 individually
don't satisfy their per-rank threshold — the step-up property means we look for the
largest k, so ranks 1, 2, 5, 6 passing brings along ranks 3 and 4.

At $\alpha = 0.05$ with the same p-values, only 2 are significant
(k=1: 0.001≤0.005 ✓, k=2: 0.008≤0.010 ✓, k=3: 0.039>0.015 ✗).

### Adjusted P-values (Holm Step-Up Formula)

The BH-adjusted p-value for rank $k$ is:

$$p_{\text{adj}}(k) = \min\left(\frac{p_{(k)} \cdot m}{k},\ 1.0\right)$$

with monotonicity enforced from right to left:
$$p_{\text{adj,mono}}(k) = \min\left(p_{\text{adj}}(k),\ p_{\text{adj,mono}}(k+1)\right)$$

A metric is significant when $p_{\text{adj,mono}}(k) < \alpha$.

## When to Use BH vs. Bonferroni

| Situation | Recommendation |
|---|---|
| 1–4 primary metrics (confirmatory) | Bonferroni or no correction |
| 5–20 metrics (exploratory) | Benjamini-Hochberg FDR |
| Dimensional breakdown (per-segment) | Bonferroni (small number of segments) |
| 20+ metrics or large-scale analysis | Benjamini-Hochberg FDR |
| Sequential / always-valid testing | mSPRT (no multiple-testing correction needed) |

## REST API Reference

### POST `/api/v1/results/{experiment_id}/fdr-correction`

Apply Benjamini-Hochberg FDR correction to per-metric p-values.

**Request body:**

```json
{
  "p_values": {
    "revenue": 0.001,
    "click_through_rate": 0.032,
    "session_duration": 0.08,
    "churn_rate": 0.41,
    "engagement_score": 0.015
  },
  "fdr_threshold": 0.05
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `p_values` | `dict[str, float]` | Yes | — | Metric name → raw p-value. All values in [0,1]. Non-empty. |
| `fdr_threshold` | `float` | No | `0.05` | FDR control level α in [0,1]. |

**Response (200):**

```json
[
  {
    "metric_name": "revenue",
    "raw_p_value": 0.001,
    "adjusted_p_value": 0.005,
    "rank": 1,
    "is_significant": true
  },
  {
    "metric_name": "engagement_score",
    "raw_p_value": 0.015,
    "adjusted_p_value": 0.0375,
    "rank": 2,
    "is_significant": true
  },
  {
    "metric_name": "click_through_rate",
    "raw_p_value": 0.032,
    "adjusted_p_value": 0.0533,
    "rank": 3,
    "is_significant": false
  },
  {
    "metric_name": "session_duration",
    "raw_p_value": 0.08,
    "adjusted_p_value": 0.1,
    "rank": 4,
    "is_significant": false
  },
  {
    "metric_name": "churn_rate",
    "raw_p_value": 0.41,
    "adjusted_p_value": 0.41,
    "rank": 5,
    "is_significant": false
  }
]
```

The response is sorted by rank ascending (smallest raw p-value first).

**Error codes:**

| Status | Condition |
|---|---|
| 404 | Experiment not found |
| 422 | Empty `p_values`, any value outside [0,1], or `fdr_threshold` outside [0,1] |
| 500 | Internal computation error |

## Example Python Usage

```python
from backend.app.services.fdr_correction_service import BenjaminiHochbergService

svc = BenjaminiHochbergService()

p_values = {
    "revenue": 0.001,
    "ctr": 0.032,
    "session_duration": 0.08,
    "churn": 0.41,
    "engagement": 0.015,
}

results = svc.correct(p_values, fdr_threshold=0.05)

for r in results:
    status = "SIGNIFICANT" if r.is_significant else "not significant"
    print(
        f"Rank {r.rank:2d}: {r.metric_name:<20s} "
        f"p={r.raw_p_value:.4f}  adj_p={r.adjusted_p_value:.4f}  {status}"
    )
```

Output:
```
Rank  1: revenue              p=0.0010  adj_p=0.0050  SIGNIFICANT
Rank  2: engagement           p=0.0150  adj_p=0.0375  SIGNIFICANT
Rank  3: ctr                  p=0.0320  adj_p=0.0533  not significant
Rank  4: session_duration     p=0.0800  adj_p=0.1000  not significant
Rank  5: churn                p=0.4100  adj_p=0.4100  not significant
```

## Integration with the Existing Results API

The `GET /api/v1/results/{experiment_id}` endpoint already accepts a
`correction_method` query parameter:

```bash
GET /api/v1/results/{experiment_id}?correction_method=benjamini_hochberg
```

This applies BH correction to per-metric p-values returned in the main results
response when multiple metrics are defined.

The `POST /api/v1/results/{experiment_id}/fdr-correction` endpoint provides finer
control: you supply any set of p-values (from post-stratification, CUPED, or raw
analysis) and receive BH-corrected results immediately.

## References

- Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate: A practical
  and powerful approach to multiple testing. *JRSS-B*, 57(1), 289–300.
- Storey, J. D., & Tibshirani, R. (2003). Statistical significance for genomewide studies.
  *PNAS*, 100(16), 9440–9445.
