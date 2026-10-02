"""The task definitions' secrets are referenced by complete ARN (#636).

Importing the secrets by name rendered a *partial* ARN -- one that stops at
the secret's name -- into every API and migration task definition's
``valueFrom``. ECS passes ``valueFrom`` to ``GetSecretValue`` unchanged, and
Secrets Manager does not resolve that partial ARN, so every task would have
stopped at start. The stacks now import the three hand-made secrets with
``from_secret_complete_arn``, from synth inputs that ``app.py`` validates
(``stacks/secret_arns.py``).

Two halves:

* **the validator** -- what each input accepts and refuses, and that a refusal
  never repeats the value it was given (an ARN carries the account ID);
* **the synthesised templates** -- for dev, staging, prod and demo, on both
  profiles: every hand-made secret's ``valueFrom`` is a literal complete ARN,
  no IAM resource holds a ``-??????`` wildcard or a suffix-less secret ARN, and
  each execution role may read exactly the secrets its task definition supplies.
"""

from __future__ import annotations

import json
import re
import runpy
from functools import cache

import aws_cdk as cdk
import pytest

from .test_app_profiles import (
    CDK_DIR,
    FAKE_ACCOUNT,
    FAKE_REGION,
    SECRET_ARN_INPUTS,
    _app_environment,
    fake_secret_arn,
    modules_present,
)

ENVIRONMENTS = ("dev", "staging", "prod", "demo")
SECRET_ARNS_PY = CDK_DIR / "stacks" / "secret_arns.py"

#: The container variable each input's secret is supplied as.
SUPPLIED_AS = {
    "SECRET_KEY": "JWT_SECRET_ARN",
    "FIRST_SUPERUSER_PASSWORD": "FIRST_SUPERUSER_PASSWORD_SECRET_ARN",
    "AUDIT_HMAC_KEY": "AUDIT_HMAC_KEY_SECRET_ARN",
}

#: The two secrets read from the database stack's generated secret, by field
#: (``<arn>:username::``). Their ARN is a cross-stack reference by nature, so
#: they are the only ``valueFrom`` allowed to be an intrinsic; any other is a
#: failure. test_database_wiring.py checks which secret they read.
DATABASE_FIELDS = {"POSTGRES_USER": ":username::", "POSTGRES_PASSWORD": ":password::"}

#: A complete Secrets Manager ARN: name, then "-" and six letters or digits.
COMPLETE_ARN = re.compile(
    r"arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:/[a-z]+/experimentation/"
    r"[a-z-]+-[A-Za-z0-9]{6}"
)


def _secret_arns():
    return runpy.run_path(str(SECRET_ARNS_PY))


def _resolve(environ: dict, env_name: str = "staging", include_modules: bool = True):
    return _secret_arns()["resolve_secret_arns"](
        environ,
        env_name=env_name,
        account=FAKE_ACCOUNT,
        region=FAKE_REGION,
        include_modules=include_modules,
    )


def _all_inputs(env_name: str, **overrides: str) -> dict:
    values = {v: fake_secret_arn(v, env_name) for v in SECRET_ARN_INPUTS}
    values.update(overrides)
    return values


def _refusal(environ: dict, env_name: str = "staging", include_modules: bool = True):
    with pytest.raises(ValueError) as excinfo:
        _resolve(environ, env_name, include_modules)
    return str(excinfo.value)


def _assert_explains(message: str, variable: str, env_name: str) -> None:
    """A refusal names the variable and the read-only command that yields it."""
    name = f"/{env_name}/experimentation/{SECRET_ARN_INPUTS[variable]}"
    assert message.startswith(variable + " "), message
    assert (
        f"aws secretsmanager describe-secret --secret-id {name} "
        "--query ARN --output text"
    ) in message, message
    assert not re.search(r"[0-9]", message), f"a refusal carries a digit: {message}"


# --- the validator ------------------------------------------------------------


@pytest.mark.parametrize("env_name", ENVIRONMENTS)
def test_the_fixture_arns_are_accepted_unchanged(env_name):
    values = _all_inputs(env_name)
    assert _resolve(values, env_name) == values


