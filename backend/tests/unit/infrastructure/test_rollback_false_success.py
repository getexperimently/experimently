"""Rollback never reports a success it did not achieve, and never stops CodeDeploy's own rollback (#148 PR-1).

Three defects on main, each driven here through rollback.yml's own `run:`
scripts, in order, with each step's `if:` evaluated from the outputs of the
steps before it:

* **The target is already serving, nothing in flight** (PE failure mode A,
  EM condition 2(a)). The run created a deployment, saw PRIMARY == target on
  its first poll, and reported "traffic is on ..." while its own deployment
  sat unapproved for 30 minutes, holding the group. Now it refuses before any
  write, and the run fails with "nothing to roll back".
* **The stop step's auto-rollback put the target back** (EM condition 2(b),
  the T31 bake case). The stop step stops the in-flight bad deployment with
  auto-rollback; PRIMARY returns to the target; the wait loop said success on
  its first poll, before approving its own deployment. Now it counts success
  only once this run has approved its own deployment.
* **An in-flight deployment is CodeDeploy's own rollback** (PE condition 3,
  UX W9). The stop step stopped every listed id with auto-rollback, which
  would put back the release CodeDeploy was rolling away from. Now every id
  is classified by creator before any is stopped; a `codeDeployRollback`, or a
  creator that cannot be read, stops nothing and fails the step.

The harness is test_dashboard_deploy_wiring.py's `Runner`: bash with
`-eo pipefail`, a fake `aws` first on PATH answering from a scenario, no AWS
credentials, and a no-op `sleep`, so nothing waits and no test measures time.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.tests.unit.infrastructure.test_dashboard_deploy_wiring import (
    ROLLBACK,
    Runner,
    _load,
    _step,
    _steps,
    api_rules,
    dashboard_rules,
    rule,
)
from backend.tests.unit.infrastructure.test_ecs_rolling_rollout import (
    NEW as DASH_NEW,
)
from backend.tests.unit.infrastructure.test_ecs_rolling_rollout import (
    OLD as DASH_OLD,
)
from backend.tests.unit.infrastructure.test_ecs_rolling_rollout import dep, svc
from backend.tests.unit.infrastructure.test_forward_deploy_completes import (
    AFTER,
    BEFORE,
    NEW,
    OLD,
    RULES_BLUE,
    RULES_GREEN,
    _split,
)

pytestmark = pytest.mark.skipif(
    not ROLLBACK.is_file(), reason="this tree has no .github/workflows"
)

#: The revision rolled back TO: the one before the bad deploy.
TARGET = OLD
ROLLBACK_ID = "d-ROLLBACK1"
BAD_ID = "d-BADDEPLOY"
CD_ROLLBACK_ID = "d-CDROLLBACK"
#: CodeDeploy's own revert of what the stop step stopped (#783).
CD_REVERT_ID = "d-CDRB"
PRIMARY_QUERY = "taskSets[?status=='PRIMARY'].taskDefinition"
#: Only the verify step's query asks for it (#816), so a rule matching it
#: answers that step and nothing else.
VERIFY_MATCH = "computedDesiredCount"
VERIFY_STEP = "Verify what is serving traffic"
VERIFY_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rollback_verify"


def _doc(name: str = "post-shift") -> dict:
    """A describe-services answer for the API service after a blue/green
    shift, during the deployment group's hour-long termination wait.

    `post-shift` is the fixture: PRIMARY on the target (`OLD`, :42) and the
    replaced set ACTIVE on `NEW` (:43), each running 2 of 2, so the service
    reports runningCount 4 against desiredCount 2 -- run 37176250648's
    "4/2". Every other name is that document with one thing changed."""
    document = json.loads((VERIFY_FIXTURES / "services-post-shift.json").read_text())
    if name == "missing-service":
        return {
            "services": [],
            "failures": [
                {
                    "arn": "arn:aws:ecs:us-west-2:123456789012:service/"
                    "experimentation-staging/experimentation-backend-staging",
                    "reason": "MISSING",
                }
            ],
        }
    service = document["services"][0]
    primary, replaced = service["taskSets"]
    if name == "post-shift":
        pass
    elif name == "empty-primary":
        primary.update(runningCount=0, pendingCount=2)
        service["runningCount"] = 2
    elif name == "short":
        primary.update(runningCount=1, pendingCount=1)
        service["runningCount"] = 3
    elif name == "pending":
        primary.update(runningCount=2, pendingCount=1)
    elif name == "two-primary":
        replaced["status"] = "PRIMARY"
    elif name == "two-primary-other-first":
        # Mid-swap: two PRIMARY sets, and `| [0]` names the other revision.
        replaced["status"] = "PRIMARY"
        service["taskSets"] = [replaced, primary]
    elif name == "no-primary":
        primary["status"] = "ACTIVE"
    elif name == "other-primary":
        primary["status"] = "ACTIVE"
        replaced["status"] = "PRIMARY"
    elif name == "desired-0":
        primary.update(computedDesiredCount=0, runningCount=0)
    elif name == "no-task-sets-key":
        del service["taskSets"]
    elif name == "desired-none":
        del primary["computedDesiredCount"]
    elif name == "pending-none":
        del primary["pendingCount"]
    elif name == "scale-50":
        primary.update(computedDesiredCount=1, runningCount=1)
        primary["scale"]["value"] = 50.0
    else:
        raise AssertionError(f"no such variant: {name}")
    return document


@pytest.fixture
def runner(tmp_path: Path) -> Runner:
    runner = Runner(tmp_path)
    # The wait loops sleep between polls; the verdict, not the wait, is
    # under test.
    sleep = runner.bin / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    # `date +%s` is a clock that advances one second per call, so a
    # ROLLBACK_TIMEOUT_SECONDS of N bounds a loop to a few polls with no real
    # waiting. Any other use of `date` fails the test loudly.
    clock = runner.state / "clock"
    date = runner.bin / "date"
    date.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "+%s" ] || { echo "fake date: unexpected $*" >&2; exit 99; }\n'
        f'n=$(cat "{clock}" 2>/dev/null || echo 1000)\n'
        f'echo $((n + 1)) > "{clock}"\n'
        'echo "$n"\n'
    )
    date.chmod(0o755)
    return runner


# --- a minimal evaluator for the `if:` expressions rollback.yml uses ------------------

_CLAUSE = re.compile(
    r"^(steps\.([\w-]+)\.(?:outputs\.([\w-]+)|(outcome))|inputs\.([\w-]+)"
    r"|env\.(\w+))"
    r"\s*(==|!=)\s*'([^']*)'$"
)


def _should_run(
    step: dict,
    outputs: dict[str, dict[str, str]],
    inputs: dict,
    failed: bool,
    env: dict | None = None,
) -> bool:
    """A job-env name not given reads as unset, as with no SLACK_BOT_TOKEN."""
    expr = str(step.get("if", "")).strip()
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2].strip()
    if not expr:
        return not failed
    clauses = [c.strip() for c in expr.split("&&")]
    status_function = False
    result = True
    for clause in clauses:
        if clause in ("always()", "!cancelled()"):
            status_function = True
            continue
        if clause == "failure()":
            status_function = True
            result = result and failed
            continue
        match = _CLAUSE.match(clause)
        # An `if:` of a shape this evaluator does not know fails the test
        # rather than being guessed at.
        assert match, f"cannot evaluate if: {step.get('if')!r}"
        _, sid, key, outcome, inp, env_name, op, literal = match.groups()
        if env_name:
            value = (env or {}).get(env_name, "")
        elif inp:
            value = inputs.get(inp, "")
        elif outcome:
            value = outputs.get(sid, {}).get("__outcome__", "")
        else:
            value = outputs.get(sid, {}).get(key, "")
        result = result and ((value == literal) == (op == "=="))
    return result if status_function else (result and not failed)


def _run_from_stop(
    runner: Runner,
    rules: list,
    dashboard: str = "",
    dashboard_target: dict[str, str] | None = None,
    replace: dict[str, str] | None = None,
    **env: str,
) -> tuple[dict[str, dict[str, str]], dict[str, tuple[int, str]], str]:
    """Run every `run:` step from the stop step to the end, as the runner
    would. Returns (outputs by step id, (exit, log) by step name, summary).

    ``dashboard_target`` is the dashboard check's outputs; ``replace`` swaps
    a step's `run:` text by name (main's verify step, say); ``env`` overrides
    a workflow value for every step."""
    runner.scenario(rules)
    inputs = {"dashboard_task_definition_arn": dashboard, "reason": "bad release"}
    outputs: dict[str, dict[str, str]] = {
        "target": {"arn": TARGET, "__outcome__": "success"},
        "dashboard-target": {**(dashboard_target or {}), "__outcome__": "success"},
    }
    results: dict[str, tuple[int, str]] = {}
    summary = ""
    failed = False
    steps = _steps(ROLLBACK)
    (start,) = [
        i
        for i, s in enumerate(steps)
        if s.get("name") == "Stop any deployment already in flight"
    ]
    for step in steps[start:]:
        if "run" not in step:
            continue  # the Slack notifications
        key = step.get("id") or step["name"]
        if not _should_run(step, outputs, inputs, failed):
            outputs[key] = {"__outcome__": "skipped"}
            continue
        if replace and step["name"] in replace:
            step = {**step, "run": replace[step["name"]]}
        code, log, written, step_summary = runner.run(
            ROLLBACK,
            step,
            outputs,
            {**inputs, "job.status": "failure" if failed else "success"},
            **env,
        )
        outputs[key] = {**written, "__outcome__": "success" if code == 0 else "failure"}
        results[step["name"]] = (code, log)
        summary += step_summary
        failed = failed or code != 0
    return outputs, results, summary


def _ops(runner: Runner) -> list[str]:
    return [" ".join(c[:2]) for c in runner.calls()]


def _headline(summary: str) -> str:
    (line,) = [x for x in summary.splitlines() if x.startswith("## Rollback of ")]
    return line


def _nothing_in_flight() -> list:
    return [rule("deploy list-deployments", answers=[""])]


def _verify(*names: str) -> list:
    """The verify step's read (#816): the fake evaluates the step's own query
    on these documents (post-shift by default), in order. Every scenario puts
    it BEFORE api_rules(), whose broad describe-services rule would otherwise
    answer it."""
    return [
        rule(
            "ecs describe-services",
            VERIFY_MATCH,
            answers=[_doc(n) for n in names or ("post-shift",)],
            query=True,
        )
    ]


def _primary(*serving: str) -> list:
    return [rule("ecs describe-services", PRIMARY_QUERY, answers=list(serving))]


def _create_and_approve(statuses: list[str]) -> list:
    return [
        rule("deploy create-deployment", answers=[ROLLBACK_ID]),
        rule(
            "deploy get-deployment",
            ROLLBACK_ID,
            "deploymentInfo.status",
            answers=statuses,
        ),
        rule("deploy continue-deployment", ROLLBACK_ID, answers=[""]),
    ]


# --- (a) the target is already serving, nothing in flight ----------------------------


@pytest.mark.regression
def test_a_rollback_to_the_revision_already_serving_is_refused_before_any_write(
    runner,
):
    """EM condition 2(a) / PE condition 2. Planted defect: main's run, which
    creates a deployment and reports "traffic is on ..." on its first poll."""
    rules = [
        *_nothing_in_flight(),
        *_verify(),
        *_primary(TARGET),
        # What main's loop reads: its own deployment, never Ready.
        *_create_and_approve(["InProgress"]),
        # scripts/api_serving.py: the target is PRIMARY in blue, and the
        # /api/* rule forwards to blue alone.
        *api_rules(BEFORE, RULES_BLUE),
    ]
    outputs, results, summary = _run_from_stop(runner, rules)
    ops = _ops(runner)
    assert "deploy create-deployment" not in ops, ops
    assert "deploy stop-deployment" not in ops, ops
    assert "deploy continue-deployment" not in ops, ops
    assert outputs["stop"]["already_serving"] == "true"
    assert outputs["codedeploy"]["__outcome__"] == "skipped"
    code, log = results["Refuse a rollback to the revision already serving"]
    assert code == 1, log
    assert (
        "The API is already on experimentation-backend-staging:42, and no "
        "deployment was in flight, so there is nothing to roll back: this run "
        "created no CodeDeploy deployment and stopped nothing." in log
    ), log
    assert "The dashboard was left as it is." in log
    assert "rollback-runbook.md Method 2" in log
    headline = _headline(summary)
    assert headline == (
        "## Rollback of staging: REFUSED: the API was already on "
        "experimentation-backend-staging:42 with nothing in flight, so this run "
        "stopped nothing and created no deployment; dashboard left as it is"
    ), headline


@pytest.mark.regression
def test_the_dashboard_half_still_runs_when_the_api_is_already_serving(runner):
    """The refusal is the API half's. A dashboard target given with it is
    rolled as the existing flow does it, and the refusal says so."""
    outputs = {
        "target": {"arn": TARGET},
        "stop": {"already_serving": "true"},
        "codedeploy": {"__outcome__": "skipped"},
        "dashboard-rollback": {
            "result": "rolled back to experimentation-dashboard-staging:6",
            "__outcome__": "success",
        },
    }
    step = _step(ROLLBACK, "Refuse a rollback to the revision already serving")
    runner.scenario([])
    inputs = {"dashboard_task_definition_arn": "experimentation-dashboard-staging:6"}
    code, log, _, _ = runner.run(ROLLBACK, step, outputs, inputs)
    assert code == 1, log
    assert "nothing to roll back" in log
    assert (
        "The dashboard half ran as asked: dashboard rolled back to "
        "experimentation-dashboard-staging:6." in log
    )
    # The dashboard step's own `if:` does not depend on the API half.
    dashboard = _step(ROLLBACK, "dashboard-rollback")
    assert dashboard["if"] == "inputs.dashboard_task_definition_arn != ''"
    # And the refusal's does not stop at a failed dashboard half.
    assert "!cancelled()" in str(step["if"])


def test_a_target_that_is_not_serving_is_rolled_back_as_before(runner):
    """The ordinary path is unchanged: the new revision is serving, so the
    run creates, approves, and reports only after its own approval."""
    rules = [
        *_nothing_in_flight(),
        *_verify(),
        # PRIMARY is still the bad revision until after the approval.
        *_primary(NEW, NEW, TARGET),
        *_create_and_approve(["InProgress", "Ready", "InProgress"]),
        *api_rules(AFTER, RULES_GREEN),
    ]
    outputs, results, summary = _run_from_stop(runner, rules)
    assert "already_serving" not in outputs["stop"]
    code, log = results["Shift traffic and wait for it to land"]
    assert code == 0, log
    assert "approved by this run" in log
    assert _ops(runner).count("deploy continue-deployment") == 1
    assert "Refuse a rollback to the revision already serving" not in results
    assert "API rolled back to experimentation-backend-staging:42" in _headline(summary)


@pytest.mark.regression
@pytest.mark.parametrize(
    "predicate_rules, exit_code",
    [
        # The /api/* rule forwards to green alone while the target's task
        # set is in blue: api_serving.py's WRONG.
        (api_rules(BEFORE, RULES_GREEN), 3),
        # An AWS read fails: api_serving.py's UNKNOWN.
        (
            [
                rule(
                    "cloudformation describe-stack-resources",
                    answers=[{"error": "AccessDenied"}],
                ),
                *api_rules(BEFORE, RULES_BLUE),
            ],
            2,
        ),
    ],
    ids=["wrong-3", "unknown-2"],
)
def test_a_predicate_that_cannot_confirm_serving_warns_and_rolls_back(
    runner, predicate_rules, exit_code
):
    """Review finding 1. Exit 2 or 3 from scripts/api_serving.py is not "already
    serving": the run warns and takes the normal path (create, then approve)."""
    rules = [
        *_nothing_in_flight(),
        *_verify(),
        *_primary(TARGET),
        *_create_and_approve(["InProgress", "Ready", "InProgress"]),
        *predicate_rules,
    ]
    outputs, results, summary = _run_from_stop(runner, rules)
    code, log = results["Stop any deployment already in flight"]
    assert code == 0, log
    assert (
        "::warning title=Could not tell what the API is serving::"
        f"scripts/api_serving.py exited {exit_code}" in log
    ), log
    assert "already_serving" not in outputs["stop"]
    ops = _ops(runner)
    assert ops.count("deploy create-deployment") == 1, ops
    assert ops.count("deploy continue-deployment") == 1, ops
    assert "Refuse a rollback to the revision already serving" not in results
    assert "API rolled back to experimentation-backend-staging:42" in _headline(summary)


