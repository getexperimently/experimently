#!/usr/bin/env python3
"""The runner's AWS CLI accepts the workflows' exact create-deployment flags (#148).

    python3 scripts/check_create_deployment_cli.py            # run the check
    python3 scripts/check_create_deployment_cli.py --print    # show the argv only

rollback.yml always, and deploy.yml under its break-glass input, create the
CodeDeploy deployment with the group's alarms overridden
(`--override-alarm-configuration` with a single-quoted JSON value). If the
runner's CLI does not know the flag, or refuses the value, the first place that
would show is a real rollback in the middle of an incident.

This takes the flags each workflow actually passes -- read from the workflow,
not typed here -- and the override's VALUE as the workflow writes it. Until
#777 this script substituted its own `enabled=false` for the value, so it
passed whatever the workflow sent. The value is found by `override_text()`: an
anchored match on the single-quoted token right after the flag, on the joined
create-deployment call and on the body of any bash array the call expands
(deploy.yml's `override=(...)`); `override_value()` then `json.loads` it. No
match, or a value that is not a JSON object, is an error. The tests use the same
two functions.

Every other flag gets a harmless value, and it runs

    aws deploy create-deployment <flags> --generate-cli-skeleton output

which validates the parameters against the CLI's model and prints a skeleton
WITHOUT calling the service (EM condition 13). It must exit 0 and print
`deploymentId`. Then the tamper runs in the same place: the same argv with the
override's `enabled` set to the string "nope" must exit 252 (parameter
validation), so an exit 0 above is not the probe passing vacuously.

What this does NOT show. Measured with aws-cli 2.28.24, the skeleton exits 0
for the shorthand `enabled=false`, for `{"enabled":false}` and for the JSON
with an `alarms` list alike, so it cannot tell a value CodeDeploy refuses from
one it accepts. The refusal of anything that is not a JSON object is this
script's own; CodeDeploy's documented rules for the value are encoded in the
fake aws's CreateDeployment contract
(backend/tests/unit/infrastructure/test_dashboard_deploy_wiring.py).

It refuses to run with any AWS credential in its environment, and blanks the
credential chain for the processes it starts, so no form of this can reach
AWS even if `--generate-cli-skeleton` were dropped.

Exit status: 0 both forms pass and the tamper fails as expected; 1 otherwise.
Standard library and PyYAML only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

OVERRIDE = "--override-alarm-configuration"

#: A harmless value for every flag the workflows pass to create-deployment,
#: except the alarm override, whose value is the workflow's own. A flag not
#: listed here fails the check: give it a value deliberately.
VALUES = {
    "--application-name": "experimentation-platform-staging",
    "--deployment-group-name": "experimentation-staging",
    "--deployment-config-name": "CodeDeployDefault.ECSAllAtOnce",
    "--description": "cli skeleton check",
    "--revision": (
        '{"revisionType": "AppSpecContent", "appSpecContent": {"content": "{}"}}'
    ),
    "--query": "deploymentId",
    "--output": "text",
}

_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z-]*)")
_CALL = "aws deploy create-deployment"
_OVERRIDE_FLAG = re.compile(r"(?<![\w-])--override-alarm-configuration(?![\w-])")
#: The override's value: the single-quoted token right after the flag. Bash
#: passes the text between single quotes through unchanged.
_OVERRIDE_VALUE = re.compile(r"(?<![\w-])--override-alarm-configuration '([^']*)'")


def _steps(path: Path) -> list[dict]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [s for job in document["jobs"].values() for s in job.get("steps", [])]


def _joined(script: str) -> str:
    code = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    return re.sub(r"\\[ \t]*\r?\n[ \t]*", " ", code)


def _call(path: Path) -> tuple[str, list[str]]:
    """`path`'s one create-deployment call, joined, from after `aws deploy
    create-deployment`; and the bodies of the bash arrays it expands
    (`${name[@]...}`), which is how deploy.yml adds the override under its
    input."""
    steps = [s for s in _steps(path) if _CALL in _joined(s.get("run", ""))]
    if len(steps) != 1:
        raise SystemExit(f"{path.name}: {len(steps)} steps call {_CALL}; expected 1")
    code = _joined(steps[0]["run"])
    (line,) = [ln for ln in code.splitlines() if _CALL in ln]
    call = line[line.index(_CALL) + len(_CALL) :]
    bodies = [
        body
        for array in dict.fromkeys(re.findall(r"\$\{(\w+)\[@\]", call))
        for body in re.findall(rf"^\s*{array}=\((.*)\)\s*$", code, re.M)
    ]
    return call, bodies


def flags(path: Path) -> list[str]:
    """The flags `path`'s one create-deployment call passes, in order.

    The call's own line, after line continuations are joined, plus the flags
    of any bash array it expands.
    """
    call, bodies = _call(path)
    # A value built by a command substitution (`--revision "$(jq -cn --arg
    # ...)"`) is that value, not flags of this call: drop the substitutions,
    # innermost first.
    while True:
        stripped = re.sub(r"\$\([^()]*\)", "", call)
        if stripped == call:
            break
        call = stripped
    found = _FLAG.findall(call)
    for body in bodies:
        found += _FLAG.findall(body)
    return found


