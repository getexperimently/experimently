"""The docs no longer say the dashboard is undeployed, or that prod reuses staging's image.

Two families of sentence were true once and are false on main:

* **"The dashboard is not yet deployed by the CDK."** False since #145: the
  Fargate stack creates the dashboard's own ECS service
  (`infrastructure/cdk/stacks/dashboard_service.py`) on
  `experimentation-platform/web:bootstrap`, and the HTTPS listener sends
  `/api/*`, `/health`, `/health/*` and `/metrics` to the API and everything
  else to the dashboard (`API_PATH_RULES` in `fargate_service_stack.py`).
  What is still missing is the Deploy workflow rolling each release onto it
  (#69); the pages say that, and this test does not forbid it.
* **"Staging and prod run the same bytes."** False when they are separate
  AWS accounts, each with its own ECR (#167): prod builds the release itself
  from the tag. An image is reused only by a repeat deploy into the same
  account.

This is a sweep, not a proof: it forbids the phrasings that were removed (and
close variants), so a page copied from an old revision, or a sentence restored
by a bad merge, fails here with the file and line. A new wording of the same
false claim is not caught; review is.

Reads only files; no git, so it runs the same in `scripts/core_build.sh`'s
copy, which has no `.git`. It is in the docs-only gate's "Docs content tests"
through its directory, `backend/tests/unit/docs/`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS = REPO_ROOT / "docs"
README = REPO_ROOT / "README.md"
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"

#: (pattern, why it is false). Matched case-insensitively against each file
#: with its whitespace collapsed and `_DROP` removed, so a claim that wraps
#: across lines, or sits inside bold, code or a comment, is still found.
STALE_DASHBOARD: Tuple[Tuple[str, str], ...] = (
    (r"dashboard is not (yet )?deployed", "the CDK runs the dashboard service"),
    (r"not (yet )?deployed by (the )?cdk", "the CDK runs the dashboard service"),
    (
        r"(cdk|stack) does not deploy [^.]{0,40}\bdashboard",
        "the CDK runs the dashboard service",
    ),
    (r"nothing (in it )?hosts the dashboard", "the dashboard's ECS service hosts it"),
    (r"no stack (builds|hosts|serves)", "the Fargate stack serves the dashboard"),
    (r"api container alone", "the Fargate stack runs two services"),
    (r"in front of the api only", "the ALB fronts the API and the dashboard"),
    (
        r"runs the api behind an application load balancer and nothing else",
        "it also runs the dashboard",
    ),
    (r"no dashboard for an app\.? subdomain", "the ALB serves the dashboard"),
    (r"app dashboard: not provided", "the ALB serves the dashboard"),
)

STALE_SAME_BYTES: Tuple[Tuple[str, str], ...] = (
    (r"same bytes", "staging and prod are separate accounts; prod rebuilds (#167)"),
    (r"another environment", "reuse is only within one account (#167)"),
)


#: Dropped before matching: emphasis, code spans, and the `#` of a YAML or
#: shell comment, so "same\n      # bytes" in a workflow still reads "same bytes".
_DROP = frozenset("*`#")


def _normalise(text: str) -> Tuple[str, List[int]]:
    """Lower-case, markup dropped, whitespace runs collapsed to one space.

    Returns the flattened text and, for each of its characters, the 1-based
    line of the raw character it came from, so a hit is reported by line.
    """
    flat: List[str] = []
    lines: List[int] = []
    line = 1
    for char in text:
        if char == "\n":
            line += 1
        if char in _DROP:
            continue
        if char.isspace():
            if flat and flat[-1] == " ":
                continue
            char = " "
        flat.append(char.lower())
        lines.append(line)
    return "".join(flat), lines


def _hits(path: Path, rules: Tuple[Tuple[str, str], ...]) -> Iterator[str]:
    flat, lines = _normalise(path.read_text(encoding="utf-8", errors="replace"))
    rel = path.relative_to(REPO_ROOT).as_posix()
    for pattern, why in rules:
        for match in re.finditer(pattern, flat):
            yield f"{rel}:{lines[match.start()]}: {match.group(0)!r} -- {why}"


def _doc_files() -> List[Path]:
    files = sorted(DOCS.rglob("*.md"))
    assert len(files) > 50, f"found {len(files)} pages under docs/: the scan is broken"
    return [README, *files]


def test_no_page_says_the_dashboard_is_not_deployed():
    hits = [hit for path in _doc_files() for hit in _hits(path, STALE_DASHBOARD)]
    assert not hits, (
        "these say the CDK does not deploy the dashboard; it has run the dashboard "
        "as its own ECS service since #145 (on web:bootstrap; per-release rollout "
        "is #69):\n" + "\n".join(hits)
    )


def test_no_page_or_deploy_comment_says_prod_reuses_stagings_image():
    paths = [*_doc_files()]
    if DEPLOY_WORKFLOW.is_file():
        paths.append(DEPLOY_WORKFLOW)
    hits = [hit for path in paths for hit in _hits(path, STALE_SAME_BYTES)]
    assert not hits, (
        "these say another environment's image is reused; each account builds "
        "the release from the tag, and only a repeat deploy into the same "
        "account reuses its tag (#167):\n" + "\n".join(hits)
    )


@pytest.mark.parametrize(
    "text, rules",
    [
        ("**The dashboard is not yet deployed by the CDK** (#69).", STALE_DASHBOARD),
        (
            "The CDK does not deploy a WAF, CloudFront or the dashboard today",
            STALE_DASHBOARD,
        ),
        ("the Fargate stack runs the API\n  container alone", STALE_DASHBOARD),
        ("reused, not rebuilt, when another\nenvironment deploys", STALE_SAME_BYTES),
        (
            "# rebuilt, so staging and prod run the same\n      # bytes.",
            STALE_SAME_BYTES,
        ),
    ],
)
def test_the_sweep_catches_the_removed_wording(text, rules):
    """Each family catches a line of the wording it replaced, even wrapped."""
    flat, _ = _normalise(text)
    assert any(re.search(pattern, flat) for pattern, _ in rules), (
        f"no rule matches the removed wording {text!r}"
    )
