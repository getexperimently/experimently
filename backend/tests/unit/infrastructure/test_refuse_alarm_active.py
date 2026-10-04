"""Deploy refuses while one of the API's 5xx alarms is in ALARM (#148 PR-3, #297).

`scripts/refuse_alarm_active.py` reads the alarm names from the deployment
group, then their states, and refuses before the snapshot and migration that
CodeDeploy's own alarm stop would otherwise leave behind ("Migrated, not
deployed"). The contract is plan-v2's PR-3 row, PE condition 11 and EM
conditions 4(h) and 11:

* ALARM refuses (exit 1), naming the alarm; OK and INSUFFICIENT_DATA pass;
* an empty, disabled or missing alarm configuration refuses, and so does a
  group that does not watch every alarm the stack defines -- with the
  break-glass too;
* with the break-glass (`--alarms-overridden`) ALARM is a warning, and every
  alarm's state is still printed;
* an AWS error, or a state the script does not know, is exit 2;
* it runs twice in deploy.yml: before the build, and immediately before the
  snapshot;
* with `--expect-config` (the before-build run only), a group whose
  `deploymentConfigName` differs from the stack's, or is missing, is a
  `::warning` annotation and a log line, never a refusal (#795).

No AWS call is made anywhere in this file. The script's `aws` callable is
answered by real botocore clients under a `Stubber`, so every request is
checked against the service model's parameters and every canned answer
against its output shape, and the credential chain is blank: a call the
stub did not expect fails with NoCredentialsError, and a `before-send` hook
fails the test before any request could leave. The step tests use the
workflow Runner's fake `aws` on PATH, with the chain blanked as well.

The alarm names are not typed here: they come from `stacks/names.py`, the
function the CDK stack names its alarms with, so renaming an alarm there fails
this file (deploy.yml's job env is also checked against a synth by
`infrastructure/tests/test_workflow_names_exist.py`).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import botocore.session
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from backend.tests.unit.infrastructure.test_dashboard_deploy_wiring import (
    DEPLOY,
    ENV,
    SCRIPTS,
    _job,
    _step,
    _steps,
    rule,
    runner,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
NAMES_PY = REPO_ROOT / "infrastructure" / "cdk" / "stacks" / "names.py"
APPLICATION = f"experimentation-platform-{ENV}"
GROUP = f"experimentation-{ENV}"
RUNBOOK = "docs/deployment/rollback-runbook.md#fix-forward-while-an-alarm-is-firing"
SINCE = datetime(2026, 9, 28, 14, 5, 0, tzinfo=timezone.utc)

#: The blank credential chain every test here runs under.
BLANK_CHAIN = {
    "AWS_ACCESS_KEY_ID": "",
    "AWS_SECRET_ACCESS_KEY": "",
    "AWS_PROFILE": "nonexistent",
    "AWS_CONFIG_FILE": "/dev/null",
    "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
    "AWS_EC2_METADATA_DISABLED": "true",
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


refuse = _load("refuse_alarm_active", SCRIPTS / "refuse_alarm_active.py")
names = _load("stacks_names_for_refuse_alarm_active", NAMES_PY)


def stack_alarms(env: str = ENV) -> list[str]:
    """The API 5xx alarm names the CDK stack creates for `env`, one per colour."""
    return [names.api_5xx_alarm_name(env, c) for c in names.API_TARGET_GROUP_COLOURS]


BLUE, GREEN = stack_alarms()

#: The deployment config deploy.yml expects the group to use, read from its job
#: env (pinned to the synthesised DeploymentConfigName by
#: infrastructure/tests/test_codedeploy_alarms.py), so it is not typed here.
STACK_CONFIG = _job(DEPLOY)["env"]["CODEDEPLOY_DEPLOYMENT_CONFIG"]
OTHER_CONFIG = "CodeDeployDefault.ECSAllAtOnce"
#: Passed as `deployment_config` to leave deploymentConfigName out.
MISSING = object()


# --- botocore Stubber behind the script's `aws` callable -----------------------


def _cli_json(value: Any) -> Any:
    """What `aws ... --output json` prints: timestamps as ISO 8601 strings."""
    return json.loads(
        json.dumps(
            value, default=lambda v: v.isoformat() if hasattr(v, "isoformat") else v
        )
    )


class StubbedAws:
    """The script's `aws(argv)` answered by Stubber-backed botocore clients.

    Each expected call is queued with the exact parameters it must be made
    with; the stubs check the parameters and the canned answer against the
    real service model.
    """

    def __init__(self) -> None:
        session = botocore.session.Session()
        self.codedeploy = session.create_client("codedeploy", region_name="us-west-2")
        self.cloudwatch = session.create_client("cloudwatch", region_name="us-west-2")
        self.stubs = {
            "deploy": Stubber(self.codedeploy),
            "cloudwatch": Stubber(self.cloudwatch),
        }
        for client in (self.codedeploy, self.cloudwatch):
            client.meta.events.register("before-send", self._no_network)
        self.calls: list[list[str]] = []

    @staticmethod
    def _no_network(**kwargs: Any) -> None:
        raise AssertionError(
            f"a real AWS request was about to be sent: {kwargs.get('request')}"
        )

    # Queueing ----------------------------------------------------------------

    def group(
        self,
        config: dict | None,
        application: str = APPLICATION,
        group: str = GROUP,
        deployment_config: Any = STACK_CONFIG,
    ):
        info: dict[str, Any] = {
            "applicationName": application,
            "deploymentGroupName": group,
        }
        if deployment_config is not MISSING:
            info["deploymentConfigName"] = deployment_config
        if config is not None:
            info["alarmConfiguration"] = config
        self.stubs["deploy"].add_response(
            "get_deployment_group",
            {"deploymentGroupInfo": info},
            {"applicationName": application, "deploymentGroupName": group},
        )

    def group_error(self, code: str = "AccessDeniedException") -> None:
        self.stubs["deploy"].add_client_error(
            "get_deployment_group", service_error_code=code, service_message="denied"
        )

    def alarms(self, queried: Sequence[str], found: Sequence[dict]) -> None:
        self.stubs["cloudwatch"].add_response(
            "describe_alarms",
            {"MetricAlarms": list(found), "CompositeAlarms": []},
            {
                "AlarmNames": list(queried),
                "AlarmTypes": ["MetricAlarm", "CompositeAlarm"],
            },
        )

    def alarms_error(self, code: str = "Throttling") -> None:
        self.stubs["cloudwatch"].add_client_error(
            "describe_alarms", service_error_code=code, service_message="slow down"
        )

    # The callable ------------------------------------------------------------

    def __call__(self, argv: Sequence[str]) -> dict:
        argv = list(argv)
        self.calls.append(argv)
        assert tuple(argv[:2]) in refuse.OPERATIONS, argv
        try:
            with self.stubs[argv[0]]:
                if argv[:2] == ["deploy", "get-deployment-group"]:
                    answer = self.codedeploy.get_deployment_group(
                        applicationName=argv[argv.index("--application-name") + 1],
                        deploymentGroupName=argv[
                            argv.index("--deployment-group-name") + 1
                        ],
                    )
                elif argv[:2] == ["cloudwatch", "describe-alarms"]:
                    start = argv.index("--alarm-names") + 1
                    end = argv.index("--alarm-types")
                    answer = self.cloudwatch.describe_alarms(
                        AlarmNames=argv[start:end], AlarmTypes=argv[end + 1 :]
                    )
                else:  # pragma: no cover - the OPERATIONS assert above
                    raise AssertionError(argv)
        except ClientError as exc:
            # The CLI prints the error to stderr and exits non-zero; run_aws
            # raises AwsError with that text.
            raise refuse.AwsError(str(exc)) from exc
        answer.pop("ResponseMetadata", None)
        return _cli_json(answer)

    def assert_done(self) -> None:
        for stub in self.stubs.values():
            stub.assert_no_pending_responses()


@pytest.fixture
def aws(monkeypatch) -> StubbedAws:
    # The clients are made with no profile set (botocore resolves the profile
    # when a client is created); the rest of the test then runs with the whole
    # blank chain, AWS_PROFILE=nonexistent included.
    for key, value in BLANK_CHAIN.items():
        if key != "AWS_PROFILE":
            monkeypatch.setenv(key, value)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    for key in ("AWS_SESSION_TOKEN", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE"):
        monkeypatch.delenv(key, raising=False)
    stubbed = StubbedAws()
    assert stubbed.codedeploy._request_signer._credentials is None
    monkeypatch.setenv("AWS_PROFILE", "nonexistent")
    return stubbed


def config(*alarm_names: str, enabled: bool = True) -> dict:
    return {
        "enabled": enabled,
        "ignorePollAlarmFailure": False,
        "alarms": [{"name": n} for n in alarm_names],
    }


def alarm(name: str, state: str, reason: str = "Threshold Crossed") -> dict:
    return {
        "AlarmName": name,
        "StateValue": state,
        "StateUpdatedTimestamp": SINCE,
        "StateReason": reason,
    }


def run(
    aws: StubbedAws,
    *extra: str,
    stage: str = "before-build",
    expect=None,
    expect_config: str | None = None,
) -> int:
    argv = [
        "--application",
        APPLICATION,
        "--group",
        GROUP,
        "--environment",
        ENV,
        "--stage",
        stage,
    ]
    for name in stack_alarms() if expect is None else expect:
        argv += ["--expect", name]
    if expect_config is not None:
        argv += ["--expect-config", expect_config]
    return refuse.main([*argv, *extra], aws=aws)


# --- the contract ------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("state", ["OK", "INSUFFICIENT_DATA"])
def test_ok_and_insufficient_data_pass_and_are_printed(aws, capsys, state):
    aws.group(config(BLUE, GREEN))
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK"), alarm(GREEN, state)])
    assert run(aws, expect_config=STACK_CONFIG) == refuse.OK
    out = capsys.readouterr().out
    assert f"{BLUE}: OK since 2026-09-28T14:05:00+00:00" in out
    assert f"{GREEN}: {state} since" in out
    assert "::error" not in out and "::warning" not in out
    aws.assert_done()


@pytest.mark.regression
@pytest.mark.parametrize("stage", ["before-build", "before-migration"])
def test_an_alarm_in_alarm_refuses_and_names_it(aws, capsys, stage):
    aws.group(config(BLUE, GREEN))
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK"), alarm(GREEN, "ALARM")])
    assert run(aws, stage=stage) == refuse.REFUSED
    out = capsys.readouterr().out
    (error,) = [ln for ln in out.splitlines() if ln.startswith("::error")]
    assert error.startswith(
        f"::error title=An alarm is already firing::{GREEN} is in ALARM in {ENV} "
        "(since 2026-09-28T14:05:00+00:00)"
    ), error
    assert refuse.STAGES[stage] in error
    assert RUNBOOK in error
    # Every alarm's state is printed, the passing one too.
    assert f"{BLUE}: OK since" in out
    # EM condition 4(f): the pre-flight copy never names the break-glass input.
    assert "override_alarms" not in out
    aws.assert_done()


@pytest.mark.regression
def test_the_break_glass_warns_on_alarm_and_goes_on(aws, capsys):
    """EM condition 4(h): with the input set, still print every state, do not
    refuse on ALARM."""
    aws.group(config(BLUE, GREEN))
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "ALARM"), alarm(GREEN, "OK")])
    assert run(aws, "--alarms-overridden") == refuse.OK
    out = capsys.readouterr().out
    assert f"{BLUE}: ALARM since" in out and f"{GREEN}: OK since" in out
    assert "::error" not in out
    assert (
        "::warning title=An alarm is firing, and the alarms are overridden::"
        f"{BLUE} is in ALARM in {ENV}"
    ) in out
    assert "override_alarms" not in out
    aws.assert_done()


BROKEN_CONFIGS = {
    "no alarm configuration": None,
    "disabled": config(BLUE, GREEN, enabled=False),
    "enabled with no alarm": config(),
}


@pytest.mark.regression
@pytest.mark.parametrize("overridden", [False, True])
@pytest.mark.parametrize("case", sorted(BROKEN_CONFIGS))
def test_an_empty_or_disabled_configuration_refuses_even_with_the_break_glass(
    aws, capsys, case, overridden
):
    """plan-v2 PR-3 / EM 4(h): an empty alarm list refuses, it does not pass."""
    aws.group(BROKEN_CONFIGS[case])
    extra = ["--alarms-overridden"] if overridden else []
    assert run(aws, *extra) == refuse.REFUSED
    out = capsys.readouterr().out
    assert "::error title=The API's alarms are not watching::" in out
    assert BLUE in out and GREEN in out  # what the stack defines
    # Nothing to read: describe-alarms is not called at all.
    assert [c[:2] for c in aws.calls] == [["deploy", "get-deployment-group"]]
    aws.assert_done()


@pytest.mark.regression
@pytest.mark.parametrize("overridden", [False, True])
def test_a_group_that_does_not_watch_a_stack_alarm_refuses(aws, capsys, overridden):
    """A drifted group cannot make the check pass by watching less."""
    aws.group(config(BLUE))
    aws.alarms([BLUE], [alarm(BLUE, "OK")])
    extra = ["--alarms-overridden"] if overridden else []
    assert run(aws, *extra) == refuse.REFUSED
    out = capsys.readouterr().out
    assert (
        f"::error title=The API's alarms are not all watching::Deployment group "
        f"{APPLICATION}/{GROUP} does not watch {GREEN}"
    ) in out
    aws.assert_done()


@pytest.mark.regression
def test_an_alarm_cloudwatch_does_not_have_refuses(aws, capsys):
    aws.group(config(BLUE, GREEN))
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK")])
    assert run(aws, "--alarms-overridden") == refuse.REFUSED
    out = capsys.readouterr().out
    assert (
        f"::error title=An alarm does not exist::Deployment group {APPLICATION}/{GROUP} watches {GREEN}"
        in out
    )
    aws.assert_done()


@pytest.mark.regression
def test_the_names_read_are_the_groups_not_the_expected_ones(aws, capsys):
    """PE condition 11: the names come from get-deployment-group. An extra
    alarm the group polls is read and can refuse."""
    extra = "experimentation-api-latency-staging"
    aws.group(config(BLUE, GREEN, extra))
    aws.alarms(
        sorted([BLUE, GREEN, extra]),
        [alarm(BLUE, "OK"), alarm(GREEN, "OK"), alarm(extra, "ALARM")],
    )
    assert run(aws) == refuse.REFUSED
    assert (
        f"::error title=An alarm is already firing::{extra}" in capsys.readouterr().out
    )
    aws.assert_done()


@pytest.mark.regression
def test_a_state_the_script_does_not_know_is_could_not_tell(aws, capsys):
    aws.group(config(BLUE, GREEN))
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK"), alarm(GREEN, "PENDING")])
    assert run(aws) == refuse.UNKNOWN
    assert (
        "::error title=An alarm's state could not be read::" in capsys.readouterr().out
    )


@pytest.mark.regression
def test_an_aws_error_on_either_read_stops_the_deploy(aws, capsys):
    aws.group_error()
    assert run(aws) == refuse.UNKNOWN
    out = capsys.readouterr().out
    assert "::error title=Could not read the API's alarms::" in out
    assert "AccessDeniedException" in out
    aws.assert_done()

    aws.group(config(BLUE, GREEN))
    aws.alarms_error()
    assert run(aws) == refuse.UNKNOWN
    assert "Throttling" in capsys.readouterr().out
    aws.assert_done()


@pytest.mark.regression
@pytest.mark.parametrize("expect", [[], [""], ["  "]])
def test_no_expected_alarm_is_could_not_tell(aws, capsys, expect):
    """`--expect` is required and must name something: a step that lost its
    alarm names stops the deploy rather than checking nothing."""
    assert run(aws, expect=expect) == refuse.UNKNOWN
    assert aws.calls == []


def test_the_stubs_refuse_anything_unexpected(aws):
    """The probe itself: a call the test did not queue is not answered, and
    with the blank chain nothing could be signed or sent."""
    with pytest.raises(botocore.exceptions.UnStubbedResponseError):
        aws(["deploy", "get-deployment-group", "--application-name", "x",
             "--deployment-group-name", "y"])  # fmt: skip
    # Outside the Stubber, the client has no credentials to send with.
    with pytest.raises(botocore.exceptions.NoCredentialsError):
        aws.cloudwatch.describe_alarms(AlarmNames=[BLUE])


def test_the_script_is_read_only():
    assert refuse.OPERATIONS == {
        ("deploy", "get-deployment-group"),
        ("cloudwatch", "describe-alarms"),
    }
    with pytest.raises(ValueError):
        refuse.run_aws(["deploy", "create-deployment"])
    literals = {
        node.value
        for node in ast.walk(
            ast.parse((SCRIPTS / "refuse_alarm_active.py").read_text())
        )
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "describe-alarms" in literals, "the probe reads nothing"
    # The CLI pages describe-alarms only when none of these is passed.
    for flag in ("--max-items", "--page-size", "--no-paginate"):
        assert flag not in literals, flag


# --- the group's deployment config (#795) ---------------------------------------

CONFIG_WARNINGS = {
    "differs": "::warning title=The deployment group's config differs from the stack's::",
    "missing": "::warning title=The deployment group names no deployment config::",
    "unchecked": "::warning title=The deployment config was not checked::",
}


def _warnings(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith("::warning")]


@pytest.mark.regression
@pytest.mark.parametrize("stage", sorted(refuse.STAGES))
def test_the_stacks_config_is_logged_and_warns_nothing(aws, capsys, stage):
    aws.group(config(BLUE, GREEN), deployment_config=STACK_CONFIG)
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK"), alarm(GREEN, "OK")])
    assert run(aws, stage=stage, expect_config=STACK_CONFIG) == refuse.OK
    out = capsys.readouterr().out
    assert f"deployment group {APPLICATION}/{GROUP} uses {STACK_CONFIG}" in out
    assert _warnings(out) == [] and "::error" not in out
    aws.assert_done()


@pytest.mark.regression
@pytest.mark.parametrize("overridden", [False, True])
def test_a_different_config_warns_and_does_not_refuse(aws, capsys, overridden):
    """PE C7: a group the stack change never reached warns; the exit status is
    the alarms' alone."""
    aws.group(config(BLUE, GREEN), deployment_config=OTHER_CONFIG)
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK"), alarm(GREEN, "OK")])
    extra = ["--alarms-overridden"] if overridden else []
    assert run(aws, *extra, expect_config=STACK_CONFIG) == refuse.OK
    out = capsys.readouterr().out
    (warning,) = _warnings(out)
    assert warning.startswith(
        CONFIG_WARNINGS["differs"]
        + f"Deployment group {APPLICATION}/{GROUP} uses {OTHER_CONFIG}; the "
        f"Fargate stack gives it {STACK_CONFIG}."
    ), warning
    assert warning.endswith("This deploy goes on."), warning
    # And as a plain line in the log, not only as an annotation.
    assert (
        "warning: The deployment group's config differs from the stack's. "
        f"Deployment group {APPLICATION}/{GROUP} uses {OTHER_CONFIG}"
    ) in out
    assert "::error" not in out
    aws.assert_done()