@pytest.mark.regression
@pytest.mark.parametrize("variable", sorted(SECRET_ARN_INPUTS))
def test_a_partial_arn_is_refused(variable):
    """The exact form the name-based import rendered: the name, no suffix."""
    partial = fake_secret_arn(variable, "staging").rsplit("-", 1)[0]
    message = _refusal(_all_inputs("staging", **{variable: partial}))
    assert "is a partial ARN" in message, message
    _assert_explains(message, variable, "staging")


@pytest.mark.regression
@pytest.mark.parametrize("variable", sorted(SECRET_ARN_INPUTS))
def test_a_staging_arn_is_refused_in_a_prod_synth(variable):
    staging = fake_secret_arn(variable, "staging")
    message = _refusal(_all_inputs("prod", **{variable: staging}), env_name="prod")
    assert "names a secret of the staging environment, not prod" in message, message
    _assert_explains(message, variable, "prod")


@pytest.mark.regression
@pytest.mark.parametrize("variable", sorted(SECRET_ARN_INPUTS))
def test_a_wrong_region_is_refused(variable):
    other = fake_secret_arn(variable, "staging", region="eu-west-1")
    message = _refusal(_all_inputs("staging", **{variable: other}))
    assert "a region other than the stack's" in message, message
    _assert_explains(message, variable, "staging")


@pytest.mark.regression
@pytest.mark.parametrize("variable", sorted(SECRET_ARN_INPUTS))
def test_a_wrong_account_is_refused(variable):
    other = fake_secret_arn(variable, "staging", account="000000000000")
    message = _refusal(_all_inputs("staging", **{variable: other}))
    assert "an account other than the stack's" in message, message
    _assert_explains(message, variable, "staging")


@pytest.mark.regression
def test_the_jwt_arn_in_the_superuser_slot_is_refused():
    jwt = fake_secret_arn("JWT_SECRET_ARN", "staging")
    message = _refusal(_all_inputs("staging", FIRST_SUPERUSER_PASSWORD_SECRET_ARN=jwt))
    assert "names the secret that belongs in JWT_SECRET_ARN" in message, message
    _assert_explains(message, "FIRST_SUPERUSER_PASSWORD_SECRET_ARN", "staging")


@pytest.mark.regression
@pytest.mark.parametrize(
    "value",
    [
        "/staging/experimentation/jwt-secret",
        "jwt-secret",
        "arn:aws:ssm:us-west-2:111111111111:parameter/staging/jwt-secret",
        "arn:aws:secretsmanager:us-west-2:1111:secret:/staging/experimentation/jwt-secret-JwtFak",
        "arn:aws:secretsmanager:us-west-2:111111111111:secret:/staging/experimentation/jwt-secret-JwtFakX",
        "arn:aws:secretsmanager:us-west-2:111111111111:secret:/staging/experimentation/other-JwtFak",
        "x" * 5000,
    ],
    ids=[
        "bare-name",
        "short-name",
        "ssm",
        "short-account",
        "seven-char-suffix",
        "other-name",
        "huge",
    ],
)
def test_a_malformed_value_is_refused(value):
    message = _refusal(_all_inputs("staging", JWT_SECRET_ARN=value))
    _assert_explains(message, "JWT_SECRET_ARN", "staging")


@pytest.mark.regression
@pytest.mark.parametrize("env_name", ENVIRONMENTS)
@pytest.mark.parametrize("variable", sorted(SECRET_ARN_INPUTS))
def test_a_missing_input_is_refused_in_every_environment(variable, env_name):
    """No environment falls back to the name: dev and demo build the same tasks."""
    for missing in (None, "", "   "):
        values = _all_inputs(env_name)
        if missing is None:
            del values[variable]
        else:
            values[variable] = missing
        message = _refusal(values, env_name)
        assert f"{variable} is not set" in message, message
        _assert_explains(message, variable, env_name)


