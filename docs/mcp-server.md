# AI Endpoints and the MCP Manifest

The platform serves two things for AI tooling:

- a **manifest** at `GET /api/v1/mcp/manifest`, a JSON document that describes
  five tools in the vocabulary of the Model Context Protocol (MCP);
- **REST endpoints** under `/api/v1/ai/` that suggest an experiment design,
  interpret a result, estimate a sample size and list experiment templates.

The platform does not run an MCP server. The manifest describes tools, but
nothing on the platform answers MCP's own requests, so an MCP client such as
Claude Code or Cursor cannot connect to the manifest's URL or call a tool
through it. Call the REST endpoints with any HTTP client instead.

The examples run against the [Quick Start](getting-started/quick-start.md)
stack, in one terminal, in order: later steps use the `$TOKEN` an earlier one
sets.

---

## The manifest

The manifest needs no sign-in:

```{.bash exec}
curl -s localhost:8000/api/v1/mcp/manifest | jq -r '.tools[].name'
```
<!-- expect: create_experiment -->
<!-- expect: get_results -->
<!-- expect: toggle_feature_flag -->
<!-- expect: suggest_experiment -->
<!-- expect: interpret_results -->

It lists five tools: `create_experiment`, `get_results`,
`toggle_feature_flag`, `suggest_experiment` and `interpret_results`. Each
entry has a `name`, a `description` and its `parameters`:

```{.bash exec}
curl -s localhost:8000/api/v1/mcp/manifest \
  | jq '.tools[] | select(.name == "suggest_experiment")'
```
<!-- expect: "name": "suggest_experiment" -->
<!-- expect: "description": "Get AI-powered experiment design suggestions based on a natural language description" -->
<!-- expect: "experiment_type" -->

```json
{
  "name": "suggest_experiment",
  "description": "Get AI-powered experiment design suggestions based on a natural language description",
  "parameters": {
    "description": {
      "type": "string",
      "description": "Natural language description of the experiment goal"
    },
    "experiment_type": {
      "type": "string",
      "description": "Type of experiment (checkout, onboarding, pricing, email, landing_page)"
    }
  }
}
```

---

## Signing in

The endpoints under `/api/v1/ai/` need a signed-in user. Without a token they
answer `401`, as this one does:

```{.bash exec}
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/v1/ai/templates
```
<!-- expect: 401 -->

Sign in as the Quick Start's administrator. The second command prints
`"ADMIN"`; if it prints `null`, the sign-in failed and `$TOKEN` holds no token:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

---

## Experiment design: `POST /api/v1/ai/design`

Send a description of what you want to test and an experiment type
(`checkout`, `onboarding`, `pricing`, `email` or `landing_page`):

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/ai/design \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "description": "We want to test whether simplifying the onboarding checklist increases activation",
    "experiment_type": "onboarding"
  }' | jq .
```
<!-- expect: "primary_metric": "activation_rate" -->
<!-- expect: "recommended_sample_size": 1000 -->
<!-- expect: "confidence": "template_based" -->

On the Quick Start stack the suggestion is the template for the experiment
type, and `confidence` says so (`"template_based"`):

```json
{
  "hypothesis": "Changing the onboarding flow will improve user outcomes",
  "primary_metric": "activation_rate",
  "guardrail_metrics": ["day7_retention", "time_to_first_action"],
  "recommended_sample_size": 1000,
  "recommended_duration_days": 14,
  "variant_descriptions": ["Control: current experience", "Variant A: proposed change"],
  "confidence": "template_based",
  "reasoning": "Template-based suggestion (AI not available)"
}
```

---

## Results interpretation: `POST /api/v1/ai/interpret/{experiment_id}`

Send one variant's result. The endpoint interprets the numbers in the request
body: it does not read the experiment's stored results or look the id up, so
the `checkout-v2` below, which does not exist on the stack, is answered like
any other:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/ai/interpret/checkout-v2 \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"experiment_id": "checkout-v2", "variant_name": "simplified", "p_value": 0.03, "relative_improvement_pct": 3.2}' \
  | jq .
```
<!-- expect: "summary": "simplified showed a 3.2% improvement (p=0.030). Recommend shipping." -->
<!-- expect: "recommendation": "ship" -->
<!-- expect: "confidence_statement": "Statistical confidence: 97.0%" -->
<!-- expect: "generated_by": "template" -->

