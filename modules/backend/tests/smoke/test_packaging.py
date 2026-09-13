"""The modules' half of the wheel contract.

``backend/tests/unit/scripts/test_packaging.py`` states the rules a
distribution must obey -- every package importable by its name, every package
holding Python, nothing from a tests/Lambda/CDK tree.  It cannot also assert
that *these* packages are present: a core file may not name a module (that is
``backend/tests/smoke/test_core_boundary.py``'s hard gate), and a core
checkout has no ``modules/`` for it to look at.

So the positive half lives here, where naming module paths is the point.  One
wheel carries both halves -- same licence, same version -- and a deployment
that wants the core profile deletes ``modules/`` from its tree
(``scripts/core_build.sh``).  An exclusion that quietly swallowed
``modules/backend/app`` would leave a wheel whose ``full`` profile is missing
every module route, with nothing to say so.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from setuptools.discovery import PEP420PackageFinder

REPO_ROOT = Path(__file__).resolve().parents[4]
PYPROJECT = REPO_ROOT / "pyproject.toml"

pytestmark = pytest.mark.smoke


def _discovered() -> list[str]:
    config = tomllib.loads(PYPROJECT.read_text())["tool"]["setuptools"]["packages"][
        "find"
    ]
    return sorted(
        PEP420PackageFinder.find(
            where=str(REPO_ROOT),
            include=config["include"],
            exclude=config["exclude"],
        )
    )


@pytest.mark.regression
@pytest.mark.parametrize(
    "package",
    [
        "modules",
        "modules.backend",
        "modules.backend.app",
        "modules.backend.app.api.v1.endpoints",
        "modules.backend.app.models",
        "modules.backend.app.schemas",
        "modules.backend.app.services",
        "modules.backend.app.services.integrations",
        "modules.backend.app.db.migrations.versions",
    ],
)
def test_the_modules_are_in_the_distribution(package: str):
    assert package in _discovered()


def test_the_modules_own_non_python_trees_are_not():
    """The dashboard's TSX, the CDK stacks, the Lambda handlers and this test
    suite are not part of the Python distribution."""
    discovered = _discovered()
    unwanted = [
        name
        for name in discovered
        if name.startswith(
            ("modules.frontend", "modules.infrastructure", "modules.lambda")
        )
        or "tests" in name.split(".")
    ]
    assert not unwanted, f"packaged but not application code: {unwanted}"
