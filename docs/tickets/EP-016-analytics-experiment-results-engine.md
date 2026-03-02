# EP-016: Analytics & Experiment Results Engine

**Status:** 🟡 In Progress
**Priority:** 🔥 Critical (Blocks production usefulness)
**Story Points:** 13
**Sprint:** Q1 2026
**Assignee:** Backend Team
**Created:** 2026-03-01
**Type:** Feature — Backend Analytics

---

## 📋 Overview

### User Story

**As a** product manager or data analyst
**I want** to view statistically rigorous experiment results through a REST API
**So that** I can make confident, data-driven decisions about which variant to ship

### Business Value

- **Decision enablement:** Without results, A/B tests are meaningless — this unlocks the core platform value proposition
- **Statistical rigour:** Proper significance testing prevents shipping regressions
- **Performance:** Cached results keep dashboards fast at scale
- **Extensibility:** Clean spec makes frontend integration straightforward (EP-015)

---

## 🔍 Current State

### What Exists (do not re-implement)

| Component | Location | State |
| --- | --- | --- |
| `AnalysisService` | `backend/app/services/analysis_service.py` | ✅ Good foundation — Fisher's exact, CI, segmentation, daily trends |
| `MetricsService` | `backend/app/services/metrics_service.py` | ✅ Feature-flag operational metrics, aggregation |
| `Metric` model | `backend/app/models/experiment.py` | ✅ Supports CONVERSION, REVENUE, COUNT, DURATION, CUSTOM |
| `Event` model | `backend/app/models/event.py` | ✅ event_type, value (Float), variant_id, experiment_id |
| Results endpoint | `backend/app/api/v1/endpoints/results.py` | ❌ Stub only — `return {"message": "Results Endpoint"}` |

### What Is Missing

1. **Results API** — no endpoints to fetch experiment results
2. **Z-test / T-test** — `analysis_service.py` only uses Fisher's exact (binary); continuous metrics (revenue, duration) need Welch's t-test
3. **Effect size** — no Cohen's d (continuous) or Cohen's h (proportions)
4. **Sample size calculator** — no minimum detectable effect (MDE) or power analysis
5. **Multiple comparison correction** — no Bonferroni/BH adjustment for multi-metric experiments
6. **Results caching** — every call re-queries and re-computes from raw events (expensive)
7. **Pydantic v2 response schemas** — no typed schemas for results responses

---

## 🎯 Technical Specification (Spec-First / RDD)

### API Contract

#### `GET /api/v1/results/{experiment_id}`

Returns full results for an experiment across all metrics and variants.

**Path params:**
- `experiment_id: UUID`

**Query params:**
- `use_cache: bool = true` — return cached result if available and fresh
- `confidence_level: float = 0.95` — statistical confidence level (0.80–0.99)
- `correction_method: str = "none"` — multiple comparison correction: `none`, `bonferroni`, `benjamini_hochberg`

**Response `200 OK`:**

```json
{
  "experiment_id": "uuid",
  "experiment_name": "Checkout Button Colour",
  "status": "running",
  "start_date": "2026-01-15T00:00:00Z",
  "end_date": null,
  "confidence_level": 0.95,
  "correction_method": "bonferroni",
  "sample_size_adequate": true,
  "computed_at": "2026-03-01T12:00:00Z",
  "summary": {
    "total_users": 12450,
    "total_events": 48320,
    "duration_days": 14,
    "has_winner": true,
    "winning_variant_id": "uuid",
    "recommendation": "SHIP_VARIANT"
  },
  "metrics": [
    {
      "metric_id": "uuid",
      "metric_name": "Checkout Conversion",
      "metric_type": "conversion",
      "is_primary": true,
      "variants": [
        {
          "variant_id": "uuid",
          "variant_name": "Control",
          "is_control": true,
          "sample_size": 6200,
          "conversions": 496,
          "mean": 0.08,
          "std_dev": null,
          "confidence_interval": [0.073, 0.087],
          "p_value": null,
          "adjusted_p_value": null,
          "is_significant": false,
          "effect_size": null,
          "effect_size_label": null,
          "relative_improvement_pct": null,
          "power": null
        },
        {
          "variant_id": "uuid",
          "variant_name": "Green Button",
          "is_control": false,
          "sample_size": 6250,
          "conversions": 587,
          "mean": 0.0939,
          "std_dev": null,
          "confidence_interval": [0.087, 0.101],
          "p_value": 0.0021,
          "adjusted_p_value": 0.0042,
          "is_significant": true,
          "effect_size": 0.051,
          "effect_size_label": "small",
          "relative_improvement_pct": 17.4,
          "power": 0.91
        }
      ]
    }
  ]
}
```

