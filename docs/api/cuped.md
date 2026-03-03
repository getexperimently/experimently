# CUPED Variance Reduction

CUPED (Controlled-experiment Using Pre-Experiment Data) reduces the variance of your metric estimates by adjusting for pre-experiment behavior. Lower variance means you reach statistical significance with fewer users — typically 20–40% fewer, depending on how predictive the covariate is.

Reference: Deng, Xu, Kohavi & Walker — *Improving the sensitivity of online controlled experiments by utilizing pre-experiment data* (WSDM 2013).

---

## How It Works

CUPED adjusts each user's observed metric by subtracting a term proportional to their pre-experiment value:

```
Y_cuped = Y - θ × (X - E[X])
```

Where:
- `Y` = observed metric (e.g. revenue in the experiment window)
- `X` = pre-experiment covariate (e.g. revenue in the 2 weeks before experiment)
- `θ` = OLS coefficient (`Cov(Y, X) / Var(X)`) estimated from the control group
- `E[X]` = population mean of the covariate

The adjustment removes the variance explained by `X`, leaving a lower-noise estimate of the treatment effect.

### Winsorization

Extreme outliers can inflate variance and destabilize `θ`. The service supports optional winsorization: values outside the `[lower_pct, upper_pct]` percentile range are clamped before the CUPED adjustment is applied.

---

## API Reference

### GET /api/v1/results/{experiment_id}/cuped

Returns CUPED-adjusted treatment effect estimates alongside the standard (unadjusted) results.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `winsorize` | bool | `false` | Apply winsorization before adjustment |
| `lower_pct` | float | `0.01` | Lower winsorization percentile (1st percentile) |
| `upper_pct` | float | `0.99` | Upper winsorization percentile (99th percentile) |

**Example Request**

```bash
curl -X GET "http://localhost:8000/api/v1/results/exp-uuid/cuped?winsorize=true" \
  -H "Authorization: Bearer $TOKEN"
```

**Example Response**

```json
{
  "experiment_id": "exp-uuid",
  "cuped_results": [
    {
      "variant_id": "variant-uuid",
      "variant_name": "Checkout v2",
      "adjusted_control_mean": 48.21,
      "adjusted_treatment_mean": 51.84,
      "adjusted_effect": 3.63,
      "adjusted_se": 0.91,
      "adjusted_p_value": 0.0002,
      "adjusted_ci": [1.85, 5.41],
      "variance_reduction_pct": 31.4,
      "theta": 0.78
    }
  ],
  "winsorized": true,
  "lower_pct": 0.01,
  "upper_pct": 0.99
}
```

**Response Fields**

| Field | Description |
|-------|-------------|
| `adjusted_effect` | CUPED-adjusted treatment effect (treatment mean − control mean) |
| `adjusted_p_value` | Two-tailed p-value from z-test on the adjusted effect |
| `adjusted_ci` | 95% confidence interval for the adjusted effect |
| `variance_reduction_pct` | % of control variance removed by CUPED. Higher = more sensitive test |
| `theta` | OLS coefficient. Values near 0 mean the covariate is a poor predictor; consider a different covariate |

---

## Choosing a Covariate

The covariate `X` should be:
- **Measured before the experiment starts** — prevents contamination
- **Correlated with the outcome metric** — higher correlation → more variance reduction
- **Available for all users** — users without covariate data are excluded from CUPED analysis

Good covariate examples:
| Outcome Metric | Covariate |
|---------------|-----------|
| Revenue in experiment window | Revenue in prior 2–4 weeks |
| Session duration | Average session duration (pre-experiment) |
| Conversion rate | Prior conversion rate |
| Click-through rate | Prior CTR on similar content |

---

## Interpreting `variance_reduction_pct`

| Value | Interpretation |
|-------|---------------|
| < 10% | Covariate is a weak predictor. Little benefit from CUPED. |
| 10–30% | Moderate benefit. Worth using. |
| 30–60% | Strong benefit. Experiment is significantly more sensitive. |
| > 60% | Excellent covariate. Consider whether the experiment and covariate are too correlated (check for data leakage). |

---

## Permissions

- **VIEWER**: ✅ Read access
- **ANALYST**: ✅ Read access
- **DEVELOPER**: ✅ Read access
- **ADMIN**: ✅ Full access
