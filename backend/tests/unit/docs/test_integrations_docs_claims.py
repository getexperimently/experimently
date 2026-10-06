"""The integration pages describe the integrations API the code serves.

The GitHub and Salesforce pages, the FAQ and the endpoint list described an
integration the API does not have, and a webhook that answers differently from
what they said. On main (`modules/backend/app/api/v1/endpoints/integrations.py`,
`modules/backend/app/schemas/integration.py`):

* An integration is addressed by its **type**, in lower case:
  `/api/v1/integrations/{integration_type}` with `jira`, `salesforce` or
  `github`. There is no id in a path, and `integration_type` in a body is lower
  case too (`"GITHUB"` is a 422).
* The body field is `encrypted_config`. A `"config"` field is not an error: it is
  ignored, so an example that sent one answered 200 and changed nothing.
* Reading is ADMIN or DEVELOPER; creating, updating and deleting is ADMIN.
* A webhook answers `{"status": "received"}` for an authenticated delivery, never
  `{"processed": true}`. Every refused delivery is one 401 (a wrong or missing
  signature included); a 400 only follows a successful authentication.

This test forbids the phrasings that were removed and requires the pages to say
what is true. It is a sweep, not a proof: a new wording of the same claim is not
caught; review is. Each forbidden pattern also has a sample it must match, so a
pattern that has silently stopped matching fails here instead of reporting
"clean" for ever. When the API changes, change the docs and this test together.

Reads only files; no git and no `modules` import, so it runs the same in
`scripts/core_build.sh`'s copy (no `.git`, no `modules/`). It is in the
docs-only gate's "Docs content tests" through its directory,
`backend/tests/unit/docs/`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS = REPO_ROOT / "docs"

#: Pages the sweep must read, named, so a wrong root fails instead of passing.
SWEEP_FLOOR = (
    "docs/api/endpoints.md",
    "docs/api/integrations.md",
    "docs/getting-started/faq.md",
    "docs/integrations/github.md",
    "docs/integrations/salesforce.md",
)

#: Where a rule applies, when it is not the whole of `docs/`.
INTEGRATION_PAGES = ("docs/integrations/", "docs/api/integrations.md")

#: (pattern, why it is wrong, the path prefixes it is limited to or None, a sample
#: of the removed text the pattern must match).
Rule = Tuple[str, str, Optional[Tuple[str, ...]], str]

STALE: Tuple[Rule, ...] = (
    (
        r"integrations/\{id\}",
        "an integration is addressed by its type, `/api/v1/integrations/{integration_type}`",
        None,
        "GET /api/v1/integrations/{id}",
    ),
    (
        r"int-uuid",
        "no route takes an id for an integration; the path parameter is the type",
        None,
        "curl -X PUT http://localhost:8000/api/v1/integrations/int-uuid-here",
    ),
    (
        r"\"processed\"\s*:\s*true",
        'a webhook answers {"status": "received"}',
        None,
        '{"processed": true}',
    ),
    (
        r"\"integration_type\"\s*:\s*\"(?:JIRA|SALESFORCE|GITHUB)\"",
        "the type is lower case (`jira`, `salesforce`, `github`); upper case is a 422",
        None,
        '"integration_type": "GITHUB",',
    ),
    (
        r"`JIRA`,\s*`SALESFORCE`,\s*`GITHUB`",
        "the `IntegrationType` values are lower case",
        None,
        "Supported `IntegrationType` values: `JIRA`, `SALESFORCE`, `GITHUB`.",
    ),
    (
        r"\"config\"\s*:",
        "the body field is `encrypted_config`; `config` is ignored, so the request does nothing",
        INTEGRATION_PAGES,
        '    "config": {',
    ),
    (
        r"/api/v1/integrations[^\n]*\((?:DEVELOPER|ANALYST)\+\)",
        "reading is ADMIN or DEVELOPER; creating, updating and deleting is ADMIN",
        None,
        "POST   /api/v1/integrations               - Create integration (DEVELOPER+)",
    ),
    (
        r"Create and manage experiments, feature flags, and integrations",
        "a DEVELOPER can read integrations but not change them",
        None,
        "| **DEVELOPER** | Create and manage experiments, feature flags, and integrations |",
    ),
    (
        r"Bad HMAC Signature|Missing Signature",
        "every refused webhook delivery is one 401; there is no separate 400 for a bad signature",
        ("docs/integrations/",),
        "### 400 Bad Request — Bad HMAC Signature",
    ),
    (
        r"Delete and recreate the integration with a consistent secret",
        "set the secret again with a PUT (the recipe in docs/api/integrations.md)",
        ("docs/integrations/",),
        "Delete and recreate the integration with a consistent secret.",
    ),
)

#: (page, text it must contain, why).
REQUIRED: Tuple[Tuple[str, str, str], ...] = (
    (
        "docs/integrations/github.md",
        '{"status": "received"}',
        "the webhook's success body",
    ),
    (
        "docs/integrations/github.md",
        "/api/v1/integrations/github",
        "the integration is addressed by its type",
    ),
    (
        "docs/integrations/github.md",
        '{"detail": "Webhook authentication failed"}',
        "the one body of every refused delivery",
    ),
    (
        "docs/integrations/salesforce.md",
        '{"status": "received"}',
        "the webhook's success body",
    ),
    (
        "docs/integrations/salesforce.md",
        "/api/v1/integrations/salesforce",
        "the integration is addressed by its type",
    ),
    (
        "docs/integrations/salesforce.md",
        "X-Experimently-Webhook-Secret",
        "how a Salesforce delivery authenticates; without it every delivery is a 401",
    ),
    (
        "docs/integrations/salesforce.md",
        "X-Hub-Signature-256",
        "the signed form a callout may use",
    ),
)


def _swept() -> List[Path]:
    files = sorted(DOCS.rglob("*.md"))
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in files}
    missing = [f for f in SWEEP_FLOOR if f not in rels]
    assert not missing, f"the sweep did not read {missing}: it is broken, not clean"
    return files


def _applies(rel: str, only: Optional[Tuple[str, ...]]) -> bool:
    return only is None or any(rel.startswith(prefix) for prefix in only)


def _hits(files: List[Path]) -> Iterator[str]:
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern, why, only, _sample in STALE:
            if not _applies(rel, only):
                continue
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                yield f"{rel}:{line}: {match.group(0)!r} -- {why}"


def test_the_sweep_reads_the_pages() -> None:
    assert len(_swept()) > len(SWEEP_FLOOR)


def test_no_page_describes_an_integration_the_api_does_not_have() -> None:
    hits = list(_hits(_swept()))
    assert not hits, "\n".join(hits)


@pytest.mark.parametrize(
    ("pattern", "sample", "only"),
    [(rule[0], rule[3], rule[2]) for rule in STALE],
    ids=[rule[0][:40] for rule in STALE],
)
def test_each_forbidden_pattern_matches_the_text_it_removed(
    pattern: str, sample: str, only: Optional[Tuple[str, ...]]
) -> None:
    assert re.search(pattern, sample), (
        f"{pattern!r} no longer matches the text it was written for"
    )
    if only is not None:
        # A scoped rule is scoped to pages that exist.
        for prefix in only:
            assert (REPO_ROOT / prefix).exists(), prefix


@pytest.mark.parametrize(
    ("page", "text", "why"), REQUIRED, ids=[f"{r[0]}::{r[1][:30]}" for r in REQUIRED]
)
def test_the_page_says_what_the_api_does(page: str, text: str, why: str) -> None:
    body = (REPO_ROOT / page).read_text(encoding="utf-8")
    assert text in body, f"{page} does not contain {text!r} ({why})"
