# LLM/AI Model Evaluation — Quick Start

This guide walks you through a complete example: comparing **GPT-4o** (treatment) against **Claude 3.5 Sonnet** (control) for a customer support task.

---

## 1. Create an Experiment

```bash
curl -X POST http://localhost:8000/api/v1/llm-experiments/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Customer Support: Claude vs GPT-4o",
    "description": "Compare Claude Sonnet and GPT-4o on customer support quality",
    "task_type": "chat_completion",
    "evaluation_metric": "business_metric",
    "variants": [
      {
        "name": "control_claude",
        "is_control": true,
        "traffic_split": 0.5,
        "provider": "anthropic",
        "model_name": "claude-3-5-sonnet-20241022",
        "system_prompt": "You are a helpful customer support agent for Acme Corp.",
        "prompt_template": "Customer question: {{customer_message}}\n\nProvide a clear, empathetic response.",
        "temperature": 0.7,
        "max_tokens": 500
      },
      {
        "name": "treatment_gpt4o",
        "is_control": false,
        "traffic_split": 0.5,
        "provider": "openai",
        "model_name": "gpt-4o",
        "system_prompt": "You are a helpful customer support agent for Acme Corp.",
        "prompt_template": "Customer question: {{customer_message}}\n\nProvide a clear, empathetic response.",
        "temperature": 0.7,
        "max_tokens": 500
      }
    ]
  }'
```

Response:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Customer Support: Claude vs GPT-4o",
  "status": "DRAFT",
  "task_type": "chat_completion",
  "evaluation_metric": "business_metric",
  "variants": [...]
}
```

---

## 2. Start the Experiment

```bash
EXPERIMENT_ID="550e8400-e29b-41d4-a716-446655440000"

curl -X POST http://localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/start \
  -H "Authorization: Bearer $TOKEN"
```

---

## 3. Route User Requests Through the Experiment

For each incoming customer message, call the `/complete` endpoint. The platform assigns the user to a variant deterministically (same user always gets the same model).

```bash
curl -X POST http://localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/complete \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "customer-12345",
    "input_variables": {
      "customer_message": "My order hasn'\''t arrived after 2 weeks. Can you help?"
    }
  }'
```

Response:
```json
{
  "variant_id": "...",
  "variant_name": "control_claude",
  "provider": "anthropic",
  "model_name": "claude-3-5-sonnet-20241022",
  "response": "I'm sorry to hear your order hasn't arrived yet...",
  "latency_ms": 1234,
  "cost_usd": 0.00087,
  "input_tokens": 89,
  "output_tokens": 142,
  "evaluation_id": "abc123..."
}
```

---

## 4. Record Business Outcomes

When the customer resolves their issue (converts), submit the business metric:

```bash
curl -X POST http://localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/evaluate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "evaluation_id": "abc123...",
    "business_metric_value": 1.0
  }'
```

You can also submit a human rating (1–5) from your QA team:

```bash
curl -X POST http://localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/evaluate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "evaluation_id": "abc123...",
    "human_rating": 4.5
  }'
```

---

## 5. Run Automated Quality Scoring (Optional)

Use LLM-as-judge to score all responses on a quality dimension:

```bash
curl -X POST http://localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/judge \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "criteria": "empathy_and_helpfulness",
    "judge_model": "claude-3-5-sonnet-20241022"
  }'
```

---

## 6. Read Results and Declare a Winner

```bash
curl http://localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/results \
  -H "Authorization: Bearer $TOKEN"
```

Response:
```json
{
  "experiment_id": "550e8400...",
  "experiment_name": "Customer Support: Claude vs GPT-4o",
  "status": "ACTIVE",
  "evaluation_metric": "business_metric",
  "total_evaluations": 1247,
  "winner_variant_name": "treatment_gpt4o",
  "variant_stats": [
    {
      "variant_name": "control_claude",
      "is_control": true,
      "n_evaluations": 624,
      "mean_latency_ms": 1850.3,
      "mean_cost_usd": 0.000923,
      "mean_business_metric": 0.71,
      "business_metric_ci_lower": 0.674,
      "business_metric_ci_upper": 0.746,
      "p_value": null,
      "effect_size": null
    },
    {
      "variant_name": "treatment_gpt4o",
      "is_control": false,
      "n_evaluations": 623,
      "mean_latency_ms": 1120.6,
      "mean_cost_usd": 0.001245,
      "mean_business_metric": 0.79,
      "business_metric_ci_lower": 0.756,
      "business_metric_ci_upper": 0.824,
      "p_value": 0.003,
      "effect_size": 0.42
    }
  ]
}
```

**Interpretation**: GPT-4o achieves a 79% resolution rate vs Claude's 71% (p=0.003, medium effect). GPT-4o costs $0.0003 more per request but is 39% faster. Based on these results, ship GPT-4o.

---

## Prompt Template Variables

Use `{{double_braces}}` in your prompt templates:

```
Template: "Summarize this article for a {{audience}} audience: {{article}}"

Input variables: {
  "audience": "5-year-old",
  "article": "Quantum computing leverages..."
}

Rendered: "Summarize this article for a 5-year-old audience: Quantum computing leverages..."
```

Missing variables will cause a `400 Bad Request` error.

---

## Pausing and Resuming

```bash
# Pause
curl -X POST http://localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/pause \
  -H "Authorization: Bearer $TOKEN"

# Resume
curl -X POST http://localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/start \
  -H "Authorization: Bearer $TOKEN"
```

---

## Permissions

| Action | Required Role |
|--------|--------------|
| Create / Start / Pause experiment | DEVELOPER or ADMIN |
| Add / update variants | DEVELOPER or ADMIN |
| Get completion | Any authenticated user (READ) |
| Submit evaluation | DEVELOPER or ADMIN |
| Get results | Any authenticated user (READ) |
| Run LLM-as-judge | DEVELOPER or ADMIN |
