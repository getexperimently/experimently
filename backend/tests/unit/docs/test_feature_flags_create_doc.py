"""`docs/feature-flags/create.md` — what can be checked without a stack.

The page's examples once failed at every step while each `curl` exited 0: a
login sent `username` (422), the create call had no trailing slash (a 307 curl
does not follow, so nothing was created), later steps used literal placeholders
(`flag-uuid-here`, `your-api-key`), and create and activate sent a `"status"`
field the API silently ignores -- there is no DRAFT status.  The documentation
runner will execute the page; until then these pin the shape of each example:

* every ```json sample parses;
* no placeholder a reader cannot fill in is left in a shell example;
* every body sent to the create or update endpoint uses only fields the request
  schema accepts, because the API drops the rest without an error;
* the collection URL is written with its trailing slash, a single flag's without;
* the page never mentions a draft state.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from backend.app.schemas.feature_flag import FeatureFlagCreate, FeatureFlagUpdate

pytestmark = [pytest.mark.unit, pytest.mark.regression]

PAGE = (
    pathlib.Path(__file__).resolve().parents[4] / "docs" / "feature-flags" / "create.md"
)

# ```bash, or the tagged form the documentation runner requires (```{.bash exec}).
_FENCE = re.compile(r"^```(?:\{\.)?(\w*)[^`]*$")
PLACEHOLDERS = (
    "your-username",
    "your-password",
    "your-api-key",
    "flag-uuid-here",
    "(unchanged:",
)


def _blocks() -> list[tuple[str, int, str]]:
    """(language, first line number, text) of every fenced block."""
    blocks, lang, start, lines = [], None, 0, []
    for number, line in enumerate(PAGE.read_text(encoding="utf-8").splitlines(), 1):
        match = _FENCE.match(line)
        if lang is None and match:
            lang, start, lines = match.group(1), number + 1, []
        elif lang is not None and line.strip() == "```":
            blocks.append((lang, start, "\n".join(lines)))
            lang = None
        elif lang is not None:
            lines.append(line)
    assert lang is None, f"unclosed fence starting at line {start}"
    return blocks


def _shell() -> list[tuple[int, str]]:
    return [(start, text) for lang, start, text in _blocks() if lang == "bash"]


def _flag_requests():
    """(line, method, url, body) of each shell call to the flag endpoints."""
    for start, text in _shell():
        for call in re.split(r"\n(?=\S)", text):
            url = re.search(r"localhost:8000(/api/v1/feature-flags[^\s\\\"']*)", call)
            body = re.search(r"-d '(\{.*?\})'", call, re.S)
            if not url or not body or "/evaluate/" in url.group(1):
                continue
            method = re.search(r"-X (\w+)", call)
            yield (
                start,
                method.group(1) if method else "GET",
                url.group(1),
                body.group(1),
            )


def test_the_page_has_its_examples():
    assert len(_shell()) == 9
    assert len(list(_flag_requests())) == 3  # create, rules, turn on


def test_every_json_sample_parses():
    for lang, start, text in _blocks():
        if lang == "json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                pytest.fail(f"create.md:{start}: {exc}")


def test_no_placeholder_is_left_in_a_shell_example():
    found = [
        f"create.md:{start}: {placeholder}"
        for start, text in _shell()
        for placeholder in PLACEHOLDERS
        if placeholder in text
    ]
    assert not found, found


def test_the_page_never_mentions_a_draft_state():
    assert "draft" not in PAGE.read_text(encoding="utf-8").lower()


def test_login_sends_an_email_not_a_username():
    login = [t for _, t in _shell() if "/auth/login" in t]
    assert login and all('"email"' in t and '"username"' not in t for t in login)


def test_every_body_uses_only_fields_the_api_accepts():
    for start, method, url, body in _flag_requests():
        schema = FeatureFlagCreate if method == "POST" else FeatureFlagUpdate
        unknown = set(json.loads(body)) - set(schema.model_fields)
        assert not unknown, (
            f"create.md:{start}: {method} {url} sends {sorted(unknown)}, which the API "
            f"drops without an error"
        )


def test_urls_are_written_the_way_the_api_serves_them():
    for start, method, url, _ in _flag_requests():
        if method == "POST":
            assert url == "/api/v1/feature-flags/", f"create.md:{start}: {url}"
        else:
            assert not url.endswith("/"), f"create.md:{start}: {url} answers 307"
