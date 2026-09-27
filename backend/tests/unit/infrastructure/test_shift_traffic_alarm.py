"""The forward deploy tells an alarm rollback apart from a failure (#148 PR-2).

Once the deployment group has alarms (infrastructure/tests/
test_codedeploy_alarms.py), CodeDeploy stops a deployment whose alarm goes
into ALARM and, with auto-rollback, moves the API back by itself. Before this,
`scripts/shift_traffic.py` reported that as a generic `failed` -- or, when the
rule was put back a moment before the status changed, as `wrong-route`, whose
copy sends the operator to Rollback: a second rollback of a release CodeDeploy
is already rolling back.

The fixtures here are INVENTED: the shape of errorInformation, rollbackInfo and
the order in which CodeDeploy reverts the rule, PRIMARY and the status on an
alarm stop have not been observed in a real account yet. They are to be
replaced with captured output from the first staging rehearsal.

The fake `aws`, the ticks and the fixtures are test_forward_deploy_completes'.
"""

from __future__ import annotations

import importlib.util

import pytest

from .test_forward_deploy_completes import (
    AFTER,
    BEFORE,
    CLUSTER,
    DEPLOYMENT,
    NEW,
    RULES_BLUE,
    SERVICE,
    SHIFT,
    _continues,
    _ops,
    _split,
    aws,
    tick,
)

BLUE_ALARM = "experimentation-api-5xx-blue-staging"
GREEN_ALARM = "experimentation-api-5xx-green-staging"
ROLLBACK_ID = "d-ROLLBACK42"
#: What the tests assume CodeDeploy's message looks like. Invented (see above).
MESSAGE = (
    f"One or more alarms have been activated according to the Amazon CloudWatch "
    f"metrics you selected, and the affected deployments have been stopped. "
    f"Activated alarms: <{GREEN_ALARM}>"
)


def alarm_tick(
    status: str = "Stopped",
    *,
    services: dict = BEFORE,
    rules: dict = RULES_BLUE,
    message: str = MESSAGE,
    rollback: bool = True,
) -> dict:
    """A deployment CodeDeploy stopped for an alarm."""
    answer = tick(status, services, rules)
    info = answer["deploy get-deployment"]["deploymentInfo"]
    info["errorInformation"] = {"code": "ALARM_ACTIVE", "message": message}
    if rollback:
        info["rollbackInfo"] = {
            "rollbackDeploymentId": ROLLBACK_ID,
            "rollbackMessage": f"Deployment rolled back by {ROLLBACK_ID}",
        }
    return answer


def _shift(aws, ticks: list[dict], *extra: str):
    return aws(
        SHIFT,
        [
            "--deployment-id",
            DEPLOYMENT,
            "--cluster",
            CLUSTER,
            "--service",
            SERVICE,
            "--task-definition",
            NEW,
            "--deadline-seconds",
            "3600",
            "--interval-seconds",
            "0",
            "--alarm",
            BLUE_ALARM,
            "--alarm",
            GREEN_ALARM,
            *extra,
        ],
        {"ticks": ticks},
    )


def _polls(calls) -> int:
    return _ops(calls).count("deploy get-deployment")


@pytest.mark.regression
@pytest.mark.parametrize("status", ["Stopped", "Failed"])
def test_an_alarm_stop_after_approval_names_the_alarm_and_the_rollback(aws, status):
    """P9a/P9b, UX W1/C1: `alarm`, the alarm's name, the rollback deployment,
    and no advice to use Rollback."""
    code, out, calls, outputs = _shift(
        aws,
        [
            tick("Ready"),
            tick("InProgress", BEFORE, _split(90, 10)),
            alarm_tick(status),
        ],
    )
    assert code == 1, out
    assert outputs == {"approved": "true", "result": "alarm", "alarms": GREEN_ALARM}
    assert "::error title=Rolled back by an alarm::" in out
    assert f"because {GREEN_ALARM} went into ALARM" in out
    assert ROLLBACK_ID in out
    assert "This run stopped nothing" in out
    assert "Do not dispatch Rollback for this" in out
    assert "docs/deployment/rollback-runbook.md#an-alarm-rolled-the-api-back" in out
    assert "rollback line" not in out and "Roll back with" not in out
    assert "override" not in out.lower()
    assert not [c for c in calls if "stop-deployment" in c]


@pytest.mark.regression
def test_a_route_reverted_by_an_alarm_rollback_is_not_a_wrong_route(aws):
    """P9c, PE condition 5: the rule is back on blue while the status still says
    InProgress for K-1 more reads, then Stopped for an alarm. K is 6; a grace of
    one read (the tamper K=1) ends this as wrong-route."""
    reverted = [tick("InProgress", AFTER, RULES_BLUE) for _ in range(5)]
    code, out, calls, outputs = _shift(
        aws,
        [
            tick("Ready"),
            tick("InProgress", AFTER, _split(10, 90)),
            *reverted,
            alarm_tick("Stopped"),
        ],
    )
    assert code == 1, out
    assert outputs["result"] == "alarm", out
    assert "wrong-route" not in outputs.values()
    assert "Rolled back by an alarm" in out
    assert _polls(calls) == 8


