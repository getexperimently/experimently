"""`scripts/ecs_rolling_rollout.sh`: a circuit-breaker rollback is never a success.

The dashboard is an ECS rolling-update service with the deployment circuit
breaker and rollback on. `aws ecs wait services-stable` succeeds when there is
one deployment and the service's running count equals its desired count -- which
is exactly the state after the breaker has put the OLD revision back. So the
script decides on the PRIMARY deployment this run started (C4 plan-v2, EM v1
condition 3, PE v1 C3 and C12):

* this run's deployment id, as `update-service` returned it, must be listed
  once before any verdict (ECS is eventually consistent);
* after that, a PRIMARY on another revision fails at once, and the id no
  longer being listed fails;
* success is one deployment, ours, PRIMARY on our revision, COMPLETED, with
  the DEPLOYMENT's own running == desired >= 1;
* desiredCount < 1 and a PRIMARY other than `--expect-primary` are refused
  before `update-service` is called.

The cases are R1-R9 and R11 of the plan (R10 is the API half of the race guard,
which C4's workflow wiring owns). Each is driven with a fake `aws` first on PATH
that serves a scripted sequence of `describe-services` answers (the first is the
pre-mutation read; the last repeats). Every run uses `--interval 0`; a case
that must reach the deadline uses `--deadline 0`, one that must not uses a
large deadline and a subprocess timeout. Nothing asserts on elapsed time.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
ROLLOUT = REPO_ROOT / "scripts" / "ecs_rolling_rollout.sh"

CLUSTER = "experimentation-staging"
SERVICE = "experimentation-dashboard-staging"
TD = "arn:aws:ecs:us-west-2:123456789012:task-definition/experimentation-dashboard-staging"
OLD = f"{TD}:6"
NEW = f"{TD}:7"
THIRD = f"{TD}:8"
OURS = "ecs-svc/7777"
PRIOR = "ecs-svc/6666"
ROLLBACK = "ecs-svc/6667"

FAKE_AWS = r"""#!{python}
import json, os, sys
args = sys.argv[1:]
state = os.environ["FAKE_AWS_STATE"]
with open(os.path.join(state, "calls.log"), "a") as log:
    log.write(json.dumps(args) + "\n")

def opt(name):
    return args[args.index(name) + 1] if name in args else None

def canned(name, default=None):
    path = os.path.join(state, name)
    return open(path).read() if os.path.exists(path) else default

service, verb = args[0], args[1]
if (service, verb) == ("ecs", "describe-services"):
    answers = json.loads(canned("services.json"))
    counter = os.path.join(state, "describe.count")
    n = int(canned("describe.count", "0"))
    open(counter, "w").write(str(n + 1))
    answer = answers[min(n, len(answers) - 1)]
    if answer is None:
        print(json.dumps({{"services": [], "failures": [{{"reason": "MISSING"}}]}}))
    else:
        print(json.dumps({{"services": [answer], "failures": []}}))
elif (service, verb) == ("ecs", "update-service"):
    error = canned("update_error")
    if error:
        print(error, file=sys.stderr)
        sys.exit(254)
    print(canned("update.json"))
elif (service, verb) == ("ecs", "describe-task-definition"):
    print("123456789012.dkr.ecr.us-west-2.amazonaws.com/experimentation-platform/web@sha256:" + "b" * 64)
elif (service, verb) == ("ecs", "list-tasks"):
    print("arn:aws:ecs:us-west-2:123456789012:task/experimentation-staging/dead")
elif (service, verb) == ("ecs", "describe-tasks"):
    print(opt("--tasks") and "{new}\tEssential container in task exited")
else:
    print(f"fake aws: unexpected call {{args}}", file=sys.stderr)
    sys.exit(99)
