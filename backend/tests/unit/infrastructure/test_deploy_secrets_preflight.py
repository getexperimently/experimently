"""Deploy checks each task definition's secret references, not names (#636).

deploy.yml's "Every secret the task definitions reference exists" step runs
`scripts/check_task_secrets.py`. The step it replaced ran `describe-secret`
by NAME, which passes while every task fails when the task definitions carry
a reference Secrets Manager does not resolve (a partial ARN, one that stops at
the name). The contract (EM T97 condition 7, PE condition C5):

* every Secrets Manager `valueFrom` of the API's, the migration's and the
  dashboard's newest revision is read;
* a reference that is not a complete ARN in this region and this account is
  refused BEFORE any `describe-secret` call;
* the rest are described by their complete ARN, and a failure fails the step;
* only secret NAMES are printed. Every reference, its account ID and its
  suffix are `::add-mask::`ed before anything else is printed, and the log
  this file checks is the one the runner would show, masks applied.

Every test RUNS the step's own `run:` script from the YAML, under the Runner
the other deploy tests use: a fake `aws` first on PATH that answers from
recorded task definitions, no AWS credentials, and the repository's conftest
behind it. The account and suffixes are fakes.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

from backend.tests.unit.infrastructure.test_dashboard_deploy_wiring import (
    DEPLOY,
    SCRIPTS,
    Runner,
    _index,
    _no_aws_credentials,
    _step,
    rule,
)

STEP = "Every secret the task definitions reference exists"
ENV = "staging"
REGION = "us-west-2"
#: Fakes, never a real account.
ACCOUNT = "111111111111"
OTHER_ACCOUNT = "222222222222"
PREFIX = f"/{ENV}/experimentation"
BACKEND = f"experimentation-backend-{ENV}"
MIGRATE = f"experimentation-migrate-{ENV}"
DASHBOARD = f"experimentation-dashboard-{ENV}"
DB_NAME = f"experimentation-database-{ENV}-aurora-credentials"

#: Secret name -> its fake suffix (six letters, distinct per secret).
SUFFIX = {
    f"{PREFIX}/jwt-secret": "JwtFak",
    f"{PREFIX}/first-superuser-password": "SupFak",
    f"{PREFIX}/audit-hmac-key": "AudFak",
    DB_NAME: "DbFake",
}


def arn(name: str, *, account: str = ACCOUNT, region: str = REGION) -> str:
    return f"arn:aws:secretsmanager:{region}:{account}:secret:{name}-{SUFFIX[name]}"


def app_secrets(profile: str = "core", **replace: str) -> list[dict]:
    """The backend container's `secrets`, as describe-task-definition returns them."""
    secrets = {
        "POSTGRES_USER": f"{arn(DB_NAME)}:username::",
        "POSTGRES_PASSWORD": f"{arn(DB_NAME)}:password::",
        "SECRET_KEY": arn(f"{PREFIX}/jwt-secret"),
        "FIRST_SUPERUSER_PASSWORD": arn(f"{PREFIX}/first-superuser-password"),
    }
    if profile == "full":
        secrets["AUDIT_HMAC_KEY"] = arn(f"{PREFIX}/audit-hmac-key")
    secrets.update(replace)
    return [{"name": k, "valueFrom": v} for k, v in secrets.items()]


def task_definition(family: str, container: str, secrets: list[dict]) -> dict:
    """The `taskDefinition` of a family's newest revision (the recorded shape)."""
    definition: dict = {"name": container, "image": "bootstrap"}
    if secrets:
        definition["secrets"] = secrets
    return {
        "taskDefinitionArn": (
            f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{family}:7"
        ),
        "family": family,
        "revision": 7,
        "status": "ACTIVE",
        "containerDefinitions": [definition],
    }


def described(name: str) -> dict:
    return {"Name": name, "ARN": arn(name)}


