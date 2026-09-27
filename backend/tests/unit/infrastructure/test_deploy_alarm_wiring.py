"""deploy.yml once the API's deployment group has alarms (#148 PR-2).

What the forward deploy says and does when CodeDeploy stops it for an alarm,
and the break-glass that lets a fix through while an alarm is firing. The
steps are RUN, as written in the YAML, by test_dashboard_deploy_wiring's
Runner: `bash -eo pipefail`, the step's `env:` resolved from the YAML, a fake
`aws` first on PATH answering from a scenario, and no credentials.

* The alarm step (PE condition 6): read-only, one branch per exit of
  scripts/api_serving.py, and none of them advises Rollback.
* Exclusivity (PE condition 7, UX C4): the approved "Migrated" warning never
  runs with the alarm step; the not-approved one does, because it stays true.
* Step (i) (PE condition 7): after an alarm in the hour after the shift it says
  so, points the dashboard at Method 2, and claims neither the re-run refusal
  nor the rollback line.
* The summary and Slack (UX W3a/W3b/W5): until when the alarms watch, from the
  shift step's `bake_end`; the plain "not announced" sentence (O6 is open).
* The break-glass (EM condition 4 (a)-(f)): off by default, a reason required,
  the run name, the override exactly once and only under the input, and the
  summary and Slack saying the deployment was unwatched.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from backend.tests.unit.infrastructure.test_dashboard_deploy_wiring import (
    API_FAMILY_REVISION,
    BEFORE_DASHBOARD,
    DEPLOY,
    ROLLBACK,
    SCRIPTS,
    _code,
    _if,
    _load,
    _step,
    _steps,
    api_rules,
    rule,
    runner,
)
from backend.tests.unit.infrastructure.test_deploy_docs import FALSE_CANARY_CLAIMS
from backend.tests.unit.infrastructure.test_forward_deploy_completes import (
    AFTER as API_AFTER,
)
from backend.tests.unit.infrastructure.test_forward_deploy_completes import (
    BEFORE as API_BEFORE,
)
from backend.tests.unit.infrastructure.test_forward_deploy_completes import (
    RULES_BLUE,
    RULES_GREEN,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
FLAG = "--override-alarm-configuration enabled=false"
GREEN_ALARM = "experimentation-api-5xx-green-staging"
ALARM_DOC = "docs/deployment/rollback-runbook.md#an-alarm-rolled-the-api-back"
FIRING_DOC = "docs/deployment/rollback-runbook.md#fix-forward-while-an-alarm-is-firing"
WRONG_DOC = "docs/deployment/deployment-guide.md#the-api-route-and-the-primary-task-set-disagree"

#: Copy that sends an operator to Rollback. None of it may appear where
#: CodeDeploy is already rolling the API back.
ROLLBACK_ADVICE = (
    "Actions → Rollback",
    "use the rollback line",
    "Roll back with",
    "puts back the API as well",
)


def _outputs(**changes: dict) -> dict:
    outputs = {k: dict(v) for k, v in BEFORE_DASHBOARD.items()}
    outputs["migrate"] = {"__outcome__": "success"}
    for key, value in changes.items():
        outputs.setdefault(key.replace("_", "-"), {}).update(value)
    return outputs


def _alarmed(approved: str = "true") -> dict:
    return _outputs(
        api_serving={
            "__outcome__": "failure",
            "result": "alarm",
            "approved": approved,
            "alarms": GREEN_ALARM,
        }
    )


# --- the alarm step: one branch per api_serving.py exit (PE condition 6) ----------------


def _unknown_rules() -> list:
    rules = api_rules(API_BEFORE, RULES_BLUE)
    rules[1] = rule(
        "cloudformation describe-stack-resources",
        answers=[{"error": "An error occurred (ExpiredToken)"}],
    )
    return rules


#: services, rules -> what api_serving.py answers for the revision serving
#: BEFORE the deploy (API_FAMILY_REVISION, the old one).
EXITS = {
    "0-back": (api_rules(API_BEFORE, RULES_BLUE), "confirmed"),
    "1-not-yet": (api_rules(API_AFTER, RULES_GREEN), "not confirmed yet"),
    "3-wrong-route": (api_rules(API_BEFORE, RULES_GREEN), "route disagrees"),
    "2-unknown": (_unknown_rules(), "could not tell"),
}


@pytest.mark.regression
@pytest.mark.parametrize("case", sorted(EXITS))
def test_the_alarm_step_says_what_api_serving_found(runner, case):
    rules, verdict = EXITS[case]
    runner.scenario(rules)
    code, out, written, _ = runner.run(
        DEPLOY, _step(DEPLOY, "alarm"), _alarmed(), {}, VERSION="v1.2.3"
    )
    assert code == 0, out
    assert written == {"api_back": verdict}, out
    assert GREEN_ALARM in out
    for advice in ROLLBACK_ADVICE:
        assert advice not in out, (advice, out)
    assert "migration stays applied" in out
    # Read-only.
    assert not [c for c in runner.calls() if c[0] == "deploy"], runner.calls()
    if case == "0-back":
        assert "experimentation-backend-staging:42 is serving (checked just now)" in out
        assert "the rollback line is not needed" in out
        assert ALARM_DOC in out
    if case == "1-not-yet":
        assert "not confirmed serving yet" in out
        assert "aws deploy get-deployment --deployment-id d-ABCDEF123" in out
    if case == "3-wrong-route":
        # Not W2b's "not confirmed yet": the route guidance.
        assert WRONG_DOC in out
        assert "not confirmed" not in out
    if case == "2-unknown":
        assert "could not be told" in out


@pytest.mark.regression
def test_an_alarm_before_the_approval_is_nothing_shifted(runner):
    runner.scenario([])
    code, out, written, _ = runner.run(
        DEPLOY, _step(DEPLOY, "alarm"), _alarmed(approved=""), {}, VERSION="v1.2.3"
    )
    assert code == 0, out
    assert written == {"api_back": "nothing shifted"}
    assert "Stopped by an alarm" in out and "nothing shifted" in out
    assert FIRING_DOC in out
    assert runner.calls() == []
    assert "override" not in out.lower()


def test_the_alarm_step_never_prints_an_empty_alarm(runner):
    runner.scenario(api_rules(API_BEFORE, RULES_BLUE))
    outputs = _alarmed()
    outputs["api-serving"]["alarms"] = ""
    _, out, _, _ = runner.run(DEPLOY, _step(DEPLOY, "alarm"), outputs, {})
    assert (
        "one of the deployment group alarms (experimentation-api-5xx-blue-staging, "
        "experimentation-api-5xx-green-staging)" in out
    )


# --- exclusivity (PE condition 7, UX C4) ---------------------------------------------------


def _migrated(approved: bool) -> dict:
    (step,) = [
        s
        for s in _steps(DEPLOY)
        if "steps.migrate.outcome" in str(s.get("if", ""))
        and ("approved == 'true'" in s["if"]) is approved
    ]
    return step


@pytest.mark.regression
@pytest.mark.parametrize("approved", ["", "true"])
@pytest.mark.parametrize("result", ["alarm", "failed", "wrong-route", "timeout"])
def test_the_alarm_step_and_the_warnings_are_exclusive_where_they_must_be(
    approved, result
):
    outputs = {
        "migrate": {"__outcome__": "success"},
        "api-serving": {
            "__outcome__": "failure",
            "approved": approved,
            "result": result,
        },
    }
    fires = {
        name: _if(step["if"], outputs, failed=True)
        for name, step in (
            ("not-approved", _migrated(False)),
            ("approved", _migrated(True)),
            ("alarm", _step(DEPLOY, "alarm")),
            ("i", _step(DEPLOY, "after-shift")),
        )
    }
    assert fires["alarm"] is (result == "alarm")
    assert not (fires["alarm"] and fires["approved"]), fires
    assert not fires["i"], fires
    # The not-approved warning stays true when an alarm stopped an unapproved
    # deployment: the migration is applied and nothing shifted.
    assert fires["not-approved"] is (approved != "true")
    assert fires["approved"] is (approved == "true" and result != "alarm")


# --- step (i) after an alarm in the hour after the shift (PE condition 7) -----------------


def _step_i(runner, error_code: str | None, **env: str):
    rules = []
    if error_code is not None:
        rules.append(rule("deploy get-deployment", answers=[error_code]))
    runner.scenario(rules)
    base = {
        "GUARD": "0",
        "GUARD_LINE": "",
        "RECHECK": "1",
        "RECHECK_LINE": "NOT YET: the PRIMARY task set runs x:42",
        "ROLLOUT": "completed",
        "VERSION": "v1.2.3",
    }
    return runner.run(
        DEPLOY, _step(DEPLOY, "after-shift"), _outputs(), {}, **{**base, **env}
    )


@pytest.mark.regression
def test_step_i_names_an_alarm_and_sends_the_dashboard_to_method_2(runner):
    code, out, written, _ = _step_i(runner, "ALARM_ACTIVE")
    assert code == 0, out
    assert written == {"alarm": "true"}
    assert "API rolled back by an alarm, dashboard not" in out
    assert "experimentation-backend-staging:42 by itself" in out
    assert "rollback-runbook.md Method 2 (the dashboard block)" in out
    assert ALARM_DOC in out
    # Failure mode C: neither is true after an alarm.
    assert "Deploy refuses a re-run" not in out
    for advice in ROLLBACK_ADVICE:
        assert advice not in out, (advice, out)
    (read,) = [c for c in runner.calls() if c[:2] == ["deploy", "get-deployment"]]
    assert "--deployment-id" in read and "d-ABCDEF123" in read


@pytest.mark.regression
@pytest.mark.parametrize("answer", ["None", "HEALTH_CONSTRAINTS", None])
def test_step_i_without_an_alarm_is_unchanged(runner, answer):
    code, out, written, _ = _step_i(runner, answer)
    assert code == 0, out
    assert "alarm" not in written
    assert "API deployed, dashboard not confirmed" in out
    assert "Deploy refuses a re-run until CodeDeploy deployment d-ABCDEF123" in out


def test_step_i_reads_nothing_when_every_api_check_passed(runner):
    code, out, _, _ = _step_i(runner, "ALARM_ACTIVE", RECHECK="", ROLLOUT="failed")
    assert code == 0, out
    assert runner.calls() == []
    assert "The API is serving v1.2.3" in out


# --- the summary and Slack (UX W3a, W3b, W5; O6) --------------------------------------------


def _summary(runner, outputs: dict, inputs: dict | None = None, **env: str):
    runner.scenario([])
    return runner.run(
        DEPLOY,
        _step(DEPLOY, "summary"),
        outputs,
        {"job.status": "success", **(inputs or {})},
        **env,
    )


@pytest.mark.regression
def test_a_green_summary_says_until_when_the_alarms_watch(runner):
    outputs = _outputs(
        api_serving={
            "__outcome__": "success",
            "result": "serving",
            "live_target_group": "green",
            "shifted_at": "2026-09-26T23:59:00Z",
            "bake_end": "2026-09-27 00:59",
        }
    )
    code, out, written, summary = _summary(runner, outputs)
    assert code == 0, out
    flat = " ".join(summary.split())
    assert (
        "Alarms watch the API until CodeDeploy deployment d-ABCDEF123 ends, about an "
        "hour after its traffic shift (until about 2026-09-27 00:59 UTC): "
        "experimentation-api-5xx-blue-staging, experimentation-api-5xx-green-staging."
    ) in flat
    assert (
        "A rollback by an alarm after this run ends is not announced in #deployments"
        in flat
    )
    assert "aws deploy get-deployment --deployment-id d-ABCDEF123" in flat
    assert "timed only" not in flat
    assert "Rollback: Actions → Rollback → environment=staging" in flat
    assert written["api_slack"] == (
        "Alarms watch the API until about 2026-09-27 00:59 UTC. A rollback by an "
        "alarm after this run ends is not announced here: check deployment "
        "d-ABCDEF123."
    )


@pytest.mark.regression
def test_an_alarm_summary_replaces_the_rollback_line(runner):
    outputs = _alarmed()
    outputs["alarm"] = {"api_back": "confirmed", "__outcome__": "success"}
    code, out, written, summary = _summary(runner, outputs, {"job.status": "failure"})
    assert code == 0, out
    flat = " ".join(summary.split())
    assert f"| Traffic shift | rolled back by alarm {GREEN_ALARM} |" in flat
    assert (
        "Rollback: not needed for the API. CodeDeploy moved it back to "
        f"experimentation-backend-staging:42 after alarm {GREEN_ALARM} (confirmed)."
    ) in flat
    assert "Actions → Rollback" not in flat
    assert "Alarms watch the API until" not in flat
    assert written["api_slack"] == (
        f"rolled back by alarm {GREEN_ALARM}; serving "
        "experimentation-backend-staging:42 (confirmed)"
    )


def test_an_alarm_before_the_approval_summary(runner):
    code, out, written, summary = _summary(runner, _alarmed(approved=""))
    flat = " ".join(summary.split())
    assert "stopped by alarm" in flat and "before any traffic shifted" in flat
    assert "Rollback: not needed. Nothing shifted" in flat
    assert "Actions → Rollback" not in flat


# --- the break-glass (EM condition 4) ---------------------------------------------------------


def _document() -> dict:
    return _load(DEPLOY)


def _preflight_step() -> dict:
    (step,) = [
        s
        for s in _document()["jobs"]["preflight"]["steps"]
        if s.get("name") == "Confirm the alarm override"
    ]
    return step


@pytest.mark.regression
def test_4a_the_inputs_are_off_by_default_and_optional():
    inputs = _document()["on"]["workflow_dispatch"]["inputs"]
    assert inputs["override_alarms"] == {
        "description": inputs["override_alarms"]["description"],
        "required": False,
        "type": "boolean",
        "default": False,
    }
    assert "No alarm watches" in inputs["override_alarms"]["description"]
    assert inputs["override_alarms_reason"]["type"] == "string"
    assert inputs["override_alarms_reason"]["required"] is False
    assert inputs["override_alarms_reason"]["default"] == ""


@pytest.mark.regression
@pytest.mark.parametrize(
    "override, reason, refused",
    [
        ("true", "", True),
        ("true", "   ", True),
        ("false", "a reason", True),
        ("true", "fix for a bug in both releases", False),
        ("false", "", False),
    ],
)
def test_4a_the_preflight_refuses_an_override_without_a_reason_and_vice_versa(
    runner, override, reason, refused
):
    runner.scenario([])
    step = _preflight_step()
    code, out, _, summary = runner.run(
        DEPLOY,
        step,
        {},
        {"override_alarms": override, "override_alarms_reason": reason},
        GITHUB_ACTOR="octocat",
    )
    assert (code != 0) is refused, out
    assert "Nothing was deployed" in out if refused else True
    assert runner.calls() == []  # the preflight holds no credential
    if override == "true" and not refused:
        assert "ALARMS OVERRIDDEN" in summary and reason in summary
        assert "::warning title=ALARMS OVERRIDDEN::" in out


def test_4a_the_preflight_holds_no_credential_and_runs_before_the_deploy_job():
    document = _document()
    preflight = document["jobs"]["preflight"]
    assert "id-token" not in preflight.get("permissions", {})
    assert "environment" not in preflight
    names = [s.get("name") for s in preflight["steps"]]
    assert names.index("Confirm the alarm override") < names.index(
        "The version is a release tag on main"
    )


@pytest.mark.regression
def test_4b_the_reason_reaches_a_shell_only_through_env():
    text = DEPLOY.read_text()
    runs = "\n".join(
        s["run"]
        for job in _document()["jobs"].values()
        for s in job["steps"]
        if "run" in s
    )
    assert "inputs.override_alarms" not in runs
    envs = [
        value
        for job in _document()["jobs"].values()
        for s in job["steps"]
        for value in (s.get("env") or {}).values()
    ]
    assert "${{ inputs.override_alarms_reason }}" in envs
    assert text.count("inputs.override_alarms_reason") == envs.count(
        "${{ inputs.override_alarms_reason }}"
    )


@pytest.mark.regression
def test_4c_the_run_name_says_alarms_overridden():
    run_name = _document()["run-name"]
    assert run_name.endswith(
        "${{ inputs.override_alarms && ' -- ALARMS OVERRIDDEN' || '' }}"
    ), run_name


def _create(runner, override: str):
    runner.scenario([rule("deploy create-deployment", answers=["d-NEW"])])
    code, out, written, _ = runner.run(
        DEPLOY,
        _step(DEPLOY, "codedeploy"),
        _outputs(api_td={"arn": API_FAMILY_REVISION}),
        {"override_alarms": override},
    )
    assert code == 0, out
    (call,) = [c for c in runner.calls() if c[:2] == ["deploy", "create-deployment"]]
    return " ".join(call), out


@pytest.mark.regression
def test_4d_p6_the_forward_deploy_overrides_the_alarms_only_under_the_input(runner):
    """P6, rewritten by EM condition 4(d): the override is in deploy.yml exactly
    once, in the create-deployment step, and passed only when the input is set.
    Dropping the gate passes it on every deploy, and this fails."""
    text = DEPLOY.read_text()
    assert text.count(FLAG) == 1
    code = "\n".join(_code(s["run"]) for s in _steps(DEPLOY) if "run" in s)
    assert code.count("--override-alarm-configuration") == 1
    assert FLAG in _step(DEPLOY, "codedeploy")["run"]
    assert _step(DEPLOY, "codedeploy")["env"]["OVERRIDE_ALARMS"] == (
        "${{ inputs.override_alarms }}"
    )
    plain, out = _create(runner, "false")
    assert "--override-alarm-configuration" not in plain, plain
    assert "ALARMS OVERRIDDEN" not in out
    overridden, out = _create(runner, "true")
    assert FLAG in overridden, overridden
    assert "::warning title=ALARMS OVERRIDDEN::" in out
    # And no script passes it. The two that name it are tooling that never
    # runs in a deploy: the IAM generator's flag map, and the CI CLI check.
    tooling = {"iam_actions.py", "check_create_deployment_cli.py"}
    for path in sorted(SCRIPTS.glob("*.py")) + sorted(SCRIPTS.glob("*.sh")):
        if path.name in tooling:
            continue
        assert "--override-alarm-configuration" not in path.read_text(), path.name


@pytest.mark.regression
def test_rollback_always_overrides_the_alarms():
    """M5a: the release being rolled back holds the alarm; without the override
    CodeDeploy stops Rollback's own deployment."""
    (step,) = [s for s in _steps(ROLLBACK) if s.get("id") == "codedeploy"]
    call = re.sub(r"\\\s*\n\s*", " ", _code(step["run"]))
    (line,) = [ln for ln in call.splitlines() if "aws deploy create-deployment" in ln]
    assert FLAG in line
    assert step["if"] == "steps.stop.outputs.already_serving != 'true'"


