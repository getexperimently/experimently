"""
LLM Proxy Service (EP-046).

Routes completion requests to the appropriate LLM provider, measures latency,
estimates cost, and stores LLMEvaluation records.
"""

import logging
import re
import time
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.models.llm_experiment import LLMEvaluation, LLMVariant
from backend.app.services.llm_experiment_service import LLMExperimentService

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
    "anthropic": {
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
        "claude-opus-4-6": {"input": 0.015, "output": 0.075},
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

    Falls back to 0.0 when provider/model is not found in the cost table.
    """
    provider_costs = COST_PER_1K_TOKENS.get(provider, {})
    model_costs = provider_costs.get(model_name, {})
    if not model_costs:
        return 0.0
    input_cost = (input_tokens / 1000.0) * model_costs.get("input", 0.0)
    output_cost = (output_tokens / 1000.0) * model_costs.get("output", 0.0)
    return round(input_cost + output_cost, 8)


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------


class ProviderResponse:
    """Normalised response from any LLM provider."""

    def __init__(
        self,
        text: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class BaseProvider:
    """Abstract base for LLM providers."""

    async def complete(
        self,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> ProviderResponse:
        raise NotImplementedError


class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider."""

    async def complete(
        self,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> ProviderResponse:
        try:
            import anthropic  # type: ignore

            client = anthropic.AsyncAnthropic()
            # Separate system message from conversation
            system = ""
            conversation = []
            for msg in messages:
                if msg.get("role") == "system":
                    system = msg.get("content", "")
                else:
                    conversation.append(msg)
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system or anthropic.NOT_GIVEN,
                messages=conversation,
                temperature=temperature,
                **kwargs,
            )
            text = response.content[0].text if response.content else ""
            input_tok = response.usage.input_tokens if response.usage else 0
            output_tok = response.usage.output_tokens if response.usage else 0
            return ProviderResponse(
                text=text, input_tokens=input_tok, output_tokens=output_tok
            )
        except Exception as exc:
            logger.error(f"Anthropic completion failed: {exc}")
            raise


class OpenAIProvider(BaseProvider):
    """OpenAI provider."""

    async def complete(
        self,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> ProviderResponse:
        try:
            import openai  # type: ignore

            client = openai.AsyncOpenAI()
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            text = response.choices[0].message.content or ""
            input_tok = response.usage.prompt_tokens if response.usage else 0
            output_tok = response.usage.completion_tokens if response.usage else 0
            return ProviderResponse(
                text=text, input_tokens=input_tok, output_tokens=output_tok
            )
        except Exception as exc:
            logger.error(f"OpenAI completion failed: {exc}")
            raise


class GoogleProvider(BaseProvider):
    """Google Gemini provider."""

    async def complete(
        self,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> ProviderResponse:
        try:
            import google.generativeai as genai  # type: ignore

            # Combine messages into a single prompt for simplicity
            prompt = "\n".join(
                m.get("content", "") for m in messages if m.get("role") != "system"
            )
            model_obj = genai.GenerativeModel(model)
            response = await model_obj.generate_content_async(
                prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            text = response.text if response.text else ""
            # Gemini doesn't always expose token counts — approximate
            input_tok = len(prompt.split())
            output_tok = len(text.split())
            return ProviderResponse(
                text=text, input_tokens=input_tok, output_tokens=output_tok
            )
        except Exception as exc:
            logger.error(f"Google completion failed: {exc}")
            raise


class LocalProvider(BaseProvider):
    """Stub local provider (Ollama / llama.cpp / vLLM)."""

    async def complete(
        self,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> ProviderResponse:
        # Minimal httpx-based call to localhost:11434 (Ollama default)
        try:
            import httpx  # type: ignore

            prompt = "\n".join(m.get("content", "") for m in messages)
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "http://localhost:11434/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                    timeout=60,
                )
                r.raise_for_status()
                data = r.json()
                text = data.get("response", "")
                return ProviderResponse(
                    text=text,
                    input_tokens=len(prompt.split()),
                    output_tokens=len(text.split()),
                )
        except Exception as exc:
            logger.error(f"Local provider completion failed: {exc}")
            raise


PROVIDERS: Dict[str, BaseProvider] = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
    "google": GoogleProvider(),
    "local": LocalProvider(),
}


def get_provider(provider_name: str) -> BaseProvider:
    """Return the provider instance for the given name."""
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(f"Unknown provider: {provider_name}")
    return provider


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def render_prompt_template(template: str, variables: Dict[str, Any]) -> str:
    """
    Replace ``{{variable}}`` placeholders in a prompt template.

    Raises:
        ValueError: if any placeholder in the template is missing from variables.
    """
    placeholders = set(re.findall(r"\{\{(\w+)\}\}", template))
    missing = placeholders - set(variables.keys())
    if missing:
        raise ValueError(
            f"Missing variables for prompt template: {', '.join(sorted(missing))}"
        )
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


# ---------------------------------------------------------------------------
# Proxy service
# ---------------------------------------------------------------------------


class LLMProxyService:
    """
    Routes LLM completion requests to the correct provider.

    Responsibilities:
    1. Render prompt template with input variables.
    2. Route to correct provider (OpenAI / Anthropic / Google / Local).
    3. Measure wall-clock latency.
    4. Record token counts and estimate cost.
    5. Persist an LLMEvaluation record.
    6. Return the normalised result.
    """

    def __init__(self, experiment_service: Optional[LLMExperimentService] = None):
        self._experiment_service = experiment_service or LLMExperimentService()

    async def complete(
        self,
        db: Session,
        experiment_id: UUID,
        user_id: str,
        input_variables: Dict[str, Any],
    ) -> LLMEvaluation:
        """
        Assign a variant, call the LLM, and persist an evaluation record.

        Returns the saved LLMEvaluation row.
        """
        variant = self._experiment_service.assign_variant(db, experiment_id, user_id)
        return await self._call_variant(
            db, variant, input_variables, user_id, experiment_id
        )

    async def _call_variant(
        self,
        db: Session,
        variant: LLMVariant,
        input_variables: Dict[str, Any],
        user_id: str,
        experiment_id: UUID,
    ) -> LLMEvaluation:
        """Internal: render prompt, call provider, save evaluation."""
        rendered = render_prompt_template(variant.prompt_template, input_variables)

        messages = []
        if variant.system_prompt:
            messages.append({"role": "system", "content": variant.system_prompt})
        messages.append({"role": "user", "content": rendered})

        provider_name = (
            variant.provider.value
            if hasattr(variant.provider, "value")
            else str(variant.provider)
        )
        provider = get_provider(provider_name)

        extra_params = variant.additional_params or {}
        start = time.monotonic()
        provider_response = await provider.complete(
            model=variant.model_name,
            messages=messages,
            temperature=variant.temperature,
            max_tokens=variant.max_tokens,
            **extra_params,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        cost = estimate_cost(
            provider_name,
            variant.model_name,
            provider_response.input_tokens,
            provider_response.output_tokens,
        )

        evaluation = LLMEvaluation(
            llm_experiment_id=experiment_id,
            variant_id=variant.id,
            user_id=user_id,
            input_variables=input_variables,
            rendered_prompt=rendered,
            model_response=provider_response.text,
            latency_ms=elapsed_ms,
            input_tokens=provider_response.input_tokens,
            output_tokens=provider_response.output_tokens,
            estimated_cost_usd=cost,
        )
        db.add(evaluation)
        db.commit()
        db.refresh(evaluation)
        return evaluation
