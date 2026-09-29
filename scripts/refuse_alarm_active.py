#!/usr/bin/env python3
"""Refuse a forward deploy while one of the API's 5xx alarms is in ALARM (#148 PR-3, #297).

    python3 scripts/refuse_alarm_active.py \\
        --application <application> --group <deployment group> \\
        --environment <env> --stage before-build|before-migration \\
        --expect <alarm name> [--expect <alarm name> ...] [--alarms-overridden]

CodeDeploy stops every deployment to the API's group while one of the
group's alarms is in ALARM. Deploy creates its deployment after the snapshot
and the migration, so without this check a deploy started while an alarm is
already firing migrates the database and is then stopped: "Migrated, not
deployed". This asks first, read-only, and refuses naming the alarm.

What it reads (PE condition 11): the alarm names from the deployment group
itself (`get-deployment-group`), because those are what CodeDeploy will poll,
then their states (`describe-alarms`). `--expect` names the alarms the CDK
stack defines (`stacks/names.py`, rendered into deploy.yml's job env and
pinned to a synth by the CDK suite); a group that does not watch every one of
them is refused, so a drifted group cannot make this check pass by watching
less.

Refused (exit 1), whatever `--alarms-overridden` says (EM condition 4(h)):
the group has no alarm configuration, has it disabled, lists no alarm, does
not list an expected alarm, or lists one CloudWatch does not have. Refused
too, unless `--alarms-overridden`: any alarm in ALARM. With
`--alarms-overridden` (Deploy's break-glass) an alarm in ALARM is printed as a
warning and the deploy goes on, unwatched. OK and INSUFFICIENT_DATA pass: only
ALARM refuses (#148 SPEC S4). Every alarm's state is printed in every case.

This check is advisory, not a guarantee (PE condition 11): an alarm that goes
into ALARM after it has passed still stops the deployment, after the
migration, and the run ends in the "Migrated, not deployed" warning. Deploy
runs it twice for that reason: before anything is built, and again
immediately before the snapshot and migration.

READ-ONLY: `OPERATIONS` is the whole allow-list; both of its calls read.

Exit status: 0 go on; 1 refused; 2 could not tell (an AWS call failed, an
answer could not be read, or an alarm is in a state this script does not
know). 2 also stops the deploy: "I could not check" is not "nothing fires".
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_text import redact

#: Every AWS CLI operation this script may run. Both of them read.
OPERATIONS = frozenset(
    {
        ("deploy", "get-deployment-group"),
        ("cloudwatch", "describe-alarms"),
    }
)

OK, REFUSED, UNKNOWN = 0, 1, 2

FIRING = "ALARM"
#: States that let a deploy go on. CodeDeploy stops a deployment on ALARM.
PASSING = ("OK", "INSUFFICIENT_DATA")
#: DescribeAlarms takes at most 100 names in one call.
MAX_NAMES = 100

RUNBOOK = "docs/deployment/rollback-runbook.md#fix-forward-while-an-alarm-is-firing"

#: What has already happened when each check runs.
STAGES = {
    "before-build": "Nothing has been built or changed.",
    "before-migration": (
        "The images were built and pushed; nothing has been snapshotted, "
        "migrated or deployed."
    ),
}


class AwsError(Exception):
    """An AWS CLI call failed; the message is its stderr."""


def run_aws(argv: Sequence[str]) -> dict:
    if tuple(argv[:2]) not in OPERATIONS:
        raise ValueError(f"not a read-only operation this script may run: {argv[:2]}")
    proc = subprocess.run(
        ["aws", *argv, "--output", "json"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise AwsError(proc.stderr.strip() or f"aws exited {proc.returncode}")
    return json.loads(proc.stdout or "{}")


def _one_line(value: object, limit: int = 200) -> str:
    """Printed inside a workflow command, which is one line."""
    return redact(" ".join(str(value)[:limit].split()))


def configured_alarms(
    aws: Callable[[Sequence[str]], dict], application: str, group: str
) -> tuple[list[str], str | None]:
    """The alarm names the group polls, or the reason it polls none."""
    info = aws(
        [
            "deploy",
            "get-deployment-group",
            "--application-name",
            application,
            "--deployment-group-name",
            group,
        ]
    ).get("deploymentGroupInfo")
    if not isinstance(info, dict):
        raise ValueError("get-deployment-group returned no deploymentGroupInfo")
    config = info.get("alarmConfiguration")
    if not isinstance(config, dict):
        return [], "has no alarm configuration"
    if config.get("enabled") is not True:
        return [], "has its alarm configuration disabled"
    names = sorted(
        {
            str(alarm.get("name"))
            for alarm in config.get("alarms") or []
            if isinstance(alarm, dict) and alarm.get("name")
        }
    )
    if not names:
        return [], "has its alarm configuration enabled with no alarm in it"
    return names, None


def alarm_states(
    aws: Callable[[Sequence[str]], dict], names: Sequence[str]
) -> dict[str, dict]:
    """AlarmName -> the alarm, for each of `names` CloudWatch has."""
    if len(names) > MAX_NAMES:
        raise ValueError(f"{len(names)} alarms; DescribeAlarms reads {MAX_NAMES}")
    # The CLI pages describe-alarms itself (no --max-items, --page-size or
    # --no-paginate is passed) and prints the pages merged. Without
    # --alarm-types, DescribeAlarms returns metric alarms only, so a
    # composite alarm in the group would read as missing.
    answer = aws(
        [
            "cloudwatch",
            "describe-alarms",
            "--alarm-names",
            *names,
            "--alarm-types",
            "MetricAlarm",
            "CompositeAlarm",
        ]
    )
    found = {}
    for key in ("MetricAlarms", "CompositeAlarms"):
        for alarm in answer.get(key) or []:
            if isinstance(alarm, dict) and alarm.get("AlarmName") in names:
                found[alarm["AlarmName"]] = alarm
    return found


def main(
    argv: Sequence[str] | None = None,
    aws: Callable[[Sequence[str]], dict] = run_aws,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--application", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--stage", required=True, choices=sorted(STAGES))
    parser.add_argument("--expect", action="append", required=True, default=[])
    parser.add_argument("--alarms-overridden", action="store_true")
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return UNKNOWN
    expected = [name for name in args.expect if name.strip()]
    if not expected:
        print("::error title=No alarm to check::--expect named no alarm.")
        return UNKNOWN
    done = STAGES[args.stage]
    where = f"{args.application}/{args.group}"

    try:
        names, why_none = configured_alarms(aws, args.application, args.group)
        states = alarm_states(aws, names) if names else {}
    except (AwsError, ValueError, json.JSONDecodeError) as exc:
        print(
            "::error title=Could not read the API's alarms::"
            f"{_one_line(exc)}. {done} This deploy stops here: a check that "
            "could not read the alarms is not a check that found none firing."
        )
        return UNKNOWN

    if why_none is not None:
        print(
            "::error title=The API's alarms are not watching::"
            f"Deployment group {where} {why_none}, so no alarm would watch this "
            "deployment or roll it back. The Fargate stack defines "
            f"{', '.join(expected)}; the group has drifted from it, or the stack "
            f"predates the alarms (#148). Deploy the Fargate stack first. {done}"
        )
        return REFUSED

    status = OK
    missing = [name for name in expected if name not in names]
    if missing:
        print(
            "::error title=The API's alarms are not all watching::"
            f"Deployment group {where} does not watch {', '.join(missing)}, "
            f"which the Fargate stack defines (it watches {', '.join(names)}). "
            f"The group has drifted from the stack. Deploy the Fargate stack first. {done}"
        )
        status = REFUSED

    firing = []
    for name in names:
        alarm = states.get(name)
        if alarm is None:
            print(
                "::error title=An alarm does not exist::"
                f"Deployment group {where} watches {name}, which CloudWatch does "
                "not have. CodeDeploy cannot poll it, and would fail this "
                f"deployment. Deploy the Fargate stack first. {done}"
            )
            status = REFUSED
            continue
        state = str(alarm.get("StateValue"))
        since = _one_line(alarm.get("StateUpdatedTimestamp") or "an unknown time", 40)
        print(f"{name}: {state} since {since}")
        if state == FIRING:
            firing.append((name, since, _one_line(alarm.get("StateReason") or "")))
        elif state not in PASSING:
            print(
                "::error title=An alarm's state could not be read::"
                f"{name} is in state {_one_line(state, 40)!s}, which this check "
                f"does not know. {done}"
            )
            if status == OK:
                status = UNKNOWN

    for name, since, reason in firing:
        if args.alarms_overridden:
            print(
                "::warning title=An alarm is firing, and the alarms are overridden::"
                f"{name} is in ALARM in {args.environment} (since {since}). This "
                "deployment is created with the alarms overridden, so it goes "
                "ahead, and no alarm watches it or rolls it back."
            )
            continue
        print(
            "::error title=An alarm is already firing::"
            f"{name} is in ALARM in {args.environment} (since {since}): {reason} "
            "CodeDeploy stops every deployment to the group while one of its "
            "alarms is in ALARM, so this one would be stopped after the snapshot "
            f"and the migration had run. {done} Find out why before deploying: "
            f"{RUNBOOK}"
        )
        status = REFUSED

    if status == OK and not firing:
        print(f"no alarm of {where} is in ALARM")
    return status


if __name__ == "__main__":
    sys.exit(main())
