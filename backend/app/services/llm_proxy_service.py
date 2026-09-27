"""
LLM Proxy Service (EP-046).

Routes completion requests to the appropriate LLM provider, measures latency,
estimates cost, and stores LLMEvaluation records.
"""

import logging
import os
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from backend.app.core.anthropic_compat import drop_unsupported_sampling, first_text

# Re-exported: callers and tests import these from here, and the prices
# live in their own module so the model-literal gate can exempt exactly it.
from backend.app.core.llm_pricing import estimate_cost
from backend.app.models.llm_experiment import LLMEvaluation, LLMVariant
from backend.app.services.llm_experiment_service import LLMExperimentService

logger = logging.getLogger(__name__)


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
            # temperature/top_p/top_k are REMOVED on Sonnet 5, Opus 5, Opus
            # 4.8/4.7 and the Fable family -- sending one returns a 400, so an
            # unconditional `temperature=` made this provider fail outright for
            # every current Claude model a user might pick.
            #
            # Filtered on the MERGED set: `kwargs` is the variant's free-form
            # `additional_params`, so `{"top_p": 0.9}` reached the API without
            # going near the named `temperature` argument that an earlier,
            # narrower check was watching.
            request = drop_unsupported_sampling(
                model, {"temperature": temperature, **kwargs}
            )
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system or anthropic.NOT_GIVEN,
                messages=conversation,
                **request,
            )
            # Not content[0]: with thinking on, the first block is a thinking
            # block and .text raises.
            text = first_text(response)
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


class GeminiError(RuntimeError):
    """A Gemini API call failed: no key, an HTTP error, or a body we cannot read.

    Raised rather than returned so the ``/complete`` endpoint maps it to the
    same ``502 LLM provider error`` as every other provider's failure.
    """


#: The API key, sent as the ``x-goog-api-key`` header. The name is the one
#: Google's Gemini API documentation uses.
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
#: Overrides the API's origin -- a proxy, a gateway, or a stub in tests.
GEMINI_BASE_URL_ENV = "GEMINI_BASE_URL"
GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
#: The longest provider error message copied into our own error, so an
#: unexpected body cannot make the 502 detail (or a log line) arbitrarily long.
_GEMINI_ERROR_DETAIL_MAX = 300
#: Finish reasons after which a candidate with no text is an empty completion.
#: ``None`` is a candidate that carries no finishReason at all.
_GEMINI_ORDINARY_FINISH = frozenset(
    {None, "STOP", "MAX_TOKENS", "FINISH_REASON_UNSPECIFIED"}
)


def _bounded(value: Any) -> str:
    """A provider-supplied value, as text no longer than the error bound."""
    return str(value)[:_GEMINI_ERROR_DETAIL_MAX]