@pytest.mark.regression
def test_4e_an_overridden_run_says_it_was_unwatched(runner):
    outputs = _outputs(
        api_serving={
            "__outcome__": "success",
            "result": "serving",
            "live_target_group": "green",
            "shifted_at": "2026-09-26T23:59:00Z",
            "bake_end": "2026-09-27 00:59",
        }
    )
    reason = "fix for the bug in both releases"
    code, out, written, summary = _summary(
        runner,
        outputs,
        {"override_alarms": "true", "override_alarms_reason": reason},
    )
    assert code == 0, out
    flat = " ".join(summary.split())
    assert (
        f"No alarm watched this deployment: it was created with the API's alarms overridden (reason: {reason})."
        in flat
    )
    assert "Nothing rolls it back by itself" in flat
    assert "roll back with the line below within that hour" in flat
    assert "The next deploy is watched again." in flat
    assert "Alarms watch the API until" not in flat
    assert "(ALARMS OVERRIDDEN)" in flat
    assert written["api_slack"].startswith("ALARMS OVERRIDDEN: no alarm watched")
    assert reason in written["api_slack"]
    for pattern in FALSE_CANARY_CLAIMS:
        assert not re.search(pattern, flat, re.I), pattern
    slack = [s for s in _steps(DEPLOY) if s.get("name") == "Notify deployment result"][
        0
    ]["with"]["slack-message"]
    assert (
        "${{ inputs.override_alarms && ' -- ALARMS OVERRIDDEN, unwatched' || '' }}"
        in slack
    )
    assert "${{ steps.summary.outputs.api_slack" in slack


