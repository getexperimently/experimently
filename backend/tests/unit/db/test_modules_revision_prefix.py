"""The ``modules_`` revision-id convention :func:`may_run_alembic` relies on.

The refusal for a revision this build cannot resolve tells two cases apart by
the id alone (``bootstrap.MODULES_REVISION_PREFIX``): a ``modules_*`` row met by
a core build is the other profile; anything else was written by a newer release
(#238).  That is only true while every modules revision carries the prefix and
no core revision does, so both halves are pinned here, from the ``revision``
value each file declares -- not its filename, which alembic ignores.

No database: this reads the version directories on disk.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.app.db.bootstrap import MODULES_REVISION_PREFIX

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
CORE_VERSIONS = REPO_ROOT / "backend" / "app" / "db" / "migrations" / "versions"
#: Built from parts: a single literal spelling a path under the modules would be
#: a core->module crossing for ``backend/tests/smoke/test_core_boundary.py``.
MODULES_VERSIONS = REPO_ROOT.joinpath(
    "modules", "backend", "app", "db", "migrations", "versions"
)


def _declared_revision(path: Path) -> str:
    """The ``revision`` a revision file assigns at module level."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "revision" for t in targets):
            assert isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ), f"{path}: revision is not a string literal"
            return node.value.value
    raise AssertionError(f"{path}: declares no revision")


def _revisions(directory: Path) -> dict[str, str]:
    """``{revision id: file name}`` for every revision file in *directory*."""
    assert directory.is_dir(), f"{directory} is missing"
    found = {
        _declared_revision(path): path.name
        for path in sorted(directory.glob("*.py"))
        if path.name != "__init__.py"
    }
    assert found, f"no revision files under {directory}"
    return found


def test_no_core_revision_id_carries_the_modules_prefix():
    offenders = {
        rev: name
        for rev, name in _revisions(CORE_VERSIONS).items()
        if rev.startswith(MODULES_REVISION_PREFIX)
    }
    assert not offenders, (
        f"core revision(s) named like modules revisions: {offenders}. A core "
        "build would call a database recorded at one 'the other profile' "
        "instead of 'a newer release'."
    )


@pytest.mark.modules
@pytest.mark.skipif(
    not REPO_ROOT.joinpath("modules").is_dir(),
    reason="core build: modules/ is absent, so there is no modules branch",
)
def test_every_modules_revision_id_carries_the_modules_prefix():
    # Keyed on modules/ itself, not on the versions directory: with modules/
    # present, a missing or moved versions directory fails in _revisions().
    offenders = {
        rev: name
        for rev, name in _revisions(MODULES_VERSIONS).items()
        if not rev.startswith(MODULES_REVISION_PREFIX)
    }
    assert not offenders, (
        f"modules revision(s) without the {MODULES_REVISION_PREFIX!r} prefix: "
        f"{offenders}. A core build would call a full database 'migrated by a "
        "newer release'."
    )
