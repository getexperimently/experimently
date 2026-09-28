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
    # The alarm copy's two runbook sections (#148, UX C5).
    assert (
        "docs/deployment/rollback-runbook.md",
        "an-alarm-rolled-the-api-back",
    ) in links
    assert (
        "docs/deployment/rollback-runbook.md",
        "fix-forward-while-an-alarm-is-firing",
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
    fences = re.findall(r"```bash\n(.*?)```", text, re.S)
    code = "\n".join(fences)
    # One line sets the environment, and the sentence before it names the
    # other one: a trailing `# or staging` on that line is a comment zsh runs.
    assert re.search(r"^export ENV=prod$", code, re.M), "no line sets ENV"
    assert "`export ENV=staging`" in text, "the prose does not name staging"
    for literal in ("experimentation-prod", "backend-prod", "platform-prod", "-prod-"):
        assert literal not in code, f"a runbook command names {literal!r}"


@pytest.mark.regression
def test_the_runbook_shows_revisions_by_digest():
    """A deploy registers `backend@sha256:...`; a sample showing a version tag
    teaches the operator to look for something that is never there."""
    text = RUNBOOK.read_text()
    assert not re.search(r"backend:v\d", text), re.findall(r".*backend:v\d.*", text)
    assert "backend@sha256:" in text


#: `ENV=prod   # or staging`: bash reads a comment; zsh (interactive_comments
#: off, its default) reads a command named `#` with ENV=prod in ITS
#: environment, so the shell's ENV keeps whatever it was -- mid-rollback, the
#: other environment. The choice goes in the sentence before the block.
_COMMENTED_ASSIGNMENT = re.compile(
    r"^[ \t]*(?:export[ \t]+)?[A-Za-z_]\w*=\S*[ \t]+#", re.M
)


@pytest.mark.regression
@pytest.mark.parametrize(
    "path", sorted((DOCS / "deployment").glob("*.md")), ids=lambda p: p.name
)
def test_no_deploy_command_assigns_a_variable_beside_a_comment(path):
    fences = re.findall(
        r"^```(?:bash|sh|shell|console)\n(.*?)^```", path.read_text(), re.S | re.M
    )
    assert fences, f"{path.name}: no shell fences read; the scan is not reading"
    hits = [m.group(0) for body in fences for m in _COMMENTED_ASSIGNMENT.finditer(body)]
    assert not hits, f"{path.name}: {hits}"


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
#: one by itself. Written when no alarm was attached to the deployment group
#: (DECISIONS T21), and all seven stay after #148 (PE condition 10): the
#: alarms watch the API's target 5xx only, while a deployment is active, so a
#: release that answers wrongly with a 2xx still reaches 100%, the dashboard is
#: never rolled back, and nothing acts after the hour. The docs say "rolls the
#: API back by itself", with those limits beside it.
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
    """EM C5: the canary judges nothing; since #148 the alarms act on target
    5xx only, in the deployment's window, and rollback.yml is the response
    to everything else."""
    text = " ".join(path.read_text().split())
    hits = [
        m.group(0)
        for pattern in FALSE_CANARY_CLAIMS
        for m in re.finditer(pattern, text, re.I)
    ]
    assert not hits, f"{path.relative_to(REPO_ROOT)} claims: {hits}"


def test_all_seven_false_canary_claims_are_kept():
    """PE condition 10: #148 inverts the timed-only wording and drops no ban."""
    assert len(FALSE_CANARY_CLAIMS) == 7
    joined = " | ".join(FALSE_CANARY_CLAIMS)
    for kept in (
        "no\\s+manual\\s+action",
        "canary\\s+is\\s+the\\s+gate",
        "automatically",
    ):
        assert kept in joined, kept


@pytest.mark.regression
@pytest.mark.parametrize(
    "path", [DOCS / "deployment" / "README.md", GUIDE, RUNBOOK], ids=lambda p: p.name
)
def test_the_deploy_docs_say_what_the_alarms_watch(path):
    """Inverted, not deleted (#148 PE condition 10), from
    test_the_deploy_docs_say_the_canary_is_timed_only (T21, EM C5/C6).

    That test required "the canary is timed only" and, for the guide and the
    runbook, that alarm-based rollback (#148) was the founder-waivable
    prerequisite for production. With the alarms in place each page must say
    what they watch and, as plainly, what they do not: the 2xx case, the
    dashboard, and the load balancer's own 502/504. The waiver sentence goes,
    and the "not yet run against a real AWS account" caveat stays.
    """
    text = " ".join(path.read_text().split())
    assert not re.search(r"canary is timed only", text, re.I), path.name
    assert re.search(r"Alarms watch the API", text), path.name
    assert "experimentation-api-5xx-blue-" in text, path.name
    assert "experimentation-api-5xx-green-" in text, path.name
    assert "2xx" in text, path.name
    assert "502" in text and "504" in text, path.name
    assert "dashboard" in text, path.name
    assert "issues/148" in text, path.name
    assert "rollback-runbook.md#an-alarm-rolled-the-api-back" in text or (
        path == RUNBOOK and "(#an-alarm-rolled-the-api-back)" in text
    ), path.name
    # EM condition 14: the waiver sentence goes only with the caveat kept.
    assert "waived it in writing" not in text, path.name
    assert "unless the founder waives it" not in text, path.name
    if path != RUNBOOK:
        assert "Not yet run against a real AWS account" in text, path.name


def _runbook_section(heading: str) -> str:
    text = RUNBOOK.read_text()
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end >= 0 else len(text)]