**Errors:**
- `404` — experiment not found
- `400` — experiment has no metrics or no assignments yet
- `422` — invalid confidence_level or correction_method

---

#### `GET /api/v1/results/{experiment_id}/daily`

Returns day-by-day metric values for trend charts.

**Query params:**
- `metric_id: Optional[UUID]` — filter to one metric
- `start_date: Optional[date]`
- `end_date: Optional[date]`

**Response `200 OK`:**

```json
{
  "experiment_id": "uuid",
  "metric_id": "uuid",
  "dates": ["2026-01-15", "2026-01-16", "..."],
  "series": [
    {
      "variant_id": "uuid",
      "variant_name": "Control",
      "is_control": true,
      "values": [
        {"date": "2026-01-15", "sample_size": 420, "conversions": 34, "rate": 0.081},
        {"date": "2026-01-16", "sample_size": 445, "conversions": 37, "rate": 0.083}
      ],
      "cumulative": [
        {"date": "2026-01-15", "sample_size": 420, "conversions": 34, "rate": 0.081},
        {"date": "2026-01-16", "sample_size": 865, "conversions": 71, "rate": 0.082}
      ]
    }
  ]
}
```

---

#### `GET /api/v1/results/{experiment_id}/sample-size`

Returns sample size adequacy analysis and MDE calculator.

**Query params:**
- `baseline_rate: float` — current control conversion rate
- `mde: float = 0.05` — minimum detectable effect (relative)
- `confidence_level: float = 0.95`
- `power: float = 0.80`

**Response `200 OK`:**

```json
{
  "required_sample_size_per_variant": 3842,
  "current_sample_size_per_variant": 6200,
  "is_adequate": true,
  "achieved_power": 0.91,
  "days_to_significance": null,
  "projected_completion_date": null
}
```

---

#### `POST /api/v1/results/{experiment_id}/invalidate-cache`

Invalidates cached results for an experiment (admin only).

---

### Statistical Methods Specification

#### Metric Type → Test Selection

| Metric Type | Statistical Test | Effect Size Metric |
| --- | --- | --- |
| `conversion` | Two-proportion z-test | Cohen's h |
| `revenue` | Welch's t-test | Cohen's d |
| `count` | Welch's t-test | Cohen's d |
| `duration` | Welch's t-test | Cohen's d |
| `custom` | Welch's t-test (default) | Cohen's d |

> **Note:** Fisher's exact test (existing) is kept for small samples (n < 30 per variant).
> The test selector chooses automatically based on sample size and metric type.

#### Two-Proportion Z-Test (Conversion Metrics)

```
H0: p_control == p_variant
H1: p_control != p_variant (two-tailed)

pooled_p = (x_c + x_v) / (n_c + n_v)
se = sqrt(pooled_p * (1 - pooled_p) * (1/n_c + 1/n_v))
z = (p_v - p_c) / se
p_value = 2 * (1 - Φ(|z|))

Cohen's h = 2 * arcsin(sqrt(p_v)) - 2 * arcsin(sqrt(p_c))
Effect labels: |h| < 0.2 → negligible, 0.2–0.5 → small, 0.5–0.8 → medium, > 0.8 → large
```

#### Welch's T-Test (Continuous Metrics)

```
H0: μ_control == μ_variant
H1: μ_control != μ_variant (two-tailed)

Uses scipy.stats.ttest_ind with equal_var=False

Cohen's d = (mean_v - mean_c) / pooled_std
pooled_std = sqrt((std_c^2 + std_v^2) / 2)
Effect labels: |d| < 0.2 → negligible, 0.2–0.5 → small, 0.5–0.8 → medium, > 0.8 → large
```

#### Multiple Comparison Correction

```
bonferroni:          adjusted_p = min(p * n_metrics, 1.0)
benjamini_hochberg:  BH procedure (statsmodels or manual implementation)
none:                adjusted_p = p (no correction)
```

#### Confidence Intervals

```
Proportions:  Wilson score interval (more accurate than normal approximation for extreme rates)
Means:        t-distribution CI using scipy.stats.t.interval
```

#### Sample Size Formula (for calculator endpoint)

```
α = 1 - confidence_level
β = 1 - power
z_α = norm.ppf(1 - α/2)   # two-tailed
z_β = norm.ppf(1 - β)

For proportions (MDE as relative change):
p1 = baseline_rate
p2 = baseline_rate * (1 + mde)
n = (z_α * sqrt(2*p_bar*(1-p_bar)) + z_β * sqrt(p1*(1-p1) + p2*(1-p2)))^2 / (p2-p1)^2
where p_bar = (p1 + p2) / 2
```

