"""A transient AWS error no longer ends a rollback mid-wait (#215).

rollback.yml's wait loops read CodeDeploy and ECS with plain assignments under
`set -e`, so one ThrottlingException ended the rollback with a bare exit 254
and no `::error::`, mid-incident. Now a failed read is "could not read, read
again on the next poll"; it never approves, fails or finishes anything, and
a bounded run of failures in a row ends the step with a labelled error that
names the deployment and the command to check it by hand.

Driven through the workflow's own `run:` scripts with
test_rollback_false_success.py's harness: a fake `aws` answering from a
scenario, a no-op `sleep` and a clock that advances a second per `date` call.
"""

from __future__ import annotations

import re

import pytest

from backend.tests.unit.infrastructure.test_dashboard_deploy_wiring import (
    ROLLBACK,
    _step,
    rule,
)
from backend.tests.unit.infrastructure.test_forward_deploy_completes import NEW
from backend.tests.unit.infrastructure.test_rollback_false_success import (
    BAD_ID,
    PRIMARY_QUERY,
    ROLLBACK_ID,
    TARGET,
    _ops,
    _primary,
    _shift,
    runner,
)

pytestmark = pytest.mark.skipif(
    not ROLLBACK.is_file(), reason="this tree has no .github/workflows"
)

THROTTLE = {
    "error": "An error occurred (ThrottlingException) when calling the "
    "GetDeployment operation (reached max retries: 2): Rate exceeded"
}
#: The shift step gives up after this many polls in a row with a failed read.
SHIFT_LIMIT = 6
#: The stop step's wait gives up after this many failed reads in a row.
STOP_LIMIT = 12
CHECK_BY_HAND = f"aws deploy get-deployment --deployment-id {ROLLBACK_ID}"


def _statuses(*answers) -> dict:
    return rule(
        "deploy get-deployment",
        ROLLBACK_ID,
        "deploymentInfo.status",
        answers=list(answers),
    )


def _error_line(log: str) -> str:
    (line,) = [
        x
        for x in log.splitlines()
        if x.startswith("::error title=Rollback could not read AWS::")
    ]
    return line


@pytest.mark.regression
def test_one_throttle_on_get_deployment_then_the_rollback_completes(runner):
    """The issue's case. Planted defect: main's loop, where the throttled
    read ended the step with exit 254 and no `::error::`."""
    code, log = _shift(
        runner,
        [
            *_primary(NEW, TARGET),
            _statuses(THROTTLE, "Ready", "InProgress"),
            rule("deploy continue-deployment", ROLLBACK_ID, answers=[""]),
        ],
    )
    assert code == 0, log
    assert "ThrottlingException" in log and "reading again on the next poll" in log
    assert f"traffic is on {TARGET}" in log and "approved by this run" in log
    assert _ops(runner).count("deploy continue-deployment") == 1


@pytest.mark.regression
def test_a_throttle_on_describe_services_is_read_again(runner):
    code, log = _shift(
        runner,
        [
            rule("ecs describe-services", PRIMARY_QUERY, answers=[THROTTLE, TARGET]),
            _statuses("Ready", "InProgress"),
            rule("deploy continue-deployment", ROLLBACK_ID, answers=[""]),
        ],
    )
    assert code == 0, log
    assert f"traffic is on {TARGET}" in log


@pytest.mark.regression
def test_persistent_throttling_ends_with_a_labelled_error_not_a_crash(runner):
    long_error = {"error": "An error occurred (ThrottlingException) " + "x" * 500}
    code, log = _shift(runner, [*_primary(TARGET), _statuses(long_error)])
    assert code == 1, log  # not 254, the aws CLI's own exit status
    line = _error_line(log)
    assert f"polls in a row could not read rollback deployment {ROLLBACK_ID}" in line
    assert "It did not stop the deployment" in line
    assert "This run had not seen the traffic shift approved" in line
    assert line.endswith(f"Check it by hand: {CHECK_BY_HAND}"), line
    # The last AWS error is in it, bounded.
    (error,) = re.findall(r"The last AWS error: (.*?)\. Check it by hand", line)
    assert error.startswith("An error occurred (ThrottlingException)")
    assert len(error) == 200
    # Exactly the limit: every failed poll counted, none after the verdict.
    polls = [c for c in runner.calls() if c[:2] == ["deploy", "get-deployment"]]
    assert len(polls) == SHIFT_LIMIT, polls
    assert "traffic is on" not in log


@pytest.mark.regression
def test_a_successful_read_resets_the_count(runner):
    """Five failed polls, a good one, five more: never six in a row, so the
    loop keeps going and completes."""
    statuses = (
        [THROTTLE] * 5 + ["InProgress"] + [THROTTLE] * 5 + ["Ready", "InProgress"]
    )
    code, log = _shift(
        runner,
        [
            *_primary(TARGET),
            _statuses(*statuses),
            rule("deploy continue-deployment", ROLLBACK_ID, answers=[""]),
        ],
    )
    assert code == 0, log
    assert "Rollback could not read AWS" not in log
    assert "approved by this run" in log


