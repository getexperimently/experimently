"""The regex-condition docs state the input limit the code enforces."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.pattern_match import MAX_REGEX_INPUT

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "page", ["docs/Enhanced_Rules_Engine_Reference.md", "docs/feature-flags/create.md"]
)
def test_the_documented_input_limit_is_the_real_one(page):
    text = (REPO_ROOT / page).read_text(encoding="utf-8")
    assert f"longer than {MAX_REGEX_INPUT} characters" in text
