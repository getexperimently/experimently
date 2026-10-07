"""The LLM evaluation page lists the providers there are, and no key setting is unread (#256).

The provider table in ``docs/llm-evaluation/overview.md`` listed Cohere and
Mistral, which have no provider class, so a variant naming either has nothing
to call. And ``Settings`` carried ``LLM_OPENAI_API_KEY``,
``LLM_ANTHROPIC_API_KEY`` and ``LLM_GOOGLE_API_KEY``, which nothing read: each
provider reads its own variable where it calls out. Both are pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.services.llm_proxy_service import PROVIDERS

pytestmark = [pytest.mark.unit, pytest.mark.regression]

PAGE = Path(__file__).resolve().parents[4] / "docs" / "llm-evaluation" / "overview.md"

#: A row of the "Supported Providers and Models" table: `| **Name** | ...`.
PROVIDER_ROW = re.compile(r"^\| \*\*([^*]+)\*\* \|", re.M)


def _documented_providers() -> list[str]:
    text = PAGE.read_text(encoding="utf-8")
    section = text.split("## Supported Providers and Models", 1)[1].split("\n## ", 1)[0]
    return [name.strip().lower() for name in PROVIDER_ROW.findall(section)]


def test_the_page_lists_exactly_the_providers_there_are():
    documented = _documented_providers()
    assert documented, "the provider table was not found"
    assert sorted(documented) == sorted(PROVIDERS), documented


def test_no_llm_key_setting_is_left_for_nothing_to_read():
    unread = [
        name for name in Settings.model_fields if re.fullmatch(r"LLM_\w+_API_KEY", name)
    ]
    assert unread == []
