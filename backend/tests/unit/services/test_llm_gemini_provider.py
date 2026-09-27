"""The Gemini provider calls the Gemini REST API over httpx (#196).

It used to import ``google.generativeai``, which no requirements file pins and
the API image does not ship, so every Gemini variant failed at request time
while the suite -- which never exercised that import -- stayed green.

Every test here runs against ``httpx.MockTransport`` with recorded response
bodies: no network, no Google package.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx
import pytest

from backend.app.services import llm_proxy_service
from backend.app.services.llm_proxy_service import (
    PROVIDERS,
    GeminiError,
    GoogleProvider,
    ProviderResponse,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

KEY = "test-gemini-key-not-real"

# A generateContent response as the API returns it (fields abridged).
RECORDED_OK = {
    "candidates": [
        {
            "content": {"parts": [{"text": "Paris"}], "role": "model"},
            "finishReason": "STOP",
            "index": 0,
        }
    ],
    "usageMetadata": {
        "promptTokenCount": 12,
        "candidatesTokenCount": 1,
        "totalTokenCount": 13,
    },
    "modelVersion": "gemini-1.5-flash",
}

# The API's answer to a bad key: HTTP 400 with this body.
RECORDED_BAD_KEY = {
    "error": {
        "code": 400,
        "message": "API key not valid. Please pass a valid API key.",
        "status": "INVALID_ARGUMENT",
    }
}

RECORDED_UNAVAILABLE = {
    "error": {
        "code": 503,
        "message": "The model is overloaded. Please try again later.",
        "status": "UNAVAILABLE",
    }
}

MESSAGES = [
    {"role": "system", "content": "You are terse."},
    {"role": "user", "content": "Capital of France?"},
    {"role": "assistant", "content": "Which France?"},
    {"role": "user", "content": "The country."},
]


@pytest.fixture(autouse=True)
def _gemini_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.delenv("GEMINI_BASE_URL", raising=False)


def _provider(status: int, body, seen: list | None = None) -> GoogleProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if isinstance(body, (dict, list)):
            return httpx.Response(status, json=body)
        return httpx.Response(status, content=body)

    return GoogleProvider(transport=httpx.MockTransport(handler))


async def test_success_maps_text_and_token_counts():
    seen: list[httpx.Request] = []
    provider = _provider(200, RECORDED_OK, seen)

    result = await provider.complete(
        "gemini-1.5-flash", MESSAGES, temperature=0.2, max_tokens=64, topP=0.9
    )

    assert isinstance(result, ProviderResponse)
    assert (result.text, result.input_tokens, result.output_tokens) == ("Paris", 12, 1)

    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/gemini-1.5-flash:generateContent"
    )
    assert request.headers["x-goog-api-key"] == KEY
    assert KEY not in str(request.url)
    sent = json.loads(request.content)
    assert sent == {
        "systemInstruction": {"parts": [{"text": "You are terse."}]},
        "contents": [
            {"role": "user", "parts": [{"text": "Capital of France?"}]},
            {"role": "model", "parts": [{"text": "Which France?"}]},
            {"role": "user", "parts": [{"text": "The country."}]},
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 64, "topP": 0.9},
    }


async def test_base_url_is_overridable(monkeypatch):
    monkeypatch.setenv("GEMINI_BASE_URL", "http://stub.test:9999/")
    seen: list[httpx.Request] = []
    await _provider(200, RECORDED_OK, seen).complete("models/gemini-1.5-pro", MESSAGES)
    assert str(seen[0].url) == (
        "http://stub.test:9999/v1beta/models/gemini-1.5-pro:generateContent"
    )


async def test_model_name_cannot_add_path_or_query():
    seen: list[httpx.Request] = []
    await _provider(200, RECORDED_OK, seen).complete("../files?x=1", MESSAGES)
    url = seen[0].url
    assert url.host == "generativelanguage.googleapis.com"
    assert url.query == b""
    assert url.raw_path.startswith(b"/v1beta/models/..%2Ffiles%3Fx%3D1:")


async def test_auth_error_raises_provider_error_without_the_key():
    with pytest.raises(GeminiError) as info:
        await _provider(400, RECORDED_BAD_KEY).complete("gemini-1.5-flash", MESSAGES)
    message = str(info.value)
    assert "HTTP 400" in message
    assert "API key not valid" in message
    assert KEY not in message


async def test_401_and_403_raise_provider_error():
    for status in (401, 403):
        with pytest.raises(GeminiError, match=f"HTTP {status}"):
            await _provider(status, {"error": {"message": "denied"}}).complete(
                "gemini-1.5-flash", MESSAGES
            )


async def test_5xx_raises_provider_error():
    with pytest.raises(GeminiError, match="HTTP 503: The model is overloaded"):
        await _provider(503, RECORDED_UNAVAILABLE).complete(
            "gemini-1.5-flash", MESSAGES
        )


async def test_5xx_with_a_non_json_body_is_truncated():
    with pytest.raises(GeminiError) as info:
        await _provider(502, b"<html>" + b"x" * 5000).complete(
            "gemini-1.5-flash", MESSAGES
        )
    assert "HTTP 502" in str(info.value)
    assert len(str(info.value)) < 400


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b"[1, 2, 3]",
        b"{}",
        b'{"candidates": []}',
        b'{"candidates": ["oops"]}',
        b'{"candidates": [{"content": {"parts": "nope"}}]}',
        b'{"candidates": {"0": {}}}',
    ],
    ids=[
        "not-json",
        "array",
        "empty",
        "no-candidates",
        "bad-candidate",
        "bad-parts",
        "candidates-not-a-list",
    ],
)
async def test_malformed_body_raises_provider_error(body):
    with pytest.raises(GeminiError):
        await _provider(200, body).complete("gemini-1.5-flash", MESSAGES)


async def test_a_candidate_with_no_content_is_an_empty_completion():
    body = {"candidates": [{"finishReason": "MAX_TOKENS"}]}
    result = await _provider(200, body).complete("gemini-1.5-flash", MESSAGES)
    assert (result.text, result.input_tokens, result.output_tokens) == ("", 0, 0)


async def test_a_candidate_with_no_finish_reason_and_no_content_is_empty():
    body = {"candidates": [{}]}
    result = await _provider(200, body).complete("gemini-1.5-flash", MESSAGES)
    assert result.text == ""


@pytest.mark.parametrize(
    "reason",
    ["SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "OTHER"],
)
async def test_a_refusal_with_no_content_raises_naming_the_reason(reason):
    """A refusal must be distinguishable from an empty answer."""
    body = {"candidates": [{"finishReason": reason}]}
    with pytest.raises(GeminiError, match=f"finishReason={reason}"):
        await _provider(200, body).complete("gemini-1.5-flash", MESSAGES)


async def test_a_refusal_after_partial_text_keeps_the_text():
    body = {
        "candidates": [
            {"content": {"parts": [{"text": "Par"}]}, "finishReason": "SAFETY"}
        ]
    }
    result = await _provider(200, body).complete("gemini-1.5-flash", MESSAGES)
    assert result.text == "Par"


async def test_blocked_prompt_names_the_reason():
    body = {"promptFeedback": {"blockReason": "SAFETY"}}
    with pytest.raises(GeminiError, match="blockReason=SAFETY"):
        await _provider(200, body).complete("gemini-1.5-flash", MESSAGES)


@pytest.mark.parametrize(
    "body",
    [
        {"promptFeedback": {"blockReason": "B" * 5000}},
        {"candidates": [{"finishReason": "F" * 5000}]},
    ],
    ids=["blockReason", "finishReason"],
)
async def test_provider_reason_text_is_bounded(body):
    with pytest.raises(GeminiError) as info:
        await _provider(200, body).complete("gemini-1.5-flash", MESSAGES)
    assert len(str(info.value)) < 400


@pytest.mark.parametrize(
    "usage",
    [
        {"promptTokenCount": "abc"},
        {"candidatesTokenCount": "1.5x"},
        {"promptTokenCount": [1]},
        {"promptTokenCount": {"n": 1}},
    ],
    ids=["non-numeric", "bad-float", "list", "dict"],
)
async def test_unreadable_usage_is_a_provider_error_not_a_value_error(usage):
    """A bare ValueError would reach /complete's ``except ValueError`` and
    answer 400 as if the caller had sent a bad request."""
    body = {**RECORDED_OK, "usageMetadata": usage}
    with pytest.raises(GeminiError, match="cannot read"):
        await _provider(200, body).complete("gemini-1.5-flash", MESSAGES)


async def test_missing_key_raises_before_any_request(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    seen: list[httpx.Request] = []
    with pytest.raises(GeminiError, match="GEMINI_API_KEY is not set"):
        await _provider(200, RECORDED_OK, seen).complete("gemini-1.5-flash", MESSAGES)
    assert seen == []


async def test_transport_error_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = GoogleProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(GeminiError, match="ConnectError"):
        await provider.complete("gemini-1.5-flash", MESSAGES)


def test_the_registered_google_provider_is_the_rest_one():
    assert isinstance(PROVIDERS["google"], GoogleProvider)


def test_the_provider_module_imports_nothing_from_google():
    """The old provider imported ``google.generativeai`` inside ``complete``,
    which no requirements file pins; this walks the whole syntax tree, so a
    function-local import is found too."""
    source = Path(llm_proxy_service.__file__).read_text(encoding="utf-8")
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    google = sorted(m for m in found if m == "google" or m.startswith("google."))
    assert google == [], f"llm_proxy_service imports {google}"
