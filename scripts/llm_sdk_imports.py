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

What is excluded, and why:

* ``google.*`` -- the Gemini provider's SDK is not installed yet and is being
  replaced separately (#196, the Gemini half). Excluding the prefix rather than
  the one module means a second ``google.`` import does not slip past either
  way: it is excluded until that work removes this exclusion.
* relative imports -- there are none in these files, and a relative import
  would need a package context this script does not have. One appearing is an
  error, not something silently skipped.

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
#: design and the power-calculator planner, and the LLM-as-judge.
SOURCES = (
    ROOT / "backend" / "app" / "services" / "llm_proxy_service.py",
    ROOT / "backend" / "app" / "services" / "ai_design_service.py",
    ROOT / "backend" / "app" / "services" / "ai_experiment_planner_service.py",
    ROOT / "backend" / "app" / "services" / "llm_analytics_service.py",
)

#: Top-level packages left out, with the reason in the module docstring.
EXCLUDED_PREFIXES = ("google",)


def _excluded(module: str) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in EXCLUDED_PREFIXES
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


def _all_imports(sources: tuple[Path, ...]) -> set[str]:
    modules: set[str] = set()
    for path in sources:
        modules |= imports_in(path)
    return modules


def derived_imports(sources: tuple[Path, ...] = SOURCES) -> list[str]:
    """The modules to check, sorted, with the exclusions applied."""
    return sorted(m for m in _all_imports(sources) if not _excluded(m))


def excluded_imports(sources: tuple[Path, ...] = SOURCES) -> list[str]:
    """What the exclusions removed, so it is reported rather than invisible."""
    return sorted(m for m in _all_imports(sources) if _excluded(m))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--oneline", action="store_true", help="space-separated")
    args = ap.parse_args(argv)
    modules = derived_imports()
    print(" ".join(modules) if args.oneline else "\n".join(modules))
    print(f"excluded: {' '.join(excluded_imports()) or 'nothing'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
