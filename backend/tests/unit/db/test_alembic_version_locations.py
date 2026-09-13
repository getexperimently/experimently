"""alembic.ini must name its version locations the same way from any directory.

The modules' branch lives outside ``script_location``, so alembic.ini lists a
second version location.  It used to be spelled relative to the *working
directory* (``modules/backend/app/db/migrations/versions``), and alembic skips a
version location that does not exist -- silently.  Run from ``backend/``, which
is where ``-c app/db/alembic.ini`` is spelled in half the repository,
``alembic heads`` printed one head, ``upgrade heads`` applied nothing and exited
0, and ``revision --autogenerate`` saw a single head, so the two-heads guard
never fired and a module's tables could land in a *core* migration.

These checks need no database: they build the same ``ScriptDirectory`` alembic
builds, from three different working directories.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "backend" / "app" / "db" / "alembic.ini"
CORE_VERSIONS = REPO_ROOT / "backend" / "app" / "db" / "migrations" / "versions"
MODULES_VERSIONS = (
    REPO_ROOT / "modules" / "backend" / "app" / "db" / "migrations" / "versions"
)

#: Repository root, a subdirectory, and somewhere else entirely.
CWDS = ("", "backend", None)

pytestmark = pytest.mark.unit


def _chdir(monkeypatch, where, tmp_path) -> None:
    monkeypatch.chdir(tmp_path if where is None else REPO_ROOT / where)


def _script(relative_ini: bool) -> ScriptDirectory:
    # Both spellings of -c that the repository uses.
    path = "app/db/alembic.ini" if relative_ini else str(ALEMBIC_INI)
    return ScriptDirectory.from_config(Config(path))


@pytest.mark.parametrize("where", CWDS, ids=["repo-root", "backend", "elsewhere"])
def test_version_locations_are_the_same_from_any_directory(
    where, monkeypatch, tmp_path
):
    _chdir(monkeypatch, where, tmp_path)
    script = _script(relative_ini=False)

    locations = {Path(p).resolve() for p in script._version_locations}
    assert CORE_VERSIONS.resolve() in locations
    assert MODULES_VERSIONS.resolve() in locations
    assert all(Path(p).is_absolute() for p in script._version_locations)


@pytest.mark.regression
@pytest.mark.modules
@pytest.mark.parametrize("where", CWDS, ids=["repo-root", "backend", "elsewhere"])
def test_both_heads_are_visible_from_any_directory(where, monkeypatch, tmp_path):
    _chdir(monkeypatch, where, tmp_path)
    heads = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).revision_map.heads

    assert len(heads) == 2, heads
    labelled = {
        head
        for head in heads
        if "modules"
        in (
            ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
            .get_revision(head)
            .branch_labels
            or set()
        )
    }
    assert len(labelled) == 1, heads


@pytest.mark.regression
@pytest.mark.modules
def test_the_relative_dash_c_spelling_from_backend_also_sees_both(monkeypatch):
    """`alembic -c app/db/alembic.ini` run from backend/ -- the spelling in CI."""
    monkeypatch.chdir(REPO_ROOT / "backend")
    assert len(_script(relative_ini=True).revision_map.heads) == 2
