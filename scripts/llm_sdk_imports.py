#!/usr/bin/env python3
"""Print every module the LLM call paths import, read from their source.

The LLM features import their provider SDKs *inside functions*
(``import anthropic`` in ``AnthropicProvider.complete``, ``import openai`` in
``OpenAIProvider.complete``), so nothing fails at start-up when an SDK is
missing from the image: the API boots, ``/health`` is green, and every call
fails or falls back at request time. That is how the image shipped without
either SDK (#196), with a test suite that mocked them.

This lists the modules those files import -- top-level and function-local
alike, by walking the whole syntax tree -- so a check can ask the environment
it runs in whether each one is there. The list is derived, not typed: an
import added to one of these files is covered the day it is written.

Nothing is excluded. The Gemini provider calls Google's REST API over the
``httpx`` the API already pins (#275), so no ``google.*`` package is imported;
one appearing is checked like any other import, and fails wherever it is not
installed. A relative import is an error rather than something silently
skipped: there are none in these files, and resolving one would need a package
context this script does not have.

The consumers are ``backend/tests/unit/scripts/test_llm_sdk_imports.py`` (the
test virtualenv) and the ``Docker Smoke`` job in ``pr-qa-gate.yml`` (the built
image). Standard library only, so the job runs it with the runner's python3.

Usage::

    python scripts/llm_sdk_imports.py            # one module per line
    python scripts/llm_sdk_imports.py --oneline  # space-separated
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The files that make a real provider call, one per call path:
#: ``POST /api/v1/llm-experiments/{id}/complete`` (the proxy), AI experiment
#: design, and the LLM-as-judge.
SOURCES = (
    ROOT / "backend" / "app" / "services" / "llm_proxy_service.py",
    ROOT / "backend" / "app" / "services" / "ai_design_service.py",
    ROOT / "backend" / "app" / "services" / "llm_analytics_service.py",
)


def imports_in(path: Path) -> set[str]:
    """Every absolute module ``path`` imports, anywhere in the file.

    ``import a.b`` gives ``a.b``; ``from a.b import c`` gives ``a.b`` (``c``
    may be an attribute rather than a module, so it is not claimed).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise ValueError(
                    f"{path}:{node.lineno}: relative import; this script "
                    "resolves absolute imports only"
                )
            found.add(node.module)
    return found


def derived_imports(sources: tuple[Path, ...] = SOURCES) -> list[str]:
    """Every module the ``sources`` import, sorted."""
    modules: set[str] = set()
    for path in sources:
        modules |= imports_in(path)
    return sorted(modules)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--oneline", action="store_true", help="space-separated")
    args = ap.parse_args(argv)
    modules = derived_imports()
    print(" ".join(modules) if args.oneline else "\n".join(modules))
    return 0


if __name__ == "__main__":
    sys.exit(main())