@pytest.mark.regression
def test_a_failed_verify_in_the_already_serving_case_says_the_dashboard_did_not_run(
    runner,
):
    """Review finding 3, end to end: already serving, a dashboard target, and
    the API verify step fails (a task-count mismatch). The dashboard step's
    outcome comes from its real `if:` (skipped), and the refusal says so,
    not "ran as asked"."""
    rules = [
        *_nothing_in_flight(),
        # The PRIMARY task set short throughout: verify reads to its limit.
        *_verify("short"),
        *api_rules(BEFORE, RULES_BLUE),
        *dashboard_rules([]),
    ]
    outputs, results, summary = _run_from_stop(
        runner, rules, dashboard="experimentation-dashboard-staging:6"
    )
    assert outputs["stop"]["already_serving"] == "true"
    assert outputs["api-verify"]["__outcome__"] == "failure"
    assert "1 of 2 tasks running (1 starting)" in results[VERIFY_STEP][1]
    assert outputs["dashboard-rollback"]["__outcome__"] == "skipped"
    assert "ecs update-service" not in _ops(runner)
    code, log = results["Refuse a rollback to the revision already serving"]
    assert code == 1, log
    assert (
        "The dashboard half did not run: an earlier step failed; see above." in log
    ), log
    assert "ran as asked" not in log
    headline = _headline(summary)
    assert headline == (
        "## Rollback of staging: REFUSED: the API was already on "
        "experimentation-backend-staging:42 with nothing in flight, so this run "
        "stopped nothing and created no deployment; dashboard NOT rolled back "
        "(not reached)"
    ), headline


# --- (b) the stop step's auto-rollback already put the target back -------------------


@pytest.mark.regression
def test_success_waits_for_this_runs_own_approval_after_the_stop_reverted_the_api(
    runner,
):
    """EM condition 2(b), the T31 bake case. The stop step stops the bad
    deployment with auto-rollback, and PRIMARY is the target again before
    this run's deployment is Ready. Planted defect: main's loop, which breaks
    on that first poll and never approves its own deployment."""
    rules = [
        rule("deploy list-deployments", answers=[BAD_ID, CD_REVERT_ID, ""]),
        rule("deploy get-deployment", BAD_ID, "creator", answers=["user\tNone"]),
        rule("deploy stop-deployment", BAD_ID, answers=[""]),
        rule(
            "deploy get-deployment",
            BAD_ID,
            "deploymentInfo.status",
            answers=["Stopped"],
        ),
        *_verify(),
        # The target from the first poll on: the stop's auto-rollback.
        *_primary(TARGET),
        *_create_and_approve(["InProgress", "InProgress", "Ready", "InProgress"]),
    ]
    outputs, results, summary = _run_from_stop(runner, rules)
    calls = runner.calls()
    ops = [" ".join(c[:2]) for c in calls]
    code, log = results["Shift traffic and wait for it to land"]
    assert code == 0, log
    # This run approved its own deployment, and only then counted success.
    assert ops.count("deploy continue-deployment") == 1, ops
    approve = ops.index("deploy continue-deployment")
    polls = [
        i
        for i, c in enumerate(calls)
        if c[:2] == ["deploy", "get-deployment"] and ROLLBACK_ID in c
    ]
    assert len(polls) == 3 and polls[-1] < approve, (polls, approve)
    # The pre-stop read, then the wait (#783): busy, empty, empty.
    assert ops.count("deploy list-deployments") == 4, ops
    assert ops.index("deploy create-deployment") > max(
        i for i in range(len(ops)) if ops[i] == "deploy list-deployments"
    ), ops
    assert f"deployment {ROLLBACK_ID}" in log and "approved by this run" in log
    assert "API rolled back to experimentation-backend-staging:42" in _headline(summary)


