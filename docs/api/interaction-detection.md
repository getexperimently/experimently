# Experiment Interaction Detection (Issue #25)

When multiple experiments run simultaneously and share users, they can interfere with each other. Interaction detection identifies experiment pairs with significant user overlap and tests whether the simultaneous exposure is distorting results.

---

## What Gets Detected

| Issue | Description |
|-------|-------------|
| **User overlap** | Users assigned to both experiments; can contaminate effect estimates |
| **Statistical interaction** | The treatment effect of experiment A changes depending on which variant of experiment B a user is in |
| **Novelty effects** | An early spike in effect that decays as users habituate — indicates the result may not hold long-term |
| **SUTVA violations** | Stable Unit Treatment Value Assumption violations — users in different variants are influencing each other (e.g. social features, shared resources) |

---

## API Reference

### GET /api/v1/interactions/scan

Scans all currently active experiment pairs and returns an overlap summary with risk levels.

**Example Request**

```bash
curl -X GET "http://localhost:8000/api/v1/interactions/scan" \
  -H "Authorization: Bearer $TOKEN"
```

**Example Response**

```json
{
  "total_active_experiments": 8,
  "pairs_analyzed": 28,
  "high_risk_pairs": 2,
  "results": [
    {
      "experiment_a_id": "exp-a-uuid",
      "experiment_b_id": "exp-b-uuid",
      "overlap_coefficient": 0.74,
      "has_significant_overlap": true,
      "overall_risk": "high",
      "recommendations": [
        "High user overlap detected. Consider using mutual exclusion groups.",
        "Run pairwise interaction analysis to check for effect contamination."
      ]
    }
  ]
}
```

---

### GET /api/v1/interactions/{exp_a_id}/{exp_b_id}

Full pairwise interaction analysis between two specific experiments.

**Example Request**

```bash
curl -X GET "http://localhost:8000/api/v1/interactions/exp-a-uuid/exp-b-uuid" \
  -H "Authorization: Bearer $TOKEN"
```

**Example Response**

```json
{
  "experiment_a_id": "exp-a-uuid",
  "experiment_b_id": "exp-b-uuid",
  "overlap_coefficient": 0.74,
  "has_significant_overlap": true,
  "interaction_result": {
    "has_interaction": true,
    "p_value": 0.003,
    "interaction_effect_size": 0.12,
    "warning_message": "Significant interaction detected. Results from both experiments may be unreliable."
  },
  "novelty_result": {
    "has_novelty": false,
    "decline_rate": 0.02,
    "recommendation": "No significant novelty effect detected."
  },
  "sutva_result": {
    "has_violation": false,
    "contamination_rate": 0.01,
    "warning_message": null
  },
  "overall_risk": "high",
  "recommendations": [
    "Interaction detected: consider pausing one experiment.",
    "Add these experiments to a mutual exclusion group for future runs."
  ]
}
```

---

### GET /api/v1/interactions/{exp_a_id}/{exp_b_id}/novelty

Focused novelty-effect analysis for a specific experiment pair. Returns the effect trajectory over time to identify early spikes that decay.

---

## Overlap Coefficient

The overlap coefficient is computed using Jaccard similarity on the user assignment sets:

```
overlap = |users_in_A ∩ users_in_B| / |users_in_A ∪ users_in_B|
```

| Value | Interpretation |
|-------|---------------|
| 0.0–0.1 | Negligible overlap — no action needed |
| 0.1–0.3 | Low overlap — monitor |
| 0.3–0.6 | Moderate overlap — run pairwise analysis |
| 0.6–1.0 | High overlap — strong candidate for mutual exclusion |

---

## Risk Levels

| Level | Meaning |
|-------|---------|
| `low` | Minimal overlap, no interaction detected |
| `medium` | Moderate overlap or weak interaction signal |
| `high` | Significant overlap AND interaction, SUTVA violation, or strong novelty effect |

---

## Permissions

| Action | Minimum Role |
|--------|-------------|
| Scan active experiments | DEVELOPER |
| Pairwise analysis | DEVELOPER |
| Novelty analysis | DEVELOPER |

VIEWER role returns HTTP 403 on all interaction endpoints.

---

## Recommended Workflow

1. Run `/scan` weekly or when launching a new experiment
2. For any pair with `overall_risk: high`, run the full pairwise analysis
3. If `has_interaction: true`, consider:
   - Pausing one experiment and re-running sequentially
   - Using [Mutual Exclusion Groups](./mutual-exclusion-groups.md) to prevent overlap in future
4. If `has_novelty: true`, extend the experiment window before making a ship/no-ship decision