@pytest.mark.regression
def test_the_break_glass_is_explained_in_one_place():
    """EM condition 4(f)/(g): only the runbook's "Fix forward while an alarm is
    firing" names the input, and it says when to use it, what it gives up, that
    the next deploy is watched again, and that the CloudWatch tricks do not
    unblock a deploy (unverified until the first staging rehearsal)."""
    section = _runbook_section("Fix forward while an alarm is firing")
    flat = " ".join(section.split())
    assert "`override_alarms`" in flat and "`override_alarms_reason`" in flat
    assert "the bug is in the release you would roll back to as well" in flat
    assert "a dependency outage holds the alarm in ALARM" in flat
    assert "no alarm watches that deployment" in flat
    assert "nothing rolls it back by itself" in flat
    assert "the next deploy is watched again with no action from anyone" in flat
    assert "`aws cloudwatch disable-alarm-actions`" in flat
    assert "`aws cloudwatch set-alarm-state`" in flat
    assert "do not unblock a deploy" in flat
    assert "not yet verified" in flat
    assert "ALARMS OVERRIDDEN" in flat
    # Nowhere else under docs/ names the input.
    others = [
        str(p.relative_to(REPO_ROOT))
        for p in sorted(DOCS.rglob("*.md"))
        if "override_alarms" in p.read_text().replace(section, "")
    ]
    assert not others, others


@pytest.mark.regression
def test_the_alarm_section_says_what_to_do_and_not_do():
    """UX's runbook section, in its order: confirm, history, the API, the
    dashboard, no Rollback while CodeDeploy's is active, the migration, no
    redeploy of the tag, and the false alarm."""
    flat = " ".join(_runbook_section("An alarm rolled the API back").split())
    order = [
        "Confirm it.",
        "See what the alarm saw.",
        "Check the API is back",
        "The dashboard.",
        "Do not dispatch Rollback while CodeDeploy's rollback is active.",
        "The migration stays applied.",
        "Do not redeploy the same tag.",
        "A false alarm",
    ]
    positions = [flat.index(step) for step in order]
    assert positions == sorted(positions), order
    assert "Method 2's dashboard block" in flat
    assert "`codeDeployRollback`" in flat


#: C9, as a test (PE condition 10): the old wording, anywhere an operator reads.
_TIMED_ONLY = re.compile(r"timed only|nothing rolls back", re.I)