def scenario(
    backend: list[dict] | None = None,
    migrate: list[dict] | None = None,
    profile: str = "core",
    describe: dict[str, object] | None = None,
) -> list[dict]:
    """The fake `aws`'s answers: three task definitions, then describe-secret."""
    names = [f"{PREFIX}/jwt-secret", f"{PREFIX}/first-superuser-password", DB_NAME]
    if profile == "full":
        names.append(f"{PREFIX}/audit-hmac-key")
    answers = {name: described(name) for name in names}
    answers.update(describe or {})
    return [
        rule(
            "ecs describe-task-definition",
            BACKEND,
            answers=[
                task_definition(BACKEND, "backend", backend or app_secrets(profile))
            ],
        ),
        rule(
            "ecs describe-task-definition",
            MIGRATE,
            answers=[
                task_definition(MIGRATE, "backend", migrate or app_secrets(profile))
            ],
        ),
        rule(
            "ecs describe-task-definition",
            DASHBOARD,
            answers=[task_definition(DASHBOARD, "dashboard", [])],
        ),
        *[
            rule("secretsmanager describe-secret", arn(name), answers=[answer])
            for name, answer in answers.items()
        ],
    ]


def run_step(
    runner: Runner, rules: list[dict], profile: str = "core", **overrides: str
) -> tuple[int, str, str]:
    """(exit, raw log, step summary): stdout and stderr interleaved, in order.

    The runner masks a value only in what is printed AFTER its `::add-mask::`
    line, so the order of the two streams matters; Runner.run concatenates
    them, which would hide a value printed to stderr before its mask.
    """
    runner.scenario(rules)
    step = _step(DEPLOY, STEP)
    env = runner.env_for(
        DEPLOY,
        step,
        {},
        {"profile": profile},
        {"EXPECTED_ACCOUNT_ID": ACCOUNT, **overrides},
    )
    script = runner.root / "step.sh"
    script.write_text(step["run"])
    summary = runner.root / "github_step_summary"
    summary.write_text("")
    base = _no_aws_credentials(dict(os.environ))
    base.update(env)
    base.update(
        PATH=f"{runner.bin}{os.pathsep}{os.environ.get('PATH', '')}",
        FAKE_AWS_STATE=str(runner.state),
        GITHUB_STEP_SUMMARY=str(summary),
        GITHUB_ENV=str(runner.root / "github_env"),
        GITHUB_OUTPUT=str(runner.root / "github_output"),
    )
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        cwd=runner.work,
        env=base,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout, summary.read_text()


def shown(raw: str) -> str:
    """What the runner shows: `::add-mask::` lines consumed, later lines masked."""
    masks: list[str] = []
    lines = []
    for line in raw.splitlines():
        if line.startswith("::add-mask::"):
            masks.append(line[len("::add-mask::") :])
            continue
        for mask in sorted(masks, key=len, reverse=True):
            if mask:
                line = line.replace(mask, "***")
        lines.append(line)
    return "\n".join(lines)


def describes(runner: Runner) -> list[list[str]]:
    return [c for c in runner.calls() if c[:2] == ["secretsmanager", "describe-secret"]]


@pytest.fixture
def runner(tmp_path):
    return Runner(tmp_path)


# --- (c) complete ARNs that all exist pass -------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("profile", ["core", "full"])
def test_complete_arns_that_all_exist_pass(runner, profile):
    code, raw, summary = run_step(runner, scenario(profile=profile), profile)
    log = shown(raw)
    assert code == 0, log
    expected = [f"{PREFIX}/jwt-secret", f"{PREFIX}/first-superuser-password", DB_NAME]
    if profile == "full":
        expected.append(f"{PREFIX}/audit-hmac-key")
    for name in expected:
        assert f"exists: {name}" in log
    # One describe per distinct secret, by its complete ARN: the database
    # secret's two JSON-key references are one secret, described without the
    # `:username::` fields ECS adds.
    ids = sorted(call[call.index("--secret-id") + 1] for call in describes(runner))
    assert ids == sorted(arn(name) for name in expected)
    # All three families were read, the dashboard's too.
    read = [
        c[c.index("--task-definition") + 1]
        for c in runner.calls()
        if c[:2] == ["ecs", "describe-task-definition"]
    ]
    assert read == [BACKEND, MIGRATE, DASHBOARD]
    assert ACCOUNT not in log and summary == ""