---

### Caching Strategy

- **Cache backend:** Redis (via `cache.py` service already in `backend/app/services/`)
- **Cache key:** `results:{experiment_id}:{confidence_level}:{correction_method}`
- **TTL:** 5 minutes for RUNNING experiments, 24 hours for COMPLETED/STOPPED
- **Invalidation:** POST to invalidate endpoint, or any new event ingestion for experiment
- **Cache miss:** compute synchronously, store result, return to caller

---

### Pydantic v2 Schemas (New File)

**Location:** `backend/app/schemas/results.py`

All schemas use:
- `model_config = ConfigDict(from_attributes=True)`
- `field_validator` not `validator`
- `Annotated` types for constraints

---

## 🧪 Acceptance Criteria (Test-Driven)

All criteria must have a corresponding passing test before the feature is considered done.

### Results API

- [ ] `GET /results/{id}` returns 200 with correct schema for a running experiment
- [ ] `GET /results/{id}` returns 404 for unknown experiment
- [ ] `GET /results/{id}` returns 400 when experiment has zero assignments
- [ ] `GET /results/{id}` respects `confidence_level` query param
- [ ] `GET /results/{id}` applies Bonferroni correction when requested
- [ ] `GET /results/{id}/daily` returns time series data per variant
- [ ] `GET /results/{id}/sample-size` returns adequacy and projected completion
- [ ] Results are served from cache on second identical request
- [ ] Cache is invalidated after POST to invalidate endpoint
- [ ] COMPLETED experiments return cached results for 24h

### Statistical Engine

- [ ] Two-proportion z-test produces correct p-value (validated against known test cases)
- [ ] Welch's t-test used for REVENUE/DURATION metric types
- [ ] Cohen's h calculated correctly for conversion metrics
- [ ] Cohen's d calculated correctly for continuous metrics
- [ ] Wilson score CI tighter than normal approximation for p < 0.1
- [ ] Bonferroni correction raises significance threshold for multiple metrics
- [ ] Sample size calculator returns n ≥ 384 for baseline=0.5, MDE=0.05, power=0.8
- [ ] `_select_test()` returns `fisher_exact` for n < 30, `z_test` for n ≥ 30 (conversion)

### Code Quality

- [ ] All new functions have full type annotations
- [ ] All new functions have docstrings with Args/Returns/Raises
- [ ] No raw SQL strings (use SQLAlchemy ORM)
- [ ] Test coverage ≥ 90% for new code
- [ ] `black` and `isort` pass with no changes

---

## 📁 Implementation Plan (TDD, Day by Day)

### Day 1 — Schemas + Results API Skeleton

1. Create `backend/app/schemas/results.py` with full Pydantic v2 schemas
2. Write skeleton tests in `backend/tests/unit/api/test_results_api.py`
3. Wire `AnalysisService.get_experiment_results()` to `results.py` endpoint
4. Make skeleton tests pass

### Day 2 — Enhanced Statistical Engine

1. Write unit tests for new stat functions in `backend/tests/unit/services/test_analysis_service.py`
2. Add `_select_test()`, `_z_test_proportions()`, `_welch_t_test()` to `AnalysisService`
3. Add `_cohens_h()`, `_cohens_d()`, `_effect_size_label()` helpers
4. Add `_wilson_ci()` to replace normal approximation CI
5. Add `_apply_correction()` for multiple comparison correction
6. Make all stat tests pass

### Day 3 — Sample Size Calculator + Daily Trends

1. Write tests for sample-size endpoint
2. Implement `calculate_sample_size()` in `AnalysisService`
3. Fix daily trends to use proper datetime handling (Event.created_at is String — parse carefully)
4. Add cumulative series to daily results

### Day 4 — Caching + Integration

1. Add cache layer to results endpoint using Redis
2. Add `POST /results/{id}/invalidate-cache` endpoint
3. Write integration tests end-to-end with DB fixtures
4. Run full test suite, fix any failures

---

## 🚫 Out of Scope (Post-MVP)

- Bayesian analysis (prior specification, posterior updating)
- Sequential testing / early stopping rules (alpha spending)
- CUPED variance reduction
- Heterogeneous treatment effects / subgroup discovery
- Automated winner declaration

---

## 📊 Definition of Done

- [ ] All acceptance criteria tests passing
- [ ] Results API returns correct data for the sample experiment in CI
- [ ] Cache reduces p95 response time from >500ms to <50ms under load
- [ ] PR reviewed and merged to main
- [ ] GitHub project board item moved to Done
- [ ] `docs/development/development-plan.md` Todo item checked off