@pytest.mark.regression
def test_a_different_config_does_not_change_an_alarm_refusal(aws, capsys):
    aws.group(config(BLUE, GREEN), deployment_config=OTHER_CONFIG)
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK"), alarm(GREEN, "ALARM")])
    assert run(aws, expect_config=STACK_CONFIG) == refuse.REFUSED
    out = capsys.readouterr().out
    assert CONFIG_WARNINGS["differs"] in out
    assert f"::error title=An alarm is already firing::{GREEN}" in out
    aws.assert_done()


@pytest.mark.regression
@pytest.mark.parametrize("value", [MISSING, "  "])
def test_a_missing_config_warns_and_does_not_refuse(aws, capsys, value):
    aws.group(config(BLUE, GREEN), deployment_config=value)
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK"), alarm(GREEN, "OK")])
    assert run(aws, expect_config=STACK_CONFIG) == refuse.OK
    out = capsys.readouterr().out
    (warning,) = _warnings(out)
    assert warning.startswith(
        CONFIG_WARNINGS["missing"]
        + f"Deployment group {APPLICATION}/{GROUP} returned no deploymentConfigName; "
        f"the Fargate stack gives it {STACK_CONFIG}."
    ), warning
    assert "warning: The deployment group names no deployment config. " in out
    assert "::error" not in out
    aws.assert_done()