# --- (a) a partial ARN fails before any describe-secret --------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "value, why",
    [
        # What `Secret.from_secret_name_v2` rendered (#636): the name, no suffix.
        (
            f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{PREFIX}/jwt-secret",
            "is a partial ARN",
        ),
        # A bare name: ECS would read it as an SSM parameter.
        (f"{PREFIX}/jwt-secret", "is not a Secrets Manager secret ARN"),
        (
            arn(f"{PREFIX}/jwt-secret", region="eu-west-1"),
            "names a secret in a region other than this deploy's",
        ),
        (
            arn(f"{PREFIX}/jwt-secret", account=OTHER_ACCOUNT),
            "names a secret in an account other than this environment's",
        ),
        (
            f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter{PREFIX}/jwt-secret",
            "is not a Secrets Manager secret ARN",
        ),
    ],
    ids=["partial-arn", "bare-name", "wrong-region", "wrong-account", "ssm"],
)
def test_a_reference_that_is_not_a_complete_arn_fails_before_any_describe(
    runner, value, why
):
    rules = scenario(migrate=app_secrets(SECRET_KEY=value))
    code, raw, _ = run_step(runner, rules)
    log = shown(raw)
    assert code == 1, log
    assert f"{MIGRATE} backend/SECRET_KEY {why}" in log
    assert describes(runner) == [], "a Secrets Manager call was made before the refusal"
    # The refusal never repeats the reference, nor any account in it.
    assert value not in log
    assert ACCOUNT not in log and OTHER_ACCOUNT not in log
    # And nothing of the copy was masked away: a partial ARN's "suffix" would
    # be the word "secret" (`.../jwt-secret`), and masking that garbles the log.
    assert "***" not in log, log
    assert "docs/deployment/secrets-management.md" in log


@pytest.mark.regression
def test_a_value_with_a_newline_is_refused_and_cannot_write_a_workflow_command(runner):
    value = arn(f"{PREFIX}/jwt-secret") + "\n::warning::planted"
    code, raw, _ = run_step(runner, scenario(backend=app_secrets(SECRET_KEY=value)))
    assert code == 1
    assert "::warning::planted" not in raw
    assert describes(runner) == []


# --- (b) a planted account never reaches the log --------------------------------


ACCESS_DENIED = (
    "An error occurred (AccessDeniedException) when calling the DescribeSecret "
    f"operation: User: arn:aws:sts::{ACCOUNT}:assumed-role/deploy/gha is not "
    "authorized to perform: secretsmanager:DescribeSecret on resource: "
    f"{arn(PREFIX + '/jwt-secret')}"
)


@pytest.mark.regression
def test_the_account_and_the_suffix_never_reach_the_log(runner):
    """AWS's own error text names the ARN, as AccessDenied does: masked before."""
    rules = scenario(describe={f"{PREFIX}/jwt-secret": {"error": ACCESS_DENIED}})
    code, raw, summary = run_step(runner, rules)
    log = shown(raw)
    assert code == 1, log
    assert f"{PREFIX}/jwt-secret: AccessDeniedException" in log
    for planted in (ACCOUNT, *SUFFIX.values(), arn(f"{PREFIX}/jwt-secret")):
        assert planted not in log, f"{planted!r} reached the log:\n{log}"
        assert planted not in summary
    # AWS's message is printed in full (it says WHY), so the reference in it
    # reaches the log, and only the masks hide its account and suffix.
    assert f"secret:{PREFIX}/jwt-secret-***" in log, log
    # Every mask is registered before anything else is printed.
    lines = raw.splitlines()
    masks = [i for i, line in enumerate(lines) if line.startswith("::add-mask::")]
    assert masks and masks == list(range(len(masks))), raw


@pytest.mark.regression
def test_a_planted_other_account_is_refused_without_being_printed(runner):
    planted = arn(f"{PREFIX}/first-superuser-password", account=OTHER_ACCOUNT)
    rules = scenario(backend=app_secrets(FIRST_SUPERUSER_PASSWORD=planted))
    code, raw, summary = run_step(runner, rules)
    log = shown(raw)
    assert code == 1
    assert OTHER_ACCOUNT not in log and OTHER_ACCOUNT not in summary
    assert "SupFak" not in log
    assert describes(runner) == []


# --- (d) a describe-secret failure fails the step ------------------------------


@pytest.mark.regression
def test_a_describe_secret_failure_fails_the_step(runner):
    missing = (
        "An error occurred (ResourceNotFoundException) when calling the "
        "DescribeSecret operation: Secrets Manager can't find the specified secret."
    )
    rules = scenario(
        describe={f"{PREFIX}/first-superuser-password": {"error": missing}}
    )
    code, raw, _ = run_step(runner, rules)
    log = shown(raw)
    assert code == 1, log
    assert f"{PREFIX}/first-superuser-password: ResourceNotFoundException" in log, log
    assert "nothing was deployed" in log
    # The others were still described, so every missing one is named at once.
    assert len(describes(runner)) == 3