# --- #783: after its own stop, the rollback waits out CodeDeploy's revert ------------


def _revert_clock(runner: Runner, d: float | None, length: float = 3.1) -> None:
    """FAKE_AWS's revert model (test_dashboard_deploy_wiring.py): every call
    takes 0.7 s of virtual time and `sleep N` takes N. Measured on staging
    (4 stops of 4): the revert is created about 0.6 s after the stop and is
    done about 3.1 s later."""
    (runner.state / "revert.json").write_text(
        json.dumps({"d": d, "length": length, "latency": 0.7, "id": CD_REVERT_ID})
    )
    clock = runner.state / "vclock"
    sleep = runner.bin / "sleep"
    sleep.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        f"p = {str(clock)!r}\n"
        "t = float(open(p).read()) if os.path.exists(p) else 0.0\n"
        "open(p, 'w').write(repr(t + float(sys.argv[1])))\n"
    )
    sleep.chmod(0o755)


def _stop_then_roll_back() -> list:
    """Run 37148722775's shape: a user deployment in flight, stopped, Stopped
    on the first read; then this run's own create, approval and verify."""
    return [
        # The pre-stop read. After the stop, FAKE_AWS answers from the revert.
        rule("deploy list-deployments", answers=[BAD_ID]),
        rule("deploy get-deployment", BAD_ID, "creator", answers=["user\tNone"]),
        rule("deploy stop-deployment", BAD_ID, answers=[""]),
        rule(
            "deploy get-deployment",
            BAD_ID,
            "deploymentInfo.status",
            answers=["Stopped"],
        ),
        *_verify(),
        *_primary(TARGET),
        *_create_and_approve(["InProgress", "InProgress", "Ready", "InProgress"]),
    ]


@pytest.mark.regression
@pytest.mark.parametrize(
    "d",
    [None, 0.6, 1.0, 1.6, 6.5],
    ids=[
        "no-revert",
        "revert-at-0.6s",
        "revert-at-1.0s",
        "revert-at-1.6s",
        "revert-at-6.5s",
    ],
)
def test_a_revert_after_the_stop_is_waited_out_before_create(runner, d):
    """#783, the run-37148722775 replay on revert state. The stop step stopped
    a user deployment with auto-rollback, read it Stopped, and the create met
    CodeDeploy's own revert: DeploymentLimitExceededException, the dashboard
    half skipped. Each `d` is when the revert starts after the stop.

    Planted defects: main (no wait) fails at 0.6 s and 1.0 s and passes with
    no revert; a single empty read with no sleep fails at 1.6 s. Putting a
    sleep before the first read passes every case here, as expected: it is
    rejected because it hides the busy read staging needs, not because it
    races at these timings."""
    _revert_clock(runner, d)
    outputs, results, summary = _run_from_stop(runner, _stop_then_roll_back())
    logs = "\n".join(log for _, log in results.values())
    assert "DeploymentLimitExceededException" not in logs, logs
    code, log = results["Roll back via CodeDeploy"]
    assert code == 0, log
    ops = _ops(runner)
    # The wait only reads: one stop, for the deployment this run stopped.
    (stop,) = [c for c in runner.calls() if c[:2] == ["deploy", "stop-deployment"]]
    assert BAD_ID in stop and CD_REVERT_ID not in stop
    lists = [i for i in range(len(ops)) if ops[i] == "deploy list-deployments"]
    assert ops.index("deploy create-deployment") > lists[-1], ops
    assert outputs["dashboard-rollback"]["__outcome__"] != "failure"
    assert "API rolled back to experimentation-backend-staging:42" in _headline(summary)


def test_a_revert_that_outlasts_a_read_is_named_while_the_wait_runs(runner):
    """The staging evidence the wait ran: a busy line naming the revert, then
    two empty reads, then the create. A revert of 15 s, started 0.6 s after
    the stop."""
    _revert_clock(runner, 0.6, length=15)
    outputs, results, summary = _run_from_stop(runner, _stop_then_roll_back())
    code, log = results["Stop any deployment already in flight"]
    assert code == 0, log
    assert f"deployment group still busy: {CD_REVERT_ID}; reading again in 5 s" in log
    assert (
        "no active deployment on the deployment group in two reads in a row; "
        "creating the rollback deployment" in log
    ), log
    assert results["Roll back via CodeDeploy"][0] == 0
    assert "API rolled back to experimentation-backend-staging:42" in _headline(summary)


@pytest.mark.regression
def test_a_group_still_busy_at_the_cap_creates_nothing_and_says_so(runner):
    """At GROUP_IDLE_POLLS (60 reads, about 5 minutes) with the group still
    busy: labelled, nothing created, only the stop step's `stopped` and
    `stop_wait` outputs (#759), and the summary still
    reads what the API is serving. Planted defect: no `exit 1` at the cap."""
    rules = [
        rule("deploy list-deployments", answers=[BAD_ID, CD_REVERT_ID]),
        rule("deploy get-deployment", BAD_ID, "creator", answers=["user\tNone"]),
        rule("deploy stop-deployment", BAD_ID, answers=[""]),
        rule(
            "deploy get-deployment",
            BAD_ID,
            "deploymentInfo.status",
            answers=["Stopped"],
        ),
        *dashboard_rules([]),
        *api_rules(BEFORE, RULES_BLUE),
    ]
    outputs, results, summary = _run_from_stop(runner, rules, dashboard=DASHBOARD)
    code, log = results["Stop any deployment already in flight"]
    assert code == 1, log
    ops = _ops(runner)
    assert "deploy create-deployment" not in ops, ops
    assert ops.count("deploy stop-deployment") == 1, ops
    # The pre-stop read, the 60 of the wait, and the summary's one (#759).
    assert ops.count("deploy list-deployments") == 1 + 60 + 1, ops
    (line,) = [
        x
        for x in log.splitlines()
        if x.startswith("::error title=Deployment group still busy::")
    ]
    assert f"This run stopped {BAD_ID} with auto-rollback" in line
    assert "waited about 5 minutes (60 reads, 5 s apart)" in line
    assert f"(last read 0 s ago) still listed: {CD_REVERT_ID}." in line
    assert "This run created no rollback deployment" in line
    assert (
        "Check by hand: aws deploy list-deployments --application-name "
        "experimentation-platform-staging --deployment-group-name "
        "experimentation-staging --include-only-statuses Created Queued "
        "InProgress Baking Ready" in line
    ), line
    assert line.endswith(
        "Do not dispatch Rollback again while any of them is active: a new "
        "Rollback refuses while CodeDeploy's revert is running."
    ), line
    # #759: what it stopped, and how its wait ended. Exactly these outputs.
    assert outputs["stop"] == {
        "stopped": BAD_ID,
        "stop_wait": "timeout",
        "__outcome__": "failure",
    }, outputs["stop"]
    assert outputs["codedeploy"]["__outcome__"] == "skipped"
    headline = _headline(summary)
    # The read says the target is serving, which wins over the wait (#759):
    # CodeDeploy's revert, still listed, gets the per-id sentence.
    expected = (
        f"{SERVING_ON_TARGET} (its verify step: skipped); {DIFFERENT_RELEASES}. "
        f"{_t32(CD_REVERT_ID)}"
    )
    assert headline == f"## Rollback of {expected}", headline
    assert "| CodeDeploy deployment | `not created` |" in summary
    assert not re.search(r"\d{12}", log + summary)


def _shift(runner: Runner, rules: list, timeout: str = "1800") -> tuple[int, str]:
    """The wait loop alone. The fake clock advances a second per `date`
    call, and the loop calls it once per poll, so `timeout` bounds the polls."""
    runner.scenario(rules)
    step = _step(ROLLBACK, "Shift traffic and wait for it to land")
    code, log, _, _ = runner.run(
        ROLLBACK,
        step,
        {"target": {"arn": TARGET}, "codedeploy": {"deployment-id": ROLLBACK_ID}},
        ROLLBACK_TIMEOUT_SECONDS=timeout,
    )
    return code, log


@pytest.mark.regression
def test_an_approval_sent_outside_this_run_counts_once_observed(runner):
    """Review finding 2. An operator approves in the console between this
    run's read of Ready and its own continue-deployment, which then fails.
    The deployment was seen Ready and has left Ready: it is approved, by
    someone. Planted defect: the previous loop, where that failed call ended
    the step (set -e) and the rollback was reported failed."""
    code, log = _shift(
        runner,
        [
            *_primary(TARGET),
            rule("deploy create-deployment", answers=[ROLLBACK_ID]),
            rule(
                "deploy get-deployment",
                ROLLBACK_ID,
                "deploymentInfo.status",
                answers=["InProgress", "Ready", "InProgress"],
            ),
            rule(
                "deploy continue-deployment",
                answers=[{"error": "DeploymentIsNotInReadyStateException"}],
            ),
        ],
    )
    assert code == 0, log
    assert "approved outside this run: seen Ready, now InProgress" in log
    assert "has since left Ready (InProgress)" in log


def test_a_failed_approval_while_still_ready_fails_loudly(runner):
    code, log = _shift(
        runner,
        [
            *_primary(TARGET),
            rule(
                "deploy get-deployment",
                ROLLBACK_ID,
                "deploymentInfo.status",
                answers=["Ready"],
            ),
            rule("deploy continue-deployment", answers=[{"error": "AccessDenied"}]),
        ],
    )
    assert code == 1, log
    assert "this run could not approve rollback deployment" in log
    assert "traffic is on" not in log


