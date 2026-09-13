"""The security scanners must walk the tree the security code lives in.

Issue #89 moved 58 files -- the SAML XML parser, the PHI encryption, the
SQL-string-building warehouse connectors and the platform's only anonymous
write path -- out of ``backend/app`` and into ``modules/backend/app``.  Every
scanner in ``security-scan.yml`` was pointed at ``backend/`` and stayed there,
so that code went from scanned to unscanned in one commit with nothing to say
so.  The asymmetry was even measurable: five files under ``backend/app`` carry
a ``# nosemgrep`` justification and none under ``modules/backend/app`` does,
because nothing had ever raised a finding there.

Bandit was widened first; Semgrep (a **required** gate -- the summary job has
it in ``needs``) and Trivy were not.  These checks are cheap YAML reads that
fail when a scanner is narrowed back to one tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security-scan.yml"

#: A distribution that does not ship the workflows has nothing here to check.
pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file(), reason="this tree has no .github/workflows"
)


def _workflow() -> Dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


def _runs(job_name: str) -> List[str]:
    """Every ``run:`` script of *job_name*."""
    job = _workflow()["jobs"][job_name]
    return [str(step["run"]) for step in job["steps"] if "run" in step]


def _script(job_name: str, needle: str) -> str:
    """The one ``run:`` script of *job_name* that mentions *needle*."""
    matching = [run for run in _runs(job_name) if needle in run]
    assert matching, f"no step in {job_name!r} runs {needle!r}"
    return "\n".join(matching)


class TestEveryScannerSeesBothTrees:
    @pytest.mark.regression
    def test_semgrep_scans_the_modules_tree(self):
        """Semgrep is a required gate and it scanned `backend/app/` only."""
        script = _script("semgrep", "semgrep scan")
        assert "backend/app/" in script
        assert "modules/backend/app" in script, (
            "Semgrep does not reach modules/backend/app: the SAML parser, the "
            "PHI encryption and the inbound webhooks are not scanned at all"
        )

    def test_semgrep_tolerates_a_core_checkout(self):
        """`modules/` is deleted in a core build, so it must be conditional."""
        script = _script("semgrep", "semgrep scan")
        assert "if [ -d modules/backend/app ]" in script

    @pytest.mark.regression
    def test_bandit_scans_the_modules_tree(self):
        script = _script("python-security", "bandit -r")
        assert "modules/backend/app" in script
        assert "if [ -d modules/backend/app ]" in script

    @pytest.mark.regression
    def test_trivy_scans_the_modules_dependencies(self):
        """The full image installs modules/requirements.txt on top of the core
        closure, and that file was in no HIGH/CRITICAL gate."""
        script = _script("container-security", "trivy fs")
        assert "--exit-code 1" in script
        assert "modules/" in script, (
            "trivy never sees modules/requirements.txt, so the full image's "
            "dependency closure is outside the blocking gate"
        )

    @pytest.mark.regression
    def test_the_sbom_covers_the_modules_dependencies(self):
        script = _script("container-security", "cyclonedx")
        assert "sbom-modules.json" in script, (
            "the published SBOM describes the core image only"
        )

    def test_the_sbom_upload_survives_a_core_checkout(self):
        """One of the two SBOMs is absent in a core build."""
        job = _workflow()["jobs"]["container-security"]
        upload = [
            step
            for step in job["steps"]
            if "upload-artifact" in str(step.get("uses", ""))
        ]
        assert upload, "the SBOM is never uploaded"
        assert upload[0]["with"].get("if-no-files-found") == "warn"

    def test_semgrep_is_still_a_required_gate(self):
        """These checks are only worth anything while the job blocks."""
        summary = _workflow()["jobs"]["security-summary"]
        assert "semgrep" in summary["needs"]
        assert "container-security" in summary["needs"]
        assert "python-security" in summary["needs"]
