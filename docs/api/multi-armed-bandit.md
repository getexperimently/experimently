# Multi-Armed Bandit

Multi-armed bandit (MAB) experiments dynamically reallocate traffic toward better-performing variants as data accumulates, rather than maintaining fixed allocations throughout the experiment. This maximizes reward during the experiment itself at the cost of some statistical power.

---

## A/B Test vs. Bandit — When to Use Which

| Scenario | Use A/B Test | Use Bandit |
|----------|-------------|------------|
| Need unbiased causal estimates for a permanent change | ✅ | ❌ |
| Regulatory or compliance reporting | ✅ | ❌ |
| Short-lived promotions where maximizing conversions matters | ❌ | ✅ |
| Content recommendation / personalization | ❌ | ✅ |
| Rapidly iterating with many variants | ❌ | ✅ |
| Statistical power and precise effect sizes required | ✅ | ❌ |

---

## Algorithms

### Thompson Sampling (Default)

Maintains a Beta distribution for each variant based on its observed successes and total pulls. At each assignment, samples from each distribution and routes the user to the variant with the highest sample. Naturally balances exploration and exploitation.

Best for: most MAB use cases, especially when you want smooth convergence.

### UCB1 (Upper Confidence Bound)

Selects the variant with the highest upper confidence bound: `mean + sqrt(2 * ln(total_pulls) / variant_pulls)`. Explores variants with high uncertainty (few pulls) while exploiting high-performing ones.

Best for: situations where you want a deterministic, easily auditable algorithm.

### Epsilon-Greedy

With probability `epsilon`, selects a random variant (exploration). Otherwise selects the current best variant (exploitation). Simple and fast.

Best for: high-volume, low-latency scenarios where simplicity matters.

---

## Creating a MAB Experiment

Set `optimization_type` to one of `thompson_sampling`, `ucb1`, or `epsilon_greedy` when creating an experiment. All other experiment fields (variants, metrics, targeting) work the same as standard A/B experiments.

```bash
curl -X POST "http://localhost:8000/api/v1/experiments" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "CTA Button Bandit",
    "optimization_type": "thompson_sampling",
    "variants": [
      {"name": "control", "is_control": true},
      {"name": "red_button"},
      {"name": "green_button"}
    ]
  }'
```

---

## API Reference

### GET /api/v1/bandit/{experiment_id}

Returns the current bandit state: variant weights, pulls, successes, and conversion rates.

**Example Response**

```json
{
  "experiment_id": "exp-uuid",
  "optimization_type": "thompson_sampling",
  "total_pulls": 12480,
  "last_updated": "2026-03-02T14:32:00Z",
  "estimated_regret_pct": 2.1,
  "variant_weights": [
    {
      "variant_id": "v1-uuid",
      "variant_name": "control",
      "current_weight": 0.18,
      "successes": 820,
      "pulls": 2246,
      "conversion_rate": 0.365
    },
    {
      "variant_id": "v2-uuid",
      "variant_name": "red_button",
      "current_weight": 0.61,
      "successes": 3890,
      "pulls": 6382,
      "conversion_rate": 0.610
    },
    {
      "variant_id": "v3-uuid",
      "variant_name": "green_button",
      "current_weight": 0.21,
      "successes": 1240,
      "pulls": 3852,
      "conversion_rate": 0.322
    }
  ]
}
```

**Response Fields**

| Field | Description |
|-------|-------------|
| `current_weight` | Current traffic allocation fraction (0–1, sums to 1.0 across variants) |
| `estimated_regret_pct` | Estimated cumulative regret as a % of optimal reward. Lower is better. |
| `pulls` | Total assignments to this variant |
| `successes` | Conversion events recorded for this variant |

---

### POST /api/v1/bandit/{experiment_id}/update

Manually trigger a weight recalculation outside the scheduler cycle. Requires DEVELOPER or ADMIN role.

```bash
curl -X POST "http://localhost:8000/api/v1/bandit/exp-uuid/update" \
  -H "Authorization: Bearer $TOKEN"
```

---

### PUT /api/v1/bandit/{experiment_id}/weights

Override variant weights manually. Requires ADMIN role. Use with caution — overrides are replaced on the next scheduler cycle unless the experiment is paused.

```bash
curl -X PUT "http://localhost:8000/api/v1/bandit/exp-uuid/weights" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "weights": {
      "v1-uuid": 0.1,
      "v2-uuid": 0.8,
      "v3-uuid": 0.1
    }
  }'
```

---

## Scheduler

The bandit scheduler runs on a background cycle and recalculates weights for all active MAB experiments. The frequency is configurable via `BANDIT_SCHEDULER_INTERVAL_SECONDS` in settings. Default: every 5 minutes.

---

## Permissions

| Action | Minimum Role |
|--------|-------------|
| View bandit status | VIEWER |
| Trigger weight update | DEVELOPER |
| Override weights | ADMIN |