@pytest.mark.regression
@pytest.mark.parametrize(
    "statuses",
    [["InProgress"], ["Baking"], ["Succeeded"], ["InProgress", "Baking", "Succeeded"]],
    ids=["InProgress", "Baking", "Succeeded", "never-Ready-sequence"],
)
def test_a_deployment_never_seen_ready_never_counts(runner, statuses):
    """The T31 bake-case protection, in every never-Ready ordering: the
    target is PRIMARY from the first poll (the stop's auto-rollback), and
    this run's deployment is never seen Ready. That is not a rollback this
    run did, and the timeout says so without contradicting itself."""
    code, log = _shift(
        runner, [*_primary(TARGET), *_create_and_approve(statuses)], timeout="5"
    )
    assert code == 1, log
    assert "traffic is on" not in log
    assert "deploy continue-deployment" not in _ops(runner)
    assert (
        "experimentation-backend-staging:42 is the PRIMARY task set, but this "
        f"run never saw its own rollback deployment {ROLLBACK_ID} approved" in log
    ), log
    assert "seen Ready by this run: no" in log
    assert "did not put" not in log
    # It polled more than once before giving up: the clock bounds it.
    polls = [c for c in runner.calls() if c[:2] == ["deploy", "get-deployment"]]
    assert len(polls) > 1


def test_ready_then_stopped_is_a_failure_not_an_approval(runner):
    code, log = _shift(
        runner,
        [
            *_primary(TARGET),
            rule(
                "deploy get-deployment",
                ROLLBACK_ID,
                "deploymentInfo.status",
                answers=["Ready", "Stopped"],
            ),
            rule(
                "deploy continue-deployment",
                answers=[{"error": "DeploymentAlreadyCompletedException"}],
            ),
            rule("deploy get-deployment", "errorInformation", answers=["{}"]),
        ],
    )
    assert code == 1, log
    assert f"rollback deployment {ROLLBACK_ID} is Stopped" in log
    assert "traffic is on" not in log


def test_the_timeout_names_what_is_serving_when_it_is_not_the_target(runner):
    code, log = _shift(
        runner,
        [*_primary(NEW), *_create_and_approve(["InProgress"])],
        timeout="3",
    )
    assert code == 1, log
    shown = TARGET.rsplit("/", 1)[-1]
    assert f"rollback deployment {ROLLBACK_ID} did not put {shown} in service" in log
    assert f"serving {NEW.rsplit('/', 1)[-1]}, not approved" in log
    assert "123456789012" not in log


# --- the stop step refuses CodeDeploy's own rollback (PE condition 3, UX W9) ----------


def _in_flight(*deployments: tuple[str, str]) -> list:
    """(id, the creator/rollback line get-deployment prints) for each."""
    rules = [
        rule(
            "deploy list-deployments",
            answers=["\t".join(d for d, _ in deployments), "", ""],
        )
    ]
    for deployment_id, line in deployments:
        answer: Any = (
            {"error": line[len("ERROR ") :]} if line.startswith("ERROR ") else line
        )
        rules.append(
            rule("deploy get-deployment", deployment_id, "creator", answers=[answer])
        )
    rules += [
        rule("deploy stop-deployment", answers=[""]),
        rule("deploy get-deployment", "deploymentInfo.status", answers=["Stopped"]),
        *_primary(NEW),
    ]
    return rules


@pytest.mark.regression
@pytest.mark.parametrize(
    "deployments",
    [
        [(CD_ROLLBACK_ID, f"codeDeployRollback\t{BAD_ID}")],
        # Classified before any is stopped: a user deployment listed first
        # is not stopped either.
        [(BAD_ID, "user\tNone"), (CD_ROLLBACK_ID, f"codeDeployRollback\t{BAD_ID}")],
    ],
    ids=["alone", "listed-after-a-user-deployment"],
)
def test_the_stop_step_never_stops_codedeploys_own_rollback(runner, deployments):
    """C11. Planted defect: main's stop step, which stops every listed id."""
    runner.scenario(_in_flight(*deployments))
    step = _step(ROLLBACK, "Stop any deployment already in flight")
    code, log, written, _ = runner.run(ROLLBACK, step, {"target": {"arn": TARGET}})
    assert code == 1, log
    assert "deploy stop-deployment" not in _ops(runner), runner.calls()
    assert (
        f"::error title=CodeDeploy is already rolling back::Deployment "
        f"{CD_ROLLBACK_ID} is CodeDeploy's own rollback of {BAD_ID} and is still "
        "active. Stopping it would put that release back, so this run stopped "
        "nothing and rolled nothing back. The API is on "
        "experimentation-backend-staging:43." in log
    ), log
    assert "Rollback refuses while CodeDeploy's rollback is active" in log
    assert "up to an hour" in log and "Method 2" in log
    assert written["refused"] == "codeDeployRollback"
    assert written["refused_id"] == CD_ROLLBACK_ID
    # T33 is unchanged by #783: refused before the stop, and no wait.
    assert _ops(runner).count("deploy list-deployments") == 1, runner.calls()


@pytest.mark.regression
@pytest.mark.parametrize(
    "line",
    ["ERROR An error occurred (AccessDenied)", "None\tNone", ""],
    ids=["read-failed", "null-creator", "empty"],
)
def test_an_unreadable_creator_stops_nothing(runner, line):
    """PE condition 3(b): fail closed."""
    runner.scenario(_in_flight((BAD_ID, line)))
    step = _step(ROLLBACK, "Stop any deployment already in flight")
    code, log, written, _ = runner.run(ROLLBACK, step, {"target": {"arn": TARGET}})
    assert code == 1, log
    assert "deploy stop-deployment" not in _ops(runner), runner.calls()
    assert "::error title=Could not classify an in-flight deployment::" in log
    assert f"The creator of CodeDeploy deployment {BAD_ID} could not be read" in log
    assert written["refused"] == "unreadable"


def test_a_user_deployment_is_still_stopped_with_auto_rollback(runner):
    runner.scenario(_in_flight((BAD_ID, "user\tNone")))
    step = _step(ROLLBACK, "Stop any deployment already in flight")
    code, log, written, _ = runner.run(ROLLBACK, step, {"target": {"arn": TARGET}})
    assert code == 0, log
    (stop,) = [c for c in runner.calls() if c[:2] == ["deploy", "stop-deployment"]]
    assert BAD_ID in stop and "--auto-rollback-enabled" in stop
    assert "refused" not in written and "already_serving" not in written


@pytest.mark.regression
def test_the_refused_run_says_so_in_the_summary_and_slack(runner):
    """W9: no "ROLLBACK initiated" without an ending. The result step runs
    always(), and its line is the summary's headline, which names the refusal."""
    rules = _in_flight((CD_ROLLBACK_ID, f"codeDeployRollback\t{BAD_ID}"))
    outputs, results, summary = _run_from_stop(runner, rules)
    assert outputs["codedeploy"]["__outcome__"] == "skipped"
    headline = _headline(summary)
    assert headline == (
        f"## Rollback of staging: REFUSED: CodeDeploy's own rollback "
        f"{CD_ROLLBACK_ID} is still active, so this run stopped nothing and "
        "created no deployment (the API is on experimentation-backend-staging:43); "
        "dashboard left as it is"
    ), headline
    notify = _step(ROLLBACK, "Notify rollback result")
    assert notify["if"] == "always() && env.SLACK_ON == 'true'"
    assert "steps.summary.outputs.slack" in notify["with"]["slack-message"]


def test_the_check_then_stop_race_is_named():
    """PE condition 3(e): the race is accepted, and written down where it is."""
    code = _step(ROLLBACK, "Stop any deployment already in flight")["run"]
    assert "check-then-stop race" in code
    classify = code.index("--query 'deploymentInfo.[creator")
    stop = code.index("aws deploy stop-deployment")
    assert classify < stop


def test_the_evaluator_knows_every_if_in_the_api_half():
    """The sequence runner above evaluates `if:`; one it cannot parse fails
    here rather than being run or skipped by guess."""
    for step in _load(ROLLBACK)["jobs"]["rollback"]["steps"]:
        if "run" in step and "if" in step:
            _should_run(step, {}, {}, False)


@pytest.mark.regression
def test_a_refused_run_with_a_dashboard_target_says_nothing_was_stopped(runner):
    """The dashboard half is not reached when the stop step refuses. The
    summary says the API half refused and stopped nothing, not "if the stop
    step already reverted the API", which cannot be true here.

    Every outcome here comes from the run, not from the test: the stop step
    refuses, and the `if:` chain skips the rest (review suggestion 4)."""
    rules = [
        *_in_flight((CD_ROLLBACK_ID, f"codeDeployRollback\t{BAD_ID}")),
        *dashboard_rules([]),
    ]
    outputs, results, summary = _run_from_stop(
        runner, rules, dashboard="experimentation-dashboard-staging:6"
    )
    assert outputs["stop"]["__outcome__"] == "failure"
    for key in ("codedeploy", "api-verify", "dashboard-rollback"):
        assert outputs[key]["__outcome__"] == "skipped", key
    assert "Refuse a rollback to the revision already serving" not in results
    code, out = results["Run summary"]
    # Every verdict but ROLLED BACK fails the summary (#759).
    assert code == 1, out
    assert "the API half refused, and nothing was stopped" in summary, summary
    assert "If the stop step already reverted the API" not in summary
    assert outputs["summary"]["slack"] == (
        f"staging: REFUSED: CodeDeploy's own rollback {CD_ROLLBACK_ID} is still "
        "active, so this run stopped nothing and created no deployment (the API "
        "is on experimentation-backend-staging:43); dashboard NOT rolled back "
        "(not reached)"
    )


# --- #755: after the run's own steps did not finish, say what is serving ----------------
#
# Run 37080696791: the stop step stopped the bad deployment with auto-rollback,
# traffic went back to the target, CreateDeployment was refused AccessDenied,
# the verify step was skipped, and the headline said "API NOT rolled back
# (its verify step: skipped); dashboard NOT rolled back (not reached)". The
# summary now reads what is serving (scripts/api_serving.py, read-only) and
# words the API's clause from that read. Headlines are matched whole or by
# prefix, never by substring.

