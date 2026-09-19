#!/usr/bin/env python3
"""Fail when the places that carry the version stop agreeing.

``VERSION`` at the repository root is the one source (see
``backend/app/core/version.py``).  Everything else quotes it, and every one of
them can drift *silently*:

* ``.release-please-manifest.json`` -- release-please's own idea of where the
  tree is.  If it and ``VERSION`` disagree, the next release PR proposes a
  version nobody expects, or none at all.
* the built distribution metadata -- ``pyproject.toml`` reads ``VERSION``
  through setuptools' ``dynamic`` version, and a build that cannot find the
  file **does not fail**: it warns and emits ``0.0.0``.  Verified against
  setuptools 80: a tree with no ``VERSION`` builds a wheel called
  ``experimently-platform-0.0.0``, with no error anywhere.
  Note what this check does *not* cover: it reads the source tree, where
  ``VERSION`` always is, so it says nothing about whether the published sdist
  carries the file.  That is a separate invariant, pinned separately by
  ``backend/tests/smoke/test_version_sources.py`` -- which is where it belongs,
  because setuptools includes the file on its own and no edit to
  ``MANIFEST.in`` could be found that stops it, so a check here could only ever
  pass.
* ``settings.VERSION`` -- what ``/health`` and ``GET /api/v1/modules`` report,
  and so what an operator reads off a running deployment.
* the git tag, when run with ``--expect`` (the release workflow passes the tag
  it is building, so a tag that does not match the tree never becomes images).

Run by ``backend/tests/smoke/test_version_sources.py`` -- so every pull request
-- and by ``.github/workflows/release.yml``, with ``--expect``, before anything
is pushed anywhere.  Not by ``make lint``: that target and the ``lint`` CI job
are kept identical, and the CI job installs ruff, import-linter and reuse, not
the backend closure this needs.

Usage::

    python scripts/check_version_sources.py              # the tree agrees
    python scripts/check_version_sources.py --expect 1.2.3   # ...and is 1.2.3
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]

#: A version that means "nobody set one".  ``0.0.0`` is what setuptools emits
#: when the dynamic version file is missing and ``0.0.0+unknown`` is
#: ``version.get_version()``'s last resort; neither may ever be released.
PLACEHOLDER_VERSIONS = frozenset({"0.0.0", "0.0.0+unknown", ""})

#: The spelling ``VERSION`` itself must use: SemVer, because release-please
#: writes it and the git tag and the image tag quote it verbatim
#: (``v0.1.0-rc.1``, ``ghcr.io/...:core-0.1.0-rc.1``).  Deliberately narrow --
#: exotic spellings are a problem, not a feature.
#:
#: PyPI is the exception, and the reason comparisons below are made on parsed
#: versions rather than strings: setuptools normalises to PEP 440, so the very
#: same tree whose ``VERSION`` says ``0.1.0-rc.1`` builds a wheel whose
#: metadata says ``0.1.0rc1``.  Both are correct for their ecosystem; a string
#: comparison would have called the rehearsal tags in the launch plan a drift.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$")


def read_version_file() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def read_release_please_manifest() -> str:
    manifest = json.loads(
        (ROOT / ".release-please-manifest.json").read_text(encoding="utf-8")
    )
    # One package, the repository root; release-please keys it by path.
    return str(manifest["."])


def read_distribution_metadata_version() -> str:
    """The version a build of this tree would stamp on the wheel.

    Asks the build backend rather than re-reading ``VERSION``, which would
    prove nothing: the point is to catch a ``pyproject.toml`` that has stopped
    reading the file.  ``prepare_metadata_for_build_wheel`` is what ``pip`` and
    ``build`` call, it is cheap (no wheel is built), and setuptools is already
    present wherever this runs.

    The directory is globbed rather than parsed out of the call's return value:
    setuptools writes its own progress to stdout, so the last line of a
    subprocess is not reliably the answer.
    """
    with tempfile.TemporaryDirectory() as tmp:
        code = (
            "import setuptools.build_meta as b;"
            f"b.prepare_metadata_for_build_wheel({tmp!r})"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # The backend's own message, not a bare CalledProcessError. It is
            # usually the useful one -- an ambient setuptools older than
            # pyproject's `requires = ["setuptools>=77"]` floor, for instance,
            # reports a schema error about `project.license` that reads like a
            # broken pyproject until you see it.
            raise AssertionError(
                "the build backend could not produce metadata:\n"
                + (result.stderr or result.stdout).strip()[-2000:]
            )
        dist_infos = sorted(Path(tmp).glob("*.dist-info"))
        if len(dist_infos) != 1:
            raise AssertionError(
                f"expected exactly one .dist-info, got {[d.name for d in dist_infos]}"
            )
        for line in (
            (dist_infos[0] / "METADATA").read_text(encoding="utf-8").splitlines()
        ):
            if line.startswith("Version:"):
                return line.split(":", 1)[1].strip()
    raise AssertionError("the build backend produced METADATA with no Version field")


def read_settings_version() -> str:
    """What a running API reports.

    Imported in a subprocess: importing ``backend.app.core.config`` pulls in
    pydantic-settings and reads the environment, and this script is run by
    ``make lint`` where neither is wanted in-process.
    """
    code = "from backend.app.core.config import settings; print(settings.VERSION)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect",
        metavar="X.Y.Z",
        help=(
            "Also require the tree to be at this version. The release workflow "
            "passes the tag it is building, with any leading 'v' stripped."
        ),
    )
    args = parser.parse_args()

    sources = {
        "VERSION": read_version_file,
        ".release-please-manifest.json": read_release_please_manifest,
        "built distribution metadata": read_distribution_metadata_version,
        "settings.VERSION": read_settings_version,
    }

    found: dict[str, str] = {}
    failures: list[str] = []
    for name, reader in sources.items():
        try:
            found[name] = reader()
        except Exception as exc:
            failures.append(
                f"{name}: could not be read ({exc.__class__.__name__}: {exc})"
            )

    for name, value in found.items():
        print(f"  {name:34} {value}")

    if failures:
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return 1

    parsed: dict[str, Version] = {}
    for name, value in found.items():
        try:
            parsed[name] = Version(value)
        except InvalidVersion:
            print(
                f"error: {name} reports {value!r}, which is not a version at all.",
                file=sys.stderr,
            )
            return 1

    if len(set(parsed.values())) != 1:
        print("error: the version sources disagree:", file=sys.stderr)
        for name, value in sorted(found.items()):
            print(f"  {name}: {value}  (normalised: {parsed[name]})", file=sys.stderr)
        return 1

    # The canonical string is VERSION's own, not the normalised one: it is what
    # the tag and the image tag have to be spelled as.
    version = found["VERSION"]

    if (
        version in PLACEHOLDER_VERSIONS
        or str(parsed["VERSION"]) in PLACEHOLDER_VERSIONS
    ):
        print(
            f"error: the tree reports the placeholder version {version!r}. "
            "A build that cannot read VERSION produces exactly this, silently.",
            file=sys.stderr,
        )
        return 1

    if not VERSION_RE.match(version):
        print(
            f"error: {version!r} is not X.Y.Z or X.Y.Z-(alpha|beta|rc).N. "
            "The git tag, the image tag and the PyPI version are all this "
            "string, so it has to be spellable in all three.",
            file=sys.stderr,
        )
        return 1

    if args.expect is not None:
        expected = args.expect.lstrip("v")
        try:
            expected_parsed = Version(expected)
        except InvalidVersion:
            print(f"error: --expect {args.expect!r} is not a version.", file=sys.stderr)
            return 1
        if expected_parsed != parsed["VERSION"]:
            print(
                f"error: asked to release {expected!r} but the tree is at {version!r}. "
                "The tag and the tree must be the same commit's version.",
                file=sys.stderr,
            )
            return 1

    print(f"version sources agree: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
