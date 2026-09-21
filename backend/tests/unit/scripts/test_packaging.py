"""What `pip wheel .` puts in the distribution.

``[tool.setuptools.packages.find]`` used to say ``include = ["backend*",
"modules*"]`` with three exclusions, and setuptools' discovery defaults to
``namespaces = true`` (PEP 420), so "a package" meant "a directory".  The wheel
swept in both Lambda trees (49 ``.py``, their tests included) and the alembic
chain twice -- ``backend/migrations`` is a tracked symlink to
``backend/app/db/migrations`` -- while the dashboard's TSX directories, one of
them not even a legal Python identifier, landed in the package list and in the
NAMESPACES map of an editable install.  ``include-package-data`` then put back
as *data* whatever the exclusions removed as *packages*, which is why excluding
the Lambda trees alone produced byte-for-byte the same wheel.

The rules below are deliberately general rather than a list of names: a
package must be importable by its name, must actually contain Python, and must
not sit under a tree that is not application code.  That mirrors what
``.dockerignore`` already states for the API image -- what the image refuses to
copy, the wheel refuses to package -- and it catches the next stray directory,
not just the ones already found.
"""

from __future__ import annotations

import keyword
import tomllib
from pathlib import Path

import pytest
from setuptools.discovery import PEP420PackageFinder

REPO_ROOT = Path(__file__).resolve().parents[4]
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: Path segments that never belong in a distribution, whatever tree they are
#: in: test suites, Lambda handlers (deployed from source by CDK, each with
#: its own requirements.txt -- and ``lambda`` is a reserved word, so nothing
#: could import them anyway), CDK stacks, and build/tooling detritus.
FORBIDDEN_SEGMENTS = frozenset(
    {"tests", "lambda", "infrastructure", "venv", ".venv", "node_modules", "build"}
)

#: Core-tree prefixes with a specific reason to stay out.
FORBIDDEN_PREFIXES = (
    # A tracked symlink to backend/app/db/migrations: the alembic chain was
    # packaged twice, once under each name.
    "backend.migrations",
)


def _setuptools_table() -> dict:
    return tomllib.loads(PYPROJECT.read_text())["tool"]["setuptools"]


def _discovered() -> list[str]:
    config = _setuptools_table()["packages"]["find"]
    return sorted(
        PEP420PackageFinder.find(
            where=str(REPO_ROOT),
            include=config["include"],
            exclude=config["exclude"],
        )
    )


def _directory(package: str) -> Path:
    return REPO_ROOT.joinpath(*package.split("."))


class TestWheelDiscovery:
    @pytest.mark.regression
    def test_every_discovered_package_is_importable_by_name(self):
        """One of the dashboard's page directories is `[id]`."""
        bad = [
            name
            for name in _discovered()
            if not all(
                segment.isidentifier() and not keyword.iskeyword(segment)
                for segment in name.split(".")
            )
        ]
        assert not bad, f"not legal dotted module names: {bad}"

    @pytest.mark.regression
    def test_every_discovered_package_contains_python(self):
        """A directory with no ``.py`` under it is not a package.

        This is what kept 16 directories of dashboard TSX and a directory of
        ``.txt`` pins in the package list: PEP 420 discovery returns
        directories, and nothing asked whether they held any Python.
        """
        empty = [
            name for name in _discovered() if not any(_directory(name).rglob("*.py"))
        ]
        assert not empty, f"packaged but hold no Python: {empty}"

    @pytest.mark.regression
    def test_nothing_outside_the_application_is_packaged(self):
        discovered = _discovered()
        swept = sorted(
            {name for name in discovered if FORBIDDEN_SEGMENTS & set(name.split("."))}
            | {
                name
                for name in discovered
                for prefix in FORBIDDEN_PREFIXES
                if name == prefix or name.startswith(prefix + ".")
            }
        )
        assert not swept, f"packaged but not application code: {swept}"

    @pytest.mark.regression
    def test_include_package_data_does_not_put_the_excluded_trees_back(self):
        """With it on, the wheel is built from the sdist manifest as well as
        the package list, and manifest files under a package directory ride
        along as package data -- which is how both Lambda trees survived being
        excluded from discovery."""
        assert _setuptools_table().get("include-package-data") is False, (
            "include-package-data must be off, or packages.find is not the "
            "answer to what is in the wheel"
        )

    def test_the_application_itself_is_packaged(self):
        """The other half: the exclusions must not have cut into the product."""
        discovered = _discovered()
        assert "backend.app" in discovered
        assert "backend.app.api.v1.endpoints" in discovered
        assert "backend.app.services" in discovered
        # The live alembic chain ships (once): the symlinked duplicate under
        # backend/migrations is the copy that was dropped.
        assert "backend.app.db.migrations.versions" in discovered
