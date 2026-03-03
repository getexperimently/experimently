# MCP Server Integration (Issue #23)

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
  "name": "experimentation-platform",
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

**Response**

```json
{
  "name": "Simplified Onboarding Checklist",
  "hypothesis": "Reducing the onboarding checklist from 8 steps to 4 will increase 7-day activation by removing friction for new users who feel overwhelmed",
  "suggested_metrics": ["7_day_activation", "checklist_completion_rate", "time_to_first_value"],
  "suggested_variants": [
    {"name": "control", "description": "Current 8-step checklist"},
    {"name": "simplified", "description": "4-step checklist focusing on core actions only"}
  ],
  "recommended_duration_days": 14,
  "recommended_traffic_pct": 50,
  "confidence": "high",
  "source": "claude_api"
}
```

`source` is either `"claude_api"` (live AI suggestion) or `"template"` (fallback).

---

## AI Results Interpretation (`/api/v1/ai/interpret/{experiment_id}`)

Returns a plain-English interpretation of experiment results with a ship/no-ship recommendation.

### POST /api/v1/ai/interpret/{experiment_id}

```bash
curl -X POST "http://localhost:8000/api/v1/ai/interpret/exp-uuid" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Response**

```json
{
  "experiment_id": "exp-uuid",
  "summary": "The simplified checkout treatment increased conversion rate by 3.2% (from 8.1% to 8.4%) with 97% statistical confidence. The improvement is consistent across mobile and desktop segments.",
  "recommendation": "ship",
  "confidence": "high",
  "caveats": ["Sample size is at the lower end of the target; monitor post-launch for regression"],
  "source": "claude_api"
}
```

---

## Sample Size Calculator (`/api/v1/ai/sample-size`)

Calculate the required sample size per variant given baseline rate, MDE, significance level, and statistical power.

```bash
curl -X GET "http://localhost:8000/api/v1/ai/sample-size?baseline=0.08&mde=0.05&alpha=0.05&power=0.80" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Experiment Templates (`/api/v1/ai/templates`)

Pre-built experiment templates for common use cases.

```bash
# List all templates
curl -X GET "http://localhost:8000/api/v1/ai/templates" \
  -H "Authorization: Bearer $TOKEN"

# Get a specific template
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

If `ANTHROPIC_API_KEY` is not set, all AI endpoints return template-based responses with `"source": "template"`. The platform degrades gracefully — no errors are raised.

---

## Connecting from Claude Code (IDE)

Add the MCP server to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "experimentation-platform": {
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
