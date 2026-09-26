"""The dashboard's pre-`cdk deploy` pin check (Stream C, C4b; EM v1 condition 4, PE v1 C7/C8).

``scripts/check_dashboard_image.py`` prints the image digest the dashboard
service is running and the ``-c dashboard_image_tag=sha256:<hex>`` that keeps
it, and with ``--expect`` refuses a deploy whose pin differs. The failure it
guards against is silent: the dashboard runs under the ECS deployment
controller, so a ``cdk deploy`` that changes its task definition re-points the
service at CloudFormation's revision -- ``web:bootstrap`` unless pinned -- and
every probe stays green.

**No test here calls AWS.** The responses are built below in the documented
shapes of ``ecs describe-services`` and ``ecs describe-task-definition`` (not
recorded from a live account; Stream I is where the script first meets real
output). An autouse fixture makes ``subprocess.run`` raise, so a test that
reached the real CLI would fail rather than call it.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "check_dashboard_image.py"
DASHBOARD = REPO_ROOT / "infrastructure" / "cdk" / "stacks" / "dashboard_service.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_dashboard_image", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load()

REGISTRY = "123456789012.dkr.ecr.us-west-2.amazonaws.com"
DIGEST = "sha256:" + "0123456789abcdef" * 4
OTHER = "sha256:" + "fedcba9876543210" * 4
TD_ARN = (
    "arn:aws:ecs:us-west-2:123456789012:task-definition/"
    "experimentation-dashboard-staging:7"
)


@pytest.fixture(autouse=True)
def no_aws(monkeypatch):
    """Any attempt to start a process -- the aws CLI -- fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"a test tried to run a process: {args!r}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(check.subprocess, "run", refuse)


def _deployment(status="PRIMARY", task_definition=TD_ARN, n=1):
    return {
        "id": f"ecs-svc/{n}",
        "status": status,
        "taskDefinition": task_definition,
        "desiredCount": 1,
        "runningCount": 1,
        "rolloutState": "COMPLETED" if status == "PRIMARY" else "IN_PROGRESS",
    }


def _services(deployments=None, status="ACTIVE"):
    return {
        "services": [
            {
                "serviceArn": "arn:aws:ecs:us-west-2:123456789012:service/"
                "experimentation-staging/experimentation-dashboard-staging",
                "serviceName": "experimentation-dashboard-staging",
                "status": status,
                "deploymentController": {"type": "ECS"},
                "deployments": [_deployment()] if deployments is None else deployments,
            }
        ],
        "failures": [],
    }


def _task_definition(image, name="dashboard"):
    return {
        "taskDefinition": {
            "taskDefinitionArn": TD_ARN,
            "family": "experimentation-dashboard-staging",
            "containerDefinitions": [{"name": name, "image": image}],
        }
    }


class FakeAws:
    """Answers each read-only operation from a canned response; records calls."""

    def __init__(self, services=None, task_definition=None):
        self.responses = {
            ("ecs", "describe-services"): _services() if services is None else services,
            ("ecs", "describe-task-definition"): task_definition
            or _task_definition(f"{REGISTRY}/experimentation-platform/web@{DIGEST}"),
        }
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv):
        op = tuple(argv[:2])
        assert op in check.READ_ONLY_OPERATIONS, f"not read-only: {op}"
        self.calls.append(tuple(argv))
        answer = self.responses[op]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _run(aws, *args, capsys):
    code = check.main(["--env", "staging", *args], aws=aws)
    out = capsys.readouterr()
    return code, out.out + out.err


# --- the running digest, printed and checked ----------------------------------


@pytest.mark.regression
def test_the_running_digest_and_its_pin_are_printed(capsys):
    aws = FakeAws()
    code, out = _run(aws, capsys=capsys)
    assert code == check.OK, out
    assert f"-c dashboard_image_tag={DIGEST}" in out
    assert f"experimentation-platform/web@{DIGEST}" in out
    # It read the PRIMARY deployment's task definition, by its ARN.
    assert aws.calls == [
        (
            "ecs",
            "describe-services",
            "--cluster",
            "experimentation-staging",
            "--services",
            "experimentation-dashboard-staging",
        ),
        ("ecs", "describe-task-definition", "--task-definition", TD_ARN),
    ]


def test_expect_the_running_digest_passes(capsys):
    code, out = _run(FakeAws(), "--expect", DIGEST, capsys=capsys)
    assert code == check.OK, out


@pytest.mark.regression
def test_expect_a_different_digest_is_refused(capsys):
    """The deploy would replace the running dashboard with other bytes."""
    code, out = _run(FakeAws(), "--expect", OTHER, capsys=capsys)
    assert code == check.REFUSED, out
    assert (
        f"REFUSED: the dashboard is running experimentation-platform/web@{DIGEST}"
        in out
    )
    assert f"Deploy with:  -c dashboard_image_tag={DIGEST}" in out


def test_a_tag_and_digest_reference_is_read_as_the_digest(capsys):
    aws = FakeAws(
        task_definition=_task_definition(
            f"{REGISTRY}/experimentation-platform/web:v0.4.0-full@{DIGEST}"
        )
    )
    code, out = _run(aws, "--expect", DIGEST, capsys=capsys)
    assert code == check.OK, out


# --- a running image that is not a digest -------------------------------------


@pytest.mark.regression
def test_bootstrap_is_printed_as_a_tag_not_a_digest(capsys):
    """Before the first release (C4) the dashboard runs the placeholder."""
    aws = FakeAws(
        task_definition=_task_definition(
            f"{REGISTRY}/experimentation-platform/web:bootstrap"
        )
    )
    code, out = _run(aws, capsys=capsys)
    assert code == check.OK, out
    assert "experimentation-platform/web:bootstrap, a TAG, not a digest" in out
    assert "sha256:" not in out
    code, out = _run(aws, "--expect", DIGEST, capsys=capsys)
    assert code == check.REFUSED, out
    assert "a TAG, not a digest, so it cannot match" in out