@pytest.mark.regression
@pytest.mark.parametrize(
    "case",
    [
        "partial",
        "wrong-env",
        "wrong-region",
        "wrong-account",
        "wrong-slot",
        "malformed",
    ],
)
def test_a_refusal_contains_none_of_the_supplied_digits(case):
    """An ARN carries the account ID; a synth log must not repeat it.

    Every supplied value carries a twelve-digit account and most a suffix with
    digits in it; the refusal must contain no digit at all, so neither the
    account, the region nor the suffix can reach a synth log.
    """
    account = FAKE_ACCOUNT
    suffix = "a0b5c9"
    good = f"arn:aws:secretsmanager:us-west-2:{account}:secret:/staging/experimentation"
    values = {
        "partial": f"{good}/jwt-secret",
        "wrong-env": good.replace("/staging/", "/prod/") + f"/jwt-secret-{suffix}",
        "wrong-region": good.replace("us-west-2", "ap-southeast-3")
        + f"/jwt-secret-{suffix}",
        "wrong-account": good.replace(account, "000000000000")
        + f"/jwt-secret-{suffix}",
        "wrong-slot": f"{good}/first-superuser-password-{suffix}",
        "malformed": f"{good}/jwt-secret-{suffix}:7:8",
    }
    value = values[case]
    assert re.search(r"[0-9]{12}", value), value
    message = _refusal(_all_inputs("staging", JWT_SECRET_ARN=value))
    assert value not in message
    carried = sorted(set(re.findall(r"[0-9]", message)))
    assert not carried, f"the refusal carries the digits {carried}: {message}"


def test_the_core_profile_does_not_need_the_audit_key_but_checks_one_given():
    values = _all_inputs("staging")
    del values["AUDIT_HMAC_KEY_SECRET_ARN"]
    assert _resolve(values, include_modules=False) == values
    bad = _all_inputs("staging", AUDIT_HMAC_KEY_SECRET_ARN="audit-hmac-key")
    message = _refusal(bad, include_modules=False)
    _assert_explains(message, "AUDIT_HMAC_KEY_SECRET_ARN", "staging")


# --- the app refuses without them ----------------------------------------------


def _run_app(environment: str, **overrides):
    synth = cdk.App.synth
    cdk.App.synth = lambda self, **kwargs: None  # type: ignore[method-assign]
    try:
        with _app_environment(CDK_DIR, ENVIRONMENT=environment, **overrides):
            return runpy.run_path(str(CDK_DIR / "app.py"), run_name="__main__")
    finally:
        cdk.App.synth = synth  # type: ignore[method-assign]


@pytest.mark.regression
@pytest.mark.parametrize("environment", ENVIRONMENTS)
@pytest.mark.parametrize(
    "variable", ["JWT_SECRET_ARN", "FIRST_SUPERUSER_PASSWORD_SECRET_ARN"]
)
def test_the_app_refuses_to_synthesise_without_an_input(environment, variable):
    with pytest.raises(ValueError) as excinfo:
        _run_app(environment, **{variable: None})
    assert f"{variable} is not set (ENVIRONMENT={environment})" in str(excinfo.value)


@pytest.mark.regression
@pytest.mark.skipif(not modules_present(), reason="core checkout: no full profile")
def test_the_full_profile_refuses_to_synthesise_without_the_audit_key():
    with pytest.raises(ValueError) as excinfo:
        _run_app("staging", AUDIT_HMAC_KEY_SECRET_ARN=None)
    assert "AUDIT_HMAC_KEY_SECRET_ARN is not set" in str(excinfo.value)


def test_the_core_profile_synthesises_without_the_audit_key():
    namespace = _run_app(
        "staging", EXPERIMENTLY_PROFILE="core", AUDIT_HMAC_KEY_SECRET_ARN=None
    )
    assert not namespace["ENABLE_MODULE_STACKS"]


# --- the synthesised templates ---------------------------------------------------

PROFILES = ("full", "core") if modules_present() else ("core",)


@cache
def _assembly(environment: str, profile: str):
    with _app_environment(
        CDK_DIR, ENVIRONMENT=environment, EXPERIMENTLY_PROFILE=profile
    ):
        namespace = runpy.run_path(str(CDK_DIR / "app.py"), run_name="__main__")
        return namespace["app"].synth()


def _templates(environment: str, profile: str) -> dict[str, dict]:
    return {s.stack_name: s.template for s in _assembly(environment, profile).stacks}


def _task_definitions(templates: dict) -> list[tuple[str, str, dict]]:
    return [
        (stack, lid, r)
        for stack, template in templates.items()
        for lid, r in template.get("Resources", {}).items()
        if r["Type"] == "AWS::ECS::TaskDefinition"
    ]


def _secrets(task_definition: dict) -> dict[str, object]:
    return {
        s["Name"]: s["ValueFrom"]
        for c in task_definition["Properties"]["ContainerDefinitions"]
        for s in c.get("Secrets", [])
    }


