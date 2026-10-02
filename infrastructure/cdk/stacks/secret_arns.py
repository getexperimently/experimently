"""The three Secrets Manager secrets the task definitions read, by complete ARN.

The API and migration task definitions supply ``SECRET_KEY``,
``FIRST_SUPERUSER_PASSWORD`` and, on the full profile, ``AUDIT_HMAC_KEY`` from
secrets an operator creates by hand under ``/<env>/experimentation/<name>``.

They were imported by name, which renders a
*partial* ARN (one that stops at the name) into the task definition's
``valueFrom``. ECS hands ``valueFrom`` to ``GetSecretValue`` unchanged, and
Secrets Manager does not resolve that partial ARN for these secrets, so every
task would have stopped at start. The ECS API documents ``valueFrom`` as the
*full* ARN of the secret, and a full ARN ends in a six-character suffix that
Secrets Manager chooses when the secret is created. Nothing can derive the
suffix at synth, so the operator supplies each complete ARN as a synth input:

* ``JWT_SECRET_ARN``: ``/<env>/experimentation/jwt-secret``, always;
* ``FIRST_SUPERUSER_PASSWORD_SECRET_ARN``:
  ``/<env>/experimentation/first-superuser-password``, always;
* ``AUDIT_HMAC_KEY_SECRET_ARN``: ``/<env>/experimentation/audit-hmac-key``,
  the full profile only.

Required in **every** environment (dev, staging, prod, demo): every one of them
builds both task definitions, and there is no fallback to the name form. A
value is accepted only when it is, in full,
``arn:<partition>:secretsmanager:<stack region>:<stack account>:secret:/<env>/experimentation/<name>-<6 letters or digits>``.
On the core profile ``AUDIT_HMAC_KEY_SECRET_ARN`` is not required, but a value
that is set is checked all the same.

A refusal names the variable and the read-only command that prints the right
value. It never repeats the value it was given, nor the stack's account or
region: an ARN carries the account ID, and a synth log is not a place for one.
That is also why the refusal contains no digits at all, which the tests assert.

Recreating a secret gives it a new suffix, so a new ARN: update the input and
run ``cdk deploy`` again, or the next task start fails with ResourceNotFound.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

#: Input variable -> the name part of the secret it must point at.
SECRET_INPUTS: dict[str, str] = {
    "JWT_SECRET_ARN": "jwt-secret",
    "FIRST_SUPERUSER_PASSWORD_SECRET_ARN": "first-superuser-password",
    "AUDIT_HMAC_KEY_SECRET_ARN": "audit-hmac-key",
}

#: Inputs only the full profile's task definitions need.
MODULE_ONLY_INPUTS = frozenset({"AUDIT_HMAC_KEY_SECRET_ARN"})

#: Every ENVIRONMENT value app.py accepts (it checks this list too).
ENVIRONMENTS = ("dev", "staging", "prod", "demo")

#: Longer than any real ARN; checked before any pattern runs.
MAX_LENGTH = 2048

# Every quantifier is bounded, and the value is length-checked first.
_ARN = re.compile(
    r"arn:(?P<partition>aws(?:-[a-z]{1,10}){0,3})"
    r":secretsmanager"
    r":(?P<region>[a-z]{2}(?:-[a-z]{1,15}){1,3}-[0-9]{1,2})"
    r":(?P<account>[0-9]{12})"
    r":secret:(?P<resource>[A-Za-z0-9/_+=.@-]{1,600})"
)
_SUFFIX = re.compile(r"-[A-Za-z0-9]{6}")


def secret_name(env_name: str, name: str) -> str:
    """``/<env>/experimentation/<name>``: the secret's name in Secrets Manager."""
    return f"/{env_name}/experimentation/{name}"


def how_to_read(variable: str, env_name: str) -> str:
    """The read-only command that prints the value ``variable`` must hold."""
    name = secret_name(env_name, SECRET_INPUTS[variable])
    return (
        f"export {variable}=$(aws secretsmanager describe-secret "
        f"--secret-id {name} --query ARN --output text)"
    )


