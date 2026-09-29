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
from typing import Any, Dict, List, Optional, Tuple

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


# -- every published image is scanned (#77) -----------------------------------

RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"
BUILD_ACTION = "docker/build-push-action"
MATRIX_PROFILE = "${{ matrix.profile }}"

#: What makes an image: its Dockerfile, its stage, and its profile build-arg.
ImageKey = Tuple[str, Optional[str], Optional[str]]


def _build_args(step: Dict[str, Any]) -> Dict[str, str]:
    raw = str(step.get("with", {}).get("build-args") or "")
    pairs = (line.strip().split("=", 1) for line in raw.splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def _expand(value: Any, profile: Optional[str], where: str) -> Optional[str]:
    """``${{ matrix.profile }}`` replaced by *profile*; ``None`` stays ``None``."""
    if value is None:
        return None
    text = str(value)
    if MATRIX_PROFILE in text:
        assert profile is not None, f"{where}: {text!r} outside a profile matrix"
        text = text.replace(MATRIX_PROFILE, profile)
    return text


def _built_images(
    workflow: Dict[str, Any], job_names: List[str]
) -> Dict[ImageKey, str]:
    """``{(file, target, profile): tags}`` for every build-push-action step of
    *job_names*, with ``${{ matrix.profile }}`` expanded over the job's matrix."""
    images: Dict[ImageKey, str] = {}
    for name in job_names:
        job = workflow["jobs"][name]
        profiles = job.get("strategy", {}).get("matrix", {}).get("profile") or [None]
        for step in job["steps"]:
            if BUILD_ACTION not in str(step.get("uses", "")):
                continue
            with_ = step["with"]
            for profile in profiles:
                key = (
                    str(_expand(with_["file"], profile, name)),
                    _expand(with_.get("target"), profile, name),
                    _expand(
                        _build_args(step).get("EXPERIMENTLY_PROFILE"), profile, name
                    ),
                )
                images[key] = str(_expand(with_.get("tags", ""), profile, name))
    return images


def _release_images() -> Dict[ImageKey, str]:
    release = yaml.safe_load(RELEASE.read_text())
    publishing = [
        name
        for name, job in release["jobs"].items()
        if any(BUILD_ACTION in str(s.get("uses", "")) for s in job.get("steps", []))
    ]
    return _built_images(release, publishing)


class TestEveryPublishedImageIsScanned:
    """release.yml publishes four images, and the Trivy gate scanned two (#77).

    The set of images is read from release.yml's own build steps rather than
    typed here, so a fifth published image fails these tests until the scan
    builds and scans it too.
    """

    def test_the_release_reader_finds_the_published_images(self):
        """A positive control: if release.yml changes shape so that the reader
        finds nothing, the comparison below would pass vacuously."""
        images = _release_images()
        assert len(images) == 4, images
        files = {key[0] for key in images}
        assert files == {"backend/Dockerfile", "frontend/Dockerfile"}, images

    @pytest.mark.regression
    def test_the_scan_builds_every_image_release_publishes(self):
        scanned = _built_images(_workflow(), ["container-security"])
        missing = sorted(set(_release_images()) - set(scanned), key=str)
        assert not missing, (
            "release.yml publishes images that security-scan.yml's "
            "container-security job never builds, so Trivy never scans them: "
            f"{missing}"
        )

    @pytest.mark.regression
    def test_trivy_scans_every_image_the_job_builds(self):
        """Each built tag must appear literally in the scan script: a tag
        assembled at run time (`...:scan-$target`) cannot be checked here."""
        script = _script("container-security", "trivy image")
        built = _built_images(_workflow(), ["container-security"])
        assert len(set(built.values())) == len(built), built
        for key, tag in built.items():
            assert tag and tag in script, (
                f"container-security builds {tag or key} and trivy never scans it"
            )

    def test_the_image_scan_blocks(self):
        """One policy for every image: HIGH/CRITICAL with a fix fails."""
        job = _workflow()["jobs"]["container-security"]
        (step,) = [s for s in job["steps"] if "trivy image" in str(s.get("run", ""))]
        script = str(step["run"])
        for flag in ("--severity HIGH,CRITICAL", "--ignore-unfixed", "--exit-code 1"):
            assert flag in script, f"trivy image runs without {flag}"
        assert 'exit "$failed"' in script
        assert not step.get("continue-on-error"), "the image scan does not block"
