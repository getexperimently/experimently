# MCP Server Integration

The platform exposes a Model Context Protocol (MCP) server that allows AI coding assistants and agents (e.g. Claude, Cursor, GitHub Copilot) to interact with the experimentation platform directly from an IDE or chat interface.

---

## What is MCP?

MCP (Model Context Protocol) is an open standard for exposing structured tool manifests to AI systems. When an AI assistant discovers the platform's MCP manifest, it can invoke platform operations — creating experiments, fetching results, toggling feature flags — using natural language instructions.

---

## Available Tools

The MCP manifest is served at `GET /api/v1/mcp/manifest` (no authentication required for discovery).

| Tool | Description |
|------|-------------|
| `create_experiment` | Create a new A/B experiment with a name, hypothesis, and metric list |
| `get_results` | Retrieve statistical results for a specific experiment by ID or key |
| `toggle_feature_flag` | Enable or disable a feature flag by key |
| `suggest_experiment` | Get AI-powered experiment design suggestions from a natural language description |
| `interpret_results` | Get a plain-English interpretation and ship/no-ship recommendation for experiment results |

---

## Discovery Endpoint

```bash
curl http://localhost:8000/api/v1/mcp/manifest
```

```json
{
  "name": "experimently",
  "version": "1.0.0",
  "tools": [
    {
      "name": "suggest_experiment",
      "description": "Get AI-powered experiment design suggestions based on a natural language description",
      "parameters": {
        "description": {"type": "string", "description": "Natural language description of the experiment goal"},
        "experiment_type": {"type": "string", "description": "Type of experiment (checkout, onboarding, pricing, email, landing_page)"}
      }
    }
  ]
}
```

---

## AI Experiment Design (`/api/v1/ai/design`)

The AI design endpoint accepts a natural language description and returns a structured experiment design suggestion, powered by the Claude API with a template-based fallback when the API is unavailable.

### POST /api/v1/ai/design

```bash
curl -X POST "http://localhost:8000/api/v1/ai/design" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "We want to test whether simplifying the onboarding checklist increases activation",
    "experiment_type": "onboarding"
  }'
```

**Response** (without `ANTHROPIC_API_KEY`, the template for `onboarding`)

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

`confidence` says where the suggestion came from: `"ai_generated"` when Claude answered,
`"template_based"` otherwise. When Claude answered, `reasoning` is its whole answer and
`hypothesis` its first 200 characters; the metrics, sample size, duration and variants come
from the experiment type's template either way.

The endpoint allows 10 requests a minute per client address; above that it answers
`429 Too Many Requests` with a `Retry-After: 60` header. With `ANTHROPIC_API_KEY` set, each
call to Claude gives up when Claude has not answered in 30 seconds, and is tried at most
twice; when it fails, the endpoint answers with the template-based suggestion.

---

## AI Results Interpretation (`/api/v1/ai/interpret/{experiment_id}`)

Returns a plain-English interpretation of one variant's result with a recommendation:
`ship`, `continue_testing` or `stop_futility`. It interprets the numbers in the request body;
it does not read the experiment's stored results, and it does not look up the experiment id.
All four body fields are required (an empty body answers 422).

### POST /api/v1/ai/interpret/{experiment_id}

```bash
curl -X POST "http://localhost:8000/api/v1/ai/interpret/checkout-v2" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"experiment_id": "checkout-v2", "variant_name": "simplified", "p_value": 0.03, "relative_improvement_pct": 3.2}'
```

**Response** (without `ANTHROPIC_API_KEY`)

```json
{
  "summary": "simplified showed a 3.2% improvement (p=0.030). Recommend shipping.",
  "recommendation": "ship",
  "confidence_statement": "Statistical confidence: 97.0%",
  "key_findings": ["simplified showed a 3.2% improvement (p=0.030). Recommend shipping."],
  "generated_by": "template"
}
```

`generated_by` is `"ai"` when Claude answered (the summary is then the first 300 characters
of Claude's answer) and `"template"` otherwise.

The endpoint allows 10 requests a minute per client address for every experiment id
together: `/interpret/a` and `/interpret/b` draw on the same 10. Above that it answers
`429 Too Many Requests` with a `Retry-After: 60` header. With `ANTHROPIC_API_KEY` set, each
call to Claude gives up when Claude has not answered in 30 seconds, and is tried at most
twice; when it fails, the endpoint answers with the template-based interpretation.

---

## Sample Size Calculator (`/api/v1/ai/sample-size`)

Calculate the required sample size per variant from a baseline rate (`baseline_rate`), a
minimum detectable effect (`mde`), a confidence level (`confidence`, default 0.95) and power
(`power`, default 0.80). `mde` is an absolute change in the rate: 0.004 on a baseline of 0.08
plans for 8% against 8.4%, a 5% relative lift.

```bash
curl -X GET "http://localhost:8000/api/v1/ai/sample-size?baseline_rate=0.08&mde=0.004&power=0.80" \
  -H "Authorization: Bearer $TOKEN"
```

**Response**

```json
{
  "required_per_variant": 73855,
  "total_required": 147710,
  "days_to_significance": null,
  "assumptions": {"baseline_rate": 0.08, "mde": 0.004, "confidence": 0.95, "power": 0.8}
}
```

---

## Experiment Templates (`/api/v1/ai/templates`)

Pre-built experiment templates for common use cases.

List all templates:

```bash
curl -X GET "http://localhost:8000/api/v1/ai/templates" \
  -H "Authorization: Bearer $TOKEN"
```

Get a specific template:

```bash
curl -X GET "http://localhost:8000/api/v1/ai/templates/checkout" \
  -H "Authorization: Bearer $TOKEN"
```

Available template types: `checkout`, `onboarding`, `pricing`, `email`, `landing_page`

---

## Configuring the Claude API

Set the following in your environment to enable live AI suggestions:

```bash
ANTHROPIC_API_KEY=sk-ant-your-api-key
```

If `ANTHROPIC_API_KEY` is not set, the design and interpretation endpoints answer with their templates (`"confidence": "template_based"` and `"generated_by": "template"`). The platform degrades gracefully — no errors are raised.

---

## Connecting from Claude Code (IDE)

Add the MCP server to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "experimently": {
      "url": "http://localhost:8000/api/v1/mcp/manifest"
    }
  }
}
```

After connecting, you can issue natural language commands directly in Claude Code:
- *"Suggest an experiment for improving email open rates"*
- *"What are the results for experiment checkout-v2?"*
- *"Toggle the dark-mode feature flag off"*

---

## Permissions

- MCP manifest discovery: No authentication required
- All other AI/design endpoints: Any authenticated user (VIEWER and above)
