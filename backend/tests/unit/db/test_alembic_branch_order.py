"""The modules branch must be ordered *after* the core revision it undoes.

Core revision ``a7b8c9d0e1f2`` drops the two ``workspace_id`` foreign keys;
the modules branch's first revision (``modules_0001_rbac``) puts them back.
One undoes the other, so the order they run in is the whole correctness of the
pair -- and alembic orders two revisions only when one is an *ancestor* of the
other.

While ``modules_0001_rbac`` was an independent alembic base there was no such
edge, and alembic scheduled it early: a single ``alembic upgrade heads`` on any
database behind ``a7b8c9d0e1f2`` restored the constraints first and dropped
them second, stamped both revisions, and left ``ON DELETE SET NULL`` silently
gone for good.  ``backend/tests/integration/database/test_profile_migrations.py``
rehearses that end to end against a real database; these checks need no
database at all, so they fail fast and they fail in the core unit job.

They are deliberately *structural* rather than about the two revisions that
exist today: a future revision added to the modules branch must also be
ordered after the core revision, and the second check below says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "backend" / "app" / "db" / "alembic.ini"

#: The core revision the modules branch must follow: it drops the two
#: ``workspace_id`` foreign keys that ``modules_0001_rbac`` restores.
BRANCH_POINT = "a7b8c9d0e1f2"
MODULES_BRANCH = "modules"

pytestmark = [pytest.mark.unit, pytest.mark.modules]


@pytest.fixture
def script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))


def _modules_revisions(script: ScriptDirectory) -> list:
    return [
        rev
        for rev in script.walk_revisions()
        if MODULES_BRANCH in (rev.branch_labels or set())
    ]


def _upgrade_order(script: ScriptDirectory) -> list[str]:
    """Revision ids in the order ``upgrade`` would apply them from base."""
    return [rev.revision for rev in reversed(list(script.walk_revisions()))]


@pytest.mark.regression
def test_the_modules_branch_descends_from_the_revision_it_undoes(script):
    """Without this edge alembic is free to run the branch first -- and did."""
    ancestors = {
        rev.revision for rev in script.iterate_revisions("modules@head", "base")
    }
    assert BRANCH_POINT in ancestors, (
        f"modules@head must descend from {BRANCH_POINT}; without that edge "
        "`alembic upgrade heads` may restore the workspace foreign keys "
        "before the core revision drops them"
    )


@pytest.mark.regression
def test_every_modules_revision_is_ordered_after_the_branch_point(script):
    """Holds for the revisions that exist now *and* for any added later."""
    order = _upgrade_order(script)
    branch_point = order.index(BRANCH_POINT)
    for rev in _modules_revisions(script):
        assert order.index(rev.revision) > branch_point, (
            f"{rev.revision} is scheduled before {BRANCH_POINT}"
        )


@pytest.mark.regression
def test_upgrade_heads_still_records_one_row_per_profile(script):
    """`heads` resolves to ``_real_heads``; a ``depends_on`` edge would make
    that one revision, and a core image could not resolve the only row."""
    assert len(script.revision_map._real_heads) == 2, script.revision_map._real_heads
    assert set(script.revision_map._real_heads) == set(script.revision_map.heads)

    labelled = [
        head
        for head in script.revision_map._real_heads
        if MODULES_BRANCH in (script.get_revision(head).branch_labels or set())
    ]
    assert len(labelled) == 1, script.revision_map._real_heads
    # The other head is the core one, and a core checkout must be able to
    # resolve it: it may not carry the modules label either.
    core_head = next(
        head for head in script.revision_map._real_heads if head not in labelled
    )
    assert MODULES_BRANCH not in (script.get_revision(core_head).branch_labels or set())


def test_the_branch_label_does_not_leak_down_the_core_chain(script):
    """alembic walks a label up until it reaches a branch point; the label
    would otherwise reach the core base and ``modules@head`` would resolve on
    a core checkout too."""
    for revision in script.iterate_revisions(BRANCH_POINT, "base"):
        assert MODULES_BRANCH not in (revision.branch_labels or set()), revision


def test_the_branch_point_has_exactly_one_core_child(script):
    """The core chain needs a head of its own past the branch point, or
    ``stamp heads`` writes a single row again."""
    children = set(script.get_revision(BRANCH_POINT).nextrev)
    core_children = {
        rev
        for rev in children
        if MODULES_BRANCH not in (script.get_revision(rev).branch_labels or set())
    }
    assert len(core_children) == 1, children


# ---------------------------------------------------------------------------
# Which chain owns the workspace foreign keys
# ---------------------------------------------------------------------------
#: The constraints the workspaces module owns.  ``a7b8c9d0e1f2``'s docstring
#: promises the core chain never re-adds them; that promise is only checkable
#: from here, where both version directories are visible.
WORKSPACE_TABLE = "workspaces"


def _upgrade_readds_a_workspace_fk(path: Path) -> bool:
    """Whether *path*'s ``upgrade()`` creates a foreign key into ``workspaces``.

    Parsed rather than grepped so that ``downgrade()`` -- which ``a7b8c9d0e1f2``
    does use to put the constraints back -- and docstrings do not count.
    """
    import ast

    tree = ast.parse(path.read_text())
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "upgrade":
            continue
        creates = any(
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "create_foreign_key"
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        )
        names = {
            sub.value
            for sub in ast.walk(node)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
        }
        return creates and WORKSPACE_TABLE in names
    return False


def _versions_dir(script: ScriptDirectory, revision: str) -> Path:
    return Path(script.get_revision(revision).module.__file__).parent


@pytest.mark.regression
def test_only_the_modules_branch_re_adds_the_workspace_foreign_keys(script):
    """The core chain must not: a core database has no ``workspaces`` table to
    point at, and a core migration naming it re-couples the two profiles."""
    core_versions = _versions_dir(script, BRANCH_POINT)
    modules_versions = _versions_dir(script, "modules_0001_rbac")
    assert core_versions != modules_versions

    core_offenders = sorted(
        path.name
        for path in core_versions.glob("*.py")
        if _upgrade_readds_a_workspace_fk(path)
    )
    assert core_offenders == [], core_offenders

    modules_restorers = sorted(
        path.name
        for path in modules_versions.glob("*.py")
        if _upgrade_readds_a_workspace_fk(path)
    )
    assert modules_restorers, (
        "no revision on the modules branch restores the workspace foreign keys; "
        f"{BRANCH_POINT} drops them and nothing would put them back"
    )