DASHBOARD = "experimentation-dashboard-staging:6"
SERVING_ON_TARGET = (
    "staging: API BACK, DASHBOARD NOT: API is serving "
    "experimentation-backend-staging:42, read at the end of the run, but this "
    "run did not finish its own steps"
)
DIFFERENT_RELEASES = (
    "dashboard NOT rolled back (not reached), so the API and dashboard are on "
    "different releases: put the dashboard back with "
    "docs/deployment/rollback-runbook.md Method 2, the dashboard block"
)


def _t32(deployment: str) -> str:
    """The per-id sentence (#759, T32), whole, as the headline ends with it."""
    return (
        f"Do not dispatch Rollback again while deployment {deployment} is active: "
        "a new Rollback stops any deployment that is not CodeDeploy's own "
        "rollback, with auto-rollback, which reverts what it shifted, and it "
        "refuses while CodeDeploy's own rollback is active."
    )


ACCESS_DENIED = {
    "error": "An error occurred (AccessDeniedException) when calling the "
    "CreateDeployment operation: User is not authorized to perform: "
    "codedeploy:GetApplicationRevision"
}


def _serving_reads(runner: Runner) -> list[list[str]]:
    """The API service reads api_serving.py makes (the verify step's read
    carries a --query, so it is not one of them)."""
    return [
        c
        for c in runner.calls()
        if c[:2] == ["ecs", "describe-services"]
        and "experimentation-backend-staging" in c
        and "--query" not in c
    ]


def _read_exit(summary: str) -> str:
    (row,) = [
        x for x in summary.splitlines() if x.startswith("| API at the end of the run |")
    ]
    match = re.search(r"\(scripts/api_serving\.py exit (\d)\) \|$", row)
    assert match, row
    return match.group(1)


def _run_summary(
    runner: Runner, rules: list, outputs: dict, dashboard: str = "", **env: str
):
    runner.scenario(rules)
    return runner.run(
        ROLLBACK,
        _step(ROLLBACK, "Run summary"),
        outputs,
        {"dashboard_task_definition_arn": dashboard, "job.status": "failure"},
        **env,
    )


@pytest.mark.regression
def test_a_stop_that_put_the_target_back_is_reported_when_the_rollback_then_fails(
    runner,
):
    """EM C5(a), V18': the run-37080696791 replay, through every step from the
    stop on. The read answers 0, so the headline says the API is serving the
    target, and the dashboard clause says the two are on different releases.
    The job still fails. Planted defect: key the headline on API_VERIFY again
    (main's line)."""
    rules = [
        rule("deploy list-deployments", answers=[BAD_ID, CD_REVERT_ID, ""]),
        rule("deploy get-deployment", BAD_ID, "creator", answers=["user\tNone"]),
        rule("deploy stop-deployment", BAD_ID, answers=[""]),
        rule(
            "deploy get-deployment",
            BAD_ID,
            "deploymentInfo.status",
            answers=["Stopped"],
        ),
        rule("deploy create-deployment", answers=[ACCESS_DENIED]),
        *dashboard_rules([]),
        # PRIMARY is the target in blue and /api/* forwards to blue alone.
        *api_rules(BEFORE, RULES_BLUE),
    ]
    outputs, results, summary = _run_from_stop(runner, rules, dashboard=DASHBOARD)
    assert outputs["stop"]["__outcome__"] == "success"
    assert outputs["codedeploy"]["__outcome__"] == "failure"
    assert outputs["api-verify"]["__outcome__"] == "skipped"
    assert outputs["dashboard-rollback"]["__outcome__"] == "skipped"
    headline = _headline(summary)
    expected = f"{SERVING_ON_TARGET} (its verify step: skipped); {DIFFERENT_RELEASES}."
    assert headline == f"## Rollback of {expected}", headline
    assert outputs["summary"]["slack"] == expected
    assert _read_exit(summary) == "0"
    # Stopped at the first 0.
    assert len(_serving_reads(runner)) == 1, runner.calls()
    # The pre-stop read, then the wait (#783): busy, empty, empty; then the
    # summary's list of what is active (#759), which reads nothing.
    assert _ops(runner).count("deploy list-deployments") == 5, runner.calls()
    assert "Job status: failure." in summary
    assert "| CodeDeploy deployment | `not created` |" in summary
    assert "123456789012" not in summary
    assert "123456789012" not in results["Run summary"][1]


@pytest.mark.regression
@pytest.mark.parametrize(
    "services, rules_answer, sentence",
    [
        # The target is PRIMARY but the /api/* rule still splits traffic: a
        # revert reroute in progress.
        (
            BEFORE,
            _split(50, 50),
            "NOT YET: the PRIMARY task set runs experimentation-backend-staging:42; "
            "the /api/* rule forwards to 2 target groups with weight: a CodeDeploy "
            "traffic shift is in progress. Wait for it to finish.",
        ),
        # The bad release is still PRIMARY.
        (
            AFTER,
            RULES_GREEN,
            "NOT YET: the PRIMARY task set runs experimentation-backend-staging:43, "
            "not experimentation-backend-staging:42",
        ),
    ],
    ids=["split-listener", "primary-other"],
)
def test_a_read_answering_1_is_never_reported_as_not_rolled_back(
    runner, services, rules_answer, sentence
):
    """EM C5(b): exit 1 is also a listener mid-reroute, so with CodeDeploy's
    revert still active the verdict is STILL MOVING, quoting api_serving.py,
    never "NOT rolled back" (#759 C5). Polled to the limit on 1, decided on
    the last answer. Planted defect: map a non-zero read to the retired
    string."""
    outputs = {
        "target": {"arn": TARGET},
        "stop": {"stopped": BAD_ID, "stop_wait": "ok", "__outcome__": "success"},
        "codedeploy": {"__outcome__": "failure"},
        "api-verify": {"__outcome__": "skipped"},
    }
    rules = [
        *api_rules(services, rules_answer),
        rule("deploy list-deployments", answers=[CD_REVERT_ID]),
    ]
    code, out, written, summary = _run_summary(
        runner, rules, outputs, SUMMARY_SERVING_POLLS="4"
    )
    assert code == 1, out
    assert _read_exit(summary) == "1"
    assert len(_serving_reads(runner)) == 4, runner.calls()
    slack = written["slack"]
    assert slack == (
        "staging: STILL MOVING: the API is not yet on "
        f"experimentation-backend-staging:42 (scripts/api_serving.py exit 1: "
        f"{sentence}) while deployment {CD_REVERT_ID} is active; dashboard left "
        f"as it is. {_t32(CD_REVERT_ID)}"
    ), slack
    assert "NOT rolled back" not in slack, slack
    assert _headline(summary) == f"## Rollback of {slack}"


@pytest.mark.regression
@pytest.mark.parametrize(
    "stop",
    [
        {
            "refused": "codeDeployRollback",
            "refused_id": CD_ROLLBACK_ID,
            "primary": "x:1",
        },
        {"refused": "unreadable", "refused_id": BAD_ID},
        {"already_serving": "true"},
    ],
    ids=["refused-rollback", "refused-unreadable", "already-serving"],
)
def test_a_decided_run_reads_nothing_from_the_summary(runner, stop):
    """EM C5(c), PE v2 C7: a refused or already-serving run's verdict is
    decided, so the summary makes no describe-services call. The reads are
    supplied (and would answer 0), so a call would be seen, not fail.
    Planted defect: drop the refused/already-serving conditions."""
    outputs = {
        "target": {"arn": TARGET},
        "stop": {**stop, "__outcome__": "failure" if "refused" in stop else "success"},
        "codedeploy": {"__outcome__": "skipped"},
        "api-verify": {"__outcome__": "skipped" if "refused" in stop else "success"},
    }
    if "already_serving" in stop:
        outputs["api-verify"]["__outcome__"] = "failure"
    code, out, written, summary = _run_summary(
        runner, api_rules(BEFORE, RULES_BLUE), outputs
    )
    assert code == 1, out
    assert runner.calls() == [], runner.calls()
    assert "| API at the end of the run |" not in summary
    assert written["slack"].startswith("staging: REFUSED: "), written


@pytest.mark.regression
@pytest.mark.parametrize(
    "error",
    [
        "An error occurred (ThrottlingException) when calling the DescribeServices "
        "operation: Rate exceeded",
        'Unable to locate credentials. You can configure credentials by running "aws configure".',
        # AWS's own text names the role, and with it the account.
        "An error occurred (AccessDeniedException) when calling the "
        "DescribeServices operation: User: arn:aws:sts::123456789012:"
        "assumed-role/deploy/x is not authorized",
    ],
    ids=["throttled", "no-credentials", "access-denied-names-the-account"],
)
def test_a_read_that_cannot_tell_still_writes_the_result(runner, error):
    """EM C5(d): the read exits 2 (a failed AWS call, or credentials never
    configured). The step does not die under `set -e`, `slack=` is written,
    and the headline is "not confirmed", quoting the read. Planted defect:
    drop the `|| rc=$?` capture."""
    outputs = {
        "target": {"arn": TARGET},
        "stop": {"stopped": BAD_ID, "stop_wait": "ok"},
        "codedeploy": {"__outcome__": "failure"},
        "api-verify": {"__outcome__": "skipped"},
    }
    rules = [
        rule(
            "ecs describe-services",
            "experimentation-backend-staging",
            answers=[{"error": error}],
        ),
        *api_rules(BEFORE, RULES_BLUE),
        # The list of what is active fails the same way (#759).
        rule("deploy list-deployments", answers=[{"error": error}]),
    ]
    code, out, written, summary = _run_summary(
        runner, rules, outputs, SUMMARY_SERVING_POLLS="2"
    )
    assert code == 1, out
    assert _read_exit(summary) == "2"
    assert len(_serving_reads(runner)) == 2, runner.calls()
    assert written["slack"].startswith(
        "staging: OUTCOME UNKNOWN: this run could not tell what the API is "
        "serving (scripts/api_serving.py exit 2: UNKNOWN: could not tell: "
    ), written
    assert written["slack"].endswith(
        "); its verify step: skipped; dashboard left as it is."
    ), written
    assert "NOT rolled back" not in written["slack"]
    # The summary and the log are public: no account, even from AWS's text.
    for text in (summary, out, written["slack"]):
        assert "123456789012" not in text, text


