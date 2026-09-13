"""Generating a revision on the right branch, from any working directory.

With ``modules/`` present there are two heads, so ``alembic revision`` has to be
told which one it extends.  Two things have to hold for that to be usable:

* a bare ``alembic revision --autogenerate`` must **refuse** ("Multiple heads
  are present").  It used to succeed when run from ``backend/``,
  because the modules' version location was spelled relative to the working
  directory and was therefore skipped -- one head, no guard, and the module
  tables (``env.py`` loads the module models either way) went into a *core*
  migration;
* ``--head modules@head`` must put the file under ``modules/``.  alembic derives
  the directory from the head revision's own file and compares it against the
  configured version locations -- the first resolved, the second only made
  absolute -- so the ``..`` in alembic.ini's ``%(here)s``-anchored path has to
  be collapsed first; ``migrations/env.py`` does that.

Both probes make alembic **write a revision file**, and both are about *where*
it decides to write it, so neither can be pointed at a throwaway
``--version-path`` the way ``tree_profiles.autogenerate`` is: the throwaway
config spells the version locations absolutely, which is the spelling these
probes exist to check.  They ran in the checkout instead, cleaning up in a
``finally`` -- and an interrupted run then left a third alembic head in a
tracked ``versions/`` directory, which every later ``upgrade heads`` or
bootstrap in that tree applies and which turns ``test_alembic_plan.py`` red for
no visible reason (review round 4, finding 6).  So they run in a *copy* of the
checkout (``tree_profiles.full_tree``): the real ``alembic.ini``, with its real
relative spelling, and nothing tracked to write into.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.tests.integration.database import tree_profiles

REPO_ROOT = tree_profiles.REPO_ROOT

pytestmark = [pytest.mark.integration, pytest.mark.modules]


@pytest.fixture(scope="module")
def probe_tree(tmp_path_factory) -> Path:
    """A copy of this checkout that alembic may write revision files into."""
    tree = tree_profiles.full_tree(tmp_path_factory.mktemp("probe-checkout"))
    assert REPO_ROOT not in tree.parents and tree != REPO_ROOT
    return tree


def _versions(tree: Path) -> tuple[Path, Path]:
    return (
        tree / "backend" / "app" / "db" / "migrations" / "versions",
        tree.joinpath("modules", "backend", "app", "db", "migrations", "versions"),
    )


def _revision_files(tree: Path) -> set[Path]:
    core, modules = _versions(tree)
    return set(core.glob("*.py")) | set(modules.glob("*.py"))


def _run(
    args: list[str], schema: str, cwd: Path, tree: Path
) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("APP_ENV", "TESTING", "ENVIRONMENT")
    }
    env.update({"PYTHONPATH": str(tree), "POSTGRES_SCHEMA": schema})
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _alembic(tree: Path, schema: str, *args: str, subdir: str = ""):
    return _run(
        ["-m", "alembic", "-c", str(tree_profiles.alembic_ini(tree)), *args],
        schema,
        tree / subdir,
        tree,
    )


@pytest.fixture
def bootstrapped_schema(test_db, probe_tree):
    """A scratch schema at both heads, so autogenerate sees no difference."""
    schema = f"branch_{uuid.uuid4().hex[:8]}"
    result = tree_profiles.bootstrap_schema(probe_tree, schema)
    assert result.returncode == 0, result.stderr[-2000:]
    try:
        yield schema
    finally:
        with test_db.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


@pytest.mark.regression
@pytest.mark.parametrize("subdir", ["", "backend"], ids=["repo-root", "backend"])
def test_a_revision_without_a_head_is_refused(probe_tree, bootstrapped_schema, subdir):
    before = _revision_files(probe_tree)
    result = _alembic(
        probe_tree,
        bootstrapped_schema,
        "revision",
        "--autogenerate",
        "-m",
        "guard probe",
        subdir=subdir,
    )
    try:
        assert result.returncode != 0
        assert "Multiple heads are present" in result.stderr + result.stdout
    finally:
        for path in _revision_files(probe_tree) - before:
            path.unlink()
    assert _revision_files(probe_tree) == before


@pytest.mark.regression
@pytest.mark.parametrize(
    "extra", [("--autogenerate",), ()], ids=["autogenerate", "plain"]
)
def test_a_module_revision_lands_under_modules(probe_tree, bootstrapped_schema, extra):
    before = _revision_files(probe_tree)
    result = _alembic(
        probe_tree,
        bootstrapped_schema,
        "revision",
        *extra,
        "--head",
        "modules@head",
        "-m",
        "branch placement probe",
        subdir="backend",
    )
    created = _revision_files(probe_tree) - before
    try:
        assert result.returncode == 0, result.stderr[-2000:]
        assert len(created) == 1, created
        written = next(iter(created))
        assert written.parent == _versions(probe_tree)[1]
        # The point of the copy: the file alembic just wrote is not in the
        # checkout, so an interrupted run cannot leave a head behind there.
        assert REPO_ROOT not in written.parents, written
    finally:
        for path in created:
            path.unlink()
    assert _revision_files(probe_tree) == before
