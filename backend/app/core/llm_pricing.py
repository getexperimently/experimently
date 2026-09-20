"""Per-1K-token list prices for the LLM providers the proxy can call.

Its own module so that the "no service hard-codes a ``claude-*`` literal"
scan in ``backend/tests/unit/services/test_anthropic_compat.py`` can exempt
*this* and nothing else. It previously exempted the whole of
``llm_proxy_service``, which is the file that makes every provider call -- so a
model literal written into ``AnthropicProvider.complete``, overriding the
user's variant selection for every experiment, would have passed the gate.
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cost table
# ---------------------------------------------------------------------------

COST_PER_1K_TOKENS: Dict[str, Dict[str, Dict[str, float]]] = {
    "openai": {
        "gpt-4o": {"input": 0.0025, "output": 0.010},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    },
    # Anthropic first-party rates, USD per 1K tokens (the published figures are
    # per MTok; divide by 1000). These also apply to Claude on Microsoft
    # Foundry. Amazon Bedrock and Vertex AI are partner-operated with their own
    # pricing, so a deployment routing through those will under- or
    # over-report here -- see the note on `estimate_cost`.
    #
    # `claude-opus-4-6` was $0.015/$0.075, i.e. $15/$75 per MTok against an
    # actual $5/$25 -- a 3x over-report -- and no current model was listed at
    # all, so every one of them costed out at exactly $0.00.
    "anthropic": {
        "claude-fable-5-1": {"input": 0.010, "output": 0.050},
        "claude-opus-5": {"input": 0.005, "output": 0.025},
        "claude-opus-4-8": {"input": 0.005, "output": 0.025},
        "claude-opus-4-7": {"input": 0.005, "output": 0.025},
        "claude-opus-4-6": {"input": 0.005, "output": 0.025},
        "claude-sonnet-5": {"input": 0.002, "output": 0.010},
        "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
        "claude-haiku-4-5": {"input": 0.001, "output": 0.005},
        "claude-fable-5": {"input": 0.010, "output": 0.050},
        "claude-sonnet-4-5": {"input": 0.003, "output": 0.015},
        "claude-opus-4-5": {"input": 0.005, "output": 0.025},
        "claude-3-7-sonnet-20250219": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
        "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
    },
    "google": {
        "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
        "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
    },
    "cohere": {
        "command-r-plus": {"input": 0.003, "output": 0.015},
        "command-r": {"input": 0.00035, "output": 0.00105},
    },
    "mistral": {
        "mistral-large-latest": {"input": 0.003, "output": 0.009},
        "mistral-small-latest": {"input": 0.0002, "output": 0.0006},
    },
}


def estimate_cost(
    provider: str, model_name: str, input_tokens: int, output_tokens: int
) -> float:
    """
    Estimate the cost of an LLM call in USD.

    Returns 0.0 when the provider/model is not in the table, and **logs a
    warning** naming it. The silence was the problem: an experiment on a model
    nobody had added -- which was every current Claude model until this change
    -- recorded a cost of exactly $0.00 in the LLM experiment record, which
    reads as "free" rather than as "unknown". 0.0 is kept as the return so a
    missing price never fails a request mid-experiment; the log is what makes
    it findable.

    Rates are Anthropic/OpenAI/... first-party list prices. A deployment
    routing Claude through Amazon Bedrock or Vertex AI pays that partner's
    rates instead, and this table does not model them.
    """
    provider_costs = COST_PER_1K_TOKENS.get(provider, {})
    model_costs = provider_costs.get(model_name, {})
    if not model_costs:
        logger.warning(
            "No cost entry for provider=%s model=%s; reporting $0.00. "
            "Add it to COST_PER_1K_TOKENS.",
            provider,
            model_name,
        )
        return 0.0
    input_cost = (input_tokens / 1000.0) * model_costs.get("input", 0.0)
    output_cost = (output_tokens / 1000.0) * model_costs.get("output", 0.0)
    return round(input_cost + output_cost, 8)
