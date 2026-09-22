"""The production rollback has to use the controller the service actually has.

`fargate_service_stack.py` creates the backend service with
`DeploymentControllerType.CODE_DEPLOY`, and ECS refuses a task-definition
change through `UpdateService` on such a service. The error text is quoted in
the CloudFormation resource specification that ships inside `aws-cdk-lib`:

    Resource handler returned message: "Invalid request provided: Unable to
    update task definition on services with a CODE_DEPLOY deployment
    controller."

`rollback.yml` called exactly that, so the whole job failed at its first step
-- during an incident, after the "ROLLBACK initiated" Slack message had
already gone out (#208). Rolling a CodeDeploy-controlled service back is the
same call as rolling it forward, with an older revision.

The second defect was subtler and would have produced the same outcome half an
hour later: the same deployment group sets
`deployment_approval_wait_time=Duration.minutes(30)` and
`auto_rollback(stopped_deployment=True)`. CodeDeploy parks after provisioning
the green task set and, if nothing calls ContinueDeployment, stops the
deployment -- which auto-rollback then reverts to the revision being rolled
back FROM. Creating the deployment is necessary and not sufficient; approving
it is the other half.

These are text reads of the workflow on purpose: no AWS, no Docker, so they
run in the ordinary unit job. Nothing has ever been deployed from this
repository, so a rehearsal against a real deployment group is not available;
these pin the shape of the calls, and the CDK configuration they have to agree
with is asserted directly in `test_rollback_matches_the_deployment_group`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
ROLLBACK = REPO_ROOT / ".github" / "workflows" / "rollback.yml"
RUNBOOK = REPO_ROOT / "docs" / "deployment" / "rollback-runbook.md"
DEPLOYMENT_README = REPO_ROOT / "docs" / "deployment" / "README.md"
STACK = REPO_ROOT / "infrastructure" / "cdk" / "stacks" / "fargate_service_stack.py"

pytestmark = pytest.mark.skipif(
    not ROLLBACK.is_file(), reason="this tree has no .github/workflows"
)


def _workflow() -> Dict[str, Any]:
    return yaml.safe_load(ROLLBACK.read_text(encoding="utf-8"))


def _steps() -> List[Dict[str, Any]]:
    """Every step of every job, not just the one named `rollback`.

    Scoped to `jobs.rollback.steps`, a `run:` added in a second job -- the
    obvious shape for a pre-flight or a notifier -- would be invisible to
    every assertion here, including the one that bans `update-service`.
    """
    return [
        step for job in _workflow()["jobs"].values() for step in job.get("steps", [])
    ]


def _run_text() -> str:
    return "\n".join(s["run"] for s in _steps() if isinstance(s.get("run"), str))


def _uncommented_run_lines() -> List[str]:
    """`run:` script lines with shell comments dropped.

    A ban on a string must not fire on a comment explaining why the string is
    banned -- the runbook check below allows exactly that, and the two should
    not disagree about it.
    """
    return [
        line
        for line in _run_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


@pytest.mark.regression
def test_the_rollback_does_not_use_a_call_the_service_rejects():
    """#208: `update-service --task-definition` on a CODE_DEPLOY service."""
    offenders = [
        ln.strip() for ln in _uncommented_run_lines() if "update-service" in ln
    ]
    assert not offenders, (
        "rollback.yml calls `aws ecs update-service`; ECS refuses a "
        "task-definition change through UpdateService on a service with a "
        "CODE_DEPLOY deployment controller, so the job fails at this step:\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


@pytest.mark.regression
def test_the_rollback_creates_a_codedeploy_deployment():
    """And uses the controller the service has -- the same call as deploying."""
    runs = _run_text()
    assert "aws deploy create-deployment" in runs, (
        "rollback.yml no longer creates a CodeDeploy deployment, which is the "
        "only way to change what a CODE_DEPLOY-controlled service runs"
    )
    # Vacuity guard: the assertion above passes on a workflow that does nothing.
    assert "task_definition_arn" in ROLLBACK.read_text(encoding="utf-8"), (
        "the workflow takes no target revision, so it rolls back to nothing"
    )


@pytest.mark.regression
def test_the_rollback_approves_its_own_traffic_shift():
    """Without ContinueDeployment the rollback parks, stops, and reverts.

    `deployment_approval_wait_time` is 30 minutes and `auto_rollback` has
    `stopped_deployment=True`, so a deployment nobody approves ends up back on
    the revision the operator was rolling away from. Creating the deployment
    is half the fix; this is the other half, and it was missing entirely.
    """
    lines = _uncommented_run_lines()
    approving = [ln for ln in lines if "continue-deployment" in ln]
    assert approving, (
        "nothing calls `aws deploy continue-deployment`. The deployment group "
        "sets deployment_approval_wait_time=30min and "
        "auto_rollback(stopped_deployment=True), so CodeDeploy parks after "
        "provisioning the green task set, stops the deployment when the wait "
        "elapses, and auto-rollback puts the BAD revision back."
    )
    assert any("READY_WAIT" in ln for ln in _run_text().splitlines()), (
        "`continue-deployment` is called without --deployment-wait-type "
        "READY_WAIT, which is the wait that gates the traffic shift"
    )


@pytest.mark.regression
def test_the_rollback_does_not_canary_its_way_back():
    """The group's CANARY_10_PERCENT_5_MINUTES is wrong for a rollback.

    Going forward it is right: the new revision is unproven. Rolling back, the
    target was serving production minutes ago and the revision being replaced
    is the one hurting users, so a canary leaves 90% of traffic on the broken
    version for another five minutes.
    """
    runs = _run_text()
    assert "--deployment-config-name CodeDeployDefault.ECSAllAtOnce" in runs, (
        "create-deployment does not override the deployment config, so the "
        "rollback inherits the deployment group's canary and leaves most "
        "traffic on the broken revision for the bake time"
    )


@pytest.mark.regression
def test_the_rollback_waits_for_the_deployment_not_the_service():
    """`services-stable` returns immediately during a blue/green deployment.

    The old task set serves the whole time, so the service is stable and the
    ECS waiter says nothing about whether the rollback took.
    """
    lines = _uncommented_run_lines()
    assert not [ln for ln in lines if "ecs wait services-stable" in ln], (
        "`ecs wait services-stable` is not a wait for a blue/green deployment"
    )
    runs = _run_text()
    assert "aws deploy get-deployment" in runs and "PRIMARY" in runs, (
        "nothing waits for the CodeDeploy deployment to put the target "
        "revision into the PRIMARY task set"
    )


@pytest.mark.regression
def test_the_rollback_refuses_a_bootstrap_revision():
    """Two producers register into this family.

    CloudFormation's revisions carry the CDK's `bootstrap` image, a tag the
    deploy workflow never writes and which need not exist in ECR. Rolling onto
    one starts tasks that cannot pull an image (#82) -- at the worst moment.

    Asserted on the check itself, not on the word: the previous version of
    this test asserted only that "bootstrap" appeared somewhere in the
    concatenated scripts, and the step's own four-line comment contains it
    twice -- so deleting the whole `case` block left the test green.
    """
    lines = _uncommented_run_lines()
    guarded = [ln for ln in lines if "*:bootstrap)" in ln.replace(" ", "")]
    assert guarded, (
        "no shell branch matches a `:bootstrap` image, so the rollback will "
        "happily deploy a CloudFormation-registered revision whose image may "
        "not exist in ECR"
    )
    assert any('-z "$image"' in ln or "-z '$image'" in ln for ln in lines), (
        "the image is not checked for emptiness. `jq 'select(.name==\"backend\")'` "
        "emits nothing and exits 0 when no container has that name, so the "
        "bootstrap guard silently passes and the AppSpec -- which hardcodes "
        "ContainerName: backend -- then fails the deployment mid-incident"
    )


@pytest.mark.regression
def test_operator_input_never_reaches_the_shell():
    """`${{ inputs.* }}` in a `run:` body is command injection.

    Actions substitutes the expression textually before bash parses the line,
    and this job holds the production OIDC role. `deploy-prod.yml` states the
    rule: values reach a script through `env:`, never through interpolation.
    """
    offenders = []
    for step in _steps():
        script = step.get("run")
        if not isinstance(script, str):
            continue
        for number, line in enumerate(script.splitlines(), start=1):
            if "${{" in line and "inputs." in line:
                offenders.append(f"{step.get('name', '?')}:{number}: {line.strip()}")
    assert not offenders, (
        "operator-supplied input is interpolated into a shell script in a job "
        "that holds the production AWS role; pass it through `env:` instead:\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


@pytest.mark.regression
def test_the_result_is_announced_even_when_the_rollback_fails():
    """Otherwise #deployments holds "ROLLBACK initiated" and nothing else.

    `continue-on-error: true` does not make a step run after an earlier step
    failed; only `if: always()` does. Responders read Slack.
    """
    notifiers = [
        s
        for s in _steps()
        if "slack" in str(s.get("uses", "")).lower()
        and "result" in str(s.get("name", "")).lower()
    ]
    assert notifiers, "no step announces the rollback result"
    for step in notifiers:
        assert str(step.get("if", "")).strip() == "always()", (
            f"{step.get('name')!r} has no `if: always()`, so every failure "
            "path leaves Slack showing only the ROLLBACK-initiated warning"
        )


@pytest.mark.skipif(not STACK.is_file(), reason="this tree has no CDK stacks")
@pytest.mark.regression
def test_rollback_matches_the_deployment_group():
    """The workflow's assumptions about the group, asserted against the group.

    If someone removes the approval wait, the ContinueDeployment call becomes
    unnecessary rather than wrong -- but if someone *adds* a longer one, or
    changes the auto-rollback behaviour, the reasoning above stops holding and
    this is where that shows up.
    """
    stack = STACK.read_text(encoding="utf-8")
    assert "deployment_approval_wait_time" in stack, (
        "the deployment group no longer sets an approval wait; re-read "
        "whether rollback.yml still needs to call continue-deployment"
    )
    assert "stopped_deployment=True" in stack, (
        "the deployment group no longer auto-rolls-back a stopped deployment; "
        "the consequence of failing to approve has changed"
    )


@pytest.mark.skipif(not RUNBOOK.is_file(), reason="this tree has no runbook")
@pytest.mark.regression
@pytest.mark.parametrize(
    "document",
    [
        pytest.param(RUNBOOK, id="rollback-runbook"),
        pytest.param(DEPLOYMENT_README, id="deployment-README"),
    ],
)
def test_the_docs_do_not_tell_an_operator_to_use_that_call(document: Path):
    """Operators follow prose, and this prose had the broken call twice.

    Only the sentence explaining *not* to use it may name it. Both documents
    are checked: the runbook was fixed while `docs/deployment/README.md` kept
    a third copy under "Emergency Rollback -- Method 2 (fastest)", which is
    the page an on-call engineer opens first.
    """
    if not document.is_file():
        pytest.skip(f"{document.name} is not in this tree")

    # Only lines an operator would COPY count -- i.e. inside a fenced code
    # block, and not a `#` shell comment. Two kinds of mention are legitimate
    # and must not fire: a comment inside a fence saying not to use the call,
    # and prose or a markdown blockquote explaining why it cannot work. The
    # first version of this check had no fence tracking and flagged its own
    # explanatory blockquote, which is the shape that tempts someone to delete
    # the check rather than the call.
    #
    # Anywhere on the line, not just at its start: the call reappears just as
    # easily inside `X=$(aws ecs update-service ...)`, and an earlier version
    # anchored on `^\s*` let exactly that through when tampered.
    offenders = []
    in_fence = False
    for number, line in enumerate(
        document.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        if "aws ecs update-service" in line and not stripped.startswith("#"):
            offenders.append(f"{number}: {stripped}")
    assert not offenders, (
        f"{document.name} still tells an operator to run a call this service "
        "rejects:\n" + "\n".join(f"  {o}" for o in offenders)
    )
