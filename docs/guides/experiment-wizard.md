# Guided experiment builder (API)

The wizard is a 5-step guided flow for designing an experiment: it keeps a draft
while you answer one question at a time, validates each step, and creates the
experiment when you submit. Submitting writes a real experiment in DRAFT status,
owned by the caller, and discards the draft.

**This release ships the wizard as an API only.** There is no wizard screen in the
dashboard; `/experiments/new` is a single form. Drafts are held in the API process's
memory, so they do not survive a restart and are not shared between replicas.

---

## Steps Overview

| Step | Name | What You Configure |
|------|------|--------------------|
| 1 | `choose_type` | Experiment type: `ab`, `multivariate` or `feature_flag_rollout` |
| 2 | `define_hypothesis` | Name, description, hypothesis, primary metric and guardrail metrics |
| 3 | `targeting` | Audience rules |
| 4 | `sample_size` | Baseline rate and minimum detectable effect (MDE) |
| 5 | `review` | Final review, then submission |

Each completed step is saved in the draft, and the draft's `current_step` moves on to the
next one. You can come back to a draft later, as long as the API process has not restarted.

---

## API Reference

All wizard endpoints are under `/api/v1/wizard`. The commands below run as written against
the stack from the [Quick Start](../getting-started/quick-start.md), in one terminal, top to
bottom; each uses the shell variables set by the ones before it. Log in first:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

It prints `"ADMIN"`.

The collection URL has no trailing slash (`/api/v1/wizard/drafts`). With one, the API
answers `307 Temporary Redirect`, which `curl` doesn't follow, so nothing is printed.

### POST /api/v1/wizard/drafts

Create a new wizard draft. The draft starts at step 1 (`choose_type`). This saves its id in
`$DRAFT_ID`:

```{.bash exec}
DRAFT=$(curl -s -X POST localhost:8000/api/v1/wizard/drafts \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"experiment_type": "ab"}')
DRAFT_ID=$(jq -r .id <<<"$DRAFT")

jq '{current_step, experiment_type, hypothesis}' <<<"$DRAFT"
```
<!-- expect: "current_step": "choose_type" -->
<!-- expect: "experiment_type": "ab" -->

The API answers `201 Created`:

```json
{
  "current_step": "choose_type",
  "experiment_type": "ab",
  "hypothesis": null
}
```

The draft also carries its `id`, `user_id` and the other step fields, all empty:
`primary_metric_id`, `guardrail_metric_ids`, `targeting_rules`, `baseline_rate`, `mde`,
`name` and `description`.

---

### POST /api/v1/wizard/validate

Validate one step's data before you save it. The body names the step and its data, and the
response lists what is wrong, if anything:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/wizard/validate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"step": "define_hypothesis", "data": {"hypothesis": "Greener"}}'
```
<!-- expect: "is_valid":false -->
<!-- expect: "hypothesis must be at least 10 characters" -->
<!-- expect: "primary_metric_id is required" -->

```json
{"is_valid":false,"errors":["hypothesis must be at least 10 characters","primary_metric_id is required"]}
```

Valid data answers `{"is_valid":true,"errors":[]}`. The rules, by step:
- `choose_type`: `experiment_type` is `ab`, `multivariate` or `feature_flag_rollout`;
- `define_hypothesis`: a `hypothesis` of at least 10 characters, and a `primary_metric_id`;
- `sample_size`: `baseline_rate` and `mde` each between 0 and 1;
- `review`: `experiment_type`, `hypothesis` and `primary_metric_id` are all set;
- `targeting`: anything.

---

### PUT /api/v1/wizard/drafts/{draft_id}/step

Save one step's data in the draft, and move the draft to the next step. The body names the
step and its data, as for validation. Fields the step doesn't send are kept.

**Step 1: type.**

```{.bash exec}
curl -s -X PUT localhost:8000/api/v1/wizard/drafts/$DRAFT_ID/step \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"step": "choose_type", "data": {"experiment_type": "ab"}}' | jq .current_step
```
<!-- expect: "define_hypothesis" -->

It prints `"define_hypothesis"`, the next step.

**Step 2: hypothesis and metrics.** `primary_metric_id` and `guardrail_metric_ids` are the
event names the metrics count, such as `checkout_completed`:

```{.bash exec}
curl -s -X PUT localhost:8000/api/v1/wizard/drafts/$DRAFT_ID/step \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "step": "define_hypothesis",
    "data": {
      "name": "Checkout CTA Button Color",
      "description": "Test whether a green CTA button increases checkout completion",
      "hypothesis": "A green button will increase checkout completion by 5% because it signals action and creates visual contrast",
      "primary_metric_id": "checkout_completed",
      "guardrail_metric_ids": ["page_error"]
    }
  }' | jq .current_step