@pytest.mark.regression
def test_a_target_serving_with_the_dashboard_not_reached_names_the_split(runner):
    """EM C5(e): read 0, a dashboard target given and not reached, and this
    run's own deployment created (the shift then failed). The headline says
    the API and dashboard are on different releases and points to Method 2;
    the page warns against a second dispatch while that deployment is active,
    in the one allowed form. Planted defect: drop the different-releases
    clause."""
    outputs = {
        "target": {"arn": TARGET},
        "codedeploy": {"deployment-id": ROLLBACK_ID, "__outcome__": "success"},
        "api-verify": {"__outcome__": "skipped"},
        "dashboard-target": {"arn": DASHBOARD},
        "dashboard-rollback": {"__outcome__": "skipped"},
    }
    rules = [
        *dashboard_rules([]),
        *api_rules(BEFORE, RULES_BLUE),
        rule("deploy list-deployments", answers=[ROLLBACK_ID]),
    ]
    code, out, written, summary = _run_summary(
        runner, rules, outputs, dashboard=DASHBOARD
    )
    assert code == 1, out
    assert _read_exit(summary) == "0"
    # The warning against a second dispatch is the headline's own (#759).
    assert written["slack"] == (
        f"{SERVING_ON_TARGET} (its verify step: skipped); {DIFFERENT_RELEASES}. "
        f"{_t32(ROLLBACK_ID)}"
    )
    assert (
        "the API and dashboard are on different releases, the newer-dashboard"
        in summary
    )


def test_an_unresolved_target_keeps_todays_copy_and_reads_nothing(runner):
    """EM C4: no target resolved, nothing to read against."""
    outputs = {"api-verify": {"__outcome__": "skipped"}}
    code, out, written, summary = _run_summary(
        runner, api_rules(BEFORE, RULES_BLUE), outputs
    )
    assert code == 1, out
    assert runner.calls() == []
    assert written["slack"] == (
        "staging: NOTHING CHANGED: the target revision was not resolved, so this "
        "run stopped nothing and created no deployment; dashboard left as it is"
    )


def test_the_poll_starts_no_read_after_its_deadline(runner):
    """EM C7: the wall-clock bound. With the deadline already passed, one
    read is made and decided on, whatever the poll count."""
    outputs = {
        "target": {"arn": TARGET},
        "codedeploy": {"deployment-id": ROLLBACK_ID},
        "api-verify": {"__outcome__": "failure"},
    }
    code, out, written, summary = _run_summary(
        runner,
        [*api_rules(AFTER, RULES_GREEN), rule("deploy list-deployments", answers=[""])],
        outputs,
        SUMMARY_SERVING_POLLS="12",
        SUMMARY_SERVING_DEADLINE_SECONDS="0",
    )
    assert code == 1, out
    assert _read_exit(summary) == "1"
    assert len(_serving_reads(runner)) == 1, runner.calls()


def test_the_poll_defaults_are_stated_and_bounded():
    """EM C7: env-overridable, the default called a guess, worst case under
    two minutes."""
    code = _step(ROLLBACK, "Run summary")["run"]
    assert 'polls="${SUMMARY_SERVING_POLLS:-12}"' in code
    assert 'poll_seconds="${SUMMARY_SERVING_POLL_SECONDS:-5}"' in code
    assert "${SUMMARY_SERVING_DEADLINE_SECONDS:-90}" in code
    assert "is a guess" in code


# --- #816: the verify step reads the PRIMARY task set's own counts ----------------------
#
# Run 37176250648: the rollback worked, and the verify step failed it with
# "4 of 2 tasks are running", because after a blue/green shift the service
# runs both task sets for the termination hour and the step compared the
# service's counts. The same comparison passed a PRIMARY with no task running
# while the replaced set ran two. These run the step as written, with the
# fake evaluating its own --query on describe-services documents (FAKE_AWS's
# query mode), and the workflow's own 300 s / 10 s: 31 reads at most.

#: What the post-shift read prints when the step passes on its first read.
VERIFIED = (
    "serving: experimentation-backend-staging:42  (PRIMARY task set: 2 of 2 "
    "running, 0 starting, scale 100.0; the service wants 2 and runs 4 tasks "
    "across 2 task sets; read {n} of 31)"
)
NOT_FINISHED = "::error title=API rollback not finished::"
ON_TARGET = (
    "Traffic is on experimentation-backend-staging:42, but after 300 s "
    "(31 reads, 10 s apart) "
)
NOT_CONFIRMED_ON_TARGET = (
    "After 300 s (31 reads, 10 s apart) this run could not confirm "
    "experimentation-backend-staging:42 is serving: "
)
ACCESS_DENIED_DESCRIBE = {
    "error": "An error occurred (AccessDeniedException) when calling the "
    "DescribeServices operation: User: arn:aws:sts::123456789012:"
    "assumed-role/deploy/x is not authorized"
}

#: Main's verify step at eb804c84, with its print commands spelled printf.
#: Run here only to show that this harness reproduces both defects: it is
#: red on the post-shift shape and green on an empty PRIMARY.
MAINS_VERIFY = """set -euo pipefail
read -r SERVING RUNNING DESIRED <<<"$(aws ecs describe-services \\
  --cluster "$ECS_CLUSTER" --services "$ECS_BACKEND_SERVICE" \\
  --query "services[0].[taskSets[?status=='PRIMARY'].taskDefinition | [0], runningCount, desiredCount]" \\
  --output text)"
printf '%s\\n' "serving: ${SERVING##*/}  ($RUNNING/$DESIRED tasks running)"
if [ "$SERVING" != "$TARGET_ARN" ]; then
  printf '%s\\n' "::error::expected ${TARGET_ARN##*/} to be serving, got ${SERVING##*/}"
  exit 1
fi
if [ "$RUNNING" != "$DESIRED" ]; then
  printf '%s\\n' "::error::$RUNNING of $DESIRED tasks are running on ${TARGET_ARN##*/}"
  exit 1
fi
"""


def _mains_verify(*names: str) -> list:
    return [
        rule(
            "ecs describe-services",
            "runningCount, desiredCount",
            answers=[_doc(n) for n in names],
            query=True,
        )
    ]


def _record_sleeps(runner: Runner) -> Path:
    log = runner.state / "sleeps.log"
    sleep = runner.bin / "sleep"
    sleep.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n')
    sleep.chmod(0o755)
    return log


def _verify_step(
    runner: Runner,
    *answers: Any,
    dashboard: str = DASHBOARD,
    deployment: str = ROLLBACK_ID,
    run: str | None = None,
    **env: str,
) -> tuple[int, str]:
    """The verify step alone. Each answer is a variant name (a document the
    step's query is evaluated on) or an {"error": ...} the read fails with."""
    docs = [_doc(a) if isinstance(a, str) else a for a in answers]
    rules = [rule("ecs describe-services", VERIFY_MATCH, answers=docs, query=True)]
    if run is not None:
        rules = [*_mains_verify(*answers), *rules]
    runner.scenario(rules)
    step = _step(ROLLBACK, VERIFY_STEP)
    if run is not None:
        step = {**step, "run": run}
    code, log, _, _ = runner.run(
        ROLLBACK,
        step,
        {"target": {"arn": TARGET}, "codedeploy": {"deployment-id": deployment}},
        {"dashboard_task_definition_arn": dashboard},
        **env,
    )
    assert "123456789012" not in log, log
    return code, log


def _describes(runner: Runner) -> int:
    return sum(1 for c in runner.calls() if c[:2] == ["ecs", "describe-services"])


def _error_line(log: str) -> str:
    (line,) = [x for x in log.splitlines() if x.startswith("::error")]
    return line


@pytest.mark.regression
def test_the_post_shift_shape_passes(runner):
    """The staging shape: PRIMARY on the target at 2 of 2, the replaced set
    still running 2, the service at 4 of 2. One read, green."""
    code, log = _verify_step(runner, "post-shift")
    assert code == 0, log
    assert VERIFIED.format(n=1) in log.splitlines(), log
    assert _describes(runner) == 1


@pytest.mark.regression
@pytest.mark.parametrize(
    "name, code, line",
    [
        (
            "post-shift",
            1,
            "::error::4 of 2 tasks are running on experimentation-backend-staging:42",
        ),
        (
            "empty-primary",
            0,
            "serving: experimentation-backend-staging:42  (2/2 tasks running)",
        ),
    ],
    ids=["red-on-post-shift", "green-on-an-empty-primary"],
)
def test_mains_step_fails_the_post_shift_shape_and_passes_an_empty_primary(
    runner, name, code, line
):
    """The planted defect, kept as a test: main's step on the same documents,
    through the same query evaluation. Both of #816's defects reproduce --
    run 37176250648's "4 of 2", and a PRIMARY with no task running reported
    as verified -- so the fixture and the fake are the staging shape."""
    got, log = _verify_step(runner, name, run=MAINS_VERIFY)
    assert got == code, log
    assert line in log.splitlines(), log


@pytest.mark.regression
def test_an_empty_primary_is_not_a_success(runner):
    """PRIMARY 0 running / 2 starting while the replaced set runs 2 and the
    service reports 2 of 2: main's step passed this. Read to the limit, then
    red, with the PRIMARY task set's own numbers."""
    code, log = _verify_step(runner, "empty-primary")
    assert code == 1, log
    assert _describes(runner) == 31
    line = _error_line(log)
    assert line.startswith(
        f"{NOT_FINISHED}{ON_TARGET}its task set has 0 of 2 tasks running (2 starting)."
    ), line


