"""What the deploy documentation promises an operator (UX section B, CHECK 6).

`mkdocs build --strict` checks links between documents; it cannot see a link
printed by a workflow's `::error::`. These do: every
`docs/<path>.md#<anchor>` a refusal sends an operator to must be a heading
that exists. And the runbook must be usable for either environment, without
the step that deleted a published release tag mid-incident.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DOCS = REPO_ROOT / "docs"
RUNBOOK = DOCS / "deployment" / "rollback-runbook.md"
GUIDE = DOCS / "deployment" / "deployment-guide.md"

pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="this tree has no docs")


def _slug(heading: str) -> str:
    """The anchor mkdocs' default `toc` extension gives a heading."""
    text = re.sub(r"[`*]", "", heading.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s]+", "-", text).strip("-")


def _anchors(path: Path) -> set[str]:
    return {
        _slug(m.group(1))
        for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", path.read_text(), re.M)
    }


@pytest.mark.regression
def test_every_doc_anchor_a_workflow_prints_exists():
    links = set()
    sources = [WORKFLOWS / n for n in ("deploy.yml", "rollback.yml", "db-migrate.yml")]
    # The scripts they run print links too (shift_traffic.py's wrong-route error).
    sources += sorted((REPO_ROOT / "scripts").glob("*.py"))
    sources += sorted((REPO_ROOT / "scripts").glob("*.sh"))
    for path in sources:
        text = path.read_text()
        links |= set(re.findall(r"(docs/[\w/.-]+\.md)#([\w-]+)", text))
    assert (
        "docs/deployment/deployment-guide.md",
        "the-api-route-and-the-primary-task-set-disagree",
    ) in links
    assert len(links) >= 2, f"found only {links}: the scan is not reading"
    for doc, anchor in sorted(links):
        path = REPO_ROOT / doc
        assert path.is_file(), f"a workflow links {doc}, which does not exist"
        assert anchor in _anchors(path), (
            f"a workflow sends operators to {doc}#{anchor}; that heading does "
            f"not exist (it has {sorted(_anchors(path))})"
        )


@pytest.mark.regression
def test_the_runbook_works_for_either_environment():
    text = RUNBOOK.read_text()
    assert "export ENV=prod   # or staging" in text
    fences = re.findall(r"```bash\n(.*?)```", text, re.S)
    code = "\n".join(fences)
    for literal in ("experimentation-prod", "backend-prod", "platform-prod", "-prod-"):
        assert literal not in code, f"a runbook command names {literal!r}"


@pytest.mark.regression
def test_the_runbook_shows_revisions_by_digest():
    """A deploy registers `backend@sha256:...`; a sample showing a version tag
    teaches the operator to look for something that is never there."""
    text = RUNBOOK.read_text()
    assert not re.search(r"backend:v\d", text), re.findall(r".*backend:v\d.*", text)
    assert "backend@sha256:" in text


@pytest.mark.regression
def test_the_runbook_does_not_delete_a_release_tag():
    text = RUNBOOK.read_text()
    assert ":refs/tags/" not in text
    assert "git tag -d" not in text


#: Where the deploy path is described to an operator.
CANARY_DOCS = [
    *sorted((DOCS / "deployment").glob("*.md")),
    DOCS / "self-hosting" / "cdk.md",
    DOCS / "integrations" / "aws.md",
]

#: Claims that the canary judges a release, or that CodeDeploy undoes a bad
#: one by itself. No alarm is attached to the deployment group (DECISIONS
#: T21), so each is false: a release that passes /health reaches 100%.
FALSE_CANARY_CLAIMS = [
    r"canary\s+is\s+the\s+gate",
    r"canary\s+(?:acts\s+as|is)\s+(?:a|the)\s+(?:gate|safety\s+net|check)",
    r"automatically\s+(?:shifts?|rolls?)\s+(?:traffic\s+)?back",
    r"shifts?\s+back\s+to\s+the\s+blue[^.\n]{0,40}automatically",
    r"configured\s+to\s+automatically\s+roll\s+back",
    r"no\s+manual\s+action\s+is\s+required",
    r"canary\b[^.\n]{0,40}\bwith\s+(?:CodeDeploy's\s+)?automatic\s+rollback",
]