```
<!-- expect: "targeting" -->

It prints `"targeting"`.

**Step 3: targeting.** Each rule is one condition, and a user must match all of them:

```{.bash exec}
curl -s -X PUT localhost:8000/api/v1/wizard/drafts/$DRAFT_ID/step \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "step": "targeting",
    "data": {
      "targeting_rules": [
        {"attribute": "country", "operator": "in", "value": ["US", "CA", "GB"]}
      ]
    }
  }' | jq .current_step
```
<!-- expect: "sample_size" -->

It prints `"sample_size"`.

**Step 4: sample size.** `baseline_rate` is the metric's current conversion rate and `mde`
the smallest relative change worth detecting:

```{.bash exec}
curl -s -X PUT localhost:8000/api/v1/wizard/drafts/$DRAFT_ID/step \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"step": "sample_size", "data": {"baseline_rate": 0.12, "mde": 0.05}}' | jq .current_step
```
<!-- expect: "review" -->

It prints `"review"`: the draft is ready to submit.

---

### GET /api/v1/wizard/drafts

List your drafts that are still in progress:

```{.bash exec}
curl -s localhost:8000/api/v1/wizard/drafts \
  -H "Authorization: Bearer $TOKEN" | jq '{total, steps: [.drafts[].current_step]}'
```
<!-- expect: "total": 1 -->
<!-- expect: "review" -->

It prints `"total": 1`, and the draft's step, `"review"`.

### GET /api/v1/wizard/drafts/{draft_id}

Retrieve one draft, with all the data its steps have saved. A draft that doesn't exist, or
was submitted, answers `404`.

---

### POST /api/v1/wizard/drafts/{draft_id}/submit

Submit the draft: this creates a real experiment in DRAFT status, and the draft is
discarded. It saves the new experiment's id in `$EXP_ID`:

```{.bash exec}
SUBMIT=$(curl -s -X POST localhost:8000/api/v1/wizard/drafts/$DRAFT_ID/submit \
  -H "Authorization: Bearer $TOKEN")
EXP_ID=$(jq -r .experiment_id <<<"$SUBMIT")

jq '{success, errors}' <<<"$SUBMIT"
```
<!-- expect: "success": true -->

```json
{
  "success": true,
  "errors": []
}
```

A draft that fails the review step's rules answers `"success": false`, with `errors` listing
them.

The experiment is an ordinary one. An `ab` draft gets two variants, `Control` and
`Variant A`, at 50% each; its primary metric counts `checkout_completed`:

```{.bash exec}
curl -s localhost:8000/api/v1/experiments/$EXP_ID \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{name, status, variants: [.variants[].name], metrics: [.metrics[].event_name]}'
```
<!-- expect: "name": "Checkout CTA Button Color" -->
<!-- expect: "status": "draft" -->
<!-- expect: "Variant A" -->

```json
{
  "name": "Checkout CTA Button Color",
  "status": "draft",
  "variants": [
    "Control",
    "Variant A"
  ],
  "metrics": [
    "checkout_completed",
    "page_error"
  ]
}
```

A `multivariate` draft gets three variants (33/33/34), and a `feature_flag_rollout` draft
gets a held-back control with `{"enabled": false}` and a treatment with `{"enabled": true}`,
at 50% each. Review the experiment and start it when you're ready.

---

## Sample Size Guidance

The draft stores `baseline_rate` and `mde`, but the wizard doesn't compute a sample size
from them. The experiments API does:

```{.bash exec}
curl -s -G localhost:8000/api/v1/experiments/analysis/sample-size \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "baseline_rate=0.12" \
  --data-urlencode "minimum_detectable_effect=0.05" | jq '{samples_per_variant, total_samples}'
```
<!-- expect: "samples_per_variant": 47034 -->
<!-- expect: "total_samples": 94068 -->

For a 12% baseline and a 5% relative change it needs `47034` users per variant, `94068` in
all, at 80% power and 5% significance (two-sided). It also takes `statistical_power`,
`significance_level`, `is_one_sided`, `variant_count`, and `daily_traffic` with
`traffic_allocation` for a duration estimate.

The calculation is the standard one for two proportions:

```text
n ≈ (z_α/2 + z_β)² × [p₁(1−p₁) + p₂(1−p₂)] / (p₁ − p₂)²
```

Where `p₁` = baseline rate, `p₂` = baseline rate × (1 + MDE), `z_α/2` = 1.96 (two-tailed, α=0.05), `z_β` = 0.842 (80% power).

---

## Permissions

- Any logged-in user can create and manage their own wizard drafts.
- Submitted experiments follow the standard experiment RBAC rules.
