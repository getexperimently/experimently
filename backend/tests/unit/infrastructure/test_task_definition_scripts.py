"""The two scripts every registered and every migration task goes through.

`scripts/register_task_definition.sh` is the only way deploy.yml and
db-migrate.yml register a task definition, and it accepts only an image DIGEST
(#138, QA 2): a version tag lives in one ECR repository shared by every
environment and profile, and ECS resolves a tag each time it starts a task.

`scripts/run_migration_task.sh` runs a migration by its registered revision
ARN, never a family (QA 1c), waits with its own deadline, and turns the three
ways a task ends badly into sentences.

Both are driven here against a fake `aws` first on PATH that records every call
and answers from canned state, so no AWS and no git are needed.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTER = REPO_ROOT / "scripts" / "register_task_definition.sh"
RUN_MIGRATION = REPO_ROOT / "scripts" / "run_migration_task.sh"

DIGEST = "sha256:" + "a" * 64
IMAGE = f"123456789012.dkr.ecr.us-west-2.amazonaws.com/experimentation-platform/backend@{DIGEST}"
FAMILY = "experimentation-migrate-staging"
ARN = f"arn:aws:ecs:us-west-2:123456789012:task-definition/{FAMILY}:7"
TASK = "arn:aws:ecs:us-west-2:123456789012:task/experimentation-staging/0abc"

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
query = opt("--query") or ""
if (service, verb) == ("ecs", "describe-task-definition"):
    if opt("--task-definition").startswith("arn:"):
        registered = json.loads(canned("registered.json"))
        image = canned("readback_image") or next(
            c["image"] for c in registered["containerDefinitions"] if c["name"] == "backend")
        print(image)
    else:
        td = canned("describe.json")
        if td is None:
            print("An error occurred (ClientException): Unable to describe task definition.", file=sys.stderr)
            sys.exit(254)
        print(td)
elif (service, verb) == ("ecs", "register-task-definition"):
    open(os.path.join(state, "registered.json"), "w").write(opt("--cli-input-json"))
    print("{arn}")
elif (service, verb) == ("ecs", "run-task"):
    print(canned("run_task.json", json.dumps({{"tasks": [{{"taskArn": "{task}"}}], "failures": []}})))
elif (service, verb) == ("ecs", "describe-tasks"):
    if "lastStatus" in query:
        print(canned("status", "STOPPED"))
    elif "exitCode" in query:
        print(canned("exit_code", "0"))
    elif "stoppedReason" in query:
        print(canned("reason", "CannotPullContainerError: pull image manifest has been retried"))
elif (service, verb) == ("logs", "get-log-events"):
    print("INFO  [alembic.runtime.migration] Running upgrade a -> b")
else:
    print(f"fake aws: unexpected call {{args}}", file=sys.stderr)
    sys.exit(99)
"""


