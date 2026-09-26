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

import re
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
from backend.tests.unit.infrastructure.test_forward_deploy_completes import (
    AFTER,
    BEFORE,
    NEW,
    OLD,
    RULES_BLUE,
    RULES_GREEN,
)

pytestmark = pytest.mark.skipif(
    not ROLLBACK.is_file(), reason="this tree has no .github/workflows"
)

#: The revision rolled back TO: the one before the bad deploy.
TARGET = OLD
ROLLBACK_ID = "d-ROLLBACK1"
BAD_ID = "d-BADDEPLOY"
CD_ROLLBACK_ID = "d-CDROLLBACK"
PRIMARY_QUERY = "taskSets[?status=='PRIMARY'].taskDefinition"


@pytest.fixture
def runner(tmp_path: Path) -> Runner:
    runner = Runner(tmp_path)
    # The wait loops sleep between polls; the verdict, not the wait, is
    # under test.
    sleep = runner.bin / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    return runner


# --- a minimal evaluator for the `if:` expressions rollback.yml uses ------------------

_CLAUSE = re.compile(
    r"^(steps\.([\w-]+)\.(?:outputs\.([\w-]+)|(outcome))|inputs\.([\w-]+))"
    r"\s*(==|!=)\s*'([^']*)'$"
)


def _should_run(
    step: dict, outputs: dict[str, dict[str, str]], inputs: dict, failed: bool
) -> bool:
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
        _, sid, key, outcome, inp, op, literal = match.groups()
        if inp:
            value = inputs.get(inp, "")
        elif outcome:
            value = outputs.get(sid, {}).get("__outcome__", "")
        else:
            value = outputs.get(sid, {}).get(key, "")
        result = result and ((value == literal) == (op == "=="))
    return result if status_function else (result and not failed)


def _run_from_stop(
    runner: Runner, rules: list, dashboard: str = ""
) -> tuple[dict[str, dict[str, str]], dict[str, tuple[int, str]], str]:
    """Run every `run:` step from the stop step to the end, as the runner
    would. Returns (outputs by step id, (exit, log) by step name, summary)."""
    runner.scenario(rules)
    inputs = {"dashboard_task_definition_arn": dashboard, "reason": "bad release"}
    outputs: dict[str, dict[str, str]] = {
        "target": {"arn": TARGET, "__outcome__": "success"},
        "dashboard-target": {"__outcome__": "success"},
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
        code, log, written, step_summary = runner.run(
            ROLLBACK,
            step,
            outputs,
            {**inputs, "job.status": "failure" if failed else "success"},
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


def _verify(serving: str = TARGET) -> list:
    return [
        rule(
            "ecs describe-services",
            "runningCount, desiredCount",
            answers=[f"{serving}\t2\t2"],
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
    assert "API NOT rolled back: it was already on" in headline, headline
    assert "API rolled back to" not in headline


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
    assert f"deployment {ROLLBACK_ID}" in log and "approved by this run" in log
    assert "API rolled back to experimentation-backend-staging:42" in _headline(summary)


def test_the_loop_reports_whether_it_approved_when_it_times_out(runner):
    """Never Ready inside the deadline: a failure that says it never approved,
    not a success because PRIMARY happened to be the target."""
    runner.scenario(
        [
            *_primary(TARGET),
            *_create_and_approve(["InProgress"]),
        ]
    )
    step = _step(ROLLBACK, "Shift traffic and wait for it to land")
    code, log, _, _ = runner.run(
        ROLLBACK,
        step,
        {"target": {"arn": TARGET}, "codedeploy": {"deployment-id": ROLLBACK_ID}},
        ROLLBACK_TIMEOUT_SECONDS="0",
    )
    assert code == 1, log
    assert "approved by this run: no" in log


# --- the stop step refuses CodeDeploy's own rollback (PE condition 3, UX W9) ----------


def _in_flight(*deployments: tuple[str, str]) -> list:
    """(id, the creator/rollback line get-deployment prints) for each."""
    rules = [
        rule(
            "deploy list-deployments",
            answers=["\t".join(d for d, _ in deployments)],
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
    assert (
        f"API NOT rolled back: CodeDeploy's own rollback {CD_ROLLBACK_ID} is still "
        "active, so this run stopped nothing (the API is on "
        "experimentation-backend-staging:43)" in headline
    ), headline
    notify = _step(ROLLBACK, "Notify rollback result")
    assert notify["if"] == "always()"
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
    step already reverted the API", which cannot be true here."""
    runner.scenario(dashboard_rules([]))
    outputs = {
        "target": {"arn": TARGET},
        "stop": {
            "refused": "codeDeployRollback",
            "refused_id": CD_ROLLBACK_ID,
            "primary": "experimentation-backend-staging:43",
            "__outcome__": "failure",
        },
        "codedeploy": {"__outcome__": "skipped"},
        "dashboard-rollback": {"__outcome__": "skipped"},
    }
    inputs = {
        "dashboard_task_definition_arn": "experimentation-dashboard-staging:6",
        "job.status": "failure",
    }
    code, out, written, summary = runner.run(
        ROLLBACK, _step(ROLLBACK, "Run summary"), outputs, inputs
    )
    assert code == 0, out
    assert "the API half refused, and nothing was stopped" in summary, summary
    assert "If the stop step already reverted the API" not in summary
    assert written["slack"].endswith("dashboard NOT rolled back (not reached)")
