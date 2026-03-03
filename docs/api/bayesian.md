# Bayesian Experimentation API

This document describes the full Bayesian experimentation support. When Bayesian analysis is enabled on an experiment, the results endpoint returns a `bayesian_results` block alongside the existing frequentist statistics.

---

## Overview

The platform implements a **Beta-Binomial model** for conversion-rate experiments and a **Normal-Normal conjugate model** for continuous metrics. Posterior credible intervals, Bayes factors (Savage-Dickey density ratio), and a Bayesian stopping rule are provided out of the box.

Key capabilities:

- **Posterior distribution** parameters (`alpha`, `beta`) updated from observed data.
- **Credible intervals** at configurable width (e.g., 95%).
- **Bayes factor (BF10)** via the Savage-Dickey density ratio for hypothesis testing.
- **Probability of superiority** — P(treatment > control).
- **ROPE (Region of Practical Equivalence)** acceptance for declaring practical equivalence.
- **Bayesian stopping rule** — the experiment can be flagged `stopped_early` when the posterior is conclusive and the minimum sample size has been met.

---

## Enabling Bayesian Analysis on an Experiment

### Experiment Create / Update Fields

Add the following fields to the request body of `POST /api/v1/experiments/` or `PUT /api/v1/experiments/{experiment_id}`:

| Field | Type | Default | Description |
|---|---|---|---|
| `bayesian_enabled` | `boolean` | `false` | Activates Bayesian analysis for this experiment |
| `bayesian_config` | `object` | `null` | Configuration object (required when `bayesian_enabled` is `true`) |

**`bayesian_config` Object**

| Field | Type | Default | Description |
|---|---|---|---|
| `prior_alpha` | `float` | `1.0` | Alpha parameter of the Beta prior (successes + 1); must be > 0 |
| `prior_beta` | `float` | `1.0` | Beta parameter of the Beta prior (failures + 1); must be > 0 |
| `rope_low` | `float` | `-0.01` | Lower bound of the Region of Practical Equivalence (relative lift) |
| `rope_high` | `float` | `0.01` | Upper bound of the Region of Practical Equivalence (relative lift) |
| `minimum_bayes_factor` | `float` | `3.0` | BF10 threshold for the stopping rule; experiment stops when `BF10 >= minimum_bayes_factor` or `BF10 <= 1/minimum_bayes_factor` |
| `credible_interval_width` | `float` | `0.95` | Width of the posterior credible interval (e.g., `0.95` for 95% HDI) |

**Example: Create Experiment with Bayesian Config**

```bash
curl -X POST "https://your-platform.example.com/api/v1/experiments/" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Checkout Button Bayesian Test",
    "hypothesis": "Green button increases conversion rate",
    "experiment_type": "AB_TEST",
    "bayesian_enabled": true,
    "bayesian_config": {
      "prior_alpha": 1.0,
      "prior_beta": 1.0,
      "rope_low": -0.005,
      "rope_high": 0.005,
      "minimum_bayes_factor": 10.0,
      "credible_interval_width": 0.95
    },
    "variants": [
      { "key": "control",   "name": "Control",   "weight": 0.5 },
      { "key": "treatment", "name": "Treatment", "weight": 0.5 }
    ]
  }'
```

---

## Results Endpoint

```
GET /api/v1/results/{experiment_id}
```

When `bayesian_enabled` is `true`, the standard results response is augmented with a top-level `bayesian_results` block.

**Example Request**

```bash
curl -X GET "https://your-platform.example.com/api/v1/results/exp-uuid-here" \
  -H "Authorization: Bearer your_access_token"
```

**Response: 200 OK**

```json
{
  "experiment_id": "exp-uuid-here",
  "experiment_name": "Checkout Button Bayesian Test",
  "status": "RUNNING",
  "sample_size": {
    "control": 4820,
    "treatment": 4795
  },
  "metrics": [
    {
      "name": "conversion_rate",
      "control_value": 0.1240,
      "treatment_value": 0.1387,
      "difference": 0.0147,
      "p_value": 0.0312,
      "is_significant": true
    }
  ],
  "bayesian_results": {
    "metric_name": "conversion_rate",
    "posterior_alpha": 671.0,
    "posterior_beta": 4151.0,
    "posterior_mean": 0.1390,
    "credible_interval": [0.1292, 0.1490],
    "credible_interval_width": 0.95,
    "bayes_factor": 18.42,
    "probability_of_superiority": 0.9731,
    "rope_low": -0.005,
    "rope_high": 0.005,
    "rope_probability": 0.0018,
    "decision": "ACCEPT_ALTERNATIVE",
    "stopped_early": false,
    "stopping_rule_met_at": null,
    "iterations": 100000
  }
}
```

