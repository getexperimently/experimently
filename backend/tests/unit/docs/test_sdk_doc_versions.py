"""The SDK version a page quotes is the version in that SDK's manifest.

docs/sdk/local-evaluation.md and docs/sdk/javascript.md said the JavaScript
and Python SDKs were "1.1" while both manifests said 0.1.0 (#784). This reads
every place docs/sdk/*.md and docs/sdk-guide.md quote a package with a
version -- `` `@getexperimently/js-sdk` (v0.1.0) ``, a tarball name such as
``getexperimently-js-sdk-0.1.0.tgz`` -- and compares it with the manifest.

A quoted version may be shorter than the manifest's ("v1.1" for 1.1.0), but
every part it gives must match. The plain name ``experimently`` is shared by
the Python, Ruby, Elixir and Flutter packages, so it is checked only on the
pages about the Python SDK.

Reads files only: no git and no `modules` import, so it runs the same in
`scripts/core_build.sh`'s copy.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
SDK_DIR = REPO_ROOT / "sdk"
DOCS = REPO_ROOT / "docs"

#: npm package -> its manifest directory under sdk/.
NPM = ("js", "react", "react-native", "openfeature", "edge")
#: Python distribution -> its manifest directory under sdk/.
PYPI = ("python", "openfeature-python")
#: Pages on which the bare name `experimently` means the Python SDK.
PYTHON_PAGES = {"python.md", "local-evaluation.md"}

VERSION = r"(\d+(?:\.\d+){1,2})"
#: `` `name` `` then at most a "(v" before the version; whitespace already folded.
QUOTED = re.compile(
    r"`(@getexperimently/[A-Za-z0-9_-]+|experimently(?:-openfeature)?)` \(?v?" + VERSION
)
TARBALL = re.compile(r"getexperimently-([A-Za-z0-9-]+?)-" + r"(\d+\.\d+\.\d+)\.tgz")


def manifest_versions() -> Dict[str, str]:
    versions: Dict[str, str] = {}
    for name in NPM:
        data = json.loads((SDK_DIR / name / "package.json").read_text(encoding="utf-8"))
        versions[data["name"]] = data["version"]
    for name in PYPI:
        data = tomllib.loads(
            (SDK_DIR / name / "pyproject.toml").read_text(encoding="utf-8")
        )
        versions[data["project"]["name"]] = data["project"]["version"]
    return versions


def quotes(page: Path) -> List[Tuple[str, str]]:
    """Every (package, quoted version) on ``page``, with a line break allowed anywhere."""
    text = re.sub(r"\s+", " ", page.read_text(encoding="utf-8"))
    found = [(m.group(1), m.group(2)) for m in QUOTED.finditer(text)]
    found += [
        (f"@getexperimently/{m.group(1)}", m.group(2)) for m in TARBALL.finditer(text)
    ]
    if page.name not in PYTHON_PAGES:
        found = [(pkg, ver) for pkg, ver in found if pkg != "experimently"]
    return found


PAGES = sorted((DOCS / "sdk").glob("*.md")) + [DOCS / "sdk-guide.md"]


def test_the_scan_finds_the_quotes_it_exists_for():
    # A pattern that matched nothing would pass every page below.
    found = {q for page in PAGES for q in quotes(page)}
    names = {pkg for pkg, _ in found}
    assert {
        "@getexperimently/js-sdk",
        "@getexperimently/react-sdk",
        "experimently",
    } <= names
    on_local = {pkg for pkg, _ in quotes(DOCS / "sdk" / "local-evaluation.md")}
    assert {"@getexperimently/js-sdk", "experimently"} <= on_local


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_quoted_sdk_versions_match_the_manifests(page):
    versions = manifest_versions()
    wrong = []
    for pkg, quoted in quotes(page):
        actual = versions.get(pkg)
        if actual is None:
            wrong.append(f"{pkg} {quoted}: no manifest under sdk/ declares {pkg}")
        elif actual.split(".")[: len(quoted.split("."))] != quoted.split("."):
            wrong.append(f"{pkg} is quoted as {quoted}; the manifest says {actual}")
    assert not wrong, f"{page.relative_to(REPO_ROOT)}:\n" + "\n".join(wrong)