@pytest.mark.regression
def test_an_answer_for_a_different_secret_fails_the_step(runner):
    other = {"Name": f"{PREFIX}/jwt-secret", "ARN": arn(f"{PREFIX}/jwt-secret")[:-6]}
    rules = scenario(describe={f"{PREFIX}/jwt-secret": other})
    code, raw, _ = run_step(runner, rules)
    assert code == 1
    assert "answered for a different secret" in shown(raw)


# --- the profile's secrets must be referenced -----------------------------------


@pytest.mark.regression
def test_full_needs_the_audit_key_referenced_by_both_app_families(runner):
    rules = scenario(backend=app_secrets("full"), migrate=app_secrets("core"))
    code, raw, _ = run_step(runner, rules, profile="full")
    log = shown(raw)
    assert code == 1, log
    assert f"{MIGRATE} does not reference {PREFIX}/audit-hmac-key" in log
    assert f"{BACKEND} does not reference" not in log
    assert describes(runner) == []


@pytest.mark.regression
def test_an_app_family_that_references_no_jwt_secret_fails(runner):
    secrets = [s for s in app_secrets() if s["name"] != "SECRET_KEY"]
    code, raw, _ = run_step(runner, scenario(backend=secrets))
    assert code == 1
    assert f"{BACKEND} does not reference {PREFIX}/jwt-secret" in shown(raw)


@pytest.mark.regression
def test_an_unreadable_task_definition_stops_the_deploy(runner):
    rules = scenario()
    rules[0] = rule(
        "ecs describe-task-definition",
        BACKEND,
        answers=[{"error": "An error occurred (ClientException) Unable to describe"}],
    )
    code, raw, _ = run_step(runner, rules)
    assert code == 2
    assert f"Could not read a task definition::{BACKEND}" in raw
    assert describes(runner) == []


@pytest.mark.regression
def test_no_expected_account_stops_the_deploy(runner):
    code, raw, _ = run_step(runner, scenario(), EXPECTED_ACCOUNT_ID="")
    assert code == 2
    assert runner.calls() == []


# --- the wiring -------------------------------------------------------------------


def _script():
    path = SCRIPTS / "check_task_secrets.py"
    spec = importlib.util.spec_from_file_location("check_task_secrets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.regression
def test_the_step_reads_the_three_families_before_anything_is_built():
    run = _step(DEPLOY, STEP)["run"]
    for flag in (
        '--secrets-prefix "$SECRETS_PREFIX"',
        '--profile "$PROFILE"',
        '--region "$AWS_REGION"',
        '--app-family "$ECS_BACKEND_TASK_FAMILY"',
        '--app-family "$MIGRATE_TASK_FAMILY"',
        '--family "$ECS_DASHBOARD_TASK_FAMILY"',
    ):
        assert flag in run, flag
    # No by-name lookup is left anywhere in the workflow.
    text = DEPLOY.read_text(encoding="utf-8")
    assert "describe-secret" not in text, (
        "deploy.yml looks a secret up itself; the script is the one check"
    )
    assert _index(DEPLOY, STEP) < _index(DEPLOY, "ECR repositories exist")


@pytest.mark.regression
def test_the_script_only_reads():
    assert _script().OPERATIONS == frozenset(
        {
            ("ecs", "describe-task-definition"),
            ("secretsmanager", "describe-secret"),
        }
    )


@pytest.mark.regression
def test_the_required_names_are_the_ones_the_stacks_import():
    """Parity with stacks/secret_arns.py, the table the CDK validates inputs by."""
    import runpy

    table = runpy.run_path(
        str(
            Path(__file__).resolve().parents[4]
            / "infrastructure"
            / "cdk"
            / "stacks"
            / "secret_arns.py"
        )
    )
    inputs, module_only = table["SECRET_INPUTS"], table["MODULE_ONLY_INPUTS"]
    script = _script()
    assert set(script.APP_SECRETS) == {
        name for var, name in inputs.items() if var not in module_only
    }
    assert set(script.FULL_ONLY_SECRETS) == {inputs[var] for var in module_only}
