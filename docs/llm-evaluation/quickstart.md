# LLM/AI Model Evaluation — Quick Start

This guide walks you through a complete example: comparing **GPT-4o** (treatment) against **Claude 3.5 Sonnet** (control) for a customer support task.

Run the commands in one terminal, in order, against the stack from the
[Quick Start](../getting-started/quick-start.md). Each uses the shell variables set by the
ones before it.

**Not yet working on a stock deployment: getting a completion.** The API image doesn't
include the providers' client libraries, so `/complete` answers
`502 {"detail":"LLM provider error: No module named 'openai'"}` (or `'anthropic'`) even with
a provider key set ([#196](https://github.com/getexperimently/experimently/issues/196)).
Steps 1, 2 and 6 work; steps 3 to 5 need completions, and our documentation checks don't
run them until that is fixed.

---

## 1. Create an Experiment

Log in first. Creating and starting an experiment takes the DEVELOPER or ADMIN role:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

It prints `"ADMIN"`.

Create the experiment, with one variant per model. The collection URL ends with a slash,
`/api/v1/llm-experiments/`; without it the API answers `307`, which `curl` doesn't follow.
This saves the experiment's id in `$EXPERIMENT_ID`:

```{.bash exec}
EXPERIMENT=$(curl -s -X POST localhost:8000/api/v1/llm-experiments/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
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
  }')
EXPERIMENT_ID=$(jq -r .id <<<"$EXPERIMENT")

jq '{name, status, variants: [.variants[].name]}' <<<"$EXPERIMENT"
```
<!-- expect: "name": "Customer Support: Claude vs GPT-4o" -->
<!-- expect: "status": "DRAFT" -->

The API answers `201 Created`:

```json
{
  "name": "Customer Support: Claude vs GPT-4o",
  "status": "DRAFT",
  "variants": [
    "control_claude",
    "treatment_gpt4o"
  ]
}
```

The response also carries the experiment's `id`, `description`, `task_type`,
`evaluation_metric`, and each variant's full settings and `id`.

---

## 2. Start the Experiment

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/start \
  -H "Authorization: Bearer $TOKEN" | jq .status
```
<!-- expect: "ACTIVE" -->

It prints `"ACTIVE"`.

---

## 3. Route User Requests Through the Experiment

For each incoming customer message, call the `/complete` endpoint. The platform assigns the
user to a variant deterministically (the same user always gets the same model), renders the
variant's prompt template with `input_variables`, and calls the model. This saves the
evaluation's id in `$EVALUATION_ID`, for step 4:

```{.bash skip reason="bug #196: the API image has no LLM provider client libraries, so /complete answers 502"}
COMPLETION=$(curl -s -X POST localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/complete \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "user_id": "customer-12345",
    "input_variables": {
      "customer_message": "My order has not arrived after 2 weeks. Can you help?"
    }
  }')
EVALUATION_ID=$(jq -r .evaluation_id <<<"$COMPLETION")

jq . <<<"$COMPLETION"
```

The response names the variant and the model, and carries the model's reply with its cost:

```json
{
  "variant_id": "2f2b5ac5-0c2a-4c6b-ba31-3b773b19b8a9",
  "variant_name": "treatment_gpt4o",
  "provider": "openai",
  "model_name": "gpt-4o",
  "response": "I'm sorry to hear your order hasn't arrived yet...",
  "latency_ms": 1234,
  "cost_usd": 0.00087,
  "input_tokens": 89,
  "output_tokens": 142,
  "evaluation_id": "8c1f0d7e-3b52-4f0e-9a51-6f3d2c7b9e10"
}
```

The provider keys are the API's environment variables, such as `OPENAI_API_KEY` and
`ANTHROPIC_API_KEY`.

---

## 4. Record Business Outcomes

When the customer resolves their issue (converts), submit the business metric for that
evaluation:

```{.bash skip reason="bug #196: needs the evaluation id that /complete returns"}
curl -s -X POST localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/evaluate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d "{\"evaluation_id\": \"$EVALUATION_ID\", \"business_metric_value\": 1.0}"
```

You can also submit a human rating (1–5) from your QA team:

```{.bash skip reason="bug #196: needs the evaluation id that /complete returns"}
curl -s -X POST localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/evaluate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d "{\"evaluation_id\": \"$EVALUATION_ID\", \"human_rating\": 4.5}"
```

---

## 5. Run Automated Quality Scoring (Optional)

Use LLM-as-judge to score the responses on a quality dimension. The judge model is called
through the same provider libraries:

```{.bash skip reason="bug #196: the judge model is called through the provider client libraries the API image lacks"}
curl -s -X POST localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/judge \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "criteria": "empathy_and_helpfulness",
    "judge_model": "claude-3-5-sonnet-20241022"
  }'
```

---

## 6. Read Results and Declare a Winner

```{.bash exec}
curl -s localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/results \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{status, total_evaluations, variants: [.variant_stats[] | {variant_name, n_evaluations}]}'
```
<!-- expect: "status": "ACTIVE" -->
<!-- expect: "total_evaluations": 0 -->

With no completions yet, every count is `0`:

```json
{
  "status": "ACTIVE",
  "total_evaluations": 0,
  "variants": [
    {
      "variant_name": "control_claude",
      "n_evaluations": 0
    },
    {
      "variant_name": "treatment_gpt4o",
      "n_evaluations": 0
    }
  ]
}
```

With traffic, the full response looks like this:

```json
{
  "experiment_id": "550e8400-e29b-41d4-a716-446655440000",
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

```text
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

Pause the experiment:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/pause \
  -H "Authorization: Bearer $TOKEN" | jq .status
```
<!-- expect: "PAUSED" -->

It prints `"PAUSED"`. While paused, `/complete` answers `400`. Starting it again resumes it:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/llm-experiments/$EXPERIMENT_ID/start \
  -H "Authorization: Bearer $TOKEN" | jq .status
```
<!-- expect: "ACTIVE" -->

It prints `"ACTIVE"`.

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