"""


def dep(
    td: str,
    id: str,
    status: str = "PRIMARY",
    state: str | None = "COMPLETED",
    running: int = 1,
    desired: int = 1,
    failed: int = 0,
) -> dict:
    d = {
        "id": id,
        "status": status,
        "taskDefinition": td,
        "desiredCount": desired,
        "runningCount": running,
        "pendingCount": 0,
        "failedTasks": failed,
    }
    if state is not None:
        d["rolloutState"] = state
    return d


def svc(
    *deployments: dict,
    desired: int = 1,
    running: int | None = None,
    controller: str = "ECS",
    status: str = "ACTIVE",
) -> dict:
    return {
        "serviceName": SERVICE,
        "status": status,
        "desiredCount": desired,
        "runningCount": desired if running is None else running,
        "deploymentController": {"type": controller},
        # A rolling service has no task sets: the API's `taskSets` query
        # would find nothing here (R7).
        "taskSets": [],
        "deployments": list(deployments),
        "events": [
            {
                "createdAt": "2026-09-26T00:00:00Z",
                "message": f"(service {SERVICE}) has started 1 tasks",
            }
        ],
    }


#: The state before this run: the old revision, settled.
BEFORE = svc(dep(OLD, PRIOR))
#: What `update-service` returns: our deployment, PRIMARY, just created.
UPDATED = {
    "service": svc(
        dep(NEW, OURS, state="IN_PROGRESS", running=0),
        dep(OLD, PRIOR, status="ACTIVE"),
    )
}
IN_PROGRESS = svc(
    dep(NEW, OURS, state="IN_PROGRESS", running=0),
    dep(OLD, PRIOR, status="ACTIVE"),
)
DONE = svc(dep(NEW, OURS))


@pytest.fixture
def rollout(tmp_path):
    """(polls, *flags, before=, update=, update_error=) -> (exit, stdout, stderr, calls)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS.format(python=sys.executable, new=NEW))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state"
    state.mkdir()

    def run(
        polls: list,
        *flags: str,
        before: dict | None = BEFORE,
        update: dict | None = None,
        update_error: str | None = None,
        deadline: str = "600",
        target: str = NEW,
    ):
        (state / "services.json").write_text(json.dumps([before, *polls]))
        (state / "update.json").write_text(json.dumps(update or UPDATED))
        if update_error:
            (state / "update_error").write_text(update_error)
        result = subprocess.run(
            [
                "bash",
                str(ROLLOUT),
                "--interval",
                "0",
                "--deadline",
                deadline,
                *flags,
                CLUSTER,
                SERVICE,
                target,
            ],
            env={
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "FAKE_AWS_STATE": str(state),
            },
            capture_output=True,
            text=True,
            # A classifier that never decides would spin on the repeated last
            # answer until --deadline; this turns that into a failure.
            timeout=120,
        )
        log = state / "calls.log"
        calls = (
            [json.loads(x) for x in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        return result.returncode, result.stdout, result.stderr, calls

    return run


def updates(calls: list) -> list:
    return [c for c in calls if c[:2] == ["ecs", "update-service"]]


# --- R1: the rollout takes -----------------------------------------------------


@pytest.mark.regression
def test_r1_a_completed_rollout_of_this_revision_succeeds(rollout):
    code, out, err, calls = rollout([IN_PROGRESS, DONE])
    assert code == 0, out + err
    assert (
        f"{SERVICE}: experimentation-dashboard-staging:7 is PRIMARY, rollout COMPLETED, "
        "1/1 tasks running"
    ) in out
    (update,) = updates(calls)
    assert update[update.index("--task-definition") + 1] == NEW
    assert "--force-new-deployment" not in update
    # A progress line, on stderr.
    assert "PRIMARY experimentation-dashboard-staging:7 IN_PROGRESS, 0/1 running" in err


# --- R2: the circuit breaker ------------------------------------------------------


@pytest.mark.regression
def test_a_circuit_breaker_rollback_is_not_a_success(rollout):
    """R2. The breaker marks ours FAILED and makes the OLD revision PRIMARY.

    The last answer -- one deployment, the old revision, COMPLETED, 1/1 -- is
    what `services-stable` accepts. The script must fail at the first poll that
    shows the old revision PRIMARY, not wait for it to settle.
    """
    rolled_back = svc(
        dep(OLD, ROLLBACK, state="IN_PROGRESS", running=0),
        dep(NEW, OURS, status="ACTIVE", state="FAILED", running=0, failed=2),
    )
    settled = svc(dep(OLD, ROLLBACK))
    code, out, err, calls = rollout([IN_PROGRESS, rolled_back, settled])
    assert code == 1, out + err
    assert "circuit breaker" in out
    assert "put experimentation-dashboard-staging:6 (" in out
    assert "title=experimentation-dashboard-staging rolled back by ECS::" in out
    assert len(updates(calls)) == 1
    # It stopped at the rollback's first appearance: 1 pre-read + 2 polls.
    describes = [c for c in calls if c[1] == "describe-services"]
    assert len(describes) == 3
    # The events and a stopped task's reason are printed before the verdict.
    assert out.index("last service events") < out.index("::error")
    assert "Essential container in task exited" in out


# --- R3, R4, R6: not finished at the deadline --------------------------------------


@pytest.mark.regression
def test_r3_running_below_desired_is_not_a_success(rollout):
    code, out, _, calls = rollout([svc(dep(NEW, OURS, running=0))], deadline="0")
    assert code == 1
    assert "rollout did not finish" in out
    assert "COMPLETED (0/1 running" in out
    assert len(updates(calls)) == 1


@pytest.mark.regression
def test_r4_no_rollout_state_is_not_a_success(rollout):
    code, out, _, calls = rollout([svc(dep(NEW, OURS, state=None))], deadline="0")
    assert code == 1
    assert "rollout did not finish" in out
    assert len(updates(calls)) == 1


@pytest.mark.regression
def test_r6_still_in_progress_at_the_deadline_is_not_rerun(rollout):
    code, out, _, calls = rollout([IN_PROGRESS], deadline="0")
    assert code == 1
    assert "IN_PROGRESS (0/1 running, 0 failed tasks, 2 deployment(s))" in out
    assert "did not stop it" in out
    assert len(updates(calls)) == 1


# --- R5: our deployment gone after it was seen -----------------------------------


@pytest.mark.regression
def test_r5_this_runs_deployment_no_longer_listed_is_a_failure(rollout):
    """Replaced by another update to the same revision: not ours to claim."""
    replaced = svc(dep(NEW, "ecs-svc/9999"))
    code, out, _, calls = rollout([IN_PROGRESS, replaced])
    assert code == 1
    assert f"This run's deployment {OURS}" in out and "no longer listed" in out
    assert "ecs-svc/9999" in out
    assert len(updates(calls)) == 1


# --- the seen-id anchor (eventual consistency) --------------------------------------


@pytest.mark.regression
def test_the_first_poll_may_still_show_the_state_before_the_update(rollout):
    """No verdict before our id is listed once (PE v1 C3, gap 3).

    The first poll after `update-service` answers with the pre-update state:
    the old revision PRIMARY and our id absent. That is neither "rolled back"
    nor "no longer listed".
    """
    code, out, err, calls = rollout([BEFORE, BEFORE, IN_PROGRESS, DONE])
    assert code == 0, out + err
    assert f"waiting for ECS to list deployment {OURS}" in err
    assert len(updates(calls)) == 1


def test_never_listed_by_the_deadline_is_not_a_success(rollout):
    code, out, _, calls = rollout([BEFORE], deadline="0")
    assert code == 1
    assert f"ECS has not listed deployment {OURS}" in out
    assert len(updates(calls)) == 1


# --- R7: "serving before" is the PRIMARY deployment, not a task set -----------------


@pytest.mark.regression
def test_r7_serving_before_is_the_primary_deployment(rollout):
    code, _, err, _ = rollout([IN_PROGRESS, DONE])
    assert code == 0
    assert f"{SERVICE}: serving before this run: {OLD}" in err


# --- R8: the deployment's counts, not the service's -------------------------------


@pytest.mark.regression
def test_r8_the_service_level_counts_do_not_decide(rollout):
    """The service says 1/1; the PRIMARY deployment says 0/1."""
    misleading = svc(dep(NEW, OURS, running=0), desired=1, running=1)
    code, out, _, calls = rollout([misleading], deadline="0")
    assert code == 1
    assert "rollout did not finish" in out
    assert len(updates(calls)) == 1


# --- exactly one deployment ------------------------------------------------------


@pytest.mark.regression
def test_a_second_deployment_still_listed_is_not_a_success(rollout):
    draining = svc(dep(NEW, OURS), dep(OLD, PRIOR, status="ACTIVE"))
    code, out, _, calls = rollout([draining], deadline="0")
    assert code == 1
    assert "2 deployment(s)" in out
    assert len(updates(calls)) == 1


# --- R9: desired 0 -----------------------------------------------------------------


@pytest.mark.regression
def test_r9_a_service_that_wants_no_tasks_is_refused_before_any_change(rollout):
    code, out, _, calls = rollout([DONE], before=svc(dep(OLD, PRIOR), desired=0))
    assert code == 1
    assert "wants 0 tasks" in out and "Nothing was changed" in out
    assert updates(calls) == []


# --- R11: the dashboard changed since the caller read it ---------------------------


@pytest.mark.regression
def test_r11_a_primary_other_than_expected_is_refused_before_any_change(rollout):
    code, out, _, calls = rollout([DONE], "--expect-primary", THIRD)
    assert code == 1
    assert "changed during this run" in out
    assert "PRIMARY deployment is experimentation-dashboard-staging:6, not " in out
    assert updates(calls) == []


def test_r11_the_expected_primary_lets_the_rollout_proceed(rollout):
    code, out, err, calls = rollout([IN_PROGRESS, DONE], "--expect-primary", OLD)
    assert code == 0, out + err
    assert len(updates(calls)) == 1


@pytest.mark.parametrize("value", ["", "experimentation-dashboard-staging:6"])
def test_an_empty_or_bare_expected_primary_is_refused(rollout, value):
    """A caller whose "serving before" went missing must not switch the guard off."""
    code, out, _, calls = rollout([DONE], "--expect-primary", value)
    assert code == 1
    assert "--expect-primary" in out
    assert calls == []


# --- a third revision during the wait (UX W2 F6) ---------------------------------


@pytest.mark.regression
def test_a_third_revision_during_the_wait_is_not_called_a_circuit_breaker(rollout):
    someone_else = svc(dep(THIRD, "ecs-svc/8888"))
    code, out, _, calls = rollout([IN_PROGRESS, someone_else])
    assert code == 1
    assert "changed during this run" in out
    assert "neither this run's revision (experimentation-dashboard-staging:7)" in out
    assert "rolled back by ECS" not in out
    assert len(updates(calls)) == 1


def test_a_failed_deployment_that_stays_primary_fails_at_once(rollout):
    failed = svc(dep(NEW, OURS, state="FAILED", running=0, failed=3))
    code, out, _, calls = rollout([failed])
    assert code == 1
    assert "FAILED (0/1 running, 3 failed tasks)" in out
    assert len(updates(calls)) == 1


# --- refusals before any mutation ------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [f"{TD}", "experimentation-dashboard-staging:7", "", f"{NEW} "],
)
def test_only_a_registered_revision_arn_is_rolled_out(rollout, target):
    code, out, _, calls = rollout([DONE], target=target)
    assert code == 1
    assert "not a registered revision ARN" in out
    assert calls == []


def test_a_code_deploy_service_is_refused(rollout):
    code, out, _, calls = rollout(
        [DONE], before=svc(dep(OLD, PRIOR), controller="CODE_DEPLOY")
    )
    assert code == 1
    assert "deployed by CODE_DEPLOY" in out
    assert updates(calls) == []


@pytest.mark.parametrize("before", [None, svc(dep(OLD, PRIOR), status="DRAINING")])
def test_a_missing_or_inactive_service_is_refused(rollout, before):
    code, out, _, calls = rollout([DONE], before=before)
    assert code == 1
    assert f"No ACTIVE ECS service {SERVICE}" in out
    assert updates(calls) == []


def test_a_denied_update_says_which_permission(rollout):
    code, out, _, calls = rollout(
        [DONE],
        update_error="An error occurred (AccessDeniedException) when calling the "
        "UpdateService operation: not authorized to perform: ecs:UpdateService",
    )
    assert code == 1
    assert "ecs:UpdateService was denied" in out
    assert "still on experimentation-dashboard-staging:6" in out
    assert len(updates(calls)) == 1


def test_an_update_that_returns_no_deployment_of_ours_is_not_followed(rollout):
    code, out, _, calls = rollout([DONE], update={"service": BEFORE})
    assert code == 1
    assert "cannot be followed" in out
    assert len(updates(calls)) == 1
    assert len([c for c in calls if c[1] == "describe-services"]) == 1


# --- --no-update (rollback's assert-only use) ------------------------------------


def test_no_update_follows_a_revision_already_primary(rollout):
    code, out, err, calls = rollout([DONE], "--no-update", before=svc(dep(NEW, OURS)))
    assert code == 0, out + err
    assert "is PRIMARY, rollout COMPLETED" in out
    assert updates(calls) == []


def test_no_update_waits_under_the_same_rule(rollout):
    settling = svc(
        dep(NEW, OURS, state="IN_PROGRESS", running=0), dep(OLD, PRIOR, status="ACTIVE")
    )
    code, out, _, calls = rollout(
        [settling], "--no-update", before=settling, deadline="0"
    )
    assert code == 1
    assert "rollout did not finish" in out
    assert updates(calls) == []


def test_no_update_on_another_revision_fails_without_changing_it(rollout):
    code, out, _, calls = rollout([DONE], "--no-update")
    assert code == 1
    assert "is serving experimentation-dashboard-staging:6, not" in out
    assert updates(calls) == []


# --- the text of the script ------------------------------------------------------


def _code() -> str:
    return "\n".join(
        ln for ln in ROLLOUT.read_text().splitlines() if not ln.lstrip().startswith("#")
    )


@pytest.mark.regression
def test_the_script_never_uses_services_stable_or_forces_a_deployment():
    code = _code()
    assert "services-stable" not in code
    assert "wait" not in re.findall(r"\baws\s+ecs\s+(\S+)", code)
    assert "--force-new-deployment" not in code
    # The one mutation names the revision.
    assert re.search(
        r'aws ecs update-service [^\n]*\\\n\s*--task-definition "\$TASK_DEFINITION"',
        code,
    ), 'update-service must pass --task-definition "$TASK_DEFINITION"'
    assert len(re.findall(r"\baws ecs update-service\b", code)) == 1


@pytest.mark.parametrize(
    "args",
    [
        [],
        [CLUSTER, SERVICE],
        ["--interval", "x", CLUSTER, SERVICE, NEW],
        ["--deadline", "-1", CLUSTER, SERVICE, NEW],
        ["--bogus", CLUSTER, SERVICE, NEW],
    ],
)
def test_usage_errors_exit_2_and_call_nothing(tmp_path, args):
    result = subprocess.run(
        ["bash", str(ROLLOUT), *args],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "usage" in result.stderr
