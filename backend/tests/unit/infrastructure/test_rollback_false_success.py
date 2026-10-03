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
PRIMARY_QUERY = "taskSets[?status=='PRIMARY'].taskDefinition"


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
        rule(
            "ecs describe-services",
            "runningCount, desiredCount",
            answers=[f"{TARGET}\t1\t2"],
        ),
        *api_rules(BEFORE, RULES_BLUE),
        *dashboard_rules([]),
    ]
    outputs, results, summary = _run_from_stop(
        runner, rules, dashboard="experimentation-dashboard-staging:6"
    )
    assert outputs["stop"]["already_serving"] == "true"
    assert outputs["api-verify"]["__outcome__"] == "failure"
    assert outputs["dashboard-rollback"]["__outcome__"] == "skipped"
    assert "ecs update-service" not in _ops(runner)
    code, log = results["Refuse a rollback to the revision already serving"]
    assert code == 1, log
    assert (
        "The dashboard half did not run: an earlier step failed; see above." in log
    ), log
    assert "ran as asked" not in log
    headline = _headline(summary)
    assert "API NOT rolled back: it was already on" in headline, headline
    assert "dashboard NOT rolled back" in headline, headline


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
    assert code == 0, out
    assert "the API half refused, and nothing was stopped" in summary, summary
    assert "If the stop step already reverted the API" not in summary
    assert outputs["summary"]["slack"].endswith(
        "dashboard NOT rolled back (not reached)"
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
    "staging: API is serving experimentation-backend-staging:42, read at the end "
    "of the run, but this run did not finish its own steps"
)
DIFFERENT_RELEASES = (
    "dashboard NOT rolled back (not reached), so the API and dashboard are on "
    "different releases: put the dashboard back with "
    "docs/deployment/rollback-runbook.md Method 2, the dashboard block"
)
NOT_CONFIRMED = (
    "staging: API not confirmed on experimentation-backend-staging:42 at the end "
    "of the run (scripts/api_serving.py exit "
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
        rule("deploy list-deployments", answers=[BAD_ID]),
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
    expected = f"{SERVING_ON_TARGET} (its verify step: skipped); {DIFFERENT_RELEASES}"
    assert headline == f"## Rollback of {expected}", headline
    assert outputs["summary"]["slack"] == expected
    assert _read_exit(summary) == "0"
    # Stopped at the first 0.
    assert len(_serving_reads(runner)) == 1, runner.calls()
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
            "NOT YET: the PRIMARY task set runs experimentation-backend-staging:42; ",
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
    """EM C5(b): exit 1 is also a listener mid-reroute, so the headline says
    "not confirmed" and quotes api_serving.py, never "NOT rolled back".
    Polled to the limit on 1, decided on the last answer. Planted defect: map
    a non-zero read to the retired string."""
    outputs = {
        "target": {"arn": TARGET},
        "stop": {"__outcome__": "success"},
        "codedeploy": {"__outcome__": "failure"},
        "api-verify": {"__outcome__": "skipped"},
    }
    code, out, written, summary = _run_summary(
        runner, api_rules(services, rules_answer), outputs, SUMMARY_SERVING_POLLS="4"
    )
    assert code == 0, out
    assert _read_exit(summary) == "1"
    assert len(_serving_reads(runner)) == 4, runner.calls()
    slack = written["slack"]
    assert slack.startswith(f"{NOT_CONFIRMED}1: {sentence}"), slack
    assert slack.endswith(
        "; this run did not finish its own steps (its verify step: skipped); "
        "dashboard left as it is"
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
    assert code == 0, out
    assert runner.calls() == [], runner.calls()
    assert "| API at the end of the run |" not in summary
    assert written["slack"].startswith("staging: API NOT rolled back: "), written


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
    ]
    code, out, written, summary = _run_summary(
        runner, rules, outputs, SUMMARY_SERVING_POLLS="2"
    )
    assert code == 0, out
    assert _read_exit(summary) == "2"
    assert len(_serving_reads(runner)) == 2, runner.calls()
    assert written["slack"].startswith(
        f"{NOT_CONFIRMED}2: UNKNOWN: could not tell: "
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
    rules = [*dashboard_rules([]), *api_rules(BEFORE, RULES_BLUE)]
    code, out, written, summary = _run_summary(
        runner, rules, outputs, dashboard=DASHBOARD
    )
    assert code == 0, out
    assert _read_exit(summary) == "0"
    assert written["slack"] == (
        f"{SERVING_ON_TARGET} (its verify step: skipped); {DIFFERENT_RELEASES}"
    )
    assert (
        "the API and dashboard are on different releases, the newer-dashboard"
        in summary
    )
    assert (
        f"Do not dispatch Rollback again while CodeDeploy deployment {ROLLBACK_ID} "
        "is active" in summary
    )


def test_an_unresolved_target_keeps_todays_copy_and_reads_nothing(runner):
    """EM C4: no target resolved, nothing to read against."""
    outputs = {"api-verify": {"__outcome__": "skipped"}}
    code, out, written, summary = _run_summary(
        runner, api_rules(BEFORE, RULES_BLUE), outputs
    )
    assert code == 0, out
    assert runner.calls() == []
    assert written["slack"] == (
        "staging: API NOT rolled back (its verify step: skipped); dashboard left as it is"
    )


def test_the_poll_starts_no_read_after_its_deadline(runner):
    """EM C7: the wall-clock bound. With the deadline already passed, one
    read is made and decided on, whatever the poll count."""
    outputs = {"target": {"arn": TARGET}, "api-verify": {"__outcome__": "failure"}}
    code, out, written, summary = _run_summary(
        runner,
        api_rules(AFTER, RULES_GREEN),
        outputs,
        SUMMARY_SERVING_POLLS="12",
        SUMMARY_SERVING_DEADLINE_SECONDS="0",
    )
    assert code == 0, out
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
