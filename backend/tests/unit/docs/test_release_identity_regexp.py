"""The release notes verify a release with the identity the page uses.

``docs/self-hosting/releases.md`` checks a release's signature with an
identity regexp that names ``release.yml``, run from ``main`` or from a ``v``
tag. The notes ``release.yml`` writes into every GitHub release, and the
comment beside its signing step, used to print a looser one that accepted any
workflow of the repository. A reader who verifies from the notes must get the
same check as one who verifies from the page.

So this renders the "Release notes" step with bash, as the workflow runs it,
and compares every ``--certificate-identity-regexp`` in the notes, and the one
in the signing comment, with the page's ``IDENTITY``. It also holds the
regexp to the release paths it must accept and the identities it must refuse.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[4]
PAGE = ROOT / "docs" / "self-hosting" / "releases.md"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
REPOSITORY = "getexperimently/experimently"

_PAGE_IDENTITY = re.compile(r"^IDENTITY='(?P<regexp>[^']+)'$", re.MULTILINE)
_FLAG = re.compile(r"--certificate-identity-regexp '(?P<regexp>[^']+)'")

if not RELEASE.is_file():
    pytest.skip("this tree has no .github/workflows", allow_module_level=True)


def page_identity() -> str:
    found = _PAGE_IDENTITY.findall(PAGE.read_text(encoding="utf-8"))
    assert len(found) == 1, f"expected one IDENTITY= line in {PAGE.name}, found {found}"
    return found[0]


def rendered_notes(tmp_path: Path) -> str:
    workflow = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    step = next(
        s
        for s in workflow["jobs"]["publish"]["steps"]
        if s.get("name") == "Release notes"
    )
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "IMAGE": f"ghcr.io/{REPOSITORY}",
        "WEB_IMAGE": f"ghcr.io/{REPOSITORY}-web",
        "VERSION": "1.2.3",
        "REPOSITORY": REPOSITORY,
    }
    env.update({k: str(v) for k, v in (workflow.get("env") or {}).items()})
    result = subprocess.run(
        [shutil.which("bash") or "bash", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return (tmp_path / "notes.md").read_text(encoding="utf-8")


def test_the_release_notes_print_the_pages_identity(tmp_path: Path) -> None:
    notes = rendered_notes(tmp_path)
    printed = _FLAG.findall(notes)
    assert len(printed) == 2, f"verify and verify-attestation, found {printed}\n{notes}"
    assert printed == [page_identity()] * 2, (
        f"the release notes verify with {printed}; {PAGE.name} with {page_identity()!r}"
    )


def test_the_signing_comment_prints_the_pages_identity() -> None:
    text = RELEASE.read_text(encoding="utf-8")
    comments = [
        m.group("regexp")
        for line in text.splitlines()
        if line.lstrip().startswith("#")
        for m in _FLAG.finditer(line)
    ]
    assert len(comments) == 1, comments
    assert comments[0].replace("<owner>/<repo>", REPOSITORY) == page_identity()


def test_no_other_identity_regexp_in_the_workflow() -> None:
    """A third copy would be one this test does not compare."""
    text = RELEASE.read_text(encoding="utf-8")
    assert text.count("--certificate-identity-regexp") == 3


@pytest.mark.parametrize(
    "subject",
    [
        "release.yml@refs/heads/main",
        "release.yml@refs/tags/v0.26.3",
        "release.yml@refs/tags/v1.2.0-rc.1",
    ],
    ids=["release-please or a re-run from main", "a tag", "a pre-release tag"],
)
def test_the_identity_accepts_every_release_path(subject: str) -> None:
    identity = page_identity()
    assert re.search(
        identity, f"https://github.com/{REPOSITORY}/.github/workflows/{subject}"
    )


@pytest.mark.parametrize(
    "san",
    [
        f"https://github.com/{REPOSITORY}/.github/workflows/ci.yml@refs/heads/main",
        f"https://github.com/{REPOSITORY}/.github/workflows/release.yml@refs/heads/feature",
        f"https://github.com/{REPOSITORY}/.github/workflows/release.yml@refs/heads/main-x",
        f"https://github.com/{REPOSITORY}/.github/workflows/release.yml@refs/pull/1/merge",
        "https://github.com/someone/experimently/.github/workflows/release.yml@refs/heads/main",
        f"https://githubXcom/{REPOSITORY}/.github/workflows/release.yml@refs/heads/main",
    ],
    ids=[
        "another workflow",
        "another branch",
        "a branch named like main",
        "a pull request",
        "another repository",
        "an unescaped dot",
    ],
)
def test_the_identity_refuses_anything_else(san: str) -> None:
    assert not re.search(page_identity(), san)