@pytest.mark.regression
def test_4f_no_refusal_or_error_copy_names_the_input():
    """The input is explained in one place, the runbook section; nothing that
    refuses or fails points at it, so it is not reached for by reflex."""
    for path in (
        ROLLBACK,
        *sorted(SCRIPTS.glob("*.py")),
        *sorted(SCRIPTS.glob("*.sh")),
    ):
        assert "override_alarms" not in path.read_text(), path.name
    for line in DEPLOY.read_text().splitlines():
        if "::error" in line:
            assert "override_alarms" not in line, line


# --- the CLI check (EM condition 13) ---------------------------------------------------------


def _cli_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_create_deployment_cli", SCRIPTS / "check_create_deployment_cli.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.regression
def test_the_cli_check_reads_the_workflows_exact_flags():
    cli = _cli_module()
    rollback = cli.flags(ROLLBACK)
    deploy = cli.flags(DEPLOY)
    assert rollback == [
        "--application-name",
        "--deployment-group-name",
        "--deployment-config-name",
        "--description",
        "--override-alarm-configuration",
        "--revision",
        "--query",
        "--output",
    ]
    assert deploy.count("--override-alarm-configuration") == 1
    assert "--arg" not in rollback + deploy  # jq's, inside $(...)
    argv = cli.argv(rollback)
    assert argv[-2:] == ["--generate-cli-skeleton", "output"]
    assert "enabled=false" in argv
    assert "enabled=nope" in cli.argv(rollback, "enabled=nope")


