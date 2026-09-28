"""An older build meeting a database a newer release migrated: a rollback.

The rehearsal from the self-hosting plan's review (#238), as a test.  Release
N+1 is this tree plus one more core revision -- ``down_revision`` = this tree's
core head -- that creates a table, exactly what the next release to carry a
migration will look like.  The database is built by N, upgraded by N+1, and
then N starts against it again, which is what ``helm rollback`` or a re-pinned
image tag does.

N cannot resolve N+1's revision, so it must refuse -- exit non-zero, before
alembic touches anything -- and say what happened: *a newer release migrated
this database; run that release or restore the pre-upgrade backup*.  It used to
say "a database built by the full profile being opened by a core build ...
delete those rows from alembic_version", which was the wrong diagnosis and
harmful advice: deleting the row leaves N+1's table in place and unrecorded,
the next N run re-applies migrations over it, and rolling forward to N+1 again
dies on ``DuplicateTable``.

Both documented paths are exercised, because both reach the same guard: the
bootstrap the container runs on start-up, and the raw ``alembic upgrade
heads`` that ``deploy.yml`` and the ECS migration task run.  In-process
subprocesses rather than ``docker run``: the property is the bootstrap's, the
trees are built the way ``tree_profiles`` builds them for the other transition
tests, and a subprocess is what a container is to this code.
"""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import inspect, text

from backend.app.db import bootstrap
from backend.tests.integration.database import tree_profiles
from backend.tests.integration.database.tree_profiles import CORE, FULL

pytestmark = [pytest.mark.integration]

#: This tree's core head.  A literal, for the reason ``tree_profiles.CORE_HEAD``
#: gives; ``backend/tests/unit/db/test_alembic_plan.py`` pins it to the files.
CORE_HEAD = tree_profiles.CORE_HEAD
#: The modules branch's HEAD -- what a modules revision of release N+1 would
#: extend.  Not its first revision (``modules_0001_rbac``): the branch has two.
MODULES_HEAD = "modules_0002_warehouse_analysis"

#: The revision release N+1 adds, and the table it creates.  On the core chain
#: its id has no ``modules_`` prefix; on the modules branch it has, which is
#: what a build reads as "the other profile" -- and must not, from a full build.
NEXT_REVISION = "zz_next_release_0001"
NEXT_MODULES_REVISION = "modules_9999_next_release_probe"
NEXT_TABLE = "next_release_probe"

#: Where N+1's revision goes: (revision id, the head it extends).
CORE_CHAIN = "core_chain"
MODULES_BRANCH = "modules_branch"
_NEXT = {
    CORE_CHAIN: (NEXT_REVISION, CORE_HEAD),
    MODULES_BRANCH: (NEXT_MODULES_REVISION, MODULES_HEAD),
}

_NEXT_RELEASE_REVISION = '''"""A migration the next release carries (test fixture).

Revision ID: {revision}
Revises: {down_revision}
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "{revision}"
down_revision = "{down_revision}"
branch_labels = None
depends_on = None

SCHEMA = os.environ["POSTGRES_SCHEMA"]


def upgrade() -> None:
    op.create_table(
        "{NEXT_TABLE}",
        sa.Column("id", sa.Integer(), primary_key=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("{NEXT_TABLE}", schema=SCHEMA)
'''

#: Any advice to remove rows from the version table, however it is phrased.
_REMOVE_ROWS_ADVICE = re.compile(r"\b(delete|remove|truncate)\b", re.IGNORECASE)


@pytest.fixture
def scratch_schema(test_db):
    schema = f"rollback_{uuid.uuid4().hex[:8]}"
    try:
        yield schema
    finally:
        with test_db.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def _this_release(profile: str, tmp_path):
    """Release N: this tree, as *profile* builds it, with its ``VERSION``."""
    if profile == FULL:
        return tree_profiles.REPO_ROOT
    tree = tree_profiles.core_tree(tmp_path / "release-n")
    (tree / "VERSION").write_bytes((tree_profiles.REPO_ROOT / "VERSION").read_bytes())
    return tree


