# Experiment Interaction Detection

**Only the overlap is measured yet.** The overlap between two experiments' users is
computed from their assignments. The interaction, novelty and SUTVA analyses are not
implemented yet, so the response returns them as `null`, and `overall_risk` reflects the
overlap alone. The pairwise and novelty routes are beta: their responses carry
`"analysis_status": "beta"` and an `analysis_notice`, and they are marked
`x-stability: beta` in the OpenAPI document
([#219](https://github.com/getexperimently/experimently/issues/219)).

When multiple experiments run simultaneously and share users, they can interfere with
each other. Interaction detection finds the experiment pairs with a significant user
overlap; testing whether the simultaneous exposure distorts results is the part not built
yet.

---

## What Gets Detected

| Issue | Description | In this release |
|-------|-------------|-----------------|
| **User overlap** | Users assigned to both experiments; can contaminate effect estimates | Measured |
| **Statistical interaction** | The treatment effect of experiment A changes depending on which variant of experiment B a user is in | Not computed (`null`) |
| **Novelty effects** | An early spike in effect that decays as users habituate — indicates the result may not hold long-term | Not computed (`null`) |
| **SUTVA violations** | Stable Unit Treatment Value Assumption violations — users in different variants are influencing each other (e.g. social features, shared resources) | Not computed (`null`) |

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
experiments. Each entry in `analyses` has the pairwise analysis's fields, as below,
without `analysis_status` and `analysis_notice`: the interaction, novelty and SUTVA
results are `null` there too, and `high_risk_pairs` counts the pairs whose overlap is
above 0.6.

---

### GET /api/v1/interactions/{exp_a_id}/{exp_b_id}

The pairwise analysis of two experiments (beta). A pair with an overlap of 0.3 or less
answers with the overlap set to `0.0`, `"overall_risk": "low"` and a recommendation that
no analysis is needed:

```{.bash exec}
curl -s localhost:8000/api/v1/interactions/$PRICING_ID/$ONBOARDING_ID \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{overlap_coefficient, has_significant_overlap, interaction_result, overall_risk, analysis_status}'
```
<!-- expect: "overlap_coefficient": 1 -->
<!-- expect: "has_significant_overlap": true -->
<!-- expect: "interaction_result": null -->
<!-- expect: "overall_risk": "high" -->
<!-- expect: "analysis_status": "beta" -->

It prints an overlap of `1.0`: every user of one experiment is in the other, so the
overlap alone makes the pair high risk. The full response:

```json
{
  "experiment_a_id": "8f3b1030-0fa2-4cc5-9842-08650d708925",
  "experiment_b_id": "0ee2eb89-1aba-4e46-bbc6-7ee027e6f0e4",
  "overlap_coefficient": 1.0,
  "has_significant_overlap": true,
  "interaction_result": null,
  "novelty_result": null,
  "sutva_result": null,
  "overall_risk": "high",
  "recommendations": [
    "The two experiments share users (overlap 1.00). Each one's results include users exposed to the other; consider a mutual exclusion group for future experiments on the same surface."
  ],
  "analysis_status": "beta",
  "analysis_notice": "Beta: only the overlap between the two experiments' users is measured. The interaction, novelty and SUTVA analyses are not computed yet, so interaction_result, novelty_result and sutva_result are null and overall_risk reflects the overlap alone. https://github.com/getexperimently/experimently/issues/219"
}
```

`null` here means *not computed*, not *nothing found*.

---

### GET /api/v1/interactions/{exp_a_id}/{exp_b_id}/novelty

The novelty part of the pairwise analysis on its own (beta). Novelty is not computed yet,
so it always answers `"computed": false` with `has_novelty` and `decline_rate` set to
`null` — never `"has_novelty": false`, which would read as "no novelty found":

```{.bash exec}
curl -s localhost:8000/api/v1/interactions/$PRICING_ID/$ONBOARDING_ID/novelty \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{computed, has_novelty, analysis_status}'
```
<!-- expect: "computed": false -->
<!-- expect: "has_novelty": null -->
<!-- expect: "analysis_status": "beta" -->

It prints `"computed": false`, `"has_novelty": null` and `"analysis_status": "beta"`.

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

In this release `overall_risk` comes from the overlap alone (#219):

| Level | Overlap |
|-------|---------|
| `low` | 0.3 or less |
| `medium` | above 0.3, up to 0.6 |
| `high` | above 0.6 |

---

## Permissions

| Action | Who |
|--------|-----|
| Scan, pairwise and novelty analysis | ADMIN, DEVELOPER or ANALYST |

A VIEWER gets `403` on every interaction endpoint.

---

## Recommended Workflow

1. Run `/scan` weekly or when launching a new experiment
2. For any pair with `overall_risk: high`, the two experiments share most of their users.
   Consider:
   - Pausing one experiment and re-running sequentially
   - Using [Mutual Exclusion Groups](./mutual-exclusion-groups.md) to prevent overlap in future
3. The interaction and novelty results are not computed yet (#219): until they are, judge
   an overlapping pair from each experiment's own results, not from this endpoint
