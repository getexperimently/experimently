# Experiment Interaction Detection

When multiple experiments run simultaneously and share users, they can interfere with each other. Interaction detection identifies experiment pairs with significant user overlap and tests whether the simultaneous exposure is distorting results.

**Only the overlap is measured yet.** The overlap between two experiments' users is
computed from their assignments. The interaction, novelty and SUTVA results beside it are
not yet computed from what the users did: the interaction test uses user counts, novelty
is always `false`, and the contamination rate is the overlap itself, so any pair above the
overlap threshold reads as high risk
([#219](https://github.com/getexperimently/experimently/issues/219)).

---

## What Gets Detected

| Issue | Description |
|-------|-------------|
| **User overlap** | Users assigned to both experiments; can contaminate effect estimates |
| **Statistical interaction** | The treatment effect of experiment A changes depending on which variant of experiment B a user is in |
| **Novelty effects** | An early spike in effect that decays as users habituate — indicates the result may not hold long-term |
| **SUTVA violations** | Stable Unit Treatment Value Assumption violations — users in different variants are influencing each other (e.g. social features, shared resources) |

---

## Two overlapping experiments

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

It prints `"ADMIN"`. The demo data's running experiments share no users, so this creates
two experiments that will, and starts them. The collection URL ends with a slash,
`/api/v1/experiments/`; without it the API answers `307`, which `curl` doesn't follow.
This saves their ids in `$PRICING_ID` and `$ONBOARDING_ID`:

```{.bash exec}
PRICING_ID=$(curl -s -X POST localhost:8000/api/v1/experiments/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "name": "Pricing page",
    "key": "pricing-page",
    "variants": [
      {"name": "control", "is_control": true, "traffic_allocation": 50},
      {"name": "annual_first", "traffic_allocation": 50}
    ],
    "metrics": [{"name": "Signup", "event_name": "signup", "is_primary": true}]
  }' | jq -r .id)
ONBOARDING_ID=$(curl -s -X POST localhost:8000/api/v1/experiments/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "name": "Onboarding flow",
    "key": "onboarding-flow",
    "variants": [
      {"name": "control", "is_control": true, "traffic_allocation": 50},
      {"name": "checklist", "traffic_allocation": 50}
    ],
    "metrics": [{"name": "Signup", "event_name": "signup", "is_primary": true}]
  }' | jq -r .id)

for id in $PRICING_ID $ONBOARDING_ID; do
  curl -s -X POST localhost:8000/api/v1/experiments/$id/start \
    -H "Authorization: Bearer $TOKEN" | jq -r .status
done
```
<!-- expect: active -->
<!-- expect: active -->

It prints `active` twice. Then the same 40 users enter both, through the tracking API.
That takes an API key, which this saves in `$KEY`:

```{.bash exec}
KEY=$(curl -s -X POST localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name": "Interaction demo"}' | jq -r .key)

for i in $(seq 1 40); do
  for experiment in pricing-page onboarding-flow; do
    curl -s -X POST localhost:8000/api/v1/tracking/assign \
      -H "X-API-Key: $KEY" \
      -H 'content-type: application/json' \
      -d '{"experiment_key": "'"$experiment"'", "user_id": "shared-user-'"$i"'"}' \
      | jq -r .assigned
  done
done | sort | uniq -c
```
<!-- expect: 80 true -->

It prints `80 true`: 40 users, each enrolled in both experiments.

---

## API Reference

### GET /api/v1/interactions/scan

Checks every pair of active experiments and returns the pairs whose overlap is above
0.3, with a count of the high-risk ones:

```{.bash exec}
curl -s localhost:8000/api/v1/interactions/scan \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{total_active_experiments, pairs_analyzed, high_risk_pairs, overlaps: [.analyses[].overlap_coefficient]}'
```
<!-- expect: "total_active_experiments": 4 -->
<!-- expect: "pairs_analyzed": 1 -->

It prints four active experiments (the two new ones and the demo data's two running
ones), and one pair above the threshold, with an overlap of `1.0`: the two new
experiments. Each entry in `analyses` is a full pairwise analysis, as below.

---

### GET /api/v1/interactions/{exp_a_id}/{exp_b_id}

The pairwise analysis of two experiments. A pair with an overlap of 0.3 or less answers
with the overlap set to `0.0`, no sub-results, `"overall_risk": "low"` and a
recommendation that no analysis is needed:

```{.bash exec}
curl -s localhost:8000/api/v1/interactions/$PRICING_ID/$ONBOARDING_ID \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{overlap_coefficient, has_significant_overlap}'
```
<!-- expect: "overlap_coefficient": 1 -->
<!-- expect: "has_significant_overlap": true -->

It prints an overlap of `1.0`: every user of one experiment is in the other. The full
response:

```json
{
  "experiment_a_id": "8f3b1030-0fa2-4cc5-9842-08650d708925",
  "experiment_b_id": "0ee2eb89-1aba-4e46-bbc6-7ee027e6f0e4",
  "overlap_coefficient": 1.0,
  "has_significant_overlap": true,
  "interaction_result": {
    "has_interaction": true,
    "p_value": 1.522292196256315e-10,
    "interaction_effect_size": 0.0238,
    "warning_message": "Significant interaction detected between experiments. Results may be confounded."
  },
  "novelty_result": {
    "has_novelty": false,
    "decline_rate": 0.0,
    "recommendation": "Novelty analysis requires time-series data."
  },
  "sutva_result": {
    "has_violation": true,
    "contamination_rate": 1.0,
    "warning_message": "Contamination rate of 100.0% exceeds acceptable threshold. Some control users have been exposed to the treatment, which may bias the experiment results."
  },
  "overall_risk": "high",
  "recommendations": [
    "Significant interaction detected between experiments. Results may be confounded.",
    "Contamination rate of 100.0% exceeds acceptable threshold. Some control users have been exposed to the treatment, which may bias the experiment results."
  ]
}
```

The interaction, novelty and SUTVA results here come from the user counts, not from any
event: these users did nothing but enter both experiments
([#219](https://github.com/getexperimently/experimently/issues/219)).

---

### GET /api/v1/interactions/{exp_a_id}/{exp_b_id}/novelty

The novelty part of the pairwise analysis on its own:
`{"has_novelty", "decline_rate", "recommendation"}`. In this release it is always
`"has_novelty": false`.

---

## Overlap Coefficient

The overlap coefficient is computed using Jaccard similarity on the user assignment sets:

```text
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

| Action | Who |
|--------|-----|
| Scan, pairwise and novelty analysis | ADMIN, DEVELOPER or ANALYST |

A VIEWER gets `403` on every interaction endpoint.

---

## Recommended Workflow

1. Run `/scan` weekly or when launching a new experiment
2. For any pair with `overall_risk: high`, run the full pairwise analysis
3. If `has_interaction: true`, consider:
   - Pausing one experiment and re-running sequentially
   - Using [Mutual Exclusion Groups](./mutual-exclusion-groups.md) to prevent overlap in future
4. If `has_novelty: true`, extend the experiment window before making a ship/no-ship decision
