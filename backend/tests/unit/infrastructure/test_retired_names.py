"""Two names B3a retired stay retired.

* The production-only deploy workflow is now `deploy.yml`, for every
  environment (T25). Nineteen files named the old one, and a test constant that
  still names it skips rather than fails (QA 4d) -- so the name must be gone
  from the tree, not merely from the workflow directory.
* The one-command AWS demo script is retired (#73): it could not synthesise
  (it set neither PUBLIC_BASE_URL nor CERTIFICATE_ARN) and created no image,
  repository or secret. A document still sending someone to it is a dead end.

The equivalent of `git grep <name>` returning only CHANGELOG.md, done by
walking the files, because `scripts/core_build.sh` runs this suite in a copy
with no `.git`. The names are assembled at runtime so this file does not match
itself.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

RETIRED = {
    "the old deploy workflow": "deploy" + "-prod",
    "the AWS demo script": "setup" + "-aws",
}

#: Directories that are not the repository's own text.
PRUNE = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    ".next",
    "site",
    "dist",
    "build",
    "worktrees",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "cdk.out",
}
#: Where the history of a name legitimately lives.
ALLOWED = {"CHANGELOG.md"}


def _files():
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in PRUNE]
        for name in files:
            if name in ALLOWED or name.endswith(
                (".png", ".jpg", ".ico", ".woff2", ".pyc")
            ):
                continue
            yield Path(root) / name


@pytest.mark.regression
def test_retired_names_appear_only_in_the_changelog():
    hits: dict[str, list[str]] = {what: [] for what in RETIRED}
    scanned = 0
    for path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for what, name in RETIRED.items():
            if name in text:
                hits[what].append(str(path.relative_to(REPO_ROOT)))
    assert scanned > 500, f"only {scanned} files scanned; the walk is pruning too much"
    offenders = {what: sorted(paths) for what, paths in hits.items() if paths}
    assert not offenders, (
        "a retired name is still referenced (only CHANGELOG.md may):\n"
        + "\n".join(f"  {what}: {paths}" for what, paths in offenders.items())
    )


def test_the_retired_files_are_gone():
    assert not (REPO_ROOT / ".github" / "workflows" / ("deploy" + "-prod.yml")).exists()
    assert not (REPO_ROOT / "demo" / ("setup" + "-aws.sh")).exists()
