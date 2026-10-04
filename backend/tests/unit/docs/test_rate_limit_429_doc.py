"""The 429 body quoted in ``docs/api/endpoints.md`` is the one the API sends.

The page quoted ``Too many requests. Please try again in 60 seconds.``, a
text the rate limiter has never sent. This reads the ``detail`` of the
``JSONResponse(status_code=429, ...)`` in the middleware through ``ast`` (no
backend module is imported, so it runs with the standard library alone) and
compares it with the JSON block that follows the page's 429 heading.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
PAGE = REPO_ROOT / "docs" / "api" / "endpoints.md"
MIDDLEWARE = REPO_ROOT / "backend" / "app" / "middleware" / "rate_limiter.py"

_QUOTE = re.compile(
    r"^Response \(429 Too Many Requests\):\s*\n\s*```json\s*\n(.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def _middleware_429_details() -> list[str]:
    """Every literal ``detail`` of a ``JSONResponse(status_code=429, ...)``."""
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    details = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "JSONResponse"
        ):
            continue
        kwargs = {k.arg: k.value for k in node.keywords}
        code = kwargs.get("status_code")
        if not (isinstance(code, ast.Constant) and code.value == 429):
            continue
        content = kwargs.get("content")
        assert isinstance(content, ast.Dict), "the 429 content is no longer a dict"
        for key, value in zip(content.keys, content.values):
            if isinstance(key, ast.Constant) and key.value == "detail":
                assert isinstance(value, ast.Constant), "detail is not a literal"
                details.append(value.value)
    return details


def test_the_middleware_sends_one_429_text():
    details = _middleware_429_details()
    assert len(details) == 1, f"expected one 429 detail, found {details}"


def test_the_page_quotes_the_429_text_the_middleware_sends():
    quotes = _QUOTE.findall(PAGE.read_text(encoding="utf-8"))
    assert len(quotes) == 1, f"expected one quoted 429 body, found {len(quotes)}"
    assert json.loads(quotes[0]) == {"detail": _middleware_429_details()[0]}