@pytest.mark.regression
@pytest.mark.parametrize("expected", ["", "  "])
def test_an_empty_expected_config_warns_and_does_not_refuse(aws, capsys, expected):
    """The job env lost its value: warn that nothing was compared, go on."""
    aws.group(config(BLUE, GREEN), deployment_config=OTHER_CONFIG)
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK"), alarm(GREEN, "OK")])
    assert run(aws, expect_config=expected) == refuse.OK
    out = capsys.readouterr().out
    (warning,) = _warnings(out)
    assert warning.startswith(CONFIG_WARNINGS["unchecked"]), warning
    assert "::error" not in out
    aws.assert_done()


@pytest.mark.regression
def test_without_expect_config_the_config_is_not_compared(aws, capsys):
    """The before-migration run passes no --expect-config: no second warning."""
    aws.group(config(BLUE, GREEN), deployment_config=OTHER_CONFIG)
    aws.alarms(sorted([BLUE, GREEN]), [alarm(BLUE, "OK"), alarm(GREEN, "OK")])
    assert run(aws, stage="before-migration") == refuse.OK
    out = capsys.readouterr().out
    assert _warnings(out) == [] and "deploymentConfig" not in out
    assert OTHER_CONFIG not in out
    aws.assert_done()


@pytest.mark.regression
def test_only_the_before_build_run_passes_the_job_envs_config():
    """Warn once a run (PE C7): the before-build step passes --expect-config
    from the job env, the before-migration step does not pass it at all, and
    no step spells a config name itself."""
    passed = {}
    for step in _steps(DEPLOY):
        run_text = step.get("run", "")
        if "scripts/refuse_alarm_active.py" in run_text:
            stage = re.search(r"--stage ([\w-]+)", run_text).group(1)
            passed[stage] = re.findall(r"--expect-config (\S+)", run_text)
    assert passed == {
        "before-build": ['"$CODEDEPLOY_DEPLOYMENT_CONFIG"'],
        "before-migration": [],
    }, passed
    assert "CodeDeployDefault." not in json.dumps(
        [s for s in _steps(DEPLOY) if "refuse_alarm_active" in s.get("run", "")]
    )
    literals = {
        node.value
        for node in ast.walk(
            ast.parse((SCRIPTS / "refuse_alarm_active.py").read_text())
        )
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not [v for v in literals if "CodeDeployDefault." in v], (
        "the script spells a deployment config name; it must come from --expect-config"
    )


# --- pinned to the CDK's names --------------------------------------------------


@pytest.mark.regression
def test_the_expected_alarms_are_the_stacks():
    """deploy.yml passes exactly the alarms the CDK stack creates, one per
    target group colour. A rename in stacks/names.py, a new colour, or a step
    that drops an --expect fails here."""
    job_env = _job(DEPLOY)["env"]
    steps = [
        s
        for s in _steps(DEPLOY)
        if "scripts/refuse_alarm_active.py" in s.get("run", "")
    ]
    assert len(steps) == 2, [s["name"] for s in steps]
    for env in ("staging", "prod"):
        rendered = {
            key: str(value).replace("${{ inputs.environment }}", env)
            for key, value in job_env.items()
        }
        for step in steps:
            variables = re.findall(r'--expect "\$(\w+)"', step["run"])
            passed = [rendered[var] for var in variables]
            assert passed == stack_alarms(env), (step["name"], passed)
            # Nothing else is passed as an --expect (a literal would dodge this).
            # (--expect-config is a different flag, counted apart.)
            assert step["run"].count("--expect ") == len(variables), step["name"]


# --- deploy.yml: placement and the step itself --------------------------------------


def _index(predicate) -> list[int]:
    return [i for i, s in enumerate(_steps(DEPLOY)) if predicate(s)]


@pytest.mark.regression
def test_it_runs_before_the_build_and_immediately_before_the_snapshot():
    """PE condition 11: immediately before the snapshot and migration it
    protects; the early run keeps W7's "Nothing has been built or changed"
    true."""
    (early,) = _index(lambda s: "--stage before-build" in s.get("run", ""))
    (late,) = _index(lambda s: "--stage before-migration" in s.get("run", ""))
    (snapshot,) = _index(lambda s: s.get("id") == "snapshot")
    (migrate,) = _index(lambda s: s.get("id") == "migrate")
    (active,) = _index(
        lambda s: "scripts/refuse_active_deployment.py" in s.get("run", "")
    )
    builds = _index(lambda s: "docker push" in s.get("run", ""))
    assert builds, "no build step found: this checked nothing"
    assert active < early < min(builds)
    assert max(builds) < late == snapshot - 1 < migrate
    for index in (early, late):
        step = _steps(DEPLOY)[index]
        assert step["env"]["OVERRIDE_ALARMS"] == "${{ inputs.override_alarms }}"
        assert "if" not in step and "continue-on-error" not in step


def _scenario(
    state_blue: str, state_green: str, deployment_config: Any = STACK_CONFIG
) -> list[dict]:
    info: dict[str, Any] = {
        "applicationName": APPLICATION,
        "deploymentGroupName": GROUP,
        "alarmConfiguration": config(BLUE, GREEN),
    }
    if deployment_config is not MISSING:
        info["deploymentConfigName"] = deployment_config
    return [
        rule(
            "deploy get-deployment-group",
            f"--application-name {APPLICATION}",
            f"--deployment-group-name {GROUP}",
            answers=[{"deploymentGroupInfo": info}],
        ),
        rule(
            "cloudwatch describe-alarms",
            f"--alarm-names {' '.join(sorted([BLUE, GREEN]))}",
            answers=[
                _cli_json(
                    {
                        "MetricAlarms": [
                            alarm(BLUE, state_blue),
                            alarm(GREEN, state_green),
                        ],
                        "CompositeAlarms": [],
                    }
                )
            ],
        ),
    ]


STEP_NAMES = (
    "Refuse while an API alarm is firing (before the build)",
    "Refuse while an API alarm is firing (before the migration)",
)


@pytest.mark.regression
@pytest.mark.parametrize("name", STEP_NAMES)
def test_the_step_refuses_on_alarm_as_written(runner, name):
    runner.scenario(_scenario("OK", "ALARM"))
    code, out, _, _ = runner.run(DEPLOY, _step(DEPLOY, name))
    assert code == 1, out
    assert (
        f"::error title=An alarm is already firing::{GREEN} is in ALARM in {ENV}" in out
    )
    assert [c[:2] for c in runner.calls()] == [
        ["deploy", "get-deployment-group"],
        ["cloudwatch", "describe-alarms"],
    ]
    assert "--alarms-overridden" not in json.dumps(runner.calls())


@pytest.mark.regression
@pytest.mark.parametrize("name", STEP_NAMES)
def test_the_step_goes_on_under_the_break_glass_only(runner, name):
    runner.scenario(_scenario("ALARM", "OK"))
    code, out, _, _ = runner.run(
        DEPLOY, _step(DEPLOY, name), inputs={"override_alarms": "true"}
    )
    assert code == 0, out
    assert f"{BLUE}: ALARM since" in out
    assert "::warning title=An alarm is firing, and the alarms are overridden::" in out

    runner.scenario(_scenario("OK", "INSUFFICIENT_DATA"))
    code, out, _, _ = runner.run(
        DEPLOY, _step(DEPLOY, name), inputs={"override_alarms": "false"}
    )
    assert code == 0, out
    assert f"no alarm of {APPLICATION}/{GROUP} is in ALARM" in out


@pytest.mark.regression
@pytest.mark.parametrize("name", STEP_NAMES)
def test_the_step_fails_closed_when_aws_fails(runner, name):
    runner.scenario(
        [rule("deploy get-deployment-group", answers=[{"error": "AccessDenied"}])]
    )
    code, out, _, _ = runner.run(DEPLOY, _step(DEPLOY, name))
    assert code == 2, out
    assert "::error title=Could not read the API's alarms::AccessDenied" in out


#: (group's deploymentConfigName, the warning the before-build step prints).
STEP_CONFIG_CASES = {
    "correct": (STACK_CONFIG, None),
    "wrong": (OTHER_CONFIG, CONFIG_WARNINGS["differs"]),
    "missing": (MISSING, CONFIG_WARNINGS["missing"]),
}


@pytest.mark.regression
@pytest.mark.parametrize("case", sorted(STEP_CONFIG_CASES))
def test_the_before_build_step_warns_on_the_groups_config_as_written(runner, case):
    """deploy.yml's own step, against the fake aws: the job env's config
    reaches the script, and a wrong or missing one warns and exits 0."""
    deployment_config, expected = STEP_CONFIG_CASES[case]
    runner.scenario(_scenario("OK", "OK", deployment_config))
    code, out, _, _ = runner.run(DEPLOY, _step(DEPLOY, STEP_NAMES[0]))
    assert code == 0, out
    warnings = _warnings(out)
    if expected is None:
        assert warnings == [], out
        assert f"deployment group {APPLICATION}/{GROUP} uses {STACK_CONFIG}" in out
    else:
        assert len(warnings) == 1 and warnings[0].startswith(expected), out
        assert f"the Fargate stack gives it {STACK_CONFIG}" in warnings[0]
        assert "\nwarning: " in out


@pytest.mark.regression
@pytest.mark.parametrize("case", ["wrong", "missing"])
def test_the_before_migration_step_does_not_warn_again(runner, case):
    deployment_config, _ = STEP_CONFIG_CASES[case]
    runner.scenario(_scenario("OK", "OK", deployment_config))
    code, out, _, _ = runner.run(DEPLOY, _step(DEPLOY, STEP_NAMES[1]))
    assert code == 0, out
    assert _warnings(out) == [], out
