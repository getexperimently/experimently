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
| 1 | Choose Type | Experiment type (A/B, multivariate, bandit, feature-flag rollout) |
| 2 | Define Hypothesis | Experiment name, description, and hypothesis statement |
| 3 | Select Metrics | Primary metric, guardrail metrics |
| 4 | Configure Targeting | Audience rules, traffic allocation, MDE, baseline rate |
| 5 | Review & Launch | Final review and experiment submission |

The wizard saves your progress as a draft after each step. You can close the browser and return to any draft later.

---

## API Reference

All wizard endpoints are under `/api/v1/wizard`.

### POST /api/v1/wizard/drafts

Create a new wizard draft. The draft starts at step 1 (`choose_type`).

```bash
curl -X POST "http://localhost:8000/api/v1/wizard/drafts" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"experiment_type": "ab_test"}'
```

**Response**

```json
{
  "id": "draft-uuid",
  "user_id": "user-uuid",
  "current_step": "choose_type",
  "experiment_type": "ab_test",
  "hypothesis": null,
  "primary_metric_id": null,
  "guardrail_metric_ids": [],
  "targeting_rules": [],
  "baseline_rate": null,
  "mde": null,
  "name": null,
  "description": null
}
```

---

### GET /api/v1/wizard/drafts

List all in-progress wizard drafts for the authenticated user.

---

### GET /api/v1/wizard/drafts/{draft_id}

Retrieve a specific draft including all accumulated step data.

---

### PUT /api/v1/wizard/drafts/{draft_id}

Update a draft with data from the current step. Send only the fields being updated — all other fields are preserved.

**Step 2 — Hypothesis**

```bash
curl -X PUT "http://localhost:8000/api/v1/wizard/drafts/draft-uuid" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Checkout CTA Button Color",
    "description": "Test whether a green CTA button increases checkout completion",
    "hypothesis": "A green button will increase checkout completion by 5% because it signals action and creates visual contrast"
  }'
```

**Step 3 — Metrics**

```bash
curl -X PUT "http://localhost:8000/api/v1/wizard/drafts/draft-uuid" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "primary_metric_id": "metric-uuid",
    "guardrail_metric_ids": ["metric-uuid-2", "metric-uuid-3"]
  }'
```

**Step 4 — Targeting**

```bash
curl -X PUT "http://localhost:8000/api/v1/wizard/drafts/draft-uuid" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "targeting_rules": [
      {"attribute": "country", "operator": "in", "value": ["US", "CA", "GB"]}
    ],
    "baseline_rate": 0.12,
    "mde": 0.05
  }'
```

---

### POST /api/v1/wizard/drafts/{draft_id}/validate

Validate the current draft state before submission. Returns a list of validation errors, or an empty list if the draft is ready to submit.

```bash
curl -X POST "http://localhost:8000/api/v1/wizard/drafts/draft-uuid/validate" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "valid": true,
  "errors": []
}
```

If invalid:

```json
{
  "valid": false,
  "errors": [
    "primary_metric_id is required",
    "hypothesis must be at least 20 characters"
  ]
}
```

---

### POST /api/v1/wizard/drafts/{draft_id}/submit

Submit the draft, creating a real experiment in DRAFT status. The draft is consumed and can no longer be modified.

```bash
curl -X POST "http://localhost:8000/api/v1/wizard/drafts/draft-uuid/submit" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "experiment_id": "exp-uuid",
  "experiment_key": "checkout-cta-button-color",
  "status": "draft",
  "message": "Experiment created successfully. Review and activate when ready."
}
```

---

## Sample Size Guidance

When you enter a `baseline_rate` and `mde` (minimum detectable effect) in Step 4, the wizard automatically calculates the recommended sample size per variant:

```
n ≈ (z_α/2 + z_β)² × [p₁(1−p₁) + p₂(1−p₂)] / (p₁ − p₂)²
```

Where `p₁` = baseline rate, `p₂` = baseline rate × (1 + MDE), `z_α/2` = 1.96 (two-tailed, α=0.05), `z_β` = 0.842 (80% power).

The frontend displays this as a traffic and duration estimate based on your current daily active users.

---

## Permissions

- Any authenticated user can create and manage wizard drafts
- Submitted experiments follow the standard experiment RBAC rules