@pytest.mark.regression
def test_no_timed_only_wording_is_left():
    """`git grep -i -E 'timed only|nothing rolls back' -- docs .github scripts`
    is empty -- walked in Python, so it also holds in a tree with no .git."""
    roots = [DOCS, REPO_ROOT / ".github", REPO_ROOT / "scripts"]
    files = [
        p
        for root in roots
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix in {".md", ".yml", ".yaml", ".py", ".sh", ".txt"}
    ]
    assert any(p.name == "deploy.yml" for p in files), "the walk is not reading"
    assert GUIDE in files and RUNBOOK in files
    hits = [
        f"{p.relative_to(REPO_ROOT)}:{n}: {line.strip()[:120]}"
        for p in files
        for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1)
        if _TIMED_ONLY.search(line)
    ]
    assert not hits, hits


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
    # #148 PE condition 12: the alarm override's permission, why it is not
    # narrower, and the re-apply before the first cdk deploy with the alarms.
    assert "`codedeploy:UpdateDeploymentGroup`" in text
    assert "--override-alarm-configuration enabled=false" in text
    assert "there is no narrower action" in text
    assert "`iam:PassRole` is granted only to ECS tasks" in text
    assert (
        "Roles created from a policy before the alarms lack "
        "`codedeploy:UpdateDeploymentGroup`; re-apply this policy in every "
        "account before the first `cdk deploy` that adds the alarms." in text
    )
    assert "`AccessDenied` in the middle of an incident" in text


def test_the_guide_has_the_ordered_checklist():
    headings = [
        m.group(1) for m in re.finditer(r"^### (1\.\d) ", GUIDE.read_text(), re.M)
    ]
    assert headings == ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"], headings
    text = GUIDE.read_text()
    # Protection before any variable or secret (EM C12).
    assert text.index("required reviewer") < text.index("Secrets `AWS_ACCOUNT_ID`")
    # The account ID is a secret (Stream I PE C1): the guide sets it as one.
    assert "gh secret set AWS_ACCOUNT_ID --env <env>" in text
    assert "gh variable set AWS_ACCOUNT_ID" not in text
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


_RERUN = re.compile(r"re-?run(ning)? (the )?rollback|rollback again", re.I)


@pytest.mark.regression
def test_no_copy_advises_running_rollback_again():
    """EM ruling C3: a second Rollback inside the hour stops the first one's
    deployment with auto-rollback and puts the bad API release back. The only
    mention allowed is the warning against it.

    The scan covers every script (their ::error:: copy is operator copy too:
    shift_traffic.py, refuse_active_deployment.py) and every page under
    docs/deployment/, not only the three files the ban was first written for
    (#148 PE condition 8)."""
    texts = {
        "rollback.yml": (WORKFLOWS / "rollback.yml").read_text(),
        "deploy.yml": (WORKFLOWS / "deploy.yml").read_text(),
        "runbook": RUNBOOK.read_text(),
    }
    scripts = sorted((REPO_ROOT / "scripts").glob("*.py"))
    scripts += sorted((REPO_ROOT / "scripts").glob("*.sh"))
    pages = sorted((DOCS / "deployment").rglob("*.md"))
    # A glob that matches nothing makes this scan vacuous; say so instead.
    assert any(p.name == "shift_traffic.py" for p in scripts), scripts
    assert any(p.name == "refuse_active_deployment.py" for p in scripts), scripts
    assert RUNBOOK in pages and GUIDE in pages, pages
    for path in scripts + pages:
        texts.setdefault(str(path.relative_to(REPO_ROOT)), path.read_text())
    for where, text in texts.items():
        flat = " ".join(text.split())
        for match in _RERUN.finditer(flat):
            # The one allowed form is the warning: "Do not dispatch Rollback again".
            before = flat[max(0, match.start() - 20) : match.start()]
            assert before.endswith("Do not dispatch "), (
                where,
                flat[max(0, match.start() - 60) : match.end() + 40],
            )
    assert "Do not dispatch Rollback again while" in " ".join(texts["runbook"].split())