@pytest.mark.regression
def test_a_throttle_on_the_re_read_after_a_failed_continue_is_read_again(runner):
    """#214's re-read after a failed continue-deployment. Planted defect: the
    re-read as a plain assignment, which ended the step with exit 254."""
    code, log = _shift(
        runner,
        [
            *_primary(TARGET),
            _statuses("Ready", THROTTLE, "InProgress"),
            rule(
                "deploy continue-deployment",
                answers=[{"error": "DeploymentIsNotInReadyStateException"}],
            ),
        ],
    )
    assert code == 0, log
    assert (
        f"{ROLLBACK_ID}'s status could not be read again: the next poll decides" in log
    )
    # The next good read decides: seen Ready, now InProgress.
    assert "approved outside this run: seen Ready, now InProgress" in log


@pytest.mark.regression
def test_a_failed_re_read_is_no_approval_credit(runner):
    """Ready, continue-deployment fails, and every read after it fails. A
    failed read is not "left Ready", so nothing is approved and the target
    being PRIMARY (the stop step's auto-rollback) is not success."""
    code, log = _shift(
        runner,
        [
            rule("ecs describe-services", PRIMARY_QUERY, answers=[TARGET, THROTTLE]),
            _statuses("Ready", THROTTLE),
            rule(
                "deploy continue-deployment",
                answers=[{"error": "DeploymentIsNotInReadyStateException"}],
            ),
        ],
    )
    assert code == 1, log
    assert "traffic is on" not in log
    assert "left Ready" not in log
    line = _error_line(log)
    assert "This run had not seen the traffic shift approved" in line
    assert line.endswith(f"Check it by hand: {CHECK_BY_HAND}")


@pytest.mark.regression
def test_a_stale_serving_read_is_no_success(runner):
    """The target was PRIMARY before this run's approval (the T31 bake case);
    after the approval every describe-services fails. The earlier read must
    not stand in for the failed ones: no success, only the labelled error."""
    code, log = _shift(
        runner,
        [
            rule("ecs describe-services", PRIMARY_QUERY, answers=[TARGET, THROTTLE]),
            _statuses("InProgress", "Ready", "InProgress"),
            rule("deploy continue-deployment", ROLLBACK_ID, answers=[""]),
        ],
    )
    assert code == 1, log
    assert "traffic is on" not in log
    assert _ops(runner).count("deploy continue-deployment") == 1
    line = _error_line(log)
    assert "The traffic shift was approved by this run." in line


@pytest.mark.regression
def test_a_failed_read_of_a_failed_deployments_error_still_says_it_failed(runner):
    code, log = _shift(
        runner,
        [
            *_primary(NEW),
            _statuses("Failed"),
            rule("deploy get-deployment", "errorInformation", answers=[THROTTLE]),
        ],
    )
    assert code == 1, log
    assert f"::error::rollback deployment {ROLLBACK_ID} is Failed" in log
    assert "(its error information could not be read)" in log


# --- the stop step's wait for the deployments it stopped ------------------------------


def _stop_step(runner, statuses: list):
    runner.scenario(
        [
            rule("deploy list-deployments", answers=[BAD_ID]),
            rule("deploy get-deployment", BAD_ID, "creator", answers=["user\tNone"]),
            rule("deploy stop-deployment", BAD_ID, answers=[""]),
            rule(
                "deploy get-deployment",
                BAD_ID,
                "deploymentInfo.status",
                answers=statuses,
            ),
        ]
    )
    step = _step(ROLLBACK, "Stop any deployment already in flight")
    code, log, _, _ = runner.run(ROLLBACK, step, {"target": {"arn": TARGET}})
    return code, log


@pytest.mark.regression
def test_the_stop_steps_wait_reads_again_after_a_throttle(runner):
    code, log = _stop_step(runner, [THROTTLE, "InProgress", THROTTLE, "Stopped"])
    assert code == 0, log
    assert f"{BAD_ID} is Stopped" in log


@pytest.mark.regression
def test_the_stop_steps_wait_ends_labelled_on_persistent_throttling(runner):
    code, log = _stop_step(runner, [THROTTLE])
    assert code == 1, log
    line = _error_line(log)
    assert f"reads in a row of deployment {BAD_ID} failed" in line
    assert "created no rollback deployment" in line
    assert line.endswith(f"aws deploy get-deployment --deployment-id {BAD_ID}")
    polls = [
        c
        for c in runner.calls()
        if c[:2] == ["deploy", "get-deployment"] and "deploymentInfo.status" in c
    ]
    assert len(polls) == STOP_LIMIT, polls
