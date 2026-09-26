"""The workflow role's permissions follow the workflows (#140, PE v1 C12).

`scripts/iam_actions.py` derives the IAM actions from every `aws <service>
<verb>` in deploy.yml, rollback.yml, db-migrate.yml, the local actions and the
scripts they run. The committed policy and the documented table must be what it
generates, so a workflow that gains a call fails here until the role is given
it -- instead of failing, mid-deploy, with AccessDenied.

The trust policy is pinned to GitHub's immutable subject for this repository
and one environment (PE v1 C5): the old one allowed `repo:<name>:*`, i.e. any
branch, any pull request workflow, and a repository nobody owns any more.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "iam_actions.py"
TRUST = REPO_ROOT / "infrastructure" / "cdk" / "github-actions-trust-policy.json"
POLICY = REPO_ROOT / "infrastructure" / "cdk" / "github-actions-deploy-policy.json"
DOC = REPO_ROOT / "docs" / "deployment" / "iam-permissions.md"
IMMUTABLE_SUBJECT = "repo:getexperimently@328439352/experimently@1367480368"

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / ".github" / "workflows").is_dir(),
    reason="this tree has no .github/workflows",
)


def _module():
    spec = importlib.util.spec_from_file_location("iam_actions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.regression
def test_the_committed_policy_and_table_are_what_the_workflows_need():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.regression
def test_every_aws_call_is_granted():
    """Read the other way round: each call in the sources, against the policy."""
    iam = _module()
    granted = set()
    for statement in json.loads(POLICY.read_text())["Statement"]:
        actions = statement["Action"]
        granted |= set([actions] if isinstance(actions, str) else actions)
    found = iam.calls()
    assert len(found) >= 20, f"only {len(found)} actions found; the scan is not reading"
    assert found.keys() <= granted, sorted(found.keys() - granted)
    # The sources include the scripts the workflows run, not only the YAML.
    places = {p.split(":")[0] for ps in found.values() for p in ps}
    assert "scripts/run_migration_task.sh" in places
    assert ".github/actions/stack-outputs/action.yml" in places


def test_an_unmapped_service_is_refused():
    iam = _module()
    with pytest.raises(SystemExit, match="not mapped to an IAM prefix"):
        iam.iam_actions_for("iot", "create-thing")
    assert iam.iam_actions_for("rds", "create-db-cluster-snapshot") == [
        "rds:CreateDBClusterSnapshot"
    ]


def test_pass_role_is_only_to_ecs_tasks():
    statements = json.loads(POLICY.read_text())["Statement"]
    (passing,) = [s for s in statements if "iam:PassRole" in str(s["Action"])]
    assert passing["Action"] == "iam:PassRole"
    assert passing["Condition"] == {
        "StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}
    }


@pytest.mark.regression
def test_the_trust_policy_pins_the_immutable_subject_and_one_environment():
    (statement,) = json.loads(TRUST.read_text())["Statement"]
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    condition = statement["Condition"]
    assert set(condition) == {"StringEquals"}, (
        "StringLike admits a wildcard; the subject is pinned exactly"
    )
    assert condition["StringEquals"] == {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": (
            f"{IMMUTABLE_SUBJECT}:environment:<ENVIRONMENT>"
        ),
    }
    assert "*" not in TRUST.read_text()
    assert "amarkanday" not in TRUST.read_text()


def test_the_old_policies_are_gone():
    cdk = REPO_ROOT / "infrastructure" / "cdk"
    assert not (cdk / "cicd-deployment-policy.json").exists()
    assert not (cdk / "gitActions").exists()


def test_the_doc_says_where_the_subject_comes_from():
    text = DOC.read_text()
    assert f"{IMMUTABLE_SUBJECT}:environment:<ENVIRONMENT>" in text
    assert "gh api repos/<owner>/<repo>/actions/oidc/customization/sub" in text
    assert "decode a real token" in text.lower()
    for identity in ("bootstrap identity", "`cdk deploy` identity", "workflow role"):
        assert identity in text.lower() or identity in text, identity
    assert "sts:AssumeRole" in text and "cdk-hnb659fds-*" in text
