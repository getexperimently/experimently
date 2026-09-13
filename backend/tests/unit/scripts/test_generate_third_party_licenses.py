"""`scripts/generate_third_party_licenses.py` — the dependency licence report.

The report is what a reader checks before trusting that nothing in the tree is
incompatible with distributing an Apache-2.0 work, so a wrong flag is worse
than no flag.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[4] / "scripts" / "generate_third_party_licenses.py"
)


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("gen_third_party", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_third_party"] = module
    spec.loader.exec_module(module)
    return module


class TestFlagsFor:
    @pytest.mark.parametrize(
        "lic",
        ["LGPL", "LGPL-2.1", "LGPL-3.0-or-later", "GNU Lesser General Public (LGPL)"],
    )
    @pytest.mark.regression
    def test_lgpl_is_weak_copyleft_not_strong(self, script, lic):
        """`"GPL" in lic.lower()` is true of every LGPL string.

        psycopg2 is LGPL; reporting it as strong copyleft that "must not
        ship" sends the reader after a problem that does not exist.
        """
        flag = script.flags_for(lic)
        assert flag is not None
        assert "weak copyleft" in flag
        assert "strong copyleft" not in flag

    @pytest.mark.parametrize("lic", ["AGPL-3.0", "AGPL-3.0-only", "AGPL"])
    def test_agpl_gets_the_agpl_note(self, script, lic):
        assert script.flags_for(lic) == script.COPYLEFT_FLAGS[0][1]

    @pytest.mark.parametrize("lic", ["GPL-2.0", "GPL-3.0-or-later", "GPL"])
    def test_gpl_still_gets_the_gpl_note(self, script, lic):
        flag = script.flags_for(lic)
        assert flag is not None
        assert "strong copyleft" in flag
        assert "must not ship" in flag
        assert "network-use" not in flag  # that is the AGPL note

    @pytest.mark.parametrize(
        "lic", ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC", "MPL-2.0", "PSF-2.0"]
    )
    def test_permissive_licences_are_not_flagged(self, script, lic):
        assert script.flags_for(lic) is None

    def test_an_expression_is_searched_not_compared(self, script):
        assert script.flags_for("Apache-2.0 OR MIT") is None
        assert script.flags_for("MIT OR GPL-2.0") is not None

    @pytest.mark.parametrize(
        "lic,fragment",
        [
            ("SSPL-1.0", "NOT an open-source licence"),
            ("BUSL-1.1", "source-available"),
            ("CDDL-1.0", "weak copyleft"),
            ("MS-PL", "separate artefact"),
            ("UNKNOWN", "resolved by hand"),
            ("UNLICENSED", "no licence declared"),
        ],
    )
    def test_the_other_flags_still_fire(self, script, lic, fragment):
        assert fragment in script.flags_for(lic)


class TestNormalise:
    def test_pypi_classifier_names_become_spdx_ids(self, script):
        assert script.normalise("MIT License") == "MIT"
        assert script.normalise("Apache Software License") == "Apache-2.0"
        assert (
            script.normalise("GNU Library or Lesser General Public License (LGPL)")
            == "LGPL"
        )

    def test_an_unknown_name_is_passed_through_trimmed(self, script):
        assert script.normalise("  Zlib  ") == "Zlib"


class TestDeclaredDependencies:
    @pytest.mark.regression
    def test_the_python_section_is_the_closure_of_the_pins_not_the_venv(self, script):
        """The committed report once listed black, flake8 and isort -- tools the
        venv still held after ruff replaced them -- under a header claiming
        the pinned set. A legal document that lists a dependency set must
        list *that* set."""
        declared = script.declared_python_dependencies()
        assert "fastapi" in declared
        assert "sqlalchemy" in declared
        # Transitive: pulled in by fastapi/starlette, not pinned directly.
        assert "starlette" in declared
        assert "anyio" in declared
        for leftover in ("black", "flake8", "isort", "pycodestyle", "pyflakes"):
            assert leftover not in declared, leftover

    def test_canonical_names(self, script):
        assert script._canonical("Typing_Extensions") == "typing-extensions"
        assert script._canonical("ruamel.yaml") == "ruamel-yaml"