@pytest.mark.regression
@pytest.mark.parametrize(
    "first",
    [
        "short",
        # C3 (a): two PRIMARY sets mid-swap, and `| [0]` names the other
        # revision. Waited for, not "PRIMARY is not the target".
        "two-primary-other-first",
        # C3 (b): no PRIMARY set yet; its revision reads None.
        "no-primary",
        "desired-0",
        # rc 255: no taskSets key, so length() fails in the CLI.
        "no-task-sets-key",
        "desired-none",
        "pending-none",
        "scale-50",
        "pending",
        ACCESS_DENIED_DESCRIBE,
    ],
    ids=[
        "short",
        "c3a-two-primary-other-first",
        "c3b-no-primary",
        "desired-0",
        "jmespath-rc-255",
        "desired-none",
        "pending-none",
        "scale-50",
        "pending",
        "read-failed",
    ],
)
def test_a_first_read_that_is_not_done_is_read_again(runner, first):
    """Only "no such service" and "a single PRIMARY on another revision" fail
    on the first read. Everything else not yet done is read again: here the
    second read is healthy, so the step passes on read 2.

    Planted defect for C3 (a): move the revision comparison above the count
    check; `two-primary-other-first` goes red on read 1 ("expected ...:42 to
    be serving, got ...:43")."""
    sleeps = _record_sleeps(runner)
    code, log = _verify_step(runner, first, "post-shift")
    assert code == 0, log
    assert _describes(runner) == 2
    assert VERIFIED.format(n=2) in log.splitlines(), log
    (again,) = [x for x in log.splitlines() if x.startswith("read 1 of 31: ")]
    assert again.endswith("; reading again in 10 s"), again
    assert sleeps.read_text().split() == ["10"]


@pytest.mark.regression
@pytest.mark.parametrize(
    "answer, lead, why",
    [
        ("short", ON_TARGET, "its task set has 1 of 2 tasks running (1 starting)."),
        # pendingCount matters: 2 of 2 running with one more starting.
        ("pending", ON_TARGET, "its task set has 2 of 2 tasks running (1 starting)."),
        (
            "two-primary",
            NOT_CONFIRMED_ON_TARGET,
            "the service has 2 PRIMARY task sets, so this run cannot tell what is serving.",
        ),
        (
            "no-primary",
            NOT_CONFIRMED_ON_TARGET,
            "the service has 0 PRIMARY task sets, so this run cannot tell what is serving.",
        ),
        (
            "desired-0",
            ON_TARGET,
            "the PRIMARY task set wants 0 tasks: a rollback onto no tasks would "
            "look complete with nothing running.",
        ),
        (
            "no-task-sets-key",
            NOT_CONFIRMED_ON_TARGET,
            "the PRIMARY task set's counts could not be read (aws exit 255: In "
            "function length(), invalid type for value: None, expected one of: "
            "['string', 'array', 'object'], received: \"null\").",
        ),
        (
            "desired-none",
            ON_TARGET,
            "the PRIMARY task set's counts are not all numbers (running 2, "
            "desired None, starting 0; the service wants 2).",
        ),
        (
            "pending-none",
            ON_TARGET,
            "the PRIMARY task set's counts are not all numbers (running 2, "
            "desired 2, starting None; the service wants 2).",
        ),
        # The scale gate: 1 of 1 running is the PRIMARY's own steady state,
        # but the service wants 2.
        (
            "scale-50",
            ON_TARGET,
            "its task set wants 1 tasks, fewer than the service's 2 (scale 50.0).",
        ),
        (
            ACCESS_DENIED_DESCRIBE,
            NOT_CONFIRMED_ON_TARGET,
            "the PRIMARY task set's counts could not be read (aws exit 254: An "
            "error occurred (AccessDeniedException) when calling the "
            "DescribeServices operation: User: arn:aws:sts::<account>:"
            "assumed-role/deploy/x is not authorized).",
        ),
    ],
    ids=[
        "short",
        "pending",
        "two-primary",
        "no-primary",
        "desired-0",
        "jmespath-rc-255",
        "desired-none",
        "pending-none",
        "scale-50",
        "read-failed",
    ],
)
def test_a_read_that_stays_not_done_fails_after_exactly_31_reads(
    runner, answer, lead, why
):
    """Bounded by the number of reads (300 / 10 + 1), never by a clock, and
    the error says what the last read said.

    Planted defects: drop `[ "$pending" -eq 0 ]` from the success test and
    `pending` goes green; write the success test the negative way with no
    integer guard (`[ "$running" -ne "$desired" ] || [ "$pending" -gt 0 ]`
    waits, else success) and `pending-none` goes green (bash's `[ None -gt 0 ]`
    is an error, which is false); put scale.value through the integer guard
    and test_the_post_shift_shape_passes goes red."""
    sleeps = _record_sleeps(runner)
    code, log = _verify_step(runner, answer)
    assert code == 1, log
    assert _describes(runner) == 31
    assert sleeps.read_text().split() == ["10"] * 30
    assert len([x for x in log.splitlines() if x.startswith("read ")]) == 30
    line = _error_line(log)
    assert line.startswith(f"{NOT_FINISHED}{lead}{why}"), line


@pytest.mark.regression
def test_no_such_service_fails_on_the_first_read(runner):
    code, log = _verify_step(runner, "missing-service")
    assert code == 1, log
    assert _describes(runner) == 1
    assert _error_line(log) == (
        "::error title=API service not found::experimentation-backend-staging was "
        "not found in experimentation-staging, so this run cannot tell what is "
        "serving. The dashboard was not rolled back."
    )


@pytest.mark.regression
@pytest.mark.parametrize(
    "answers, reads",
    [(["other-primary"], 1), (["short", "other-primary"], 2)],
    ids=["first-read", "mid-wait"],
)
def test_a_single_primary_on_another_revision_fails_at_once(runner, answers, reads):
    """At the first read, or at any read during the wait: the revision is
    compared on every read, once there is exactly one PRIMARY set."""
    code, log = _verify_step(runner, *answers)
    assert code == 1, log
    assert _describes(runner) == reads
    assert _error_line(log) == (
        "::error title=API not on the target::expected "
        "experimentation-backend-staging:42 to be serving, got "
        "experimentation-backend-staging:43: the PRIMARY task set moved after the "
        "traffic shift. The dashboard was not rolled back."
    )


def test_the_wait_is_the_workflows_named_values(runner):
    """The reads and the sleep come from VERIFY_TASKS_DEADLINE_SECONDS and
    VERIFY_TASKS_POLL_SECONDS, not literals: 20 / 10 is 3 reads."""
    env = _load(ROLLBACK)["env"]
    assert env["VERIFY_TASKS_DEADLINE_SECONDS"] == "300"
    assert env["VERIFY_TASKS_POLL_SECONDS"] == "10"
    code_text = _step(ROLLBACK, VERIFY_STEP)["run"]
    assert (
        "reads=$(( 10#$VERIFY_TASKS_DEADLINE_SECONDS / "
        "10#$VERIFY_TASKS_POLL_SECONDS + 1 ))" in code_text
    )
    assert 'sleep "$VERIFY_TASKS_POLL_SECONDS"' in code_text
    sleeps = _record_sleeps(runner)
    code, log = _verify_step(
        runner,
        "short",
        VERIFY_TASKS_DEADLINE_SECONDS="20",
        VERIFY_TASKS_POLL_SECONDS="7",
    )
    assert code == 1, log
    assert _describes(runner) == 3
    assert sleeps.read_text().split() == ["7", "7"]
    assert "after 20 s (3 reads, 7 s apart)" in _error_line(log)


@pytest.mark.parametrize(
    "deadline, poll",
    [("300", "0"), ("300", "ten"), ("-1", "10"), ("300", "")],
    ids=["poll-0", "poll-not-a-number", "deadline-negative", "poll-empty"],
)
def test_a_wait_that_is_not_configured_reads_nothing_and_fails(runner, deadline, poll):
    code, log = _verify_step(
        runner,
        "post-shift",
        VERIFY_TASKS_DEADLINE_SECONDS=deadline,
        VERIFY_TASKS_POLL_SECONDS=poll,
    )
    assert code == 1, log
    assert _describes(runner) == 0
    assert _error_line(log).startswith("::error title=API verify not configured::")


@pytest.mark.parametrize(
    "dashboard, deployment",
    [(DASHBOARD, ROLLBACK_ID), ("", "")],
    ids=["dashboard-and-deployment", "neither"],
)
def test_the_deadline_copy_names_the_way_out(runner, dashboard, deployment):
    """T32's warning only when this run created a deployment; runbook Method 2
    only when a dashboard target was given; the command to watch, always."""
    code, log = _verify_step(
        runner, "short", dashboard=dashboard, deployment=deployment
    )
    assert code == 1, log
    line = _error_line(log)
    assert (
        "Watch the task set: aws ecs describe-services --cluster "
        "experimentation-staging --services experimentation-backend-staging "
        "--query \"services[0].taskSets[?status=='PRIMARY'] | [0].{Running:"
        'runningCount,Desired:computedDesiredCount,Pending:pendingCount}" '
        "--output json." in line
    ), line
    method_2 = (
        "The dashboard was not rolled back. Once the API is at its desired "
        "count, put the dashboard back with docs/deployment/rollback-runbook.md "
        "Method 2, the dashboard block."
    )
    again = (
        f"Do not dispatch Rollback again while CodeDeploy deployment {ROLLBACK_ID} "
        "is active: its stop step would stop that deployment with auto-rollback "
        "and put the API back on the release you rolled back from."
    )
    assert (method_2 in line) is bool(dashboard), line
    assert line.endswith(again) is bool(deployment), line


def _end_to_end_rules() -> list:
    return [
        *_nothing_in_flight(),
        # Both verify reads, before every broader describe-services rule.
        *_verify(),
        *_mains_verify("post-shift"),
        *_primary(NEW, NEW, TARGET),
        *_create_and_approve(["InProgress", "Ready", "InProgress"]),
        *dashboard_rules(
            [svc(dep(DASH_OLD, "ecs-svc/6000"))],
            before=svc(dep(DASH_NEW, "ecs-svc/7777")),
            update={
                "service": svc(
                    dep(DASH_OLD, "ecs-svc/6000", state="IN_PROGRESS", running=0),
                    dep(DASH_NEW, "ecs-svc/7777", status="ACTIVE"),
                )
            },
        ),
        # scripts/api_serving.py: the bad release serves when the stop step
        # reads (so this is a rollback to do), and the target by the time the
        # summary reads (it is only read when verify did not pass).
        *api_rules([AFTER, BEFORE], RULES_GREEN)[:3],
        rule("elbv2 describe-rules", answers=[RULES_GREEN, RULES_BLUE]),
    ]