def override_text(path: Path) -> str:
    """The alarm override's value exactly as `path` passes it: the text
    between the single quotes. ValueError when the flag is absent, appears
    more than once, or is not followed by a single-quoted value."""
    call, bodies = _call(path)
    sites = [call, *bodies]
    count = sum(len(_OVERRIDE_FLAG.findall(site)) for site in sites)
    values = [value for site in sites for value in _OVERRIDE_VALUE.findall(site)]
    if count != 1 or len(values) != 1:
        raise ValueError(
            f"{path.name}: expected one {OVERRIDE} followed by a single-quoted "
            f"JSON value; found the flag {count} time(s) and {len(values)} "
            "single-quoted value(s)"
        )
    return values[0]


def override_value(path: Path) -> dict:
    """The alarm override's value in `path`, parsed. ValueError when it is
    missing, not single-quoted, not JSON, or not a JSON object. (#777: the
    shorthand `enabled=false` sends no `alarms` list, and CodeDeploy refuses
    that.)"""
    text = override_text(path)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{path.name}: {OVERRIDE} {text!r} is not JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: {OVERRIDE} {text!r} is not a JSON object")
    return value


def argv(found: list[str], override: str) -> list[str]:
    """The skeleton argv: every flag in `found` with its VALUES entry, and the
    alarm override with `override`, the workflow's own text."""
    unknown = [f for f in found if f not in VALUES and f != OVERRIDE]
    if unknown:
        raise SystemExit(f"no value for {unknown}: add one to VALUES deliberately")
    out = ["aws", "deploy", "create-deployment", "--region", "us-west-2"]
    for flag in found:
        out += [flag, override if flag == OVERRIDE else VALUES[flag]]
    return out + ["--generate-cli-skeleton", "output"]


def tampered(value: dict) -> str:
    """The workflow's value with `enabled` made a string, which the CLI must
    refuse with 252."""
    return json.dumps({**value, "enabled": "nope"}, separators=(",", ":"))


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(
        AWS_CONFIG_FILE=os.devnull,
        AWS_SHARED_CREDENTIALS_FILE=os.devnull,
        AWS_EC2_METADATA_DISABLED="true",
    )
    return env


def main(args: list[str]) -> int:
    held = sorted(
        k
        for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
        if os.environ.get(k)
    )
    cases = []
    for name in ("rollback.yml", "deploy.yml"):
        path = WORKFLOWS / name
        found = flags(path)
        if OVERRIDE not in found:
            print(f"::error::{name}'s create-deployment passes no alarm override")
            return 1
        try:
            value = override_value(path)
        except ValueError as error:
            print(f"::error::{error}")
            return 1
        cases.append((name, found, override_text(path), value))
    if "--print" in args:
        for name, found, text, _ in cases:
            print(name, " ".join(argv(found, text)))
        return 0
    if held:
        print(
            f"::error::refusing to run with AWS credentials in the environment: {held}"
        )
        return 1
    failed = False
    for name, found, text, value in cases:
        good = subprocess.run(
            argv(found, text), capture_output=True, text=True, env=_env()
        )
        ok = good.returncode == 0 and "deploymentId" in good.stdout
        print(
            f"{name}: {len(found)} flags ({' '.join(found)}), override {text}: "
            f"exit {good.returncode}, stdout {good.stdout.strip()!r}"
        )
        if not ok:
            print(f"::error::{name}: the CLI refused the flags: {good.stderr.strip()}")
            failed = True
        bad_value = tampered(value)
        bad = subprocess.run(
            argv(found, bad_value), capture_output=True, text=True, env=_env()
        )
        print(f"{name} with override {bad_value}: exit {bad.returncode}")
        if bad.returncode != 252:
            print(
                f'::error::{name}: enabled "nope" exited {bad.returncode}, not 252: '
                "the check above cannot tell a valid value from an invalid one"
            )
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
