"""The version is one number, and every place that quotes it agrees.

``VERSION`` at the repository root is the source (see
``backend/app/core/version.py``); ``pyproject.toml``, the release-please
manifest, the images and ``settings.VERSION`` all derive from it.  Each of
those derivations can break *silently*:

* a ``pyproject.toml`` that stops reading ``VERSION`` does not fail the build
  -- setuptools warns and stamps ``0.0.0`` on the wheel;
* a ``.release-please-manifest.json`` out of step with ``VERSION`` makes the
  next release PR propose a version nobody expects;
* an image built without ``--build-arg VERSION`` labels itself, correctly, as
  unreleased -- but only because that default is written down, and a default
  nobody asserts is one edit from becoming a stale literal.

So this is a gate, not a convention.  ``scripts/check_version_sources.py`` is
the implementation -- called here rather than reimplemented, so that the thing
``.github/workflows/release.yml`` runs before it pushes any image is the thing
these tests cover.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "scripts" / "check_version_sources.py"

pytestmark = pytest.mark.smoke


def run_checker(*args: str, tree: Path | None = None) -> subprocess.CompletedProcess:
    """Run the gate against *tree* (this repository by default).

    The script anchors on its own location -- ``parents[1]`` of
    ``__file__`` -- rather than on the working directory, so it cannot be
    aimed at the wrong tree by a stray ``cd``. Checking another tree therefore
    means running *that tree's copy* of the script, which is also what makes
    the tamper test below meaningful: it exercises the shipped file, not this
    one with a different argument.
    """
    root = tree or ROOT
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "check_version_sources.py"), *args],
        cwd=root,
        capture_output=True,
        text=True,
    )


def test_version_sources_agree() -> None:
    """The tree as committed passes its own gate."""
    result = run_checker()
    assert result.returncode == 0, (
        f"the version sources disagree:\n{result.stdout}\n{result.stderr}"
    )


def test_version_file_is_a_single_semver_line() -> None:
    """``VERSION`` holds the version and nothing else.

    Everything that reads it takes the whole file, stripped -- setuptools, the
    release workflow's ``$(cat VERSION)``, ``version.get_version()``.  A second
    line, or a trailing comment, reaches all three.
    """
    raw = (ROOT / "VERSION").read_text(encoding="utf-8")
    assert raw.endswith("\n"), "VERSION must end with a newline"
    lines = [line for line in raw.splitlines() if line.strip()]
    assert len(lines) == 1, f"VERSION must be one line, got {lines!r}"
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?", lines[0]), (
        f"{lines[0]!r} is not X.Y.Z or X.Y.Z-(alpha|beta|rc).N"
    )


def test_settings_version_is_the_version_file() -> None:
    """What ``/health`` and ``GET /api/v1/modules`` report is the file."""
    from backend.app.core.config import settings

    assert settings.VERSION == (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_release_please_manifest_tracks_the_version_file() -> None:
    manifest = json.loads(
        (ROOT / ".release-please-manifest.json").read_text(encoding="utf-8")
    )
    assert set(manifest) == {"."}, (
        "release-please-config.json declares one package, the repository root; "
        f"the manifest has {sorted(manifest)}"
    )
    assert manifest["."] == (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_release_please_config_writes_the_version_file() -> None:
    """release-please must be pointed at ``VERSION``.

    Its ``simple`` strategy defaults to ``version.txt``; left at the default it
    would create a *second* version file and leave ``VERSION`` -- and so the
    running API -- frozen at whatever it says today, while the tags moved on.
    """
    config = json.loads(
        (ROOT / "release-please-config.json").read_text(encoding="utf-8")
    )
    package = config["packages"]["."]
    assert package["release-type"] == "simple"
    assert package["version-file"] == "VERSION"


def test_checker_rejects_a_mismatched_expectation() -> None:
    """``--expect`` is what stops a tag from releasing a different tree.

    The tamper test for the release workflow's guard: ask the gate to confirm a
    version the tree is not at, and it must refuse.
    """
    result = run_checker("--expect", "99.99.99")
    assert result.returncode != 0, (
        "the gate accepted a version the tree is not at:\n" + result.stdout
    )
    assert "99.99.99" in result.stderr


def test_checker_rejects_a_drifting_manifest(tmp_path: Path) -> None:
    """Break the invariant in a copy of the tree; the gate must notice.

    A copy rather than the real tree: a gate test that edits the files it
    guards leaves the repository broken when it fails half way.

    The copy is assembled file by file rather than taken with ``git worktree``,
    which is how this was written first and which ``make core-build`` promptly
    failed -- the core build's tree is a deliberate *non*-repository copy, so
    ``git worktree add`` exits 128 there. Everything the checker reads is
    listed below (2.6 MB, well under a second); anything it needs that is not
    here shows up as the baseline assertion failing, not as a false pass.
    """
    copy = tmp_path / "tree"
    (copy / "scripts").mkdir(parents=True)

    for name in (
        "VERSION",
        ".release-please-manifest.json",
        "pyproject.toml",
        "MANIFEST.in",
        # setuptools reads both: `license-files` in pyproject names them, and a
        # missing one fails the metadata build rather than the comparison.
        "LICENSE",
        "NOTICE",
    ):
        shutil.copy2(ROOT / name, copy / name)
    shutil.copy2(
        ROOT / "scripts" / "check_version_sources.py",
        copy / "scripts" / "check_version_sources.py",
    )
    # settings.VERSION comes from importing backend.app.core.config, so the
    # package has to be importable from the copy's root.
    shutil.copytree(
        ROOT / "backend" / "app",
        copy / "backend" / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (copy / "backend" / "__init__.py").touch()

    baseline = run_checker(tree=copy)
    assert baseline.returncode == 0, (
        "the copy does not pass before tampering, so a failure after tampering "
        f"would prove nothing:\n{baseline.stdout}\n{baseline.stderr}"
    )

    (copy / ".release-please-manifest.json").write_text(
        json.dumps({".": "42.0.0"}, indent=2) + "\n", encoding="utf-8"
    )
    tampered = run_checker(tree=copy)
    assert tampered.returncode != 0, (
        "the gate passed with the manifest at 42.0.0 and VERSION elsewhere:\n"
        + tampered.stdout
    )
    assert "disagree" in tampered.stderr


def test_the_sdist_carries_the_version_file() -> None:
    """A published sdist must contain ``VERSION``, however it gets there.

    Without it a rebuild from the sdist emits ``0.0.0`` -- setuptools warns
    about the missing dynamic-version file and carries on -- so the package on
    PyPI would be misversioned with nothing failing.

    This is a *dependency's* behaviour, which is why it is pinned rather than
    trusted. Measured on setuptools 84: naming the file in
    ``[tool.setuptools.dynamic]`` is enough on its own, and neither removing
    ``include VERSION`` from ``MANIFEST.in`` nor writing ``exclude VERSION``
    there takes it back out. ``MANIFEST.in`` states the intent anyway; this
    test is what would notice a setuptools that stopped inferring it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import setuptools.build_meta as b; b.build_sdist({tmp!r})",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"building the sdist failed:\n{result.stderr}"
        archives = sorted(Path(tmp).glob("*.tar.gz"))
        assert len(archives) == 1, [a.name for a in archives]

        with tarfile.open(archives[0]) as archive:
            names = archive.getnames()
            # `<name>-<version>/VERSION` at the tarball root, not some deeper file.
            matches = [
                name
                for name in names
                if name.count("/") == 1 and name.endswith("/VERSION")
            ]
            assert matches, (
                f"{archives[0].name} does not contain VERSION; a build from this "
                "sdist would silently produce version 0.0.0"
            )
            member = archive.extractfile(matches[0])
            assert member is not None
            packaged = member.read().decode("utf-8").strip()

    assert packaged == (ROOT / "VERSION").read_text(encoding="utf-8").strip()