@pytest.fixture
def aws(tmp_path):
    """Return a runner: (script, args, **canned files) -> (exit, output, calls)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS.format(python=sys.executable, arn=ARN, task=TASK))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state"
    state.mkdir()

    def run(script: Path, *args: str, env: dict | None = None, **files: str):
        for name, content in files.items():
            (state / name.replace("__", ".")).write_text(content)
        result = subprocess.run(
            ["bash", str(script), *args],
            env={
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "FAKE_AWS_STATE": str(state),
                **(env or {}),
            },
            capture_output=True,
            text=True,
        )
        log = state / "calls.log"
        calls = (
            [json.loads(x) for x in log.read_text().splitlines()]
            if log.exists()
            else []
        )
        registered = state / "registered.json"
        return (
            result.returncode,
            result.stdout,
            result.stderr,
            calls,
            json.loads(registered.read_text()) if registered.exists() else None,
        )

    return run


def _described(**extra) -> str:
    return json.dumps(
        {
            "taskDefinitionArn": f"arn:aws:ecs:us-west-2:123456789012:task-definition/{FAMILY}:6",
            "family": FAMILY,
            "revision": 6,
            "status": "ACTIVE",
            "requiresAttributes": [{"name": "x"}],
            "compatibilities": ["FARGATE"],
            "registeredAt": "2026-09-26T00:00:00Z",
            "registeredBy": "arn:aws:iam::123456789012:role/cfn",
            "executionRoleArn": "arn:aws:iam::123456789012:role/exec",
            "cpu": "512",
            "memory": "1024",
            "containerDefinitions": [
                {
                    "name": "backend",
                    "image": "123456789012.dkr.ecr.us-west-2.amazonaws.com/experimentation-platform/backend:bootstrap",
                    "secrets": [{"name": "SECRET_KEY", "valueFrom": "arn:x"}],
                }
            ],
            **extra,
        }
    )


# --- register_task_definition.sh -----------------------------------------------


@pytest.mark.regression
def test_registers_the_digest_and_changes_nothing_else(aws):
    code, out, err, calls, registered = aws(
        REGISTER, FAMILY, IMAGE, describe__json=_described()
    )
    assert code == 0, err
    assert out.strip() == ARN, "stdout must be the ARN and nothing else"
    (backend,) = registered["containerDefinitions"]
    assert backend["image"] == IMAGE
    assert backend["secrets"] == [{"name": "SECRET_KEY", "valueFrom": "arn:x"}]
    assert registered["executionRoleArn"].endswith("role/exec")
    for field in (
        "taskDefinitionArn",
        "revision",
        "status",
        "requiresAttributes",
        "compatibilities",
        "registeredAt",
        "registeredBy",
    ):
        assert field not in registered, field
    # Based on the FAMILY's newest revision (CloudFormation's shape).
    assert ["ecs", "describe-task-definition", "--task-definition", FAMILY] == calls[0][
        :4
    ]


@pytest.mark.regression
@pytest.mark.parametrize(
    "image",
    [
        "123456789012.dkr.ecr.us-west-2.amazonaws.com/experimentation-platform/backend:v1.2.3-full",
        "123456789012.dkr.ecr.us-west-2.amazonaws.com/experimentation-platform/backend:latest",
        "repo@sha256:short",
        "",
    ],
)
def test_refuses_anything_but_a_digest(aws, image):
    code, out, err, calls, registered = aws(
        REGISTER, FAMILY, image, describe__json=_described()
    )
    assert code != 0
    assert registered is None and not [
        c for c in calls if c[1] == "register-task-definition"
    ]
    if image:
        assert "not an image digest" in err


def test_refuses_a_family_that_does_not_exist(aws):
    code, _, err, _, registered = aws(REGISTER, FAMILY, IMAGE)
    assert code == 1 and registered is None
    assert f"No task definition family {FAMILY}" in err


def test_refuses_a_revision_without_exactly_one_backend(aws):
    two = json.loads(_described())
    two["containerDefinitions"].append(dict(two["containerDefinitions"][0]))
    code, _, err, _, registered = aws(
        REGISTER, FAMILY, IMAGE, describe__json=json.dumps(two)
    )
    assert code == 1 and registered is None
    assert "2 containers named 'backend'" in err


def test_refuses_when_the_stored_revision_is_not_what_was_sent(aws):
    code, _, err, _, _ = aws(
        REGISTER, FAMILY, IMAGE, describe__json=_described(), readback_image="other:tag"
    )
    assert code == 1
    assert "was registered with 'other:tag'" in err


# --- run_migration_task.sh -----------------------------------------------------

NETWORK = '{"awsvpcConfiguration":{"subnets":["subnet-1"],"securityGroups":["sg-1"],"assignPublicIp":"DISABLED"}}'
OVERRIDES = '{"containerOverrides":[{"name":"backend","command":["python","-m","backend.app.db.bootstrap"]}]}'
LOG_GROUP = "/ecs/experimentation-migrate-staging"


def _migrate(aws, task_definition=ARN, env=None, **files):
    return aws(
        RUN_MIGRATION,
        "experimentation-staging",
        task_definition,
        NETWORK,
        OVERRIDES,
        LOG_GROUP,
        env=env,
        **files,
    )


@pytest.mark.regression
@pytest.mark.parametrize("task_definition", [FAMILY, f"{FAMILY}:7", ""])
def test_runs_only_a_registered_revision_arn(aws, task_definition):
    """A family resolves to whatever registered last (QA 1c)."""
    code, _, err, calls, _ = _migrate(aws, task_definition)
    assert code != 0
    assert not calls, f"aws was called with a non-ARN task definition: {calls}"


@pytest.mark.regression
def test_a_successful_migration(aws):
    code, out, _, calls, _ = _migrate(aws)
    assert code == 0, out
    (run,) = [c for c in calls if c[1] == "run-task"]
    assert run[run.index("--task-definition") + 1] == ARN
    assert run[run.index("--overrides") + 1] == OVERRIDES
    assert run[run.index("--network-configuration") + 1] == NETWORK
    # The log stream the awslogs driver writes: <prefix>/<container>/<task id>.
    (logs,) = [c for c in calls if c[:2] == ["logs", "get-log-events"]]
    assert logs[logs.index("--log-stream-name") + 1] == "migrate/backend/0abc"
    assert "Running upgrade a -> b" in out


@pytest.mark.regression
def test_a_failed_migration_names_the_exit_code(aws):
    code, out, _, _, _ = _migrate(aws, exit_code="3")
    assert code == 1
    assert "exited 3" in out


@pytest.mark.regression
def test_a_task_that_never_ran_says_why(aws):
    code, out, _, _, _ = _migrate(aws, exit_code="None")
    assert code == 1
    assert (
        "Migration task stopped before the container ran: CannotPullContainerError"
        in out
    )


@pytest.mark.regression
def test_a_migration_still_running_at_the_deadline_is_not_rerun(aws):
    code, out, _, calls, _ = _migrate(
        aws, env={"MIGRATION_TIMEOUT_SECONDS": "0"}, status="RUNNING"
    )
    assert code == 1
    assert "still running" in out and "Do not re-run it" in out
    assert len([c for c in calls if c[1] == "run-task"]) == 1


def test_ecs_refusing_to_start_the_task_is_reported(aws):
    code, out, _, _, _ = _migrate(
        aws, run_task__json='{"tasks": [], "failures": [{"reason": "RESOURCE:ENI"}]}'
    )
    assert code == 1
    assert "did not start the migration task" in out and "RESOURCE:ENI" in out
