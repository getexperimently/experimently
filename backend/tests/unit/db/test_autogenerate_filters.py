"""The core migration chain must not absorb module-owned constraints or tables.

Two kinds of object, and the second was missing until review round 3.

*The constraints* -- the two ``workspace_id`` foreign keys -- are managed by the
modules' alembic branch, so a core autogenerate that emitted them would put a
reference to ``workspaces`` into a core migration.

*The tables* -- all twelve.  Nine are created by revisions that sit in the core
chain for historical reasons, so a database can hold all twelve while this
build's ``Base.metadata`` holds none of them: a core checkout, or a full one
whose registration was asked for core models only.  With
``include_schemas=True`` on (round 2) autogenerate reflects them and, with
nothing filtering them, proposed twelve ``op.drop_table`` calls plus their
indexes -- a core migration that destroys every workspace, SSO configuration,
BAA and PHI audit row on any full-profile database it reaches.

This file used to assert the opposite of the second rule
(``include_object(..., "experiments", "table", ...) is True`` and nothing about
module tables), so the suite endorsed the bug.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Index, Integer, MetaData, Table, UniqueConstraint

from backend.app.db.autogenerate_filters import (
    MODULE_MANAGED_CONSTRAINTS,
    MODULE_TABLES,
    include_object,
)

pytestmark = pytest.mark.unit


@pytest.mark.regression
@pytest.mark.parametrize("name", sorted(MODULE_MANAGED_CONSTRAINTS))
@pytest.mark.parametrize("reflected", [True, False])
def test_the_module_foreign_keys_are_excluded_both_ways(name, reflected):
    """Whether the constraint is in the metadata and not the database (a
    migrated full-profile database) or the other way round, autogenerate must
    neither add nor drop it: it belongs to the modules branch."""
    assert (
        include_object(object(), name, "foreign_key_constraint", reflected, None)
        is False
    )


# ---------------------------------------------------------------------------
# The module tables (review round 3, finding 2)
# ---------------------------------------------------------------------------
@pytest.mark.regression
@pytest.mark.parametrize("name", sorted(MODULE_TABLES))
@pytest.mark.parametrize("reflected", [True, False])
def test_a_module_table_is_never_compared(name, reflected):
    """Reflected (a drop) or not (a create): the core chain owns neither."""
    assert include_object(object(), name, "table", reflected, None) is False


def _table(name: str, schema: str = "experimentation") -> Table:
    metadata = MetaData(schema=schema)
    return Table(
        name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("workspace_id", Integer),
    )


@pytest.mark.regression
@pytest.mark.parametrize("kind", ["column", "index", "unique_constraint"])
def test_what_lives_on_a_module_table_is_not_compared_either(kind):
    """A table drop comes with its indexes; both have to be filtered.

    The revision review round 3 reproduced carried 37 ``op.drop_index`` calls
    alongside the twelve ``op.drop_table`` calls, and an index left in a core
    migration names a table a core database does not have.
    """
    table = _table("workspaces")
    objects = {
        "column": table.c.workspace_id,
        "index": Index("experimentation_workspace_slug", table.c.id),
        "unique_constraint": UniqueConstraint(table.c.id, name="uq_workspace"),
    }
    obj = objects[kind]

    assert include_object(obj, getattr(obj, "name", None), kind, True, None) is False


def test_a_core_table_and_everything_on_it_is_compared():
    """The filter is a list, not a switch: core DDL still autogenerates."""
    table = _table("experiments")

    assert include_object(table, "experiments", "table", False, None) is True
    assert include_object(table.c.workspace_id, "workspace_id", "column", True, None)
    assert (
        include_object(object(), "experiments_pkey", "primary_key", False, None) is True
    )
    assert (
        include_object(
            Index("ix_experiments_key", table.c.id),
            "ix_experiments_key",
            "index",
            True,
            None,
        )
        is True
    )
    assert include_object(
        object(), "some_other_fkey", "foreign_key_constraint", False, None
    )


# ---------------------------------------------------------------------------
# The list itself
# ---------------------------------------------------------------------------
def test_the_table_list_is_the_manifest_s():
    """``modules-manifest.txt`` is the source of truth; this is the copy.

    Core code cannot read the manifest at runtime (``backend/Dockerfile`` ships
    ``backend/`` and ``modules/backend/`` and nothing else), so the names are
    spelled in ``autogenerate_filters.py`` and kept honest here -- the same
    arrangement as ``hooks.KNOWN_MODULES`` (pinned by
    ``backend/tests/unit/core/test_module_names.py``) and
    ``MODULE_MANAGED_CONSTRAINTS`` (pinned against the module's own model in
    ``modules/backend/tests/unit/db/test_autogenerate_filters_names.py``).

    Adding a module model means adding its table in both places; if you have
    just done one, this is the other.
    """
    from backend.tests.smoke.modules_manifest import module_tables

    assert MODULE_TABLES == frozenset(module_tables())


def test_the_core_tables_are_not_on_the_module_list():
    """Named individually because the manifest warns about these two.

    ``audit_logs`` and ``audit_events_v2`` read like compliance tables and are
    core: the compliance module only fills in the HMAC signature.
    """
    for name in ("audit_logs", "audit_events_v2", "experiments", "feature_flags"):
        assert name not in MODULE_TABLES


# ---------------------------------------------------------------------------
# Which chain is being generated for (issue #89: the `modules` alembic branch)
# ---------------------------------------------------------------------------


from backend.app.db.autogenerate_filters import (
    MODULES_VERSIONS_DIR,
)

REPO_ROOT = MODULES_VERSIONS_DIR.parents[5]


def _cmd_opts(**kwargs):
    """A stand-in for alembic's parsed command line (``config.cmd_opts``)."""
    from types import SimpleNamespace

    defaults = {"head": None, "branch_label": None, "version_path": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestTargetsModulesBranch:
    @pytest.mark.parametrize(
        "opts",
        [
            _cmd_opts(head="modules@head"),
            _cmd_opts(head="modules"),
            _cmd_opts(head=["modules@head"]),
            _cmd_opts(branch_label="modules"),
            # A --version-path is recognised by resolving it, not by looking
            # for a component called "modules": both spellings of the branch's
            # real directory count, and only that directory.
            _cmd_opts(version_path=str(MODULES_VERSIONS_DIR)),
            _cmd_opts(
                version_path=str(MODULES_VERSIONS_DIR).replace(str(REPO_ROOT) + "/", "")
            ),
        ],
    )
    def test_modules_branch_targets(self, opts):
        from backend.app.db.autogenerate_filters import (
            include_object_for,
            targets_modules_branch,
        )

        assert targets_modules_branch(opts) is True
        assert include_object_for(opts) is None  # nothing filtered

    @pytest.mark.parametrize(
        "opts",
        [
            None,  # driven from Python (db/bootstrap.py): never a revision
            _cmd_opts(),  # a core checkout: one head, nothing named
            _cmd_opts(head="a7b8c9d0e1f2"),
            _cmd_opts(head="heads"),
            _cmd_opts(version_path="backend/app/db/migrations/versions"),
            _cmd_opts(branch_label="feature"),
            # A checkout whose *parent* directory happens to be called
            # "modules": the path names the core versions directory, so the
            # core filter must stay on.  A bare component match said
            # otherwise and handed this command no filter at all, which put
            # the two module-managed foreign keys into a core migration.
            pytest.param(
                _cmd_opts(
                    version_path="/home/dev/modules/checkout/backend/app/db/migrations/versions"
                ),
                marks=pytest.mark.regression,
            ),
        ],
    )
    def test_core_chain_targets(self, opts):
        from backend.app.db.autogenerate_filters import (
            include_object,
            include_object_for,
            targets_modules_branch,
        )

        assert targets_modules_branch(opts) is False
        assert include_object_for(opts) is include_object

    @pytest.mark.regression
    def test_the_core_filter_is_not_decided_by_the_loaded_profile(self):
        """A developer on the full profile generating a *core* migration is
        the common case: the modules' models are loaded (so the metadata
        carries the two constraints) and the target is the core chain.  The
        decision must come from the command line, never from
        ``load_modules()``."""
        from backend.app.db.autogenerate_filters import (
            MODULE_MANAGED_CONSTRAINTS,
            include_object_for,
        )

        # Whatever profile this process runs, the target names the core
        # chain, so the constraints are filtered.
        hook = include_object_for(_cmd_opts(head="a7b8c9d0e1f2"))
        assert hook is not None
        for name in MODULE_MANAGED_CONSTRAINTS:
            assert hook(object(), name, "foreign_key_constraint", False, None) is False
