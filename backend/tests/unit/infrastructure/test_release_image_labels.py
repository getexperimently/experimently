"""The release's image-label gate, against the shapes a registry really returns.

``.github/workflows/release.yml`` runs ``scripts/check_image_labels.py`` on
every image it has just pushed, before signing it.  The labels are set from a
``--build-arg``, which means a renamed ``ARG`` in either Dockerfile silently
produces a whole release labelled ``0.0.0+unknown`` -- the exact shape of
defect this repository keeps finding: a check that passes for the wrong reason,
or none at all.

So the gate itself is tested, and tested by *breaking* it.  The fixtures below
are trimmed from real ``docker buildx imagetools inspect --format
'{{ json .Image }}'`` output captured against a registry: a single-platform
image (one config object at the top level) and a two-platform one built with
``--provenance=mode=max --sbom=true`` (a map keyed by platform -- and note that
the attestation manifests riding in the same index do *not* appear here, which
is why the script needs no special case for them).

Cheap text reads, no Docker: these run in the ordinary unit job.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
CHECKER = ROOT / "scripts" / "check_image_labels.py"

pytestmark = pytest.mark.unit


def labels(version: str = "0.1.0", profile: str = "core") -> dict:
    return {
        "org.opencontainers.image.title": "Experimently API",
        "org.opencontainers.image.licenses": "Apache-2.0",
        "org.opencontainers.image.version": version,
        "io.experimently.profile": profile,
    }


def single_platform(**kwargs) -> dict:
    """One image config at the top level, as a single-platform manifest gives."""
    return {
        "created": "2026-09-18T00:00:00Z",
        "architecture": "arm64",
        "os": "linux",
        "config": {"Labels": labels(**kwargs)},
        "rootfs": {"type": "layers", "diff_ids": []},
    }


def multi_platform(second: dict | None = None, **kwargs) -> dict:
    """A map keyed by platform, as a manifest list gives."""
    first = dict(single_platform(**kwargs), architecture="amd64")
    return {
        "linux/amd64": first,
        "linux/arm64": second if second is not None else single_platform(**kwargs),
    }


def run(payload: dict, tmp_path: Path, version: str = "0.1.0", profile: str = "core"):
    path = tmp_path / "image.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--file",
            str(path),
            "--version",
            version,
            "--profile",
            profile,
        ],
        capture_output=True,
        text=True,
    )


def test_single_platform_image_passes(tmp_path: Path) -> None:
    result = run(single_platform(), tmp_path)
    assert result.returncode == 0, result.stderr
    assert "1 platform config(s)" in result.stdout


def test_multi_platform_image_passes(tmp_path: Path) -> None:
    result = run(multi_platform(), tmp_path)
    assert result.returncode == 0, result.stderr
    assert "2 platform config(s)" in result.stdout


def test_image_built_without_the_version_arg_is_refused(tmp_path: Path) -> None:
    """The defect the gate exists for: the Dockerfile's placeholder default."""
    result = run(single_platform(version="0.0.0+unknown"), tmp_path)
    assert result.returncode != 0
    assert "0.0.0+unknown" in result.stderr


def test_one_bad_platform_out_of_two_is_refused(tmp_path: Path) -> None:
    """A per-platform check, not a first-one-wins check.

    An arm64 variant built without the argument while amd64 carries it is the
    failure a "read the first config" implementation would wave through.
    """
    payload = multi_platform(second=single_platform(version="0.0.0+unknown"))
    result = run(payload, tmp_path)
    assert result.returncode != 0
    assert "linux/arm64" in result.stderr


def test_wrong_profile_is_refused(tmp_path: Path) -> None:
    """A `full` tag must not be a `core` image: the profile decides what ships."""
    result = run(single_platform(profile="core"), tmp_path, profile="full")
    assert result.returncode != 0
    assert "io.experimently.profile" in result.stderr


def test_missing_licence_label_is_refused(tmp_path: Path) -> None:
    payload = single_platform()
    del payload["config"]["Labels"]["org.opencontainers.image.licenses"]
    result = run(payload, tmp_path)
    assert result.returncode != 0
    assert "licenses" in result.stderr


def test_no_labels_at_all_is_refused(tmp_path: Path) -> None:
    payload = single_platform()
    payload["config"] = {}
    result = run(payload, tmp_path)
    assert result.returncode != 0


def test_confirming_the_placeholder_version_is_refused(tmp_path: Path) -> None:
    """Asking the gate to bless 0.0.0+unknown must fail, not tautologically pass."""
    result = run(
        single_platform(version="0.0.0+unknown"), tmp_path, version="0.0.0+unknown"
    )
    assert result.returncode != 0
    assert "placeholder" in result.stderr


def test_unparseable_payload_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "image.json"
    path.write_text("[]", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--file",
            str(path),
            "--version",
            "0.1.0",
            "--profile",
            "core",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_both_dockerfiles_define_the_version_arg_the_workflow_passes() -> None:
    """The other half of the gate: the ARG the label reads has to exist.

    ``docker build`` warns about an unknown ``--build-arg`` and carries on, so
    a renamed ARG produces a green build and an unlabelled image; the registry
    check above catches it after the push, and this catches it in review.
    """
    for dockerfile in ("backend/Dockerfile", "frontend/Dockerfile"):
        text = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert "ARG VERSION=0.0.0+unknown" in text, (
            f"{dockerfile} must declare `ARG VERSION` with the placeholder default; "
            "release.yml passes --build-arg VERSION and the label reads it"
        )
        assert 'org.opencontainers.image.version="${VERSION}"' in text, (
            f"{dockerfile} must label the image from that ARG"
        )