---

## `BayesianDecision` Enum

| Value | Description |
|---|---|
| `ACCEPT_NULL` | Strong evidence in favour of the null hypothesis (BF10 <= 1/minimum_bayes_factor). Recommend stopping; control wins. |
| `ACCEPT_ALTERNATIVE` | Strong evidence in favour of the alternative hypothesis (BF10 >= minimum_bayes_factor). Recommend stopping; treatment wins. |
| `INCONCLUSIVE` | Insufficient evidence to make a decision. Experiment should continue collecting data. |
| `ROPE_ACCEPT` | The posterior credible interval falls entirely within the ROPE. The effect is practically equivalent to zero; either variant is acceptable. |

---

## `BayesianResultsResponse` Schema

| Field | Type | Description |
|---|---|---|
| `metric_name` | `string` | The primary metric used for Bayesian inference |
| `posterior_alpha` | `float` | Alpha parameter of the posterior Beta distribution (Beta-Binomial model) |
| `posterior_beta` | `float` | Beta parameter of the posterior Beta distribution |
| `posterior_mean` | `float` | Mean of the posterior distribution (`alpha / (alpha + beta)`) |
| `credible_interval` | `[float, float]` | Highest Density Interval (HDI) at `credible_interval_width` |
| `credible_interval_width` | `float` | Width of the HDI used (e.g., `0.95`) |
| `bayes_factor` | `float` | BF10 computed via the Savage-Dickey density ratio |
| `probability_of_superiority` | `float` | Posterior probability that treatment conversion rate > control (via Monte Carlo with `iterations` samples) |
| `rope_low` | `float` | Lower bound of the configured ROPE |
| `rope_high` | `float` | Upper bound of the configured ROPE |
| `rope_probability` | `float` | Posterior probability that the true effect size lies entirely within the ROPE |
| `decision` | `BayesianDecision` | The automated decision based on the stopping rule |
| `stopped_early` | `boolean` | `true` if the stopping rule was triggered before the planned end date |
| `stopping_rule_met_at` | `datetime` or `null` | UTC timestamp when the stopping criterion was first satisfied |
| `iterations` | `int` | Number of Monte Carlo samples used for probability of superiority estimate |

---

## Bayesian Stopping Rule Behaviour

The platform evaluates the stopping rule after each scheduled metrics collection cycle (every 15 minutes by default). The rule fires when all of the following conditions are met:

1. **Minimum sample size reached**: Both the control and treatment groups have at least the configured `min_sample_size` observations (defaults to 1,000 per variant when unset).
2. **Conclusive Bayes factor**: `BF10 >= minimum_bayes_factor` (evidence for alternative) or `BF10 <= 1 / minimum_bayes_factor` (evidence for null).
3. **OR ROPE acceptance**: The full credible interval lies within `[rope_low, rope_high]`.

When the rule fires:

- `stopped_early` is set to `true`.
- `stopping_rule_met_at` is recorded.
- The experiment status transitions to `STOPPED_EARLY`.
- A notification is dispatched to configured channels (Slack / email) if alerting is enabled.

**Note**: The Bayesian stopping rule is mathematically valid for early stopping and does not inflate the false-positive rate in the way that frequentist sequential testing does without alpha spending, making it safe to check continuously.

---

## Prior Selection Guide

| Scenario | Recommended Prior | Rationale |
|---|---|---|
| No prior knowledge | `alpha=1, beta=1` (uniform) | Completely uninformative; posterior is driven entirely by data |
| Historical baseline known | `alpha = baseline_rate * N, beta = (1 - baseline_rate) * N` | Encodes prior experiments as an equivalent number of observations `N` |
| Conservative (shrink toward zero) | `alpha=0.5, beta=0.5` (Jeffreys) | Weakly informative, recommended when sample sizes are small |

---

## Error Responses

| Status | Meaning |
|---|---|
| `400 Bad Request` | `bayesian_config` provided without `bayesian_enabled: true`, or invalid parameter values |
| `401 Unauthorized` | Missing or invalid Bearer token |
| `403 Forbidden` | Insufficient role |
| `404 Not Found` | Experiment ID does not exist |
| `422 Unprocessable Entity` | Validation error (e.g., `prior_alpha <= 0`, `rope_low >= rope_high`) |

```json
{
  "detail": [
    {
      "loc": ["body", "bayesian_config", "prior_alpha"],
      "msg": "prior_alpha must be greater than 0",
      "type": "value_error"
    }
  ]
}
```
