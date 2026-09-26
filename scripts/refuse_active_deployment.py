#!/usr/bin/env python3
"""Refuse a forward deploy while an earlier CodeDeploy deployment is still active (PE v2 C7).

    python3 scripts/refuse_active_deployment.py <application> <deployment group>

A forward deploy's job ends once the API serves the new revision. The
deployment itself stays active for another hour after that, because the
deployment group keeps the old task set that long before terminating it. That
hour is when Rollback can still act. CodeDeploy refuses a second deployment to
a group while one is active, so a deploy dispatched inside that hour would
fail at `create-deployment`, after it had already built, snapshotted and
migrated. rollback.yml's "stop any in-flight deployment" would be worse:
stopping a deployment that has shifted traffic, with auto-rollback, rolls
back the release that just succeeded.

So the deploy asks first, before it changes anything, and refuses with the
deployment's id and roughly how long it may stay active. It never stops the
deployment. Rollback is the workflow that stops one.

READ-ONLY: `OPERATIONS` is the whole allow-list, and it holds only
`list-deployments` and `get-deployment`.

Exit status: 0 nothing active; 1 refused (a deployment is active); 2 could
not tell (an AWS call failed). 2 also stops the deploy: "I could not check"
is not "nothing is there".
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

#: Every AWS CLI operation this script may run. Both of them read.
OPERATIONS = frozenset(
    {
        ("deploy", "list-deployments"),
        ("deploy", "get-deployment"),
    }
)

#: Every non-final status in botocore's DeploymentStatus enum. `Baking` is
#: here because nobody has observed whether a deployment reports `InProgress`
#: or `Baking` during the termination wait (PE v2 finding 6). rollback.yml's
#: filter leaves it out.
ACTIVE = ("Created", "Queued", "InProgress", "Baking", "Ready")

#: The deployment group's own waits (fargate_service_stack.py), used when a
#: deployment does not report them.
DEFAULT_READY_WAIT_MINUTES = 30
DEFAULT_TERMINATION_WAIT_MINUTES = 60
#: Starting the replacement tasks, plus the canary's five minutes. This is an
#: allowance for the estimate. It is not a measurement.
SHIFT_ALLOWANCE_MINUTES = 15

OK, REFUSED, UNKNOWN = 0, 1, 2


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


def _when(value: object) -> float | None:
    """CLI v2 prints ISO 8601; `cli_timestamp_format = wire` prints epoch seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return float(value)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None


def describe(info: dict, now: float) -> str:
    """One sentence: which deployment, what it is doing, and roughly how long it has left."""
    deployment_id = info.get("deploymentId", "?")
    status = info.get("status", "?")
    # A rollback's description carries its operator-typed reason. It is
    # printed inside a workflow command, which is one line, so it is flattened
    # to one line and truncated before anything else is done with it.
    what = " ".join(str(info.get("description") or "no description")[:200].split())
    blue_green = info.get("blueGreenDeploymentConfiguration") or {}
    ready_wait = (blue_green.get("deploymentReadyOption") or {}).get(
        "waitTimeInMinutes"
    ) or DEFAULT_READY_WAIT_MINUTES
    termination_wait = (
        blue_green.get("terminateBlueInstancesOnDeploymentSuccess") or {}
    ).get("terminationWaitTimeInMinutes") or DEFAULT_TERMINATION_WAIT_MINUTES

    if info.get("instanceTerminationWaitTimeStarted"):
        phase = (
            "its traffic has shifted, and CodeDeploy is keeping the previous task "
            f"set for up to {termination_wait} minutes before it terminates it"
        )
    elif status == "Ready":
        phase = (
            "it is waiting for approval, and CodeDeploy stops it when its "
            f"{ready_wait}-minute approval wait ends"
        )
    else:
        phase = "it has not finished shifting traffic"

    created = _when(info.get("createTime"))
    if created is None:
        timing = "Its creation time could not be read, so there is no estimate of when it ends."
    else:
        age = max(0, int((now - created) // 60))
        bound = ready_wait + SHIFT_ALLOWANCE_MINUTES + termination_wait
        left = max(0, bound - age)
        stamp = datetime.fromtimestamp(created, timezone.utc).strftime("%H:%M UTC")
        timing = (
            f"It was created at {stamp}, {age} minutes ago, and may stay active "
            f"for about {left} more minutes. That is an estimate: {ready_wait} "
            f"minutes of approval wait, plus about {SHIFT_ALLOWANCE_MINUTES} "
            f"minutes to shift, plus {termination_wait} minutes before the old "
            "task set is terminated."
        )
    return (
        f"CodeDeploy deployment {deployment_id} ({what}) is {status}: {phase}. {timing}"
    )


def check(
    aws: Callable[[Sequence[str]], dict],
    application: str,
    group: str,
    now: float,
) -> tuple[int, list[str]]:
    listed = aws(
        [
            "deploy",
            "list-deployments",
            "--application-name",
            application,
            "--deployment-group-name",
            group,
            "--include-only-statuses",
            *ACTIVE,
        ]
    ).get("deployments", [])
    sentences = []
    for deployment_id in listed:
        info = aws(["deploy", "get-deployment", "--deployment-id", deployment_id]).get(
            "deploymentInfo", {}
        )
        # Listed as active a moment ago; it may have finished since.
        if info.get("status") in ACTIVE:
            sentences.append(describe(info, now))
    return (REFUSED if sentences else OK), sentences


def main(
    argv: Sequence[str] | None = None,
    aws: Callable[[Sequence[str]], dict] = run_aws,
    now: Callable[[], float] = time.time,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(
            "usage: refuse_active_deployment.py <application> <deployment group>",
            file=sys.stderr,
        )
        return UNKNOWN
    application, group = args
    try:
        status, sentences = check(aws, application, group, now())
    except (AwsError, ValueError) as exc:
        print(
            "::error title=Could not check for an active deployment::"
            f"{exc}. Nothing has been built or changed."
        )
        return UNKNOWN
    if status == OK:
        print(f"no deployment is active in {application}/{group}")
        return OK
    for sentence in sentences:
        print(
            "::error title=A deployment is still active::"
            f"{sentence} Nothing has been built or changed. Re-run this deploy "
            "once it is no longer active. If the release it deployed is bad, use "
            "Rollback instead: Rollback stops it. This workflow never stops a "
            "deployment itself, because stopping one whose traffic has shifted "
            "rolls back the release that succeeded."
        )
    return REFUSED


if __name__ == "__main__":
    sys.exit(main())
