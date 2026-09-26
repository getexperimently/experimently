"""The forward deploy completes, and says whether it did (#143, PE v2 C6-C8).

Three scripts carry what deploy.yml does after `create-deployment`:

* `scripts/refuse_active_deployment.py` refuses, before anything changes,
  while an earlier deployment of the group is still active (PE v2 C7), and
  never stops it;
* `scripts/shift_traffic.py` is rollback.yml's polling loop. On `Ready` it
  checks that every target in the replacement task set's target group is
  healthy and that the count equals the desired count (C6(b)). Then it sends
  `continue-deployment --deployment-wait-type READY_WAIT`, once.
  `Failed`/`Stopped` end the run, and `Baking` does not. It never stops a
  deployment;
* `scripts/api_serving.py` is the success predicate. The PRIMARY task set
  must be the new ARN, and check_live_target_group.py, with `--expect`
  derived from that task set's target group, must confirm the `/api/*` rule.
  A split rule means "not yet", and an unsplit one to the other group means
  "wrong" (C8).

Each is driven against a fake `aws` first on PATH, as in
test_task_definition_scripts.py. The fake answers from a scenario and records
every call, so no AWS is involved. A scenario is a list of *ticks*: every
`deploy get-deployment` call starts the next one, and every other call is
answered from the current tick. Deadlines and intervals are parameters. The
loop tests run with an interval of 0, and no test measures elapsed time.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = REPO_ROOT / "scripts"
SHIFT = SCRIPTS / "shift_traffic.py"
SERVING = SCRIPTS / "api_serving.py"
REFUSE = SCRIPTS / "refuse_active_deployment.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "live_target_group"

CLUSTER = "experimentation-staging"
SERVICE = "experimentation-backend-staging"
OLD = "arn:aws:ecs:us-west-2:123456789012:task-definition/experimentation-backend-staging:42"
NEW = "arn:aws:ecs:us-west-2:123456789012:task-definition/experimentation-backend-staging:43"
DEPLOYMENT = "d-ABCDEF123"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


RULES_BLUE = _fixture("rules-api-blue.json")
RULES_GREEN = _fixture("rules-api-green.json")
BLUE = RULES_BLUE["Rules"][0]["Actions"][0]["TargetGroupArn"]
GREEN = RULES_GREEN["Rules"][0]["Actions"][0]["TargetGroupArn"]


def _split(blue_weight: int = 90, green_weight: int = 10) -> dict:
    rules = copy.deepcopy(RULES_BLUE)
    for rule in rules["Rules"][:2]:
        rule["Actions"][0]["ForwardConfig"]["TargetGroups"] = [
            {"TargetGroupArn": BLUE, "Weight": blue_weight},
            {"TargetGroupArn": GREEN, "Weight": green_weight},
        ]
    return rules


def _task_set(arn: str, group: str, status: str, desired: int = 2) -> dict:
    return {
        "id": f"ecs-svc/{arn[-2:]}",
        "status": status,
        "taskDefinition": arn,
        "computedDesiredCount": desired,
        "loadBalancers": [
            {"targetGroupArn": group, "containerName": "backend", "containerPort": 8000}
        ],
    }


def _services(*task_sets: dict) -> dict:
    services = _fixture("services-primary-blue.json")
    services["services"][0]["taskSets"] = list(task_sets)
    return services


#: Before the flip: the old revision PRIMARY in blue, the new one beside it in green.
BEFORE = _services(_task_set(OLD, BLUE, "PRIMARY"), _task_set(NEW, GREEN, "ACTIVE"))
#: After: the new revision PRIMARY in green.
AFTER = _services(_task_set(NEW, GREEN, "PRIMARY"), _task_set(OLD, BLUE, "ACTIVE"))


def _health(*states: str) -> dict:
    return {
        "TargetHealthDescriptions": [
            {
                "Target": {"Id": f"10.0.0.{i}", "Port": 8000},
                "TargetHealth": {"State": state},
            }
            for i, state in enumerate(states, 1)
        ]
    }


def tick(
    status: str,
    services: dict = BEFORE,
    rules: dict = RULES_BLUE,
    health: dict | None = None,
) -> dict:
    return {
        "deploy get-deployment": {
            "deploymentInfo": {"deploymentId": DEPLOYMENT, "status": status}
        },
        "ecs describe-services": services,
        "elbv2 describe-rules": rules,
        "elbv2 describe-target-health": health or _health("healthy", "healthy"),
        "elbv2 describe-listeners": _fixture("listener-default-dashboard.json"),
        "cloudformation describe-stack-resources": _fixture("stack-resources.json"),
        "deploy continue-deployment": {},
    }


FAKE_AWS = r"""#!{python}
import json, os, sys
args = sys.argv[1:]
state = os.environ["FAKE_AWS_STATE"]
with open(os.path.join(state, "calls.log"), "a") as log:
    log.write(json.dumps(args) + "\n")
