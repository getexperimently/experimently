# LLM/AI Model Evaluation — Overview

EP-046 extends the platform to become the first open-source experimentation platform with **native LLM experiment support**. Users can compare prompt versions, model variants (GPT-4 vs Claude vs Gemini), agent configurations, and system prompts against real business metrics — all without leaving the platform.

---

## Why LLM Evaluation is Different from Traditional A/B Testing

Traditional A/B tests compare binary outcomes (conversion yes/no) or continuous metrics (revenue). LLM experiments introduce new dimensions:

| Dimension | Traditional A/B | LLM Experiment |
|-----------|----------------|----------------|
| Unit | Page / feature variant | Prompt / model config |
| Response | Binary or numeric | Free-form text |
| Latency | Milliseconds (deterministic) | 500 ms – 30 s (variable) |
| Cost | Fixed infra cost | Per-token billing |
| Quality | Implicit (conversion) | Explicit (human rating / LLM judge) |
| Reproducibility | High | Low (temperature / sampling) |

The platform handles all of this automatically: it tracks latency, estimates cost, supports human rating collection, and can run automated LLM-as-judge scoring.

---

## Supported Providers and Models

| Provider | Models | Notes |
|----------|--------|-------|
| **Anthropic** | claude-3-5-sonnet-20241022, claude-3-haiku-20240307, claude-opus-4-6 | Recommended judge model |
| **OpenAI** | gpt-4o, gpt-4o-mini, gpt-3.5-turbo | Cost-efficient options available |
| **Google** | gemini-1.5-pro, gemini-1.5-flash | Flash: lowest cost per token |
| **Cohere** | command-r-plus, command-r | Enterprise RAG use cases |
| **Mistral** | mistral-large-latest, mistral-small-latest | EU-hosted option |
| **Local** | Any Ollama-compatible model | Privacy / cost-free option |

Configure API keys via environment variables:
```bash
LLM_ANTHROPIC_API_KEY=sk-ant-...
LLM_OPENAI_API_KEY=sk-...
LLM_GOOGLE_API_KEY=...
```

---

## Task Types

Each LLM experiment is associated with a task type that describes what the model does:

| Task Type | Description | Example Use Case |
|-----------|-------------|-----------------|
| `chat_completion` | Multi-turn conversational interaction | Customer support chatbot |
| `text_generation` | Single-turn open-ended generation | Product description writer |
| `classification` | Categorise input into predefined classes | Sentiment analyser |
| `summarization` | Condense long text into shorter form | Document summariser |
| `code_generation` | Produce executable code | Programming assistant |
| `embedding` | Produce vector representations | Semantic search |

---

## Evaluation Metrics

Choose the primary metric that defines "winning" for your experiment:

| Metric | Description | When to Use |
|--------|-------------|-------------|
| `business_metric` | Downstream KPI (conversion, revenue, engagement) | Most production scenarios |
| `human_rating` | Human expert 1–5 score | High-stakes quality evaluation |
| `auto_eval_score` | LLM-as-judge 0–1 score | Scalable quality evaluation |
| `latency` | Response time in milliseconds | Latency-sensitive applications |
| `cost` | Estimated USD per request | Budget-constrained deployments |
| `accuracy` | Binary correctness on ground truth | Classification / QA tasks |
| `relevance` | Relevance to the query | Search / retrieval tasks |
| `fluency` | Natural language quality | Text generation tasks |

---

## Variant Assignment

Variants are assigned using **consistent MD5 hashing** (the same algorithm used by all platform SDKs). The same `user_id` always receives the same variant, ensuring reproducibility and preventing confounding from re-assignment.

The hash key is `"{experiment_id}:{user_id}"`, mapped to a bucket in [0, 1) and distributed across variants according to their `traffic_split` values.

---

## LLM-as-Judge Scoring

The platform supports automated quality evaluation using a judge LLM (default: claude-3-5-sonnet-20241022). The judge is prompted:

```
Rate the following AI response on '{criteria}' using a score from 0 (terrible)
to 1 (excellent).

Original prompt: {prompt}
Response: {response}

Reply with ONLY: {"score": <float 0-1>, "reasoning": "<one sentence>"}
```

Judge scores are stored as `auto_eval_score` on each evaluation record and included in the results analytics.

---

## Cost Estimation

The platform automatically estimates the cost of each LLM call using a built-in cost table:

```
claude-3-5-sonnet-20241022: $0.003/1k input + $0.015/1k output
gpt-4o:                     $0.0025/1k input + $0.010/1k output
gemini-1.5-flash:           $0.000075/1k input + $0.0003/1k output
```

Cost data is visible per-variant in the results dashboard, enabling cost/quality trade-off analysis.

---

## Statistical Analysis

Results include:
- **Mean and 95% confidence interval** for latency, cost, auto-eval score, and business metric
- **Welch's t-test p-value** (treatment vs control) for continuous metrics
- **Cohen's d effect size** for business metric and auto-eval score
- **Winner determination** based on the highest mean business metric (falls back to auto-eval score)
