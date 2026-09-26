"""Every message docs/auth/sso.md's troubleshooting quotes is one the code sends.

An operator searches the page for the text in front of them, so a heading
that quotes a message the code does not produce sends them nowhere. Each
quoted heading must match a string literal in the SSO service or endpoints,
where an f-string's placeholders and the heading's ``…`` stand for any text.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[5]
DOC = REPO_ROOT / "docs" / "auth" / "sso.md"
SOURCES = [
    REPO_ROOT / "modules" / "backend" / "app" / "services" / "sso_service.py",
    REPO_ROOT / "modules" / "backend" / "app" / "api" / "v1" / "endpoints" / "sso.py",
]
GAP = "\u2026"  # the ellipsis a heading elides with


def _literals() -> List[str]:
    """Every string literal in the sources; an f-string's placeholders become ``…``."""
    found: List[str] = []
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append(node.value)
            elif isinstance(node, ast.JoinedStr):
                found.append(
                    "".join(
                        part.value
                        if isinstance(part, ast.Constant)
                        and isinstance(part.value, str)
                        else GAP
                        for part in node.values
                    )
                )
    return found


def _quoted_troubleshooting_headings() -> List[str]:
    text = DOC.read_text(encoding="utf-8")
    section = text.split("\n## Troubleshooting\n", 1)[1]
    return re.findall(r'^### [^"\n]*"([^"\n]+)"', section, flags=re.MULTILINE)


def _pattern(text: str) -> "re.Pattern[str]":
    return re.compile(".+".join(re.escape(piece) for piece in text.split(GAP)))


def _is_sent(quote: str, literals: List[str]) -> bool:
    for literal in literals:
        # The heading elides with …: its pieces appear, in order, in the literal.
        if GAP in quote and _pattern(quote).search(literal.replace(GAP, "x")):
            return True
        # The literal has placeholders: the heading is one of its renderings.
        # Not a literal that is mostly placeholder (f"{what}" renders as
        # anything at all, and would make every heading pass).
        fixed = len(literal.replace(GAP, ""))
        if GAP in literal and fixed >= 12 and _pattern(literal).fullmatch(quote):
            return True
        if quote == literal:
            return True
    return False


def test_the_page_quotes_messages_in_its_troubleshooting_headings():
    """A positive control, so the check below cannot pass by finding nothing."""
    assert len(_quoted_troubleshooting_headings()) >= 10


def test_every_quoted_troubleshooting_message_is_one_the_code_sends():
    literals = _literals()
    missing = [
        q for q in _quoted_troubleshooting_headings() if not _is_sent(q, literals)
    ]
    assert missing == [], (
        f"docs/auth/sso.md quotes messages the code never sends: {missing}"
    )
