"""`scripts/module_only_packages.py` — the derived "not in the core image" list.

The ``docker-smoke`` job asserts the core API image ships none of the packages
only the modules need.  That list used to be six names typed by hand, and it
had already gone stale: ``requests`` and ``defusedxml`` were installed in the
core image with no importer under ``backend/app``, ``backend/lambda`` or
``backend/scripts`` -- their only runtime importer is
``modules/backend/app/services/sso_service.py`` -- and neither name was on the
list, so nothing caught it.

The list is now the difference between the two locks the Dockerfile installs.
These tests pin that contract: the difference is non-empty, it contains the
packages whose only importer is a module, and it contains nothing the core
image legitimately needs.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "module_only_packages.py"
CORE_LOCK = REPO_ROOT / "backend" / "requirements" / "runtime.lock"
MODULES_LOCK = REPO_ROOT / "modules" / "requirements.lock"

pytestmark = pytest.mark.skipif(
    not MODULES_LOCK.exists(), reason="core checkout: no modules/requirements.lock"
)

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==")


def _pinned(lock: Path) -> set[str]:
    return {
        re.sub(r"[-_.]+", "-", match.group(1)).lower()
        for line in lock.read_text(encoding="utf-8").splitlines()
        if (match := _PIN.match(line.strip()))
    }


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )


def names() -> list[str]:
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.split()


class TestDerivedList:
    def test_it_is_exactly_the_difference_between_the_two_locks(self):
        assert set(names()) == _pinned(MODULES_LOCK) - _pinned(CORE_LOCK)

    def test_oneline_is_the_same_list(self):
        result = _run("--oneline")
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.split() == names()
        assert result.stdout.count("\n") == 1

    def test_it_names_the_packages_the_modules_declare(self):
        """Every direct pin in modules/requirements.txt that core does not share."""
        listed = set(names())
        declared = {
            re.sub(r"[-_.]+", "-", match.group(1)).lower()
            for raw in (REPO_ROOT / "modules" / "requirements.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if (match := _PIN.match(raw.split("#", 1)[0].strip()))
        }
        assert declared - _pinned(CORE_LOCK) <= listed
        # The five the hand-written list used to carry, so this is not weaker.
        assert {
            "python3-saml",
            "authlib",
            "pymysql",
            "clickhouse-connect",
            "databricks-sql-connector",
        } <= listed

    @pytest.mark.regression
    @pytest.mark.parametrize("package", ["requests", "defusedxml"])
    def test_the_packages_the_hand_written_list_missed_are_on_it(self, package):
        """Module-only runtime imports that shipped in the core image regardless.

        `requests` and `defusedxml` were pinned in
        backend/requirements/runtime.txt -- the core image's install list --
        with no importer anywhere under backend/app, backend/lambda or
        backend/scripts.
        """
        assert package in names()

    def test_it_covers_the_transitive_closure_not_just_the_direct_pins(self):
        """lxml/xmlsec (the SAML signature stack) arrive through python3-saml."""
        assert {"lxml", "xmlsec"} <= set(names())

    def test_nothing_the_core_image_installs_is_denied(self):
        """A name on both sides would fail the core image on every run."""
        assert not set(names()) & _pinned(CORE_LOCK)


class TestNoModuleOnlyRuntimeImportsInCore:
    """No shipped core source file imports a module-only distribution.

    The list is derived from the locks; this is the other half -- that the
    core *code* really does not need any of them, so removing them from
    backend/requirements/runtime.txt cannot break the image.
    """

    #: import name -> distribution name, for the ones that differ.
    IMPORT_NAMES = {
        "onelogin": "python3-saml",
        "clickhouse_connect": "clickhouse-connect",
        "databricks": "databricks-sql-connector",
        "charset_normalizer": "charset-normalizer",
        "et_xmlfile": "et-xmlfile",
    }

    @pytest.mark.regression
    def test_no_core_source_file_imports_one(self):
        distributions = set(names())
        modules = {name.replace("-", "_") for name in distributions}
        modules |= {
            imp for imp, dist in self.IMPORT_NAMES.items() if dist in distributions
        }

        pattern = re.compile(
            r"^\s*(?:from|import)\s+(" + "|".join(sorted(modules)) + r")\b", re.M
        )
        offenders = []
        for root in ("backend/app", "backend/lambda", "backend/scripts"):
            for path in (REPO_ROOT / root).rglob("*.py"):
                for match in pattern.finditer(path.read_text(encoding="utf-8")):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}: {match.group(0).strip()}"
                    )
        assert not offenders, (
            "core code imports a package only the full image installs; either "
            "the import belongs in a module or the pin belongs back in "
            "backend/requirements/runtime.txt: " + "; ".join(offenders)
        )