CASES = [
    pytest.param(env, profile, id=f"{env}-{profile}")
    for env in ENVIRONMENTS
    for profile in PROFILES
]


@pytest.mark.regression
@pytest.mark.parametrize("environment, profile", CASES)
def test_every_hand_made_secret_is_a_literal_complete_arn(environment, profile):
    templates = _templates(environment, profile)
    checked = 0
    for stack, lid, td in _task_definitions(templates):
        for name, value_from in _secrets(td).items():
            where = f"{stack}/{lid} {name}"
            if name in DATABASE_FIELDS:
                # The only intrinsic allowed: a field of the database stack's
                # generated secret, exactly "<imported ARN>:<field>::".
                assert value_from == {
                    "Fn::Join": [
                        "",
                        [value_from["Fn::Join"][1][0], DATABASE_FIELDS[name]],
                    ]
                }, where
                assert set(value_from["Fn::Join"][1][0]) == {"Fn::ImportValue"}, where
                continue
            assert isinstance(value_from, str), (
                f"{where}: valueFrom is an intrinsic, not a literal ARN: {value_from}"
            )
            assert COMPLETE_ARN.fullmatch(value_from), (
                f"{where}: {value_from} is not a complete secret ARN"
            )
            variable = SUPPLIED_AS[name]
            assert value_from == fake_secret_arn(variable, environment), where
            checked += 1
    # API + migration, two or three secrets each.
    assert checked == (6 if profile == "full" else 4), checked


def _policies(template: dict) -> dict[str, dict]:
    return {
        lid: r
        for lid, r in template.get("Resources", {}).items()
        if r["Type"]
        in ("AWS::IAM::Policy", "AWS::IAM::ManagedPolicy", "AWS::IAM::Role")
    }


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


@pytest.mark.regression
@pytest.mark.parametrize("environment, profile", CASES)
def test_no_iam_resource_names_a_partial_secret(environment, profile):
    for stack, template in _templates(environment, profile).items():
        for lid, policy in _policies(template).items():
            for text in _strings(policy):
                assert "??????" not in text, f"{stack}/{lid}: {text}"
                if ":secret:" in text:
                    assert COMPLETE_ARN.fullmatch(text), (
                        f"{stack}/{lid}: {text} is a secret ARN without its suffix"
                    )


def _key(value) -> str:
    """One comparable form for a valueFrom and an IAM resource."""
    # "<imported ARN>:<field>::" reads the secret the import names. Only that
    # exact shape is reduced; any other intrinsic is compared whole, so a
    # partial ARN's Fn::Join and its "-??????" grant stay different keys.
    parts = value.get("Fn::Join", [None, []])[1] if isinstance(value, dict) else []
    if (
        len(parts) == 2
        and isinstance(parts[0], dict)
        and set(parts[0]) == {"Fn::ImportValue"}
        and parts[1] in DATABASE_FIELDS.values()
    ):
        value = parts[0]
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _role_id(arn) -> str:
    (attribute,) = arn.values()
    assert attribute[1] == "Arn", arn
    return attribute[0]


@pytest.mark.regression
@pytest.mark.parametrize("environment, profile", CASES)
def test_each_execution_role_reads_exactly_its_task_definitions_secrets(
    environment, profile
):
    seen = 0
    for stack, template in _templates(environment, profile).items():
        resources = template["Resources"]
        for _, lid, td in _task_definitions({stack: template}):
            supplied = {_key(v) for v in _secrets(td).values()}
            role = _role_id(td["Properties"]["ExecutionRoleArn"])
            readable = set()
            for policy in resources.values():
                if policy["Type"] != "AWS::IAM::Policy":
                    continue
                if {"Ref": role} not in policy["Properties"]["Roles"]:
                    continue
                for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
                    actions = statement["Action"]
                    actions = [actions] if isinstance(actions, str) else actions
                    if "secretsmanager:GetSecretValue" not in actions:
                        continue
                    targets = statement["Resource"]
                    targets = targets if isinstance(targets, list) else [targets]
                    readable |= {_key(t) for t in targets}
            assert readable == supplied, (
                f"{stack}/{lid}: the execution role may read "
                f"{sorted(readable - supplied)} it never supplies, and cannot read "
                f"{sorted(supplied - readable)} it does"
            )
            seen += bool(supplied)
    assert seen == 2, f"expected the API and migration task definitions, saw {seen}"
