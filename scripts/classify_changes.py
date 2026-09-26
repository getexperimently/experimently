#!/usr/bin/env python3
"""Is a pull request documentation only?  Reads a file list, answers yes or no.

``pr-qa-gate.yml``'s ``changes`` job feeds this the output of::

    git diff --no-renames --name-only "$BASE" "$HEAD"

one path per line on stdin, and appends what it prints to ``$GITHUB_OUTPUT``.
The answer decides whether the heavy jobs do their work or only report, so a
wrong "yes" is the dangerous direction: a code change classed as docs merges
green without its tests.  Everything here is therefore fail-closed.

THE RULE

A change is documentation only when it is non-empty and every path is either

* under ``docs/`` but NOT under ``docs/api/``, or
* exactly ``mkdocs.yml``.

``docs/api/**`` is never documentation.  The OpenAPI snapshots there are
generated from the code and pinned by ``test_openapi_snapshot.py`` and
``test_version_sources.py``; a change to them is a change to the API contract.

``mkdocs.yml`` IS documentation.  It configures the site and nothing else
imports it; the one test that reads it (``test_doc_examples.py``, which renders
through its ``markdown_extensions``) is among the docs tests the core leg of
``profile-build`` still runs on a docs-only pull request.

An empty list is NOT documentation only: nothing to classify means nothing was
proven, so the full gate runs.

WHY ``--no-renames``

Rename detection is on by default in ``git diff`` and ``--name-only`` then
prints only the destination.  ``git mv backend/a.py docs/a.py`` would list just
``docs/a.py`` -- a code deletion classed as documentation.  With
``--no-renames`` both sides are listed and the ``backend/`` path fails the rule.
This script cannot see how its input was produced, so the flag is pinned in the
workflow by ``test_docs_only_gate.py``; the script's job is to classify the pair
correctly when it gets it.

OUTPUT

stdout: exactly one line, ``docs_only=true`` or ``docs_only=false``.
stderr: the files and the verdict, for the job log.
Exit status is 0 either way; the answer is the output, not the status.

No git, no network, no imports beyond the standard library: it runs anywhere,
including ``scripts/core_build.sh``'s copy, which has no ``.git``.
"""

from __future__ import annotations

import sys
from typing import Iterable, List, Tuple

#: Paths below this are documentation, unless NEVER_DOCS claims them first.
DOCS_PREFIX = "docs/"
#: Generated from the code; a change here is an API change.
NEVER_DOCS_PREFIXES: Tuple[str, ...] = ("docs/api/",)
#: Individual files outside docs/ that are documentation.
DOCS_FILES: Tuple[str, ...] = ("mkdocs.yml",)


def is_docs_path(path: str) -> bool:
    """True when *path* alone is documentation under the rule above."""
    if any(path.startswith(prefix) for prefix in NEVER_DOCS_PREFIXES):
        return False
    if path in DOCS_FILES:
        return True
    return path.startswith(DOCS_PREFIX)


def parse(lines: Iterable[str]) -> List[str]:
    """The non-blank paths, stripped of surrounding whitespace."""
    return [line.strip() for line in lines if line.strip()]


def classify(paths: Iterable[str]) -> Tuple[bool, List[str]]:
    """``(docs_only, offending_paths)`` for a list of changed paths."""
    files = list(paths)
    offending = [path for path in files if not is_docs_path(path)]
    return bool(files) and not offending, offending


def main() -> int:
    files = parse(sys.stdin)
    docs_only, offending = classify(files)
    log = sys.stderr
    print(f"changed files ({len(files)}):", file=log)
    for path in files:
        print(f"  {path}", file=log)
    if docs_only:
        print("==> documentation only: the heavy jobs report without working", file=log)
    elif not files:
        print("==> no changed files: running the full gate", file=log)
    else:
        print("==> not documentation only, because of:", file=log)
        for path in offending:
            print(f"  {path}", file=log)
    print(f"docs_only={'true' if docs_only else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
