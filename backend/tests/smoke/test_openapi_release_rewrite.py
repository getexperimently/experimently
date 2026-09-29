"""A release rewrites the OpenAPI snapshots, and must change only the version.

``release-please-config.json`` lists the OpenAPI snapshots and the frontend's
fixture as ``extra-files`` of type ``json``: to bump ``$.info.version`` the
updater parses the whole file into JavaScript values and prints it again with
``JSON.stringify``.  Whatever JavaScript prints differently comes back changed.
Harmless so far -- release 0.2.1 unescaped ``\\u2192`` to ``→`` and 0.11.0
turned ``1.0`` into ``1`` -- until the 0.12.0 release pull request rewrote the
warehouse filter's ``maximum: 9223372036854775808`` as
``9223372036854776000``: a different number, committed as the API description.

So each of those files must already be in the form JavaScript prints:

* an integer's magnitude is at most 2**53 - 1 (``Number.MAX_SAFE_INTEGER``;
  above it a double skips integers, and a schema that needs the int64 range
  says ``format: int64`` -- see ``IntLiteral`` in
  ``modules/backend/app/schemas/warehouse_sources.py``);
* a fraction is in its shortest round-trip form, with no exponent and no
  trailing ``.0`` (JavaScript prints ``1.0`` as ``1`` and ``1e-05`` as
  ``0.00001``);
* the text is a fixed point of a two-space ``JSON.stringify``: non-ASCII
  unescaped, and integer-like object keys first in numeric order, which is the
  order JavaScript enumerates them in.

``backend/scripts/dump_openapi.py`` writes that form.  The file list is read
from the release-please configuration, so a JSON file added to
``extra-files`` later is checked too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
RELEASE_PLEASE_CONFIG = ROOT / "release-please-config.json"

#: JavaScript's Number.MAX_SAFE_INTEGER.
MAX_SAFE_INTEGER = 2**53 - 1

#: The three files the release bumps today; the configuration may add more.
EXPECTED_AT_LEAST = {
    "docs/api/openapi-v1.stable.json",
    "docs/api/openapi-v1.full.json",
    "frontend/src/tests/fixtures/openapi.json",
}

pytestmark = [pytest.mark.smoke, pytest.mark.regression]


def json_extra_files() -> list[str]:
    config = json.loads(RELEASE_PLEASE_CONFIG.read_text(encoding="utf-8"))
    return sorted(
        entry["path"]
        for package in config["packages"].values()
        for entry in package.get("extra-files", [])
        if isinstance(entry, dict) and entry.get("type") == "json"
    )


def unsafe_numbers(text: str) -> list[str]:
    """Return every number literal in *text* that JavaScript prints differently."""
    found: list[str] = []

    def check_int(literal: str) -> int:
        if abs(int(literal)) > MAX_SAFE_INTEGER:
            found.append(literal)
        return int(literal)

    def check_float(literal: str) -> float:
        value = float(literal)
        if "e" in literal.lower() or literal.endswith(".0") or repr(value) != literal:
            found.append(literal)
        return value

    json.loads(text, parse_int=check_int, parse_float=check_float)
    return found


def _is_array_index(key: str) -> bool:
    return key.isdigit() and str(int(key)) == key and int(key) < 2**32 - 1


def _javascript_key_order(node: Any) -> Any:
    if isinstance(node, dict):
        keys = list(node)
        ordered = sorted((k for k in keys if _is_array_index(k)), key=int) + [
            k for k in keys if not _is_array_index(k)
        ]
        return {k: _javascript_key_order(node[k]) for k in ordered}
    if isinstance(node, list):
        return [_javascript_key_order(v) for v in node]
    return node


def javascript_rewrite(text: str) -> str:
    """What ``JSON.stringify(JSON.parse(text), null, 2)`` prints, numbers aside."""
    document = _javascript_key_order(json.loads(text))
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def test_the_release_rewrites_the_expected_json_files() -> None:
    # Without this, a renamed key in the configuration would leave the tests
    # below checking nothing and passing.
    assert EXPECTED_AT_LEAST <= set(json_extra_files())


@pytest.mark.parametrize("relative", json_extra_files())
def test_every_number_survives_a_javascript_rewrite(relative: str) -> None:
    unsafe = unsafe_numbers((ROOT / relative).read_text(encoding="utf-8"))
    assert not unsafe, (
        f"{relative} holds number(s) that release-please's JSON updater would "
        f"rewrite: {unsafe}. Integers must be within +/-(2**53 - 1); describe a "
        "64-bit range with format: int64 rather than minimum/maximum, then "
        "run `make openapi`."
    )


@pytest.mark.parametrize("relative", json_extra_files())
def test_the_text_is_what_a_javascript_rewrite_prints(relative: str) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert javascript_rewrite(text) == text, (
        f"{relative} is not in the form release-please's JSON updater prints, "
        "so the next release pull request will change more than the version. "
        "Regenerate it with `make openapi`."
    )


@pytest.mark.parametrize(
    "literal",
    ["9223372036854775808", "-9223372036854775808", "9007199254740992", "1.0", "1e-05"],
)
def test_the_number_check_refuses_what_javascript_rewrites(literal: str) -> None:
    assert unsafe_numbers(f'{{"n": {literal}}}') == [literal]


@pytest.mark.parametrize(
    "literal", ["9007199254740991", "-9007199254740991", "0", "0.05", "1.5"]
)
def test_the_number_check_accepts_what_javascript_prints_unchanged(
    literal: str,
) -> None:
    assert unsafe_numbers(f'{{"n": {literal}}}') == []


@pytest.mark.parametrize(
    "text",
    [
        '{\n  "a": "\\u2192"\n}\n',  # JavaScript unescapes non-ASCII
        '{\n  "default": 1,\n  "200": 2\n}\n',  # and lists integer keys first
        '{"a": 1}\n',  # and indents by two spaces
    ],
)
def test_the_text_check_refuses_what_javascript_rewrites(text: str) -> None:
    assert javascript_rewrite(text) != text