def _refuse(variable: str, env_name: str, why: str) -> ValueError:
    name = secret_name(env_name, SECRET_INPUTS[variable])
    return ValueError(
        f"{variable} {why} (ENVIRONMENT={env_name}). It must be the complete ARN "
        f"of the existing secret {name}, in the account and region this app "
        "deploys to, including the six-character suffix Secrets Manager adds "
        f"after the name. Read it, read-only, with: {how_to_read(variable, env_name)} "
        "(add --region if your CLI's default region is not the stack's). "
        "Recreating a secret changes its ARN: update the input and run cdk "
        "deploy again. See docs/deployment/secrets-management.md."
    )


def _names(resource: str, name: str) -> bool:
    """Whether ``resource`` is exactly ``name`` plus a six-character suffix."""
    return resource.startswith(name) and bool(_SUFFIX.fullmatch(resource[len(name) :]))


def _what_it_names(resource: str) -> tuple[str, str] | None:
    """``(env, input variable)`` of a known secret ``resource`` names, if any."""
    for env in ENVIRONMENTS:
        for variable, name in SECRET_INPUTS.items():
            full = secret_name(env, name)
            if resource == full or _names(resource, full):
                return env, variable
    return None


def check_secret_arn(
    variable: str, value: str, *, env_name: str, account: str, region: str
) -> str:
    """``value`` if it is the complete ARN ``variable`` must hold, else ValueError."""
    if len(value) > MAX_LENGTH:
        raise _refuse(variable, env_name, "is far too long to be an ARN")
    match = _ARN.fullmatch(value)
    if match is None:
        raise _refuse(
            variable,
            env_name,
            "is not a Secrets Manager secret ARN "
            "(arn:<partition>:secretsmanager:<region>:<account>:secret:<name>-<suffix>)",
        )
    if match["region"] != region:
        raise _refuse(
            variable, env_name, "names a secret in a region other than the stack's"
        )
    if match["account"] != account:
        raise _refuse(
            variable, env_name, "names a secret in an account other than the stack's"
        )
    resource = match["resource"]
    expected = secret_name(env_name, SECRET_INPUTS[variable])
    if _names(resource, expected):
        return value
    if resource == expected:
        raise _refuse(
            variable,
            env_name,
            "is a partial ARN: it ends at the secret's name, without the "
            "six-character suffix, and Secrets Manager does not resolve it",
        )
    named = _what_it_names(resource)
    if named is not None and named[0] != env_name:
        raise _refuse(
            variable,
            env_name,
            f"names a secret of the {named[0]} environment, not {env_name}",
        )
    if named is not None and named[1] != variable:
        raise _refuse(
            variable,
            env_name,
            f"names the secret that belongs in {named[1]}, not this one",
        )
    raise _refuse(variable, env_name, f"does not name the secret {expected}")


def resolve_secret_arns(
    environ: Mapping[str, str],
    *,
    env_name: str,
    account: str,
    region: str,
    include_modules: bool,
) -> dict[str, str]:
    """``{input variable: complete ARN}`` for the stacks, or ValueError.

    Every input the profile needs must be set; one that is set but not needed
    (``AUDIT_HMAC_KEY_SECRET_ARN`` on the core profile) is checked anyway and
    returned, and the stacks ignore it.
    """
    resolved: dict[str, str] = {}
    for variable in SECRET_INPUTS:
        value = (environ.get(variable) or "").strip()
        required = include_modules or variable not in MODULE_ONLY_INPUTS
        if not value:
            if required:
                raise _refuse(variable, env_name, "is not set")
            continue
        resolved[variable] = check_secret_arn(
            variable, value, env_name=env_name, account=account, region=region
        )
    return resolved


def require_secret_arns(
    stack: str, secret_arns: Mapping[str, str] | None, include_modules: bool
) -> Mapping[str, str]:
    """The stack-side check: every input the profile needs was passed in.

    ``app.py`` validates the values with :func:`resolve_secret_arns`; this only
    stops a stack being built with none, so there is no path back to a name.
    """
    needed = [
        variable
        for variable in SECRET_INPUTS
        if include_modules or variable not in MODULE_ONLY_INPUTS
    ]
    missing = [v for v in needed if not (secret_arns or {}).get(v)]
    if missing:
        raise ValueError(
            f"{stack} requires secret_arns with {', '.join(missing)}: the "
            "complete ARNs of the secrets its task definition supplies, from "
            "stacks/secret_arns.resolve_secret_arns (app.py passes them)."
        )
    return secret_arns  # type: ignore[return-value]
