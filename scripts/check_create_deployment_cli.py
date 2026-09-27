#!/usr/bin/env python3
"""The runner's AWS CLI accepts the workflows' exact create-deployment flags (#148).

    python3 scripts/check_create_deployment_cli.py            # run the check
    python3 scripts/check_create_deployment_cli.py --print    # show the argv only

rollback.yml always, and deploy.yml under its break-glass input, create the
CodeDeploy deployment with `--override-alarm-configuration enabled=false`. If
the runner's CLI does not know the flag, or parses the value differently, the
first place that would show is a real rollback in the middle of an incident.

This takes the flags each workflow actually passes -- read from the workflow,
not typed here -- gives each a harmless value, and runs

    aws deploy create-deployment <flags> --generate-cli-skeleton output

which validates the parameters against the CLI's model and prints a skeleton
WITHOUT calling the service (EM condition 13). It must exit 0 and print
`deploymentId`. Then the tamper runs in the same place: the same argv with
`enabled=nope` must exit 252 (parameter validation), so an exit 0 above is not
the probe passing vacuously.

It refuses to run with any AWS credential in its environment, and blanks the
credential chain for the processes it starts, so no form of this can reach
AWS even if `--generate-cli-skeleton` were dropped.

Exit status: 0 both forms pass and the tamper fails as expected; 1 otherwise.
Standard library and PyYAML only.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: A harmless value for every flag the workflows pass to create-deployment. A
#: flag not listed here fails the check: give it a value deliberately.
VALUES = {
    "--application-name": "experimentation-platform-staging",
    "--deployment-group-name": "experimentation-staging",
    "--deployment-config-name": "CodeDeployDefault.ECSAllAtOnce",
    "--description": "cli skeleton check",
    "--override-alarm-configuration": "enabled=false",
    "--revision": (
        '{"revisionType": "AppSpecContent", "appSpecContent": {"content": "{}"}}'
    ),
    "--query": "deploymentId",
    "--output": "text",
}

_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z-]*)")
_CALL = "aws deploy create-deployment"


def _steps(path: Path) -> list[dict]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [s for job in document["jobs"].values() for s in job.get("steps", [])]


def _joined(script: str) -> str:
    code = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    return re.sub(r"\\[ \t]*\r?\n[ \t]*", " ", code)


def flags(path: Path) -> list[str]:
    """The flags `path`'s one create-deployment call passes, in order.

    The call's own line, after line continuations are joined, plus the flags
    of any bash array it expands (`${name[@]...}`), which is how deploy.yml
    adds the override under its input.
    """
    steps = [s for s in _steps(path) if _CALL in _joined(s.get("run", ""))]
    if len(steps) != 1:
        raise SystemExit(f"{path.name}: {len(steps)} steps call {_CALL}; expected 1")
    code = _joined(steps[0]["run"])
    (line,) = [ln for ln in code.splitlines() if _CALL in ln]
    call = line[line.index(_CALL) + len(_CALL) :]
    # A value built by a command substitution (`--revision "$(jq -cn --arg
    # ...)"`) is that value, not flags of this call: drop the substitutions,
    # innermost first.
    while True:
        stripped = re.sub(r"\$\([^()]*\)", "", call)
        if stripped == call:
            break
        call = stripped
    found = _FLAG.findall(call)
    for array in dict.fromkeys(re.findall(r"\$\{(\w+)\[@\]", call)):
        for body in re.findall(rf"^\s*{array}=\((.*)\)\s*$", code, re.M):
            found += _FLAG.findall(body)
    return found


def argv(found: list[str], override_value: str = "enabled=false") -> list[str]:
    unknown = [f for f in found if f not in VALUES]
    if unknown:
        raise SystemExit(f"no value for {unknown}: add one to VALUES deliberately")
    out = ["aws", "deploy", "create-deployment", "--region", "us-west-2"]
    for flag in found:
        value = VALUES[flag]
        if flag == "--override-alarm-configuration":
            value = override_value
        out += [flag, value]
    return out + ["--generate-cli-skeleton", "output"]


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
        found = flags(WORKFLOWS / name)
        if "--override-alarm-configuration" not in found:
            print(f"::error::{name}'s create-deployment passes no alarm override")
            return 1
        cases.append((name, found))
    if "--print" in args:
        for name, found in cases:
            print(name, " ".join(argv(found)))
        return 0
    if held:
        print(
            f"::error::refusing to run with AWS credentials in the environment: {held}"
        )
        return 1
    failed = False
    for name, found in cases:
        good = subprocess.run(argv(found), capture_output=True, text=True, env=_env())
        ok = good.returncode == 0 and "deploymentId" in good.stdout
        print(
            f"{name}: {len(found)} flags ({' '.join(found)}): exit {good.returncode}, "
            f"stdout {good.stdout.strip()!r}"
        )
        if not ok:
            print(f"::error::{name}: the CLI refused the flags: {good.stderr.strip()}")
            failed = True
        bad = subprocess.run(
            argv(found, "enabled=nope"), capture_output=True, text=True, env=_env()
        )
        print(f"{name} with enabled=nope: exit {bad.returncode}")
        if bad.returncode != 252:
            print(
                f"::error::{name}: enabled=nope exited {bad.returncode}, not 252: "
                "the check above cannot tell a valid flag from an invalid one"
            )
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