def test_another_tag_is_printed_plainly_and_cannot_match_a_digest(capsys):
    aws = FakeAws(
        task_definition=_task_definition(
            f"{REGISTRY}/experimentation-platform/web:abc1234-full"
        )
    )
    code, out = _run(aws, capsys=capsys)
    assert code == check.OK, out
    assert "web:abc1234-full, a TAG, not a digest" in out
    assert "There is no digest to pin" in out
    code, out = _run(aws, "--expect", DIGEST, capsys=capsys)
    assert code == check.REFUSED, out


def test_an_image_from_another_repository_is_refused(capsys):
    """No dashboard_image_tag value reproduces it: the CDK names the web repository."""
    aws = FakeAws(
        task_definition=_task_definition(
            f"{REGISTRY}/experimentation-platform/backend@{DIGEST}"
        )
    )
    code, out = _run(aws, capsys=capsys)
    assert code == check.REFUSED, out
    assert "not from experimentation-platform/web" in out


# --- what cannot be decided ---------------------------------------------------


def test_a_rollout_in_progress_is_refused(capsys):
    aws = FakeAws(
        services=_services(
            [_deployment(), _deployment("ACTIVE", TD_ARN.replace(":7", ":6"), 2)]
        )
    )
    code, out = _run(aws, capsys=capsys)
    assert code == check.REFUSED, out
    assert "a rollout is in progress" in out
    assert len(aws.calls) == 1


def test_a_task_definition_without_a_dashboard_container_is_unknown(capsys):
    aws = FakeAws(
        task_definition=_task_definition(
            f"{REGISTRY}/experimentation-platform/web@{DIGEST}", name="backend"
        )
    )
    code, out = _run(aws, capsys=capsys)
    assert code == check.UNKNOWN, out


def test_any_aws_error_is_unknown_not_ok(capsys):
    aws = FakeAws(services=check.AwsError("An error occurred (ExpiredTokenException)"))
    code, out = _run(aws, capsys=capsys)
    assert code == check.UNKNOWN, out


@pytest.mark.parametrize(
    "services",
    [
        {"services": [], "failures": [{"arn": "x", "reason": "MISSING"}]},
        _services(status="INACTIVE"),
        check.AwsError(
            "An error occurred (ClusterNotFoundException) when calling the "
            "DescribeServices operation: Cluster not found."
        ),
    ],
    ids=["missing", "inactive", "no-cluster"],
)
def test_a_new_environment_has_nothing_to_pin(services, capsys):
    aws = FakeAws(services=services)
    code, out = _run(aws, capsys=capsys)
    assert code == check.OK, out
    assert "nothing to pin" in out
    code, out = _run(aws, "--expect", DIGEST, capsys=capsys)
    assert code == check.REFUSED, out


# --- arguments -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        DIGEST[len("sha256:") :],  # the hex without the algorithm
        DIGEST.upper(),
        DIGEST[:-1],
        "bootstrap",
        f"web@{DIGEST}",
    ],
)
def test_expect_must_be_a_digest(value, capsys):
    def no_calls(*_args, **_kwargs):
        raise AssertionError("the check called AWS with an unusable --expect")

    with pytest.raises(SystemExit) as exc_info:
        check.main(["--env", "staging", "--expect", value], aws=no_calls)
    assert exc_info.value.code == 2
    assert "expected sha256:<64 lowercase hex>" in capsys.readouterr().err


@pytest.mark.parametrize("env", ["stagng", "production", "", "STAGING"])
def test_an_unknown_environment_is_refused_before_any_call(env, capsys):
    def no_calls(*_args, **_kwargs):
        raise AssertionError("the check called AWS for an unknown environment")

    with pytest.raises(SystemExit) as exc_info:
        check.main(["--env", env], aws=no_calls)
    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_the_environments_are_the_live_target_group_check_s(capsys):
    """The two pre-deploy checks run side by side with the same --env."""
    spec = importlib.util.spec_from_file_location(
        "check_live_target_group", REPO_ROOT / "scripts" / "check_live_target_group.py"
    )
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)

    usage = {}
    for name, module in (("dashboard", check), ("live_tg", guard)):
        with pytest.raises(SystemExit):
            module.main(["--help"])
        text = capsys.readouterr().out
        usage[name] = text[text.index("--env {") : text.index("}") + 1]
    assert usage["dashboard"] == usage["live_tg"] == "--env {dev,staging,prod,demo}"


# --- read-only, and nothing but ------------------------------------------------


@pytest.mark.regression
def test_the_operations_are_exactly_two_describe_calls():
    """Pinned exactly: widening the allow-list is an edit this test sees."""
    assert check.READ_ONLY_OPERATIONS == {
        ("ecs", "describe-services"),
        ("ecs", "describe-task-definition"),
    }


@pytest.mark.regression
@pytest.mark.parametrize(
    "argv",
    [
        ["ecs", "update-service", "--service", "x", "--force-new-deployment"],
        ["ecs", "register-task-definition", "--cli-input-json", "{}"],
        ["cloudformation", "deploy", "--stack-name", "x"],
    ],
)
def test_run_aws_refuses_a_write_before_starting_a_process(argv):
    """`no_aws` would fail the test with a different message if a process started."""
    with pytest.raises(ValueError, match="not a read-only operation"):
        check.run_aws(argv)


def test_the_context_key_is_the_one_the_cdk_reads():
    source = DASHBOARD.read_text()
    assert f'try_get_context("{check.CONTEXT_KEY}")' in source