@pytest.mark.regression
@pytest.mark.parametrize("step", ["this", "mains"], ids=["this-step", "mains-step"])
def test_a_rollback_after_a_shift_rolls_the_dashboard_back_too(runner, step):
    """End to end from the stop step, post-shift: the API verify step passes
    and the dashboard leg runs, so the headline says both were rolled back.
    With main's verify step in its place it is run 37176250648 again: verify
    red on "4 of 2", the dashboard skipped, and the headline naming the split.
    """
    outputs, results, summary = _run_from_stop(
        runner,
        _end_to_end_rules(),
        dashboard=DASHBOARD,
        dashboard_target={"arn": DASH_OLD, "expect": DASH_NEW},
        replace={VERIFY_STEP: MAINS_VERIFY} if step == "mains" else None,
        DASHBOARD_ROLLOUT_POLL_SECONDS="0",
        DASHBOARD_ROLLOUT_DEADLINE_SECONDS="3",
        SUMMARY_SERVING_POLL_SECONDS="0",
    )
    headline = _headline(summary)
    if step == "this":
        assert outputs["api-verify"]["__outcome__"] == "success", results[VERIFY_STEP]
        assert outputs["dashboard-rollback"]["__outcome__"] == "success"
        assert headline == (
            "## Rollback of staging: ROLLED BACK: API rolled back to "
            f"experimentation-backend-staging:42 (CodeDeploy deployment {ROLLBACK_ID}, "
            "verified); dashboard rolled back to experimentation-dashboard-staging:6. "
            f"{_t32(ROLLBACK_ID)}"
        ), headline
    else:
        assert outputs["api-verify"]["__outcome__"] == "failure"
        assert "4 of 2 tasks are running" in results[VERIFY_STEP][1]
        assert outputs["dashboard-rollback"]["__outcome__"] == "skipped"
        assert headline == (
            f"## Rollback of {SERVING_ON_TARGET} (its verify step: failure); "
            f"{DIFFERENT_RELEASES}."
        ), headline


@pytest.mark.regression
def test_a_verify_rule_after_api_rules_is_not_answered_by_them(runner):
    """The rule-order hazard (PE condition 8): api_rules()' describe-services
    rule also matches the verify call. A scenario that puts it first must
    fail, not pass on api_rules' JSON."""
    rules = [
        *_nothing_in_flight(),
        *_primary(NEW, NEW, TARGET),
        *_create_and_approve(["InProgress", "Ready", "InProgress"]),
        *api_rules(AFTER, RULES_GREEN),
        *_verify(),
    ]
    outputs, results, _ = _run_from_stop(runner, rules)
    assert outputs["api-verify"]["__outcome__"] == "failure", results[VERIFY_STEP]


# --- FAKE_AWS's query mode prints what the CLI prints (#816, PE condition 6) ------------
#
# Every expected string below is aws-cli 2.28.24's own output, captured by
# running it against a local stub endpoint that answered the same documents
# (no AWS call). The fake is only as good as this table: a shape not in it is
# refused (exit 98), not guessed.

NINE_FIELDS = (
    "services[0].[length(taskSets[?status=='PRIMARY']), "
    "taskSets[?status=='PRIMARY'] | [0].taskDefinition, "
    "taskSets[?status=='PRIMARY'] | [0].runningCount, "
    "taskSets[?status=='PRIMARY'] | [0].computedDesiredCount, "
    "taskSets[?status=='PRIMARY'] | [0].pendingCount, "
    "taskSets[?status=='PRIMARY'] | [0].scale.value, "
    "desiredCount, runningCount, length(taskSets)]"
)
#: The plan's seven-field draft, as the principal engineer captured it.
SEVEN_FIELDS = (
    "services[0].[length(taskSets[?status=='PRIMARY']), "
    "taskSets[?status=='PRIMARY'] | [0].taskDefinition, "
    "taskSets[?status=='PRIMARY'] | [0].runningCount, "
    "taskSets[?status=='PRIMARY'] | [0].computedDesiredCount, "
    "taskSets[?status=='PRIMARY'] | [0].pendingCount, "
    "runningCount, length(taskSets)]"
)
MAINS_QUERY = (
    "services[0].[taskSets[?status=='PRIMARY'].taskDefinition | [0], "
    "runningCount, desiredCount]"
)
LENGTH_OF_NONE = (
    "\nIn function length(), invalid type for value: None, expected one of: "
    "['string', 'array', 'object'], received: \"null\"\n"
)


def _json(*values: Any) -> str:
    return "[\n" + ",\n".join(f"    {v}" for v in values) + "\n]\n"


@pytest.mark.regression
@pytest.mark.parametrize(
    "name, query, output, rc, stdout, stderr",
    [
        (
            "post-shift",
            NINE_FIELDS,
            "text",
            0,
            f"1\t{OLD}\t2\t2\t0\t100.0\t2\t4\t2\n",
            "",
        ),
        (
            "empty-primary",
            NINE_FIELDS,
            "text",
            0,
            f"1\t{OLD}\t0\t2\t2\t100.0\t2\t2\t2\n",
            "",
        ),
        ("short", NINE_FIELDS, "text", 0, f"1\t{OLD}\t1\t2\t1\t100.0\t2\t3\t2\n", ""),
        (
            "two-primary",
            NINE_FIELDS,
            "text",
            0,
            f"2\t{OLD}\t2\t2\t0\t100.0\t2\t4\t2\n",
            "",
        ),
        (
            "no-primary",
            NINE_FIELDS,
            "text",
            0,
            "0\tNone\tNone\tNone\tNone\tNone\t2\t4\t2\n",
            "",
        ),
        ("missing-service", NINE_FIELDS, "text", 0, "None\n", ""),
        (
            "desired-0",
            NINE_FIELDS,
            "text",
            0,
            f"1\t{OLD}\t0\t0\t0\t100.0\t2\t4\t2\n",
            "",
        ),
        ("no-task-sets-key", NINE_FIELDS, "text", 255, "", LENGTH_OF_NONE),
        (
            "desired-none",
            NINE_FIELDS,
            "text",
            0,
            f"1\t{OLD}\t2\tNone\t0\t100.0\t2\t4\t2\n",
            "",
        ),
        (
            "pending-none",
            NINE_FIELDS,
            "text",
            0,
            f"1\t{OLD}\t2\t2\tNone\t100.0\t2\t4\t2\n",
            "",
        ),
        ("scale-50", NINE_FIELDS, "text", 0, f"1\t{OLD}\t1\t1\t0\t50.0\t2\t4\t2\n", ""),
        (
            "post-shift",
            NINE_FIELDS,
            "json",
            0,
            _json(1, f'"{OLD}"', 2, 2, 0, "100.0", 2, 4, 2),
            "",
        ),
        (
            "no-primary",
            NINE_FIELDS,
            "json",
            0,
            _json(0, "null", "null", "null", "null", "null", 2, 4, 2),
            "",
        ),
        ("missing-service", NINE_FIELDS, "json", 0, "null\n", ""),
        ("no-task-sets-key", NINE_FIELDS, "json", 255, "", LENGTH_OF_NONE),
        ("post-shift", SEVEN_FIELDS, "text", 0, f"1\t{OLD}\t2\t2\t0\t4\t2\n", ""),
        (
            "no-primary",
            SEVEN_FIELDS,
            "text",
            0,
            "0\tNone\tNone\tNone\tNone\t4\t2\n",
            "",
        ),
        ("missing-service", SEVEN_FIELDS, "text", 0, "None\n", ""),
        ("post-shift", MAINS_QUERY, "text", 0, f"{OLD}\t4\t2\n", ""),
        ("empty-primary", MAINS_QUERY, "text", 0, f"{OLD}\t2\t2\n", ""),
        ("missing-service", MAINS_QUERY, "text", 0, "None\n", ""),
    ],
)
def test_the_fakes_query_mode_prints_what_the_cli_prints(
    runner, name, query, output, rc, stdout, stderr
):
    """Planted defects: join the text fields with a space, or print `null`
    for None in text; each fails rows here."""
    runner.scenario([rule("ecs describe-services", answers=[_doc(name)], query=True)])
    result = _fake_aws(runner, query, output)
    assert (result.returncode, result.stdout, result.stderr) == (rc, stdout, stderr)


@pytest.mark.parametrize(
    "query, output",
    [
        # A nested list: the CLI's text output reorders it.
        ("services[0].[taskSets[*].runningCount, desiredCount]", "text"),
        # A dict, and an empty list: not measured.
        ("services[0].deploymentController", "text"),
        ("services[0].taskSets[?status=='DRAINING']", "text"),
        (NINE_FIELDS, "table"),
    ],
    ids=["nested-list", "dict", "empty-list", "table"],
)
def test_the_fakes_query_mode_refuses_what_was_not_measured(runner, query, output):
    runner.scenario([rule("ecs describe-services", answers=[_doc()], query=True)])
    result = _fake_aws(runner, query, output)
    assert result.returncode == 98, result
    assert result.stdout == ""
    assert result.stderr.startswith("fake aws: query mode "), result.stderr


def _fake_aws(runner: Runner, query: str, output: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            str(runner.bin / "aws"),
            "ecs",
            "describe-services",
            "--cluster",
            "experimentation-staging",
            "--services",
            "experimentation-backend-staging",
            "--query",
            query,
            "--output",
            output,
        ],
        env={**os.environ, "FAKE_AWS_STATE": str(runner.state)},
        capture_output=True,
        text=True,
        timeout=60,
    )