class GoogleProvider(BaseProvider):
    """Google Gemini provider, over the Gemini REST API.

    ``POST {GEMINI_BASE_URL}/v1beta/models/{model}:generateContent`` with the
    key from ``GEMINI_API_KEY``. It uses the ``httpx`` the API already pins:
    the ``google-generativeai`` SDK this used to import was never installed in
    the image, so every Gemini variant failed (#196).

    ``transport`` is for tests (``httpx.MockTransport``); production passes none.
    """

    def __init__(self, transport: Optional[Any] = None):
        self._transport = transport

    @staticmethod
    def _request_body(
        messages: list, temperature: float, max_tokens: int, extra: Dict[str, Any]
    ) -> Dict[str, Any]:
        system_parts = []
        contents = []
        for msg in messages:
            role = msg.get("role")
            text = str(msg.get("content", ""))
            if role == "system":
                system_parts.append({"text": text})
            else:
                # Gemini calls the assistant turn "model".
                contents.append(
                    {
                        "role": "model" if role == "assistant" else "user",
                        "parts": [{"text": text}],
                    }
                )
        body: Dict[str, Any] = {
            "contents": contents,
            # The variant's free-form additional_params go into the generation
            # config, where Gemini's sampling settings (topP, topK, ...) live.
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                **extra,
            },
        }
        if system_parts:
            body["systemInstruction"] = {"parts": system_parts}
        return body

    @staticmethod
    def _error_detail(response: Any) -> str:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text
        return str(message)[:_GEMINI_ERROR_DETAIL_MAX]

    @staticmethod
    def _parse(data: Any) -> ProviderResponse:
        """Map a generateContent body to a ProviderResponse.

        Anything unexpected -- including a ValueError or TypeError from a
        field of the wrong type -- becomes a GeminiError, so ``/complete``
        answers its 502 rather than the 400 it gives a ValueError.
        """
        try:
            return GoogleProvider._parse_unchecked(data)
        except GeminiError:
            raise
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise GeminiError(
                f"Gemini returned a response we cannot read ({type(exc).__name__})"
            ) from exc

    @staticmethod
    def _parse_unchecked(data: Any) -> ProviderResponse:
        if not isinstance(data, dict):
            raise GeminiError("Gemini returned a response body that is not an object")
        candidates = data.get("candidates")
        if not candidates:
            feedback = data.get("promptFeedback") or {}
            reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
            raise GeminiError(
                "Gemini returned no candidates"
                + (f" (blockReason={_bounded(reason)})" if reason else "")
            )
        candidate = candidates[0] if isinstance(candidates, list) else None
        content = candidate.get("content", {}) if isinstance(candidate, dict) else None
        parts = content.get("parts", []) if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise GeminiError("Gemini returned a candidate we cannot read")
        text = "".join(
            str(p["text"]) for p in parts if isinstance(p, dict) and "text" in p
        )
        # No text is an empty completion only when the model stopped for an
        # ordinary reason (MAX_TOKENS before any text, say). Any other finish
        # reason with no text -- SAFETY, RECITATION, BLOCKLIST,
        # PROHIBITED_CONTENT, SPII, OTHER, or a value added after this was
        # written -- is a refusal, and reported as one rather than recorded
        # as an empty answer.
        finish = candidate.get("finishReason") if isinstance(candidate, dict) else None
        if not text and finish not in _GEMINI_ORDINARY_FINISH:
            raise GeminiError(
                f"Gemini returned no text (finishReason={_bounded(finish)})"
            )
        usage = data.get("usageMetadata") or {}
        if not isinstance(usage, dict):
            usage = {}
        return ProviderResponse(
            text=text,
            input_tokens=int(usage.get("promptTokenCount") or 0),
            output_tokens=int(usage.get("candidatesTokenCount") or 0),
        )

    async def complete(
        self,
        model: str,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> ProviderResponse:
        try:
            api_key = os.environ.get(GEMINI_API_KEY_ENV, "")
            if not api_key:
                raise GeminiError(f"{GEMINI_API_KEY_ENV} is not set")
            base_url = (
                os.environ.get(GEMINI_BASE_URL_ENV) or GEMINI_DEFAULT_BASE_URL
            ).rstrip("/")
            # Quoted whole, so a model name cannot add path segments or a
            # query to the request; "models/gemini-x" and "gemini-x" both work.
            model_id = quote(model.removeprefix("models/"), safe="")
            url = f"{base_url}/v1beta/models/{model_id}:generateContent"
            body = self._request_body(messages, temperature, max_tokens, kwargs)

            try:
                async with httpx.AsyncClient(
                    transport=self._transport, timeout=60
                ) as client:
                    response = await client.post(
                        url, json=body, headers={"x-goog-api-key": api_key}
                    )
            except httpx.HTTPError as exc:
                # The key travels in a header, never the URL, so the message
                # of a transport error does not carry it.
                raise GeminiError(
                    f"Gemini request failed: {type(exc).__name__}"
                ) from exc

            if response.status_code >= 400:
                raise GeminiError(
                    f"Gemini API returned HTTP {response.status_code}: "
                    f"{self._error_detail(response)}"
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise GeminiError(
                    "Gemini returned a response that is not JSON"
                ) from exc
            return self._parse(data)
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
