"""One ruff version, declared in three places, with nothing to keep them equal.

The invariant is one tool, one config block (``[tool.ruff]`` in
``pyproject.toml``), and the same version in CI, pre-commit and the venv.
``.pre-commit-config.yaml`` states it in its own comment -- "Same ruff version
... so a clean commit is a green job" -- and nothing asserted it.

A dependency batch then bumped ``backend/requirements.txt`` to 0.16.8 and left
``lint.yml`` and ``.pre-commit-config.yaml`` on 0.16.7.  The drift is silent in
both directions and only surfaces as a contradiction: ``make format`` (which
runs the venv's ruff) formats a file one way, ``ruff format --check`` in the
``lint`` job reads it with a different release and fails, or a pre-commit-clean
commit goes red in CI.  Neither failure names a version, so the cost is a
debugging round, not a diff.

These are three cheap text reads.  They fail when the three drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]

REQUIREMENTS = REPO_ROOT / "backend" / "requirements.txt"
LINT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lint.yml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"

#: A distribution that ships neither the workflows nor the hooks has nothing
#: here to check.  ``backend/requirements.txt`` ships everywhere.
pytestmark = pytest.mark.skipif(
    not (LINT_WORKFLOW.is_file() and PRE_COMMIT.is_file()),
    reason="this tree has no .github/workflows or .pre-commit-config.yaml",
)

RUFF_PRE_COMMIT_REPO = "https://github.com/astral-sh/ruff-pre-commit"


def _requirements_pin() -> str:
    """The ``ruff==`` pin in ``backend/requirements.txt``."""
    for line in REQUIREMENTS.read_text().splitlines():
        match = re.match(r"^\s*ruff\s*==\s*([0-9][^\s;#]*)", line)
        if match:
            return match.group(1)
    raise AssertionError(f"no `ruff==` pin found in {REQUIREMENTS}")


def _workflow_version() -> str:
    """``env.RUFF_VERSION`` in the lint workflow."""
    workflow = yaml.safe_load(LINT_WORKFLOW.read_text())
    version = workflow.get("env", {}).get("RUFF_VERSION")
    assert version, f"no `RUFF_VERSION` in the `env:` block of {LINT_WORKFLOW}"
    return str(version)


def _pre_commit_rev() -> str:
    """The ``rev:`` of the ruff-pre-commit repo, without its leading ``v``."""
    config = yaml.safe_load(PRE_COMMIT.read_text())
    for repo in config["repos"]:
        if str(repo.get("repo", "")).rstrip("/") == RUFF_PRE_COMMIT_REPO:
            return str(repo["rev"]).lstrip("v")
    raise AssertionError(f"no {RUFF_PRE_COMMIT_REPO} entry in {PRE_COMMIT}")


def test_the_lint_job_installs_the_ruff_the_venv_installs() -> None:
    """``ruff format --check`` in CI must be the ruff that ran ``make format``."""
    assert _workflow_version() == _requirements_pin(), (
        f"lint.yml installs ruff {_workflow_version()} but "
        f"backend/requirements.txt pins {_requirements_pin()}; a file formatted "
        "locally can then fail `ruff format --check` in CI"
    )


def test_the_pre_commit_hook_runs_the_ruff_the_venv_installs() -> None:
    """A pre-commit-clean commit must be a lint-clean commit."""
    assert _pre_commit_rev() == _requirements_pin(), (
        f".pre-commit-config.yaml pins ruff {_pre_commit_rev()} but "
        f"backend/requirements.txt pins {_requirements_pin()}; the hook then "
        "rewrites a file the gate rejects, or passes one the gate fails"
    )


def test_all_three_declaration_sites_name_one_version() -> None:
    """The whole invariant in one assertion, naming every site that disagrees."""
    declared = {
        "backend/requirements.txt": _requirements_pin(),
        ".github/workflows/lint.yml": _workflow_version(),
        ".pre-commit-config.yaml": _pre_commit_rev(),
    }
    assert len(set(declared.values())) == 1, (
        "ruff is declared at three versions: "
        + ", ".join(
            f"{where} = {version}" for where, version in sorted(declared.items())
        )
    )