scenario = json.load(open(os.path.join(state, "scenario.json")))
key = " ".join(args[:2])
counter = os.path.join(state, "tick")
n = int(open(counter).read()) if os.path.exists(counter) else 0
if key == "deploy get-deployment" and "ticks" in scenario:
    n += 1
    open(counter, "w").write(str(n))
if "ticks" in scenario:
    ticks = scenario["ticks"]
    table = ticks[min(max(n, 1), len(ticks)) - 1]
else:
    table = scenario["responses"]
if key not in table:
    print("fake aws: unexpected call " + json.dumps(args), file=sys.stderr)
    sys.exit(99)
answer = table[key]
if isinstance(answer, dict) and "by" in answer:
    answer = answer["values"][args[args.index(answer["by"]) + 1]]
if isinstance(answer, dict) and set(answer) == {"error"}:
    print(answer["error"], file=sys.stderr)
    sys.exit(254)
print(json.dumps(answer))
"""


@pytest.fixture
def aws(tmp_path):
    """Return a runner: (script, args, scenario) -> (exit, stdout+stderr, calls, outputs)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS.replace("{python}", sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state"
    state.mkdir()
    outputs = tmp_path / "github_output"

    def run(script: Path, args: list[str], scenario: dict):
        (state / "scenario.json").write_text(json.dumps(scenario))
        for stale in ("calls.log", "tick"):
            (state / stale).unlink(missing_ok=True)
        outputs.write_text("")
        result = subprocess.run(
            [sys.executable, str(script), *args],
            env={
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "FAKE_AWS_STATE": str(state),
                "GITHUB_OUTPUT": str(outputs),
            },
            capture_output=True,
            text=True,
            timeout=120,
        )
        log = state / "calls.log"
        calls = (
            [json.loads(x) for x in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        written = dict(
            line.split("=", 1) for line in outputs.read_text().splitlines() if line
        )
        return result.returncode, result.stdout + result.stderr, calls, written

    return run


def _shift(aws, ticks: list[dict], deadline: str = "3600"):
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
            deadline,
            "--interval-seconds",
            "0",
        ],
        {"ticks": ticks},
    )


def _ops(calls: list[list[str]]) -> list[str]:
    return [" ".join(c[:2]) for c in calls]


def _continues(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if c[:2] == ["deploy", "continue-deployment"]]


# --- shift_traffic.py: the happy path ------------------------------------------


@pytest.mark.regression
def test_a_deploy_is_approved_on_healthy_targets_and_succeeds_when_serving(aws):
    code, out, calls, outputs = _shift(
        aws,
        [
            tick("InProgress"),
            tick("Ready"),
            tick("InProgress", BEFORE, _split(90, 10)),
            tick("InProgress", AFTER, _split(10, 90)),
            tick("InProgress", AFTER, RULES_GREEN),
        ],
    )
    assert code == 0, out
    (approval,) = _continues(calls)
    assert approval == [
        "deploy",
        "continue-deployment",
        "--deployment-id",
        DEPLOYMENT,
        "--deployment-wait-type",
        "READY_WAIT",
        "--output",
        "json",
    ]
    ops = _ops(calls)
    # Target health was read before the approval, not after.
    assert ops.index("elbv2 describe-target-health") < ops.index(
        "deploy continue-deployment"
    )
    assert outputs == {"result": "serving", "live_target_group": "green"}
    assert f"serving: {NEW} is the PRIMARY task set" in out
    assert not [c for c in calls if "stop-deployment" in c]


@pytest.mark.regression
def test_the_approval_is_sent_once_however_long_ready_lasts(aws):
    code, out, calls, _ = _shift(
        aws,
        [
            tick("Ready"),
            tick("Ready"),
            tick("Ready"),
            tick("InProgress", AFTER, RULES_GREEN),
        ],
    )
    assert code == 0, out
    assert len(_continues(calls)) == 1


@pytest.mark.regression
def test_baking_is_not_terminal(aws):
    """PE v2 C7: the loop treats Baking as still going."""
    code, out, calls, outputs = _shift(
        aws,
        [
            tick("Ready"),
            tick("Baking", AFTER, _split(10, 90)),
            tick("Baking", AFTER, RULES_GREEN),
        ],
    )
    assert code == 0, out
    assert outputs["result"] == "serving"


# --- shift_traffic.py: target health before the approval (PE v2 C6(b)) ----------


@pytest.mark.regression
@pytest.mark.parametrize(
    "health",
    [
        _health("healthy", "initial"),
        _health("healthy", "unhealthy"),
        _health("healthy"),  # one of the two desired
        _health("healthy", "healthy", "draining"),  # an extra, not-healthy target
        _health(),
    ],
    ids=["initial", "unhealthy", "count-short", "extra-draining", "none"],
)
def test_no_approval_until_every_target_is_healthy_and_counted(aws, health):
    code, out, calls, outputs = _shift(
        aws,
        [
            tick("Ready", health=health),
            tick("Ready", health=_health("healthy", "healthy")),
            tick("InProgress", AFTER, RULES_GREEN),
        ],
    )
    assert code == 0, out
    ops = _ops(calls)
    health_reads = [
        i for i, op in enumerate(ops) if op == "elbv2 describe-target-health"
    ]
    (approval,) = [i for i, op in enumerate(ops) if op == "deploy continue-deployment"]
    assert len(health_reads) == 2 and health_reads[0] < health_reads[1] < approval
    assert "Ready, not yet approved" in out


@pytest.mark.regression
def test_unhealthy_until_the_deadline_is_never_approved_and_never_stopped(aws):
    code, out, calls, outputs = _shift(
        aws, [tick("Ready", health=_health("unhealthy", "unhealthy"))], deadline="0"
    )
    assert code == 1
    assert not _continues(calls)
    assert outputs == {"result": "unhealthy"}
    assert "Nothing has shifted" in out and "0 of 2 desired targets healthy" in out


def test_a_replacement_task_set_wanting_no_tasks_is_not_approved(aws):
    empty = _services(
        _task_set(OLD, BLUE, "PRIMARY"), _task_set(NEW, GREEN, "ACTIVE", 0)
    )
    code, out, calls, _ = _shift(aws, [tick("Ready", empty, health=_health())], "0")
    assert code == 1 and not _continues(calls)
    assert "desired count is 0" in out


# --- shift_traffic.py: failure, and never a stop ----------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("status", ["Failed", "Stopped"])
def test_failed_or_stopped_ends_the_run_red(aws, status):
    code, out, calls, outputs = _shift(aws, [tick("Ready"), tick(status)])
    assert code == 1
    assert outputs == {"result": "failed"}
    assert f"is {status} after this run approved the traffic shift" in out


@pytest.mark.regression
def test_a_deadline_after_the_approval_leaves_the_deployment_running(aws):
    """#143: stopping a deployment whose traffic has shifted rolls back a success."""
    code, out, calls, outputs = _shift(
        aws, [tick("Ready", BEFORE, _split(90, 10))], deadline="0"
    )
    assert code == 1
    assert len(_continues(calls)) == 1
    assert outputs == {"result": "timeout"}
    assert "It was NOT stopped" in out
    assert set(_ops(calls)) <= {
        "deploy get-deployment",
        "deploy continue-deployment",
        "ecs describe-services",
        "elbv2 describe-target-health",
    }


def test_succeeded_but_not_serving_is_red(aws):
    code, out, _, outputs = _shift(aws, [tick("Succeeded", BEFORE)])
    assert code == 1 and outputs == {"result": "failed"}


def test_the_loop_refuses_any_other_operation_before_starting_a_process():
    spec = importlib.util.spec_from_file_location("shift_traffic", SHIFT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="not an operation this script may run"):
        module.run_aws(["deploy", "stop-deployment", "--deployment-id", "d-1"])


# --- shift_traffic.py + api_serving.py: success ordering (PE v2 C8) ---------------


@pytest.mark.regression
def test_a_split_rule_after_the_flip_is_still_shifting(aws):
    """PRIMARY may flip while the canary still splits the rule: retry, not red."""
    code, out, calls, outputs = _shift(
        aws,
        [
            tick("Ready"),
            tick("InProgress", AFTER, _split(90, 10)),
            tick("InProgress", AFTER, _split(90, 10)),
            tick("InProgress", AFTER, RULES_GREEN),
        ],
    )
    assert code == 0, out
    assert outputs["live_target_group"] == "green"


@pytest.mark.regression
def test_an_unsplit_rule_on_the_other_group_after_the_flip_is_red(aws):
    """C3 OPEN 1 made visible: the traffic shift left the /api/* rule behind."""
    code, out, calls, outputs = _shift(
        aws, [tick("Ready"), tick("InProgress", AFTER, RULES_BLUE)]
    )
    assert code == 1
    assert outputs == {"result": "wrong-route"}
    assert "Roll back with the line in this run's summary" in out
    assert "The deployment was not stopped" in out


@pytest.mark.regression
def test_could_not_tell_is_red_not_green(aws):
    broken = tick("InProgress", AFTER, RULES_GREEN)
    broken["cloudformation describe-stack-resources"] = {
        "error": "An error occurred (ExpiredToken)"
    }
    # Deadline 0: one poll. "Could not tell" must be red at once, not a
    # "timeout" after polling on as if the shift were still going.
    code, out, _, outputs = _shift(aws, [broken], deadline="0")
    assert code == 1
    assert outputs == {"result": "unknown"}
    assert "Could not tell whether the API is serving" in out


# --- api_serving.py on its own: the predicate C4 calls ------------------------------


def _serving(aws, services: dict, rules: dict, arn: str = NEW, **extra):
    responses = tick("InProgress", services, rules)
    responses.update(extra)
    return aws(SERVING, [CLUSTER, SERVICE, arn], {"responses": responses})


@pytest.mark.regression
def test_the_predicate_is_zero_only_when_serving(aws):
    code, out, calls, _ = _serving(aws, AFTER, RULES_GREEN)
    assert code == 0, out
    assert "-c api_live_target_group=green" in out
    # Read-only, and only these.
    assert set(_ops(calls)) == {
        "ecs describe-services",
        "cloudformation describe-stack-resources",
        "elbv2 describe-listeners",
        "elbv2 describe-rules",
    }


@pytest.mark.regression
def test_the_expected_colour_is_derived_not_defaulted(aws):
    """Blue is the default of check_live_target_group.py. A green PRIMARY with a
    green rule must pass, and a blue rule must not, whatever the default is."""
    assert _serving(aws, AFTER, RULES_GREEN)[0] == 0
    blue_primary = _services(_task_set(NEW, BLUE, "PRIMARY"))
    assert _serving(aws, blue_primary, RULES_BLUE)[0] == 0
    assert _serving(aws, blue_primary, RULES_GREEN)[0] == 3


@pytest.mark.parametrize(
    "services, rules, arn, expected",
    [
        (BEFORE, RULES_BLUE, NEW, 1),  # PRIMARY is the old revision
        (AFTER, _split(50, 50), NEW, 1),  # shifting
        (AFTER, RULES_BLUE, NEW, 3),  # unsplit, other group
        (AFTER, RULES_GREEN, OLD, 1),  # the ARN asked about is not PRIMARY
        (AFTER, RULES_GREEN, "experimentation-backend-staging:43", 2),  # not an ARN
    ],
    ids=["old-primary", "split", "wrong-group", "other-arn", "family-not-arn"],
)
def test_the_predicate_exit_codes(aws, services, rules, arn, expected):
    code, out, calls, _ = _serving(aws, services, rules, arn)
    assert code == expected, out


def test_the_predicate_refuses_a_service_of_another_environment(aws):
    code, out, calls, _ = aws(
        SERVING, [CLUSTER, "experimentation-backend-prod", NEW], {"responses": {}}
    )
    assert code == 2 and not calls


# --- refuse_active_deployment.py (PE v2 C7) -------------------------------------


def _refuse(aws, listed: list[str], infos: dict[str, dict]):
    return aws(
        REFUSE,
        ["experimentation-platform-staging", "experimentation-staging"],
        {
            "responses": {
                "deploy list-deployments": {"deployments": listed},
                "deploy get-deployment": {
                    "by": "--deployment-id",
                    "values": {k: {"deploymentInfo": v} for k, v in infos.items()},
                },
            }
        },
    )


def _info(status: str, **extra) -> dict:
    return {
        "deploymentId": "d-PRIOR",
        "status": status,
        "description": "deploy v1.2.3 (full)",
        "createTime": "2026-09-26T10:00:00.000000+00:00",
        "blueGreenDeploymentConfiguration": {
            "deploymentReadyOption": {
                "actionOnTimeout": "STOP_DEPLOYMENT",
                "waitTimeInMinutes": 30,
            },
            "terminateBlueInstancesOnDeploymentSuccess": {
                "action": "TERMINATE",
                "terminationWaitTimeInMinutes": 60,
            },
        },
        **extra,
    }


@pytest.mark.regression
def test_nothing_active_passes(aws):
    code, out, calls, _ = _refuse(aws, [], {})
    assert code == 0, out
    (listing,) = calls
    statuses = listing[listing.index("--include-only-statuses") + 1 : -2]
    # Baking included: nobody has seen which status the termination wait reports.
    assert statuses == ["Created", "Queued", "InProgress", "Baking", "Ready"]


@pytest.mark.regression
@pytest.mark.parametrize(
    "status", ["InProgress", "Baking", "Ready", "Created", "Queued"]
)
def test_an_active_deployment_is_refused_by_name_and_never_stopped(aws, status):
    code, out, calls, _ = _refuse(
        aws,
        ["d-PRIOR"],
        {"d-PRIOR": _info(status, instanceTerminationWaitTimeStarted=True)},
    )
    assert code == 1, out
    assert "d-PRIOR (deploy v1.2.3 (full)) is " + status in out
    assert "Nothing has been built or changed" in out
    assert "may stay active for about" in out
    assert set(_ops(calls)) == {"deploy list-deployments", "deploy get-deployment"}


def test_one_that_finished_since_it_was_listed_passes(aws):
    code, out, _, _ = _refuse(aws, ["d-PRIOR"], {"d-PRIOR": _info("Succeeded")})
    assert code == 0, out


@pytest.mark.regression
def test_could_not_check_is_not_nothing_there(aws):
    code, out, _, _ = aws(
        REFUSE,
        ["experimentation-platform-staging", "experimentation-staging"],
        {"responses": {"deploy list-deployments": {"error": "AccessDenied"}}},
    )
    assert code == 2
    assert "Could not check for an active deployment" in out


def _refuse_module():
    spec = importlib.util.spec_from_file_location("refuse_active_deployment", REFUSE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_time_left_is_estimated_from_the_creation_time():
    """In-process, with the clock injected: no test reads the real time."""
    refuse = _refuse_module()
    created = refuse._when("2026-09-26T10:00:00+00:00")
    sentence = refuse.describe(
        _info("InProgress", instanceTerminationWaitTimeStarted=True), created + 20 * 60
    )
    # 30 approval + 15 shift allowance + 60 termination - 20 elapsed.
    assert "created at 10:00 UTC, 20 minutes ago" in sentence
    assert "about 85 more minutes" in sentence
    assert "keeping the previous task set for up to 60 minutes" in sentence
    ready = refuse.describe(_info("Ready"), created)
    assert "waiting for approval" in ready and "30-minute approval wait" in ready
    assert refuse._when(created) == created  # `wire` timestamps: epoch seconds


def test_an_operator_typed_description_stays_on_one_line():
    refuse = _refuse_module()
    sentence = refuse.describe(
        _info("InProgress", description="rollback: bad\n::add-mask::x"), 0
    )
    assert "\n" not in sentence


def test_the_refusal_refuses_any_write_before_starting_a_process():
    refuse = _refuse_module()
    with pytest.raises(ValueError, match="not a read-only operation"):
        refuse.run_aws(["deploy", "stop-deployment", "--deployment-id", "d-1"])
