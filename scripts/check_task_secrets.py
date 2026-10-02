#!/usr/bin/env python3
"""Every secret the task definitions reference exists, by the reference ECS will use (#636).

    EXPECTED_ACCOUNT_ID=<account> python3 scripts/check_task_secrets.py \\
        --secrets-prefix /<env>/experimentation --profile core|full \\
        --region <region> \\
        --app-family <family> [--app-family <family> ...] \\
        [--family <family> ...]

Deploy registers each new revision as a copy of its family's newest ACTIVE
revision (scripts/register_task_definition.sh), so that revision's
`secrets[].valueFrom` is exactly what ECS hands to GetSecretValue when the
task starts. This reads those references and checks them, rather than looking
the secrets up by name: a by-name lookup passes while every task fails, when
the task definitions carry a reference Secrets Manager does not resolve (a
partial ARN, one that stops at the name).

In this order:

1. Read every container's `secrets` in the newest revision of each family.
2. Register an `::add-mask::` for every reference, the account ID in it and
   its six-character suffix, before anything else is printed.
3. Refuse, before any Secrets Manager call, any reference that is not a
   complete Secrets Manager ARN in this region and this account: the name,
   a `-` and six letters or digits, optionally followed by the three ECS
   fields `:<json key>:<version stage>:<version id>`. A reference whose
   resource is exactly one of the secrets below (no suffix) is a partial ARN
   and is refused as one.
4. Require each `--app-family` to reference the profile's secrets:
   `<prefix>/jwt-secret` and `<prefix>/first-superuser-password` always, and
   `<prefix>/audit-hmac-key` on the full profile.
5. `describe-secret` each distinct secret by its complete ARN, and require
   the answer to be that secret.

What is printed (the workflow log is public): family names, environment
variable names, and each secret's NAME. Never a reference, an ARN, an account
ID or a suffix. An AWS error message is printed only after the masks are
registered, and through `public_text.redact` as well.

READ-ONLY: `OPERATIONS` is the whole allow-list; both of its calls read.

Exit status: 0 every reference exists; 1 refused (a reference is not a
complete ARN, a required secret is not referenced, or a secret does not
exist); 2 could not tell (a task definition could not be read). 2 also stops
the deploy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_text import redact

#: Every AWS CLI operation this script may run. Both of them read.
OPERATIONS = frozenset(
    {
        ("ecs", "describe-task-definition"),
        ("secretsmanager", "describe-secret"),
    }
)

OK, REFUSED, UNKNOWN = 0, 1, 2

#: The secrets an operator creates under the prefix, which every app family
#: (the API's and the migration's) must reference. The same names as
#: SECRET_INPUTS in infrastructure/cdk/stacks/secret_arns.py; a test pins it.
APP_SECRETS = ("jwt-secret", "first-superuser-password")
#: Only the full profile's task definitions reference these.
FULL_ONLY_SECRETS = ("audit-hmac-key",)

DOCS = "docs/deployment/secrets-management.md"

#: Longer than any real reference; checked before any pattern runs.
MAX_LENGTH = 2048

# Every quantifier is bounded, and the value is length-checked first.
_STRUCTURE = re.compile(
    r"arn:(?P<partition>aws(?:-[a-z]{1,10}){0,3})"
    r":secretsmanager"
    r":(?P<region>[a-z]{2}(?:-[a-z]{1,15}){1,3}-[0-9]{1,2})"
    r":(?P<account>[0-9]{12})"
    r":secret:(?P<resource>[A-Za-z0-9/_+=.@-]{1,512})"
    r"(?P<fields>(?::[^:\s]{0,256}){3})?"
)
_SUFFIXED = re.compile(
    r"(?P<name>[A-Za-z0-9/_+=.@-]{1,505})-(?P<suffix>[A-Za-z0-9]{6})"
)
_TWELVE_DIGITS = re.compile(r"[0-9]{12}")
_ERROR_CODE = re.compile(r"\(([A-Za-z]{1,64})\)")


class AwsError(Exception):
    """An AWS CLI call failed; the message is its stderr."""


def run_aws(argv: Sequence[str]) -> object:
    if tuple(argv[:2]) not in OPERATIONS:
        raise ValueError(f"not a read-only operation this script may run: {argv[:2]}")
    proc = subprocess.run(
        ["aws", *argv, "--output", "json"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise AwsError(proc.stderr.strip() or f"aws exited {proc.returncode}")
    return json.loads(proc.stdout or "null")


def say(line: str) -> None:
    """One line on stdout, flushed: the masks must reach the runner first."""
    print(line, flush=True)


def _one_line(value: object, limit: int = 600) -> str:
    """Printed inside a workflow command, which is one line."""
    return redact(" ".join(str(value)[:limit].split()))


def _printable(value: str) -> bool:
    return value.isprintable() and "\n" not in value and "\r" not in value


def masks_for(value: str, known: frozenset[str] = frozenset()) -> list[str]:
    """What to hide of one reference: itself, any account ID in it, its suffix.

    No suffix is masked for a partial ARN of a ``known`` name: the "suffix" of
    ``.../jwt-secret`` would be ``secret``, and masking that word would garble
    the rest of the log.

    A value with a control character is not masked whole (an `::add-mask::`
    line ends at the first newline, and the rest would print); it is refused
    without being printed, and its digit runs are still masked.
    """
    found: list[str] = []
    if len(value) >= 8 and len(value) <= MAX_LENGTH and _printable(value):
        found.append(value)
    found.extend(_TWELVE_DIGITS.findall(value[:MAX_LENGTH]))
    match = _STRUCTURE.fullmatch(value) if len(value) <= MAX_LENGTH else None
    if match is not None:
        suffixed = _SUFFIXED.fullmatch(match["resource"])
        if suffixed is not None and match["resource"] not in known:
            found.append(suffixed["suffix"])
        if match["fields"]:
            found.append(value[: len(value) - len(match["fields"])])
    return list(dict.fromkeys(found))


def complete_arn(
    value: str, *, region: str, account: str, known: frozenset[str]
) -> tuple[str, str] | str:
    """``(secret ARN, secret name)`` for a complete reference, else why not.

    ``known`` holds the names a partial ARN would end at. The reason never
    repeats any part of ``value``.
    """
    if len(value) > MAX_LENGTH:
        return "is far too long to be an ARN"
    match = _STRUCTURE.fullmatch(value)
    if match is None:
        return (
            "is not a Secrets Manager secret ARN "
            "(arn:<partition>:secretsmanager:<region>:<account>:secret:<name>-<suffix>)"
        )
    if match["region"] != region:
        return "names a secret in a region other than this deploy's"
    if match["account"] != account:
        return "names a secret in an account other than this environment's"
    resource = match["resource"]
    suffixed = _SUFFIXED.fullmatch(resource)
    if resource in known or suffixed is None:
        return (
            "is a partial ARN: it ends at the secret's name, without the "
            "six-character suffix, and Secrets Manager does not resolve it"
        )
    arn = value[: len(value) - len(match["fields"] or "")]
    return arn, suffixed["name"]


def _secrets_of(task_definition: object) -> list[tuple[str, str, str]]:
    """``(container, variable, valueFrom)`` for every secret of every container."""
    if not isinstance(task_definition, dict):
        raise ValueError("describe-task-definition returned no taskDefinition")
    found = []
    for container in task_definition.get("containerDefinitions") or []:
        if not isinstance(container, dict):
            continue
        for secret in container.get("secrets") or []:
            if not isinstance(secret, dict):
                continue
            found.append(
                (
                    str(container.get("name", "")),
                    str(secret.get("name", "")),
                    str(secret.get("valueFrom", "")),
                )
            )
    return found


def main(
    argv: Sequence[str] | None = None,
    aws: Callable[[Sequence[str]], object] = run_aws,
    environ: dict[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--secrets-prefix", required=True)
    parser.add_argument("--profile", required=True, choices=("core", "full"))
    parser.add_argument("--region", required=True)
    parser.add_argument("--app-family", action="append", required=True, default=[])
    parser.add_argument("--family", action="append", default=[])
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return UNKNOWN
    environ = dict(os.environ) if environ is None else environ
    account = environ.get("EXPECTED_ACCOUNT_ID", "")
    if not re.fullmatch(r"[0-9]{12}", account):
        say(
            "::error title=Not configured::EXPECTED_ACCOUNT_ID is not a 12-digit "
            "account ID, so no secret reference could be checked against it."
        )
        return UNKNOWN
    prefix = args.secrets_prefix.rstrip("/")
    required = [f"{prefix}/{name}" for name in APP_SECRETS]
    if args.profile == "full":
        required += [f"{prefix}/{name}" for name in FULL_ONLY_SECRETS]
    known = frozenset(f"{prefix}/{n}" for n in (*APP_SECRETS, *FULL_ONLY_SECRETS))
    families = list(dict.fromkeys([*args.app_family, *args.family]))

    # 1. Read every reference. Nothing secret has been read yet, so an error
    # here can be printed (redacted) as it is.
    references: dict[str, list[tuple[str, str, str]]] = {}
    for family in families:
        try:
            answer = aws(
                [
                    "ecs",
                    "describe-task-definition",
                    "--task-definition",
                    family,
                    "--query",
                    "taskDefinition",
                ]
            )
            references[family] = _secrets_of(answer)
        except (AwsError, ValueError, json.JSONDecodeError) as exc:
            say(
                f"::error title=Could not read a task definition::{family}: "
                f"{_one_line(exc)}. Nothing has been built or changed."
            )
            return UNKNOWN

    # 2. Mask every reference before anything else is printed.
    for found in references.values():
        for _, _, value in found:
            for mask in masks_for(value, known):
                say(f"::add-mask::{mask}")

    # 3. Refuse anything that is not a complete ARN, before any Secrets
    # Manager call.
    bad: list[str] = []
    secrets: dict[str, str] = {}
    named: dict[str, set[str]] = {family: set() for family in families}
    for family in families:
        for container, variable, value in references[family]:
            outcome = complete_arn(
                value, region=args.region, account=account, known=known
            )
            if isinstance(outcome, str):
                bad.append(f"{family} {container}/{variable} {outcome}")
                continue
            arn, name = outcome
            secrets[arn] = name
            named[family].add(name)
    if bad:
        for line in bad:
            say(f"::error title=Secret reference is not a complete ARN::{line}.")
        say(
            f"::error::{len(bad)} secret reference(s) in the task definitions "
            "would stop every task at start, so nothing was deployed. Run cdk "
            "deploy from a checkout that imports each secret by its complete ARN "
            f"(JWT_SECRET_ARN and the others): {DOCS}."
        )
        return REFUSED

    # 4. The profile's secrets are referenced by every app family.
    missing = [
        f"{family} does not reference {name}"
        for family in args.app_family
        for name in required
        if name not in named[family]
    ]
    if missing:
        for line in missing:
            say(f"::error title=Secret not referenced::{line}.")
        say(
            f"::error::profile={args.profile} needs these secrets in the task "
            "definitions, so nothing was deployed. Redeploy the stacks for this "
            f"profile: {DOCS}."
        )
        return REFUSED

    # 5. Each secret exists, and is the one referenced.
    absent = []
    for arn, name in sorted(secrets.items(), key=lambda item: item[1]):
        try:
            answer = aws(
                [
                    "secretsmanager",
                    "describe-secret",
                    "--secret-id",
                    arn,
                    "--query",
                    "{Name: Name, ARN: ARN}",
                ]
            )
        except (AwsError, ValueError, json.JSONDecodeError) as exc:
            codes = _ERROR_CODE.findall(str(exc)[:600])
            code = codes[0] if codes else "error"
            absent.append(f"{name}: {code}: {_one_line(exc)}")
            continue
        if not (
            isinstance(answer, dict)
            and answer.get("ARN") == arn
            and answer.get("Name") == name
        ):
            absent.append(f"{name}: describe-secret answered for a different secret")
            continue
        say(f"exists: {name}")
    if absent:
        for line in absent:
            say(f"::error title=Secret could not be described::{line}")
        say(
            f"::error::{len(absent)} secret(s) the task definitions reference "
            "could not be found by that reference, so nothing was deployed. "
            f"Create or restore them, then redeploy the stacks: {DOCS}."
        )
        return REFUSED
    say(
        f"profile={args.profile}: all {len(secrets)} secret(s) the task "
        f"definitions of {len(families)} famil{'y' if len(families) == 1 else 'ies'} "
        "reference exist, by the complete ARN each task will use"
    )
    return OK


if __name__ == "__main__":
    sys.exit(main())
