"""What the bootstrap says when a database records a revision it has no file for.

Two builds can meet such a database, and they need different answers (#238):

* a **core** build opened against a database the **full** profile migrated --
  the unresolvable rows are all ``modules_*`` revisions;
* an **older** build opened against a database a **newer release** migrated --
  a rollback.  The unresolvable row is a core-chain id this build has never
  seen (or a modules revision a full build has no file for).

The refusal used to diagnose every case as the first, and told the reader to
delete the rows "with a backup taken".  On a rolled-back database that is
harmful: the newer release's tables stay, alembic forgets they are there, the
next run re-applies migrations over them and the next upgrade dies on
``DuplicateTable``.  So neither message may advise removing rows, and each must
name its own diagnosis.

No database: :func:`may_run_alembic` decides from the recorded revision ids and
the revision files on disk.  The end-to-end version, with a real planted
revision and the bootstrap run as a subprocess, is
``backend/tests/integration/database/test_newer_database_rollback.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.core.version import get_version
from backend.app.db import bootstrap

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
CORE_VERSIONS = REPO_ROOT / "backend" / "app" / "db" / "migrations" / "versions"

SCHEMA = "rollback_probe"
#: The core revision the modules branch starts from; recorded with the modules
#: head, it is a full database whose core chain is behind this build's.
BRANCH_POINT = "a7b8c9d0e1f2"
MODULES_HEAD = "modules_0001_rbac"
#: A core-chain id no build of this tree has: what a newer release records.
NEWER_CORE_REVISION = "zz_newer_release_0001"

#: Any advice to remove rows from the version table, however it is phrased.
_REMOVE_ROWS_ADVICE = re.compile(r"\b(delete|remove|truncate|drop)\b", re.IGNORECASE)


def _core_config():
    """The alembic config a core build has: the core versions directory only."""
    cfg = bootstrap.alembic_config()
    cfg.set_main_option("version_locations", str(CORE_VERSIONS))
    return cfg


def _refusal(cfg, recorded: set[str]) -> str:
    with pytest.raises(RuntimeError) as refused:
        bootstrap.may_run_alembic(cfg, recorded, SCHEMA)
    return str(refused.value)


def _assert_no_remove_rows_advice(message: str) -> None:
    found = _REMOVE_ROWS_ADVICE.search(message)
    assert found is None, (
        f"the refusal advises removing rows ({found.group(0)!r}): {message}"
    )


@pytest.mark.regression
def test_an_older_core_build_on_a_newer_database_says_newer_release():
    """The PE rehearsal's case: an unknown core-chain revision."""
    message = _refusal(_core_config(), {NEWER_CORE_REVISION})

    _assert_no_remove_rows_advice(message)
    assert "migrated by a newer Experimently release" in message
    assert NEWER_CORE_REVISION in message
    assert get_version() in message
    assert "restore the backup taken before that upgrade" in message
    assert "full profile" not in message


@pytest.mark.regression
def test_a_newer_database_with_the_modules_row_too_is_still_a_newer_release():
    """A core build meeting a full database a newer release migrated.

    One of the rows *is* from the other profile, but not all of them: the core
    row is one no release of this build has, so running "the full image" of
    this release would not help either.
    """
    message = _refusal(_core_config(), {NEWER_CORE_REVISION, MODULES_HEAD})

    _assert_no_remove_rows_advice(message)
    assert "migrated by a newer Experimently release" in message
    assert NEWER_CORE_REVISION in message
    assert MODULES_HEAD in message


@pytest.mark.regression
def test_a_core_build_on_a_full_database_keeps_the_other_profile_diagnosis():
    """The core-on-full refusal: the other profile, and still no row removal."""
    message = _refusal(_core_config(), {BRANCH_POINT, MODULES_HEAD})

    _assert_no_remove_rows_advice(message)
    assert "full profile being opened by a core build" in message
    assert "Run the full image of this release against it" in message
    assert MODULES_HEAD in message
    assert "newer" not in message


@pytest.mark.regression
@pytest.mark.modules
def test_a_full_build_on_a_newer_modules_revision_says_newer_release():
    """A modules row a *full* build has no file for is not the other profile."""
    newer_modules_revision = "modules_9999_newer"
    message = _refusal(
        bootstrap.alembic_config(), {"b8c9d0e1f2a3", newer_modules_revision}
    )

    _assert_no_remove_rows_advice(message)
    assert "migrated by a newer Experimently release" in message
    assert newer_modules_revision in message


def test_nothing_foreign_runs_alembic():
    """The guard does not get in the way of an ordinary database."""
    assert bootstrap.may_run_alembic(_core_config(), {BRANCH_POINT}, SCHEMA) is True


def test_the_regex_catches_the_old_advice():
    """The probe itself: the sentence #238 is about must trip it."""
    old = (
        "Run the full image against it, or -- with a backup taken -- delete "
        'those rows from "x".alembic_version.'
    )
    assert _REMOVE_ROWS_ADVICE.search(old)
