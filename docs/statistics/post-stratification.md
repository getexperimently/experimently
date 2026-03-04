# Post-Stratification Variance Reduction

Post-stratification is a statistical technique that reduces the variance of experiment
effect estimates by reweighting stratum-specific means to match the population stratum
proportions. It is particularly powerful when treatment and control group sizes differ
within strata — a situation where CUPED is less effective.

## When to Use Post-Stratification

Use post-stratification when:

- **Stratum sizes are imbalanced**: Control and treatment groups have different proportions
  of users from each stratum (e.g., 70% US in control vs. 40% US in treatment).
- **Strata are correlated with the metric**: The stratum assignment (country, device type,
  user tier) predicts the metric outcome. The higher this correlation, the larger the
  variance reduction.
- **You have discrete categorical covariates**: Post-strat works on categorical groupings,
  whereas CUPED works on continuous pre-experiment covariates.
- **You have at least 2 observations per stratum per group**: Below this threshold the
  within-stratum variance estimate is unstable.

### Comparison with CUPED

| Property | CUPED | Post-Stratification |
|---|---|---|
| Covariate type | Continuous (pre-exp metric) | Categorical (country, device) |
| Bias correction for imbalance | No | Yes (reweights by population) |
| Variance reduction mechanism | Regression adjustment | Reweighting |
| Best when | Pre-exp data available | Stratum sizes differ by group |
| Minimum data per stratum | N/A | 2 per group |

## Mathematical Formulation

### Horvitz-Thompson Estimator

Let $h = 1, \ldots, H$ index strata. Define:

- $W_h = N_h / N$ — population weight of stratum $h$ (estimated from the combined sample)
- $\bar{Y}_{g,h}$ — sample mean of the outcome in group $g \in \{\text{ctrl}, \text{trt}\}$ within stratum $h$
- $n_{g,h}$ — number of observations in group $g$, stratum $h$
- $s^2_{g,h}$ — sample variance (ddof=1) in group $g$, stratum $h$

The post-stratified mean for group $g$:

$$\hat{\mu}_g = \sum_{h=1}^{H} W_h \bar{Y}_{g,h}$$

The treatment effect estimate:

$$\hat{\delta} = \hat{\mu}_\text{trt} - \hat{\mu}_\text{ctrl}$$

### Variance (Cochran's Formula)

$$\text{Var}(\hat{\delta}) = \sum_{h=1}^{H} W_h^2 \left( \frac{s^2_{\text{ctrl},h}}{n_{\text{ctrl},h}} + \frac{s^2_{\text{trt},h}}{n_{\text{trt},h}} \right)$$

### Variance Reduction

$$\text{VR} = \frac{\text{SE}^2_\text{naive} - \text{SE}^2_\text{poststrat}}{\text{SE}^2_\text{naive}} \times 100\%$$

where the naive SE uses the overall (unstratified) variances.

### Inference

- **z-statistic**: $z = \hat{\delta} / \hat{\text{SE}}$
- **p-value**: Two-tailed from $N(0,1)$
- **95% CI**: $\hat{\delta} \pm z_{1-\alpha/2} \cdot \hat{\text{SE}}$

## Required Data Format

Both `control_data` and `treatment_data` must be pandas DataFrames with:

| Column | Type | Description |
|---|---|---|
| `metric_value` | float | Outcome metric per user (or custom `metric_col`) |
| `<stratum_col>` | str/category | Stratum identifier(s) |

Example:

```python
import pandas as pd

control_df = pd.DataFrame({
    "metric_value": [10.2, 9.8, 11.5, 8.9, ...],
    "country": ["US", "US", "UK", "DE", ...],
    "device": ["mobile", "desktop", "mobile", "mobile", ...],
})

treatment_df = pd.DataFrame({
    "metric_value": [10.8, 10.3, 12.1, 9.5, ...],
    "country": ["US", "UK", "US", "DE", ...],
    "device": ["mobile", "mobile", "desktop", "desktop", ...],
})
```

## REST API Reference

### POST `/api/v1/results/{experiment_id}/post-stratification`

Compute post-stratification variance-reduced effect estimates for an experiment.

**Request body:**

```json
{
  "stratum_cols": ["country", "device"],
  "metric_col": "metric_value",
  "alpha": 0.05
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `stratum_cols` | `list[str]` | Yes | — | Column names defining strata. Non-empty. |
| `metric_col` | `str` | No | `"metric_value"` | Name of the outcome column. |
| `alpha` | `float` | No | `0.05` | Significance level for CI (exclusive: 0–1). |

**Response (200):**

```json
{
  "metric_name": "metric_value",
  "control_mean": 10.05,
  "treatment_mean": 10.68,
  "effect_size": 0.63,
  "effect_size_relative": 0.063,
  "variance_reduction": 28.4,
  "adjusted_se": 0.095,
  "p_value": 0.0021,
  "confidence_interval": [0.444, 0.816],
  "n_strata": 4,
  "strata_sizes": {
    "US_mobile": 1200,
    "US_desktop": 800,
    "UK_mobile": 600,
    "UK_desktop": 400
  }
}
```

**Error codes:**

| Status | Condition |
|---|---|
| 404 | Experiment not found |
| 422 | Missing/invalid `stratum_cols`, invalid `alpha`, or stratum validation failure |
| 500 | Internal computation error |

## Example Python Usage

```python
import pandas as pd
from backend.app.services.post_stratification_service import PostStratificationService

# Prepare data
control_df = pd.DataFrame({
    "metric_value": control_outcomes,
    "country": control_countries,
    "device": control_devices,
})
treatment_df = pd.DataFrame({
    "metric_value": treatment_outcomes,
    "country": treatment_countries,
    "device": treatment_devices,
})

# Run post-stratification
svc = PostStratificationService()
result = svc.compute(
    control_data=control_df,
    treatment_data=treatment_df,
    stratum_cols=["country", "device"],
    metric_col="metric_value",
    alpha=0.05,
)

print(f"Effect size: {result.effect_size:.4f}")
print(f"p-value: {result.p_value:.4f}")
print(f"95% CI: {result.confidence_interval}")
print(f"Variance reduction: {result.variance_reduction:.1f}%")
print(f"Number of strata: {result.n_strata}")
```

## Limitations and Gotchas

1. **Minimum stratum size**: Each stratum must have at least 2 observations in each group.
   Merge sparse strata before calling the service.
2. **Empty strata**: Strata that appear in one group but not the other are not supported.
   The service raises `ValueError` for stratum size violations.
3. **Multiple stratum columns create interaction strata**: `["country", "device"]` creates
   `N_country × N_device` strata — make sure each combination has sufficient data.
4. **Single stratum degenerates to Welch's t-test**: With `n_strata=1`, variance reduction
   is 0% (no gain from stratification).
5. **Continuous covariates**: For continuous pre-experiment metrics use CUPED instead.
