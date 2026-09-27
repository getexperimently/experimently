# CUPED Variance Reduction

CUPED (Controlled-experiment Using Pre-Experiment Data) reduces the variance of your metric estimates by adjusting for pre-experiment behavior. Lower variance means you reach statistical significance with fewer users — typically 20–40% fewer, depending on how predictive the covariate is.

Reference: Deng, Xu, Kohavi & Walker — *Improving the sensitivity of online controlled experiments by utilizing pre-experiment data* (WSDM 2013).

**Not yet a pre-experiment covariate.** In this release the endpoint below uses each
user's position in the order of assignment as the covariate, not a pre-experiment metric,
so it removes almost no variance: `variance_reduction_pct` is close to 0 and `cuped`
gives the same numbers as `winsorization`
([#217](https://github.com/getexperimently/experimently/issues/217)). The method below
describes what CUPED does; the response shape is the one the API returns today.

---

## How It Works

CUPED adjusts each user's observed metric by subtracting a term proportional to their pre-experiment value:

```text
Y_cuped = Y - θ × (X - E[X])
```

Where:
- `Y` = observed metric (e.g. revenue in the experiment window)
- `X` = pre-experiment covariate (e.g. revenue in the 2 weeks before experiment)
- `θ` = OLS coefficient (`Cov(Y, X) / Var(X)`) estimated from the control group
- `E[X]` = population mean of the covariate

The adjustment removes the variance explained by `X`, leaving a lower-noise estimate of the treatment effect.

### Winsorization

Extreme outliers can inflate variance and destabilize `θ`. With the `winsorization`
method, values above `winsorization_percentile` are clipped to that percentile before the
effect is computed.

---

## Choosing the method

The method is part of the experiment, in its `variance_reduction_config`, set when you
create it (`POST /api/v1/experiments/`) or change it (`PUT /api/v1/experiments/{id}`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `method` | string | `none` | `none`, `cuped`, `cuped_plus` or `winsorization` |
| `covariate_metric_id` | string | `null` | The pre-experiment metric to use as the covariate (not read yet, #217) |
| `covariate_lookback_days` | int | `7` | Days of pre-experiment data, 1–90 (not read yet, #217) |
| `winsorization_percentile` | float | `99.0` | The percentile above which values are clipped, 50–100 |

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

It prints `"ADMIN"`. The examples use the demo data's `checkout_button_color` experiment.
This saves its id in `$EXP_ID`, and sets its method to `winsorization` at the 99th
percentile. The collection URL ends with a slash, `/api/v1/experiments/`; without it the
API answers `307`, which `curl` doesn't follow:

```{.bash exec}
EXP_ID=$(curl -s localhost:8000/api/v1/experiments/ \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r '.items[] | select(.key == "checkout_button_color") | .id')

curl -s -o /dev/null -w '%{http_code}\n' -X PUT localhost:8000/api/v1/experiments/$EXP_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"variance_reduction_config": {"method": "winsorization", "winsorization_percentile": 99}}'
```
<!-- expect: 200 -->

It prints `200`. The experiment's own response reports `variance_reduction_config` as
`null` whatever is stored ([#197](https://github.com/getexperimently/experimently/issues/197)):
the results below say which method was applied.

---

## API Reference

### GET /api/v1/results/{experiment_id}/cuped

Returns the adjusted treatment effect for each of the experiment's metrics, comparing the
control with the first treatment variant. It takes no query parameters: the method comes
from the experiment. Any logged-in user can read it; an experiment that doesn't exist
answers `404`.

```{.bash exec}
curl -s localhost:8000/api/v1/results/$EXP_ID/cuped \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{method, metrics: [.metrics[] | {metric_name, method, adjusted_effect, adjusted_p_value}]}'
```
<!-- expect: "method": "winsorization" -->
<!-- expect: "metric_name": "Checkout Completion" -->

It prints `"method": "winsorization"` and the adjusted effect on the experiment's
`Checkout Completion` metric. The full response:

```json
{
  "experiment_id": "f39b72eb-7173-49f7-bbd1-9fc01d381778",
  "method": "winsorization",
  "metrics": [
    {
      "metric_id": "98f7219e-fd54-4acc-96ee-4b76892af3b1",
      "metric_name": "Checkout Completion",
      "adjusted_control_mean": 0.0797,
      "adjusted_treatment_mean": 0.0891,
      "adjusted_effect": 0.0094,
      "adjusted_se": 0.0032,
      "adjusted_p_value": 0.0035,
      "adjusted_ci_lower": 0.0031,
      "adjusted_ci_upper": 0.0156,
      "variance_reduction_pct": 0.0002,
      "theta": 8.7e-08,
      "method": "winsorization"
    }
  ],
  "computed_at": "2026-09-26T22:54:12.480010+00:00",
  "seed": null,
  "n_samples": null,
  "engine_version": "1.1.0"
}
```

**Response Fields**

| Field | Description |
|-------|-------------|
| `adjusted_effect` | Adjusted treatment effect (treatment mean − control mean) |
| `adjusted_p_value` | Two-tailed p-value from a z-test on the adjusted effect |
| `adjusted_ci_lower`, `adjusted_ci_upper` | 95% confidence interval for the adjusted effect |
| `variance_reduction_pct` | % of control variance removed by the adjustment. Higher = more sensitive test |
| `theta` | OLS coefficient. Values near 0 mean the covariate is a poor predictor |

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

Any logged-in user can read the results. Changing an experiment's
`variance_reduction_config` is a change to the experiment: an ADMIN can make it on any
experiment, while a DEVELOPER, ANALYST or VIEWER gets `403` on the demo experiment, which
another user created.