@pytest.mark.regression
def test_the_wrong_route_grace_is_bounded(aws):
    """The grace ends: a rule that stays on the other group is wrong-route after
    K consecutive reads, and that copy says to check for an alarm first."""
    code, out, calls, outputs = _shift(
        aws, [tick("Ready"), tick("InProgress", AFTER, RULES_BLUE)]
    )
    assert code == 1, out
    assert outputs == {"approved": "true", "result": "wrong-route"}
    assert _polls(calls) == 1 + 6
    assert len(_continues(calls)) == 1
    assert (
        f"First check aws deploy get-deployment --deployment-id {DEPLOYMENT}: if it "
        "is Stopped with ALARM_ACTIVE, CodeDeploy is already rolling the API back, "
        "so do not dispatch Rollback" in out
    )


def test_the_grace_is_six_reads_and_a_parameter():
    spec = importlib.util.spec_from_file_location("shift_traffic", SHIFT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.WRONG_ROUTE_GRACE_POLLS == 6


def test_a_grace_of_one_read_is_the_old_behaviour(aws):
    """The same scenario as the P9c test, with the grace set to 1 on the command
    line: it is wrong-route. This is the tamper, run as a test."""
    reverted = [tick("InProgress", AFTER, RULES_BLUE) for _ in range(5)]
    code, out, _, outputs = _shift(
        aws,
        [
            tick("Ready"),
            tick("InProgress", AFTER, _split(10, 90)),
            *reverted,
            alarm_tick("Stopped"),
        ],
        "--wrong-route-grace-polls",
        "1",
    )
    assert code == 1
    assert outputs["result"] == "wrong-route", out


@pytest.mark.regression
def test_no_rollback_is_claimed_without_rollback_info(aws):
    """P9d: CodeDeploy reported no rollback, so the copy does not claim one."""
    code, out, _, outputs = _shift(
        aws,
        [tick("Ready"), alarm_tick("Stopped", rollback=False)],
    )
    assert code == 1
    assert outputs["result"] == "alarm"
    assert "no rollbackInfo" in out
    assert "moving the API back" not in out
    assert "auto-rollback puts" not in out
    assert f"python3 scripts/api_serving.py {CLUSTER} {SERVICE} {NEW}" in out


@pytest.mark.regression
def test_an_alarm_before_the_approval_says_nothing_shifted(aws):
    """P9e, UX C2: never approved, so nothing shifted and nothing rolls back."""
    code, out, calls, outputs = _shift(
        aws, [tick("InProgress"), alarm_tick("Stopped", rollback=False)]
    )
    assert code == 1
    assert outputs == {"result": "alarm", "alarms": GREEN_ALARM}
    assert not _continues(calls)
    assert "before any traffic shifted" in out
    assert "the previous revision keeps serving" in out
    assert (
        "docs/deployment/rollback-runbook.md#fix-forward-while-an-alarm-is-firing"
        in out
    )
    assert "override" not in out.lower()


@pytest.mark.regression
@pytest.mark.parametrize(
    "message, alarms, expected",
    [
        (
            "Activated alarms: <something CodeDeploy did not name>",
            ["--alarm", BLUE_ALARM, "--alarm", GREEN_ALARM],
            f"one of the deployment group's alarms ({BLUE_ALARM}, {GREEN_ALARM})",
        ),
        ("", ["--alarm", BLUE_ALARM, "--alarm", GREEN_ALARM], None),
        ("", [], "one of the deployment group's alarms"),
        (f"<{BLUE_ALARM}> <{GREEN_ALARM}>", [], "one of the deployment group's alarms"),
        (
            f"<{BLUE_ALARM}> <{GREEN_ALARM}>",
            ["--alarm", BLUE_ALARM, "--alarm", GREEN_ALARM],
            f"{BLUE_ALARM}, {GREEN_ALARM}",
        ),
    ],
    ids=["unnamed", "empty-message", "nothing-known", "names-not-passed", "both"],
)
def test_the_alarm_is_never_an_empty_name(aws, message, alarms, expected):
    """UX C3: the copy never prints an empty name; it falls back."""
    if expected is None:
        expected = f"one of the deployment group's alarms ({BLUE_ALARM}, {GREEN_ALARM})"
    code, out, _, outputs = aws(
        SHIFT,
        [
            "--deployment-id",
            DEPLOYMENT,
            "--cluster",
            CLUSTER,
            "--service",
            SERVICE,
            "--task-definition",
            NEW,
            "--deadline-seconds",
            "3600",
            "--interval-seconds",
            "0",
            *alarms,
        ],
        {"ticks": [tick("Ready"), alarm_tick("Stopped", message=message)]},
    )
    assert code == 1
    assert outputs["alarms"] == expected
    assert f"because {expected} went into ALARM" in out
    assert "because  " not in out


@pytest.mark.regression
def test_a_stop_for_another_reason_is_still_failed(aws):
    """Only ALARM_ACTIVE is an alarm."""
    stopped = tick("Stopped")
    stopped["deploy get-deployment"]["deploymentInfo"]["errorInformation"] = {
        "code": "HEALTH_CONSTRAINTS",
        "message": "tasks failed their health checks",
    }
    code, out, _, outputs = _shift(aws, [tick("Ready"), stopped])
    assert code == 1
    assert outputs == {"approved": "true", "result": "failed"}


def test_a_long_or_multiline_message_is_one_bounded_line(aws):
    long = "line one\nline two " + "x" * 1000
    code, out, _, outputs = _shift(
        aws, [tick("Ready"), alarm_tick("Stopped", message=long)]
    )
    (error,) = [line for line in out.splitlines() if line.startswith("::error")]
    assert "line one line two" in error
    assert "x" * 300 not in error