def test_the_cli_check_refuses_a_workflow_without_the_override(tmp_path, monkeypatch):
    cli = _cli_module()
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    for path in (DEPLOY, ROLLBACK):
        (workflows / path.name).write_text(path.read_text())
    tampered = workflows / "rollback.yml"
    text = tampered.read_text()
    tampered.write_text(text.replace(f" \\\n            {FLAG} \\", " \\"))
    assert tampered.read_text() != text
    assert "--override-alarm-configuration" not in cli.flags(tampered)
    monkeypatch.setattr(cli, "WORKFLOWS", workflows)
    assert cli.main(["--print"]) == 1


def test_the_cli_check_refuses_to_run_with_credentials(monkeypatch):
    cli = _cli_module()
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKEFAKEFAKEFAKE")
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: calls.append(a))
    assert cli.main([]) == 1
    assert calls == []


def test_the_cli_check_runs_in_the_unfiltered_cdk_job():
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "infrastructure-tests.yml").read_text()
    )
    assert "paths" not in workflow[True]["pull_request"]
    job = workflow["jobs"]["cdk-python-tests"]
    assert job["permissions"] == {"contents": "read"}
    (step,) = [
        s
        for s in job["steps"]
        if "scripts/check_create_deployment_cli.py" in s.get("run", "")
    ]
    assert step["env"] == {
        "AWS_CONFIG_FILE": "/dev/null",
        "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    assert "--print" not in step["run"]


def test_the_cli_check_script_runs_standalone_for_print():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_create_deployment_cli.py"), "--print"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("--generate-cli-skeleton output") == 2


def test_names_used_by_the_alarm_copy_are_the_jobs():
    env = [j for j in _load(DEPLOY)["jobs"].values() if "environment" in j][0]["env"]
    assert (
        env["API_ALARM_BLUE"]
        == "experimentation-api-5xx-blue-${{ inputs.environment }}"
    )
    assert env["API_ALARM_GREEN"] == (
        "experimentation-api-5xx-green-${{ inputs.environment }}"
    )
    shift = _step(DEPLOY, "api-serving")["run"]
    assert (
        '--alarm "$API_ALARM_BLUE"' in shift and '--alarm "$API_ALARM_GREEN"' in shift
    )
    assert '--bake-minutes "$BAKE_MINUTES"' in shift