def _next_release(profile: str, tmp_path, chain: str = CORE_CHAIN):
    """Release N+1: a copy of this tree plus one revision on *chain*."""
    destination = tmp_path / "release-n-plus-1"
    if profile == FULL:
        tree = tree_profiles.full_tree(destination)
    else:
        tree = tree_profiles.core_tree(destination)
    revision, down_revision = _NEXT[chain]
    if chain == MODULES_BRANCH:
        # Built from parts: see tree_profiles._ALEMBIC_INI_PARTS.
        versions = tree.joinpath("modules", "backend", "app", "db", "migrations")
    else:
        versions = tree / "backend" / "app" / "db" / "migrations"
    (versions / "versions" / f"{revision}.py").write_text(
        _NEXT_RELEASE_REVISION.format(
            revision=revision, down_revision=down_revision, NEXT_TABLE=NEXT_TABLE
        ),
        encoding="utf-8",
    )
    return tree


def _rows(engine, schema: str) -> set[str]:
    return bootstrap.recorded_revisions(engine, schema)


def _tables(engine, schema: str) -> set[str]:
    return set(inspect(engine).get_table_names(schema=schema))


@pytest.mark.regression
@pytest.mark.parametrize(
    ("profile", "chain"),
    [
        pytest.param(CORE, CORE_CHAIN, id="core"),
        pytest.param(FULL, CORE_CHAIN, marks=pytest.mark.modules, id="full"),
        # A newer *modules* revision met by a full build: the prefix says
        # "modules", the build is full, so it is a newer release -- which is
        # what the previous full image says to a database modules_0002 migrated.
        pytest.param(
            FULL, MODULES_BRANCH, marks=pytest.mark.modules, id=MODULES_BRANCH
        ),
    ],
)
def test_an_older_release_refuses_a_database_a_newer_release_migrated(
    test_db, scratch_schema, tmp_path, profile, chain
):
    next_revision = _NEXT[chain][0]
    release_n = _this_release(profile, tmp_path)
    release_n_plus_1 = _next_release(profile, tmp_path, chain)
    version = (tree_profiles.REPO_ROOT / "VERSION").read_text("utf-8").strip()

    # N builds the database; N+1 upgrades it and applies its migration.
    built = tree_profiles.bootstrap_schema(release_n, scratch_schema)
    assert built.returncode == 0, built.stderr[-3000:]
    upgraded = tree_profiles.bootstrap_schema(release_n_plus_1, scratch_schema)
    assert upgraded.returncode == 0, upgraded.stderr[-3000:]
    assert NEXT_TABLE in _tables(test_db, scratch_schema)
    after_upgrade = _rows(test_db, scratch_schema)
    assert next_revision in after_upgrade
    tables_after_upgrade = _tables(test_db, scratch_schema)

    # The rollback: N again, by both documented paths.
    rolled_back = tree_profiles.bootstrap_schema(release_n, scratch_schema)
    raw_upgrade = tree_profiles.alembic(release_n, scratch_schema, "upgrade", "heads")

    for result in (rolled_back, raw_upgrade):
        assert result.returncode != 0, result.stdout[-2000:]
        assert "migrated by a newer Experimently release" in result.stderr, (
            result.stderr[-3000:]
        )
        assert next_revision in result.stderr
        assert f"({version})" in result.stderr
        assert "restore the backup taken before that upgrade" in result.stderr
        assert "full profile being opened by a core build" not in result.stderr
        # The refusal's own sentence, not the traceback around it.
        refusal = result.stderr[result.stderr.rindex("RuntimeError") :]
        advice = _REMOVE_ROWS_ADVICE.search(refusal)
        assert advice is None, f"removal advice {advice.group(0)!r}: {refusal}"

    # Nothing recorded, nothing applied, nothing dropped.
    assert _rows(test_db, scratch_schema) == after_upgrade
    assert _tables(test_db, scratch_schema) == tables_after_upgrade
