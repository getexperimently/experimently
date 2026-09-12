"""The feature-name contract: licence claims, `require_feature`, the dashboard.

Three places have to spell the same ten names and have no other way to agree:
`KNOWN_FEATURES` here, the `features` claim in a signed licence, and
`FEATURES` in `frontend/src/services/edition.ts`. A typo in any of them is
silent — the feature is simply never granted, and the dashboard hides a tab
the licence paid for. These tests are the only thing that would catch it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from backend.app.core.license import KNOWN_FEATURES, require_feature

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
EDITION_TS = REPO_ROOT / "frontend" / "src" / "services" / "edition.ts"
MANIFEST = REPO_ROOT / "ee-manifest.txt"


def _dashboard_features() -> list[str]:
    """The string values of the `FEATURES` object in edition.ts, in order."""
    source = EDITION_TS.read_text(encoding="utf-8")
    block = re.search(
        r"export const FEATURES = \{(.*?)\}\s*as const;", source, re.DOTALL
    )
    assert block, f"could not find `export const FEATURES` in {EDITION_TS}"
    return re.findall(r"^\s*[A-Z_]+:\s*'([^']+)'", block.group(1), re.MULTILINE)


@pytest.mark.regression
def test_the_dashboard_and_the_backend_name_the_same_features():
    assert _dashboard_features() == list(KNOWN_FEATURES)


def test_feature_names_are_lowercase_identifiers():
    """They travel in a JSON claim and in a URL-free JSON response; keep them
    boring so no layer has to escape or case-fold them."""
    for name in KNOWN_FEATURES:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name


def test_there_is_one_feature_per_enterprise_manifest_group():
    """`ee-manifest.txt` groups 1..10 are the Enterprise features; group 11 is
    the dashboard's implementation directory and 12 is the licence gate, which
    is CE. A group added without a feature name is a group nothing can gate."""
    headings = re.findall(r"^# (\d+)\. (.+)$", MANIFEST.read_text(), re.MULTILINE)
    numbered = [int(n) for n, _title in headings]
    assert numbered == sorted(numbered), f"manifest groups out of order: {numbered}"
    feature_groups = [n for n in numbered if n <= len(KNOWN_FEATURES)]
    assert len(feature_groups) == len(KNOWN_FEATURES), (
        f"{len(feature_groups)} feature groups in ee-manifest.txt but "
        f"{len(KNOWN_FEATURES)} names in KNOWN_FEATURES"
    )


def test_no_duplicate_names():
    assert len(set(KNOWN_FEATURES)) == len(KNOWN_FEATURES)


@pytest.mark.parametrize("name", KNOWN_FEATURES)
def test_require_feature_accepts_every_known_name(name):
    assert callable(require_feature(name))


def test_require_feature_refuses_an_unknown_name_at_build_time():
    """A typo must fail while the router is being built, not turn into a route
    that refuses every caller with a 403 nobody can explain."""
    with pytest.raises(ValueError) as excinfo:
        require_feature("workspace")  # singular; the real name is plural
    assert "unknown feature 'workspace'" in str(excinfo.value)
    assert "workspaces" in str(excinfo.value)