```json
{
  "summary": "simplified showed a 3.2% improvement (p=0.030). Recommend shipping.",
  "recommendation": "ship",
  "confidence_statement": "Statistical confidence: 97.0%",
  "key_findings": ["simplified showed a 3.2% improvement (p=0.030). Recommend shipping."],
  "generated_by": "template"
}
```

On the Quick Start stack the interpretation comes from a template
(`"generated_by": "template"`), and `recommendation` is `ship` when `p_value`
is below 0.05 and the improvement is positive, `stop_futility` when `p_value`
is below 0.05 and the improvement is negative, and `continue_testing`
otherwise. These two print `stop_futility`, then `continue_testing`:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/ai/interpret/checkout-v2 \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"experiment_id": "checkout-v2", "variant_name": "simplified", "p_value": 0.03, "relative_improvement_pct": -2.5}' \
  | jq -r .recommendation

curl -s -X POST localhost:8000/api/v1/ai/interpret/checkout-v2 \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"experiment_id": "checkout-v2", "variant_name": "simplified", "p_value": 0.4, "relative_improvement_pct": 1.1}' \
  | jq -r .recommendation
```
<!-- expect: stop_futility -->
<!-- expect: continue_testing -->

All four body fields are required. An empty body answers `422`, naming each
missing field:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/ai/interpret/checkout-v2 \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{}' | jq -r '.detail[].loc[1]'
```
<!-- expect: experiment_id -->
<!-- expect: variant_name -->
<!-- expect: p_value -->
<!-- expect: relative_improvement_pct -->

---

## Sample size: `GET /api/v1/ai/sample-size`

Give a baseline rate (`baseline_rate`) and a minimum detectable effect
(`mde`); a confidence level (`confidence`) and power (`power`) are optional,
0.95 and 0.80 by default. `mde` is an absolute change in the rate: 0.004 on a
baseline of 0.08 plans for 8% against 8.4%, a 5% relative lift.

The estimate is for a control and one treatment. Add `daily_traffic`, the
users a day who enter the experiment (1 to 10^12), and `days_to_significance`
is the whole days until each variant has `required_per_variant` users. The
two variants split the day's users, so at 10,000 a day each gets 5,000, and
73,855 per variant takes 14.8 days: 15. Without `daily_traffic` it is `null`.

```{.bash exec}
curl -s "localhost:8000/api/v1/ai/sample-size?baseline_rate=0.08&mde=0.004&power=0.80&daily_traffic=10000" \
  -H "Authorization: Bearer $TOKEN" | jq .
```
<!-- expect: "required_per_variant": 73855 -->
<!-- expect: "total_required": 147710 -->
<!-- expect: "days_to_significance": 15 -->

```json
{
  "required_per_variant": 73855,
  "total_required": 147710,
  "days_to_significance": 15,
  "assumptions": {"baseline_rate": 0.08, "mde": 0.004, "confidence": 0.95, "power": 0.8}
}
```

---

## Experiment templates: `GET /api/v1/ai/templates`

Five templates, one for each experiment type. This prints each one's id and
type:

```{.bash exec}
curl -s localhost:8000/api/v1/ai/templates \
  -H "Authorization: Bearer $TOKEN" | jq -r '.[] | "\(.id) \(.experiment_type)"'
```
<!-- expect: checkout-cta checkout -->
<!-- expect: onboarding-flow onboarding -->
<!-- expect: pricing-display pricing -->
<!-- expect: email-subject email -->
<!-- expect: landing-page-hero landing_page -->

`type` keeps the templates of one experiment type:

```{.bash exec}
curl -s "localhost:8000/api/v1/ai/templates?type=pricing" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.[].id'
```
<!-- expect: pricing-display -->

One template, by its id:

```{.bash exec}
curl -s localhost:8000/api/v1/ai/templates/checkout-cta \
  -H "Authorization: Bearer $TOKEN" | jq '{name, primary_metric, guardrail_metrics}'
```
<!-- expect: "name": "Checkout CTA Button Test" -->
<!-- expect: "primary_metric": "conversion_rate" -->
