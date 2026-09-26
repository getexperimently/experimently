"""The pre-deploy guard against black-holing the API (Stream C, C3; EM condition 8a).

``scripts/check_live_target_group.py`` reads which of the API's blue and green
target groups is live and refuses a ``cdk deploy`` whose
``api_live_target_group`` context names the other one. The failure it guards
against is silent: after an odd number of CodeDeploy deployments green is
live, and a deploy that writes the ``/api/*`` rule against blue sends every
API request to an empty target group while ``/`` and every probe stay green.

**No test here calls AWS.** Every AWS response is a fixture under
``fixtures/live_target_group/``, written by hand in the documented response
shapes of the four describe calls (not recorded from a live account -- there
is none yet; Stream I is where the script first meets real output). An
autouse fixture makes ``subprocess.run`` raise, so a test that reached the
real CLI would fail rather than call it.
"""

from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "check_live_target_group.py"
NAMES = REPO_ROOT / "infrastructure" / "cdk" / "stacks" / "names.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "live_target_group"


def _load():
    spec = importlib.util.spec_from_file_location("check_live_target_group", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load()


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def no_aws(monkeypatch):
    """Any attempt to start a process -- the aws CLI -- fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"a test tried to run a process: {args!r}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(guard.subprocess, "run", refuse)


class FakeAws:
    """Answers each read-only operation from a fixture and records the calls."""

    def __init__(self, listener: str, rules: str, services: str, stack=None):
        self.responses = {
            ("cloudformation", "describe-stack-resources"): stack
            or _fixture("stack-resources.json"),
            ("elbv2", "describe-listeners"): _fixture(listener),
            ("elbv2", "describe-rules"): _fixture(rules),
            ("ecs", "describe-services"): _fixture(services),
        }
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv):
        op = tuple(argv[:2])
        assert op in guard.READ_ONLY_OPERATIONS, f"not read-only: {op}"
        self.calls.append(tuple(argv))
        answer = self.responses[op]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _run(aws, *args, capsys):
    code = guard.main(["--env", "staging", *args], aws=aws)
    out = capsys.readouterr()
    return code, out.out + out.err


# --- the two cases EM condition 8 names --------------------------------------


@pytest.mark.regression
def test_blue_live_passes_with_the_default(capsys):
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
    )
    code, out = _run(aws, capsys=capsys)
    assert code == guard.OK, out
    assert "ok: blue is live; deploy with -c api_live_target_group=blue" in out


@pytest.mark.regression
def test_green_live_without_the_context_is_refused(capsys):
    """The black hole: green is live and the deploy would route the API to blue."""
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-green.json",
        "services-primary-green.json",
    )
    code, out = _run(aws, capsys=capsys)
    assert code == guard.REFUSED, out
    assert "REFUSED: green is live" in out
    assert "-c api_live_target_group=green" in out


def test_green_live_with_the_context_passes(capsys):
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-green.json",
        "services-primary-green.json",
    )
    code, out = _run(aws, "--expect", "green", capsys=capsys)
    assert code == guard.OK, out


# --- the first deploy of C3 onto a stack from before the dashboard ------------


@pytest.mark.regression
def test_before_the_dashboard_the_default_action_is_read(capsys):
    """No /api/* rule yet: the API is the listener's default action.

    This is the deploy PE's failure mode names -- CloudFormation creating the
    rule against blue on a stack where CodeDeploy has left green live.
    """
    aws = FakeAws(
        "listener-default-green.json",
        "rules-default-only-green.json",
        "services-primary-green.json",
    )
    code, out = _run(aws, capsys=capsys)
    assert code == guard.REFUSED, out
    assert "-c api_live_target_group=green" in out

    aws = FakeAws(
        "listener-default-blue.json",
        "rules-default-only-blue.json",
        "services-primary-blue.json",
    )
    code, out = _run(aws, capsys=capsys)
    assert code == guard.OK, out


# --- the load balancer and ECS disagree --------------------------------------


def test_listener_and_primary_task_set_disagreeing_is_refused(capsys):
    """The route is already not where the tasks are; no context value is safe."""
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-green.json",
    )
    code, out = _run(aws, capsys=capsys)
    assert code == guard.REFUSED, out
    assert "already pointing at the wrong target group" in out
    code, out = _run(aws, "--expect", "green", capsys=capsys)
    assert code == guard.REFUSED, out


def test_a_traffic_shift_in_progress_is_refused(capsys):
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
    )
    rules = aws.responses[("elbv2", "describe-rules")]
    blue = rules["Rules"][0]["Actions"][0]["TargetGroupArn"]
    green = _fixture("rules-api-green.json")["Rules"][0]["Actions"][0]["TargetGroupArn"]
    # Both API rules mid-shift, 90/10 -- the canary's first step.
    for rule in rules["Rules"][:2]:
        rule["Actions"][0]["ForwardConfig"]["TargetGroups"] = [
            {"TargetGroupArn": blue, "Weight": 90},
            {"TargetGroupArn": green, "Weight": 10},
        ]
    code, out = _run(aws, capsys=capsys)
    assert code == guard.REFUSED, out
    assert "traffic shift is in progress" in out


@pytest.mark.regression
@pytest.mark.parametrize("split", ["api", "health"])
def test_a_split_in_either_rule_is_shifting_before_the_rules_are_compared(split):
    """PE B3b C1: one rule split and the other not is a shift in progress. It
    used to be compared first and refused as "already wrong"."""
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
    )
    rules = aws.responses[("elbv2", "describe-rules")]
    blue = rules["Rules"][0]["Actions"][0]["TargetGroupArn"]
    green = _fixture("rules-api-green.json")["Rules"][0]["Actions"][0]["TargetGroupArn"]
    index = 0 if split == "api" else 1
    rules["Rules"][index]["Actions"][0]["ForwardConfig"]["TargetGroups"] = [
        {"TargetGroupArn": blue, "Weight": 90},
        {"TargetGroupArn": green, "Weight": 10},
    ]
    with pytest.raises(guard.Shifting):
        guard.check(aws, "staging", "blue")


@pytest.mark.regression
def test_a_split_is_its_own_refusal_and_no_target_is_not_one():
    """The forward deploy's loop reads a split as "still shifting" (PE v2 C8);
    everything else refused stays a plain refusal. The CLI's exit is 1 for both."""
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
    )
    rules = aws.responses[("elbv2", "describe-rules")]
    blue = rules["Rules"][0]["Actions"][0]["TargetGroupArn"]
    green = _fixture("rules-api-green.json")["Rules"][0]["Actions"][0]["TargetGroupArn"]
    for rule in rules["Rules"][:2]:
        rule["Actions"][0]["ForwardConfig"]["TargetGroups"] = [
            {"TargetGroupArn": blue, "Weight": 90},
            {"TargetGroupArn": green, "Weight": 10},
        ]
    with pytest.raises(guard.Shifting):
        guard.check(aws, "staging", "blue")
    assert issubclass(guard.Shifting, guard.Refused)

    for rule in rules["Rules"][:2]:
        rule["Actions"][0]["ForwardConfig"]["TargetGroups"] = [
            {"TargetGroupArn": blue, "Weight": 0},
            {"TargetGroupArn": green, "Weight": 0},
        ]
    with pytest.raises(guard.Refused) as refused:
        guard.check(aws, "staging", "blue")
    assert not isinstance(refused.value, guard.Shifting)


def test_the_health_rule_on_a_different_group_is_refused(capsys):
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
    )
    green = _fixture("rules-api-green.json")["Rules"][1]
    aws.responses[("elbv2", "describe-rules")]["Rules"][1] = green
    code, out = _run(aws, capsys=capsys)
    assert code == guard.REFUSED, out
    assert "/health and /api/* rules forward to different" in out


def test_a_route_to_a_foreign_target_group_is_refused(capsys):
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
    )
    foreign = "arn:aws:elasticloadbalancing:us-west-2:123456789012:targetgroup/x/1"
    for rule in aws.responses[("elbv2", "describe-rules")]["Rules"][:2]:
        action = rule["Actions"][0]
        action["TargetGroupArn"] = foreign
        action["ForwardConfig"]["TargetGroups"] = [
            {"TargetGroupArn": foreign, "Weight": 1}
        ]
    code, out = _run(aws, capsys=capsys)
    assert code == guard.REFUSED, out
    assert "neither the blue nor the green" in out


# --- no stack, and AWS errors ------------------------------------------------


def test_a_new_environment_starts_in_blue(capsys):
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
        stack=guard.AwsError(
            "An error occurred (ValidationError) when calling the "
            "DescribeStackResources operation: Stack with id "
            "experimentation-fargate-staging does not exist"
        ),
    )
    code, out = _run(aws, capsys=capsys)
    assert code == guard.OK, out
    code, out = _run(aws, "--expect", "green", capsys=capsys)
    assert code == guard.REFUSED, out


def test_any_other_aws_error_is_unknown_not_ok(capsys):
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
        stack=guard.AwsError("An error occurred (ExpiredToken)"),
    )
    code, out = _run(aws, capsys=capsys)
    assert code == guard.UNKNOWN, out


def test_a_stack_that_is_not_ours_is_unknown(capsys):
    stack = _fixture("stack-resources.json")
    stack["StackResources"] = [
        r
        for r in stack["StackResources"]
        if not r["LogicalResourceId"].startswith("GreenTargetGroup")
    ]
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
        stack=stack,
    )
    code, out = _run(aws, capsys=capsys)
    assert code == guard.UNKNOWN, out
    assert "GreenTargetGroup<hash>" in out


# --- read-only, and nothing but ------------------------------------------------


@pytest.mark.regression
def test_the_operations_are_exactly_four_describe_calls():
    """Pinned exactly: widening the allow-list is an edit this test sees."""
    assert guard.READ_ONLY_OPERATIONS == {
        ("cloudformation", "describe-stack-resources"),
        ("elbv2", "describe-listeners"),
        ("elbv2", "describe-rules"),
        ("ecs", "describe-services"),
    }
    assert all(op.startswith("describe-") for _, op in guard.READ_ONLY_OPERATIONS)


def test_a_full_check_makes_exactly_those_calls(capsys):
    aws = FakeAws(
        "listener-default-dashboard.json",
        "rules-api-blue.json",
        "services-primary-blue.json",
    )
    _run(aws, capsys=capsys)
    assert {c[:2] for c in aws.calls} == guard.READ_ONLY_OPERATIONS
    assert len(aws.calls) == 4


def test_run_aws_refuses_a_write_before_starting_a_process():
    """`no_aws` would fail the test with a different message if a process started."""
    with pytest.raises(ValueError, match="not a read-only operation"):
        guard.run_aws(["elbv2", "modify-rule", "--rule-arn", "x"])


def test_the_default_agrees_with_the_cdk():
    """The script's key and default are the ones the stack reads (names.py)."""
    names = runpy.run_path(str(NAMES))
    assert guard.CONTEXT_KEY == names["API_LIVE_TARGET_GROUP_CONTEXT"]
    assert guard.DEFAULT_EXPECT == names["API_LIVE_TARGET_GROUP_DEFAULT"]


@pytest.mark.parametrize("env", ["stagng", "production", "", "STAGING"])
def test_an_unknown_environment_is_refused_before_any_call(env, capsys):
    """A typo must not reach the "stack does not exist" branch, which reports
    the default group as live."""

    def no_calls(*_args, **_kwargs):
        raise AssertionError("the guard called AWS for an unknown environment")

    with pytest.raises(SystemExit) as exc_info:
        guard.main(["--env", env], aws=no_calls)
    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