@pytest.mark.regression
@pytest.mark.parametrize("path", CANARY_DOCS, ids=lambda p: p.name)
def test_no_document_says_the_canary_judges_a_release(path):
    """EM C5: the canary is timed only, and rollback.yml is the response."""
    text = " ".join(path.read_text().split())
    hits = [
        m.group(0)
        for pattern in FALSE_CANARY_CLAIMS
        for m in re.finditer(pattern, text, re.I)
    ]
    assert not hits, f"{path.relative_to(REPO_ROOT)} claims: {hits}"


@pytest.mark.regression
@pytest.mark.parametrize(
    "path", [DOCS / "deployment" / "README.md", GUIDE, RUNBOOK], ids=lambda p: p.name
)
def test_the_deploy_docs_say_the_canary_is_timed_only(path):
    text = " ".join(path.read_text().split())
    assert re.search(r"canary is timed only", text, re.I), path.name
    # EM C6: alarm-based rollback is the prod prerequisite, founder-waivable.
    if path != DOCS / "deployment" / "README.md":
        assert "issues/148" in text and "founder" in text, path.name


@pytest.mark.regression
@pytest.mark.parametrize(
    "path", [DOCS / "deployment" / "README.md", GUIDE], ids=lambda p: p.name
)
def test_the_docs_say_the_deploy_path_is_unproven(path):
    """EM B3b C8: until a real account has run it, the docs say so."""
    text = " ".join(path.read_text().split())
    assert "Not yet run against a real AWS account" in text, path.name
    assert "first staging deploy" in text, path.name


@pytest.mark.regression
def test_the_public_docs_do_not_name_internal_streams():
    """Operators read "the first staging deploy", not a plan's stream name."""
    hits = [
        f"{p.relative_to(REPO_ROOT)}:{n}"
        for p in sorted(DOCS.rglob("*.md"))
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if re.search(r"\bStream [A-Z]\b", line)
    ]
    assert not hits, hits


@pytest.mark.regression
@pytest.mark.parametrize("path", [GUIDE, RUNBOOK], ids=lambda p: p.name)
def test_the_fix_forward_cost_is_written_down(path):
    """EM B3b C5: within the hour, Rollback first; then its own hour."""
    text = " ".join(path.read_text().split())
    assert re.search(r"Rollback first", text), path.name
    assert "the next forward deploy is refused until it is no longer active" in text
    assert "expected behaviour" in text and "first staging deploy" in text


@pytest.mark.regression
def test_the_policy_upgrade_step_is_written_down():
    """PE B3b C6: roles made before the four new read actions need the policy."""
    text = " ".join((DOCS / "deployment" / "iam-permissions.md").read_text().split())
    assert "must have it re-applied" in text
    for action in (
        "cloudformation:DescribeStackResources",
        "elasticloadbalancing:DescribeListeners",
        "elasticloadbalancing:DescribeRules",
        "elasticloadbalancing:DescribeTargetHealth",
    ):
        assert action in text, action
    assert "Could not tell whether the API is serving" in text
    assert "Nothing shifts" in text


def test_the_guide_has_the_ordered_checklist():
    headings = [
        m.group(1) for m in re.finditer(r"^### (1\.\d) ", GUIDE.read_text(), re.M)
    ]
    assert headings == ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"], headings
    text = GUIDE.read_text()
    # Protection before any variable or secret (EM C12).
    assert text.index("required reviewer") < text.index("Variables `AWS_ACCOUNT_ID`")
    # The OIDC subject is decoded before the trust policy is written (PE C5).
    assert "Decode a\n  real token" in text or "decode a real token" in text.lower()


# --- the dashboard's deploy and rollback (#69) ---------------------------------


@pytest.mark.regression
def test_the_iam_doc_says_why_update_service_is_on_star_and_to_re_apply():
    """UpdateService on `*`, and why; and the re-apply before the first deploy."""
    text = " ".join((DOCS / "deployment" / "iam-permissions.md").read_text().split())
    assert "`ecs:UpdateService`" in text
    assert "on `*`" in text and "dominates" in text
    assert (
        "Roles created from a policy before the dashboard rollout lack "
        "`ecs:UpdateService`" in text
    )


@pytest.mark.regression
def test_the_guide_pins_the_dashboard_digest_and_the_runbook_covers_the_dashboard():
    assert "dashboard_image_tag=sha256:" in GUIDE.read_text()
    runbook = RUNBOOK.read_text()
    assert "deployments[?status=='PRIMARY']" in runbook
    assert "dashboard_task_definition_arn" in runbook
    assert "### The dashboard is the opposite case" in runbook