# The committed OpenAPI artefacts carry the version too -- `main.py` passes
# `settings.VERSION` to FastAPI, so `info.version` in every dump is it.
OPENAPI_FIXTURES = (
    "docs/api/openapi-v1.stable.json",
    "docs/api/openapi-v1.full.json",
    "frontend/src/tests/fixtures/openapi.json",
)


@pytest.mark.parametrize("fixture", OPENAPI_FIXTURES)
def test_committed_openapi_fixtures_carry_the_current_version(fixture: str) -> None:
    """The published API contract must not advertise a version nobody serves.

    These three sat at ``1.0.0`` while the running API reported ``0.1.0``:
    ``settings.VERSION`` and ``pyproject.toml`` had disagreed for a long time
    and unifying them moved one of the two. Nothing caught it --
    ``test_openapi_snapshot.py`` compares per-operation objects and the schemas
    they reference, not ``info`` -- so the stale number simply sat in published
    documentation, and a client generated from the checked-in spec would stamp
    it into its user agent.

    Regenerate with ``make openapi``.
    """
    spec = json.loads((ROOT / fixture).read_text(encoding="utf-8"))
    expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert spec["info"]["version"] == expected, (
        f"{fixture} advertises {spec['info']['version']}, but the tree is at "
        f"{expected}; run `make openapi` and commit the result"
    )
