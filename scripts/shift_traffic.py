#!/usr/bin/env python3
"""Approve a forward CodeDeploy deployment and wait until the API serves it (#143).

    python3 scripts/shift_traffic.py --deployment-id d-XXXX \\
        --cluster experimentation-<env> --service experimentation-backend-<env> \\
        --task-definition <ARN> --deadline-seconds N --interval-seconds M

This is rollback.yml's polling loop, applied to the forward deploy.

* `Ready` is the deployment group's approval wait: CodeDeploy has started
  the replacement task set and waits up to 30 minutes for ContinueDeployment,
  then stops the deployment. Before approving, every target in the
  replacement task set's target group must be `healthy`, and the count must
  equal the task set's desired count (PE v2 C6(b)). Until they are, it keeps
  polling. Then it sends `continue-deployment --deployment-wait-type
  READY_WAIT`, once. `READY_WAIT` is passed explicitly and never
  `TERMINATION_WAIT` (PE v2 C7).
* `Failed` and `Stopped` end the run red. `Baking` is not terminal.
* SUCCESS is `scripts/api_serving.py`'s verdict, checked after every poll:
  the PRIMARY task set is this revision, and check_live_target_group.py
  confirms that the `/api/*` rule forwards to that task set's target group
  (PE v2 C8). A split rule means the shift is still going, so it retries until
  the deadline. An unsplit rule to the other group ends the run red, and so
  does "could not tell".
* It does not wait for `Succeeded`. After the shift, the deployment group
  keeps the old task set for an hour and the deployment stays active. That
  hour is the window in which Rollback can act (DECISIONS T21).

It NEVER stops a deployment. The only CodeDeploy write it can make is
`continue-deployment`. Two allow-lists cover every AWS call it makes:
`OPERATIONS` below, for its own `run_aws` (the deployment, the replacement
task set, target health), and `check_live_target_group.READ_ONLY_OPERATIONS`,
four describe calls, for the `serving()` path through `api_serving.py`. Each
`run_aws` refuses anything outside its list before a process starts. A deadline passed
before the approval leaves the deployment to CodeDeploy, which stops it when
the approval wait ends; nothing has shifted by then. A deadline passed after
the approval leaves it running. Stopping a deployment whose traffic has
shifted rolls back a release that may be succeeding (#143).

Deadlines and intervals are parameters. The unit tests run with 0.

Exit status: 0 the API is serving the revision; 1 anything else, with the
reason on stdout as a workflow `::error`. An exception it does not expect (a
missing `aws` binary, a malformed rule) is `result=unknown` with its type and
message, not an uncaught traceback with no `result`. When `GITHUB_OUTPUT` is set it
writes `approved=true` as soon as it approves the shift, `result` (serving |
failed | unhealthy | timeout | wrong-route | unknown), and, on success,
`live_target_group`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import api_serving

#: Every AWS CLI operation this script may run. The one write is
#: continue-deployment. A test pins the exact set, so stop-deployment cannot
#: be added without a reviewer seeing it.
OPERATIONS = frozenset(
    {
        ("deploy", "get-deployment"),
        ("deploy", "continue-deployment"),
        ("ecs", "describe-services"),
        ("elbv2", "describe-target-health"),
    }
)

#: Where the wrong-route error sends the operator. One literal, so the docs
#: test that checks every printed anchor exists can see it.
WRONG_ROUTE_DOC = "docs/deployment/deployment-guide.md#the-api-route-and-the-primary-task-set-disagree"

#: The statuses after which this deployment will not shift any further.
TERMINAL_FAILURES = ("Failed", "Stopped")


class AwsError(Exception):
    """An AWS CLI call failed; the message is its stderr."""


def run_aws(argv: Sequence[str]) -> dict:
    """Run one allowed AWS CLI call and return its JSON output."""
    if tuple(argv[:2]) not in OPERATIONS:
        raise ValueError(f"not an operation this script may run: {argv[:2]}")
    proc = subprocess.run(
        ["aws", *argv, "--output", "json"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise AwsError(proc.stderr.strip() or f"aws exited {proc.returncode}")
    return json.loads(proc.stdout or "{}")


def replacement_ready(
    aws: Callable[[Sequence[str]], dict], cluster: str, service: str, arn: str
) -> tuple[bool, str]:
    """Every target in the replacement task set's group is healthy, count == desired."""
    services = aws(
        ["ecs", "describe-services", "--cluster", cluster, "--services", service]
    ).get("services", [])
    task_sets = [
        t
        for s in services
        for t in s.get("taskSets", [])
        if t.get("taskDefinition") == arn
    ]
    if len(task_sets) != 1:
        return False, f"{len(task_sets)} task sets run {arn}; expected one"
    task_set = task_sets[0]
    desired = int(task_set.get("computedDesiredCount") or 0)
    if desired < 1:
        return False, f"the replacement task set's desired count is {desired}"
    groups = {lb["targetGroupArn"] for lb in task_set.get("loadBalancers", [])}
    if len(groups) != 1:
        return False, f"the replacement task set is in {len(groups)} target groups"
    group = groups.pop()
    targets = aws(["elbv2", "describe-target-health", "--target-group-arn", group]).get(
        "TargetHealthDescriptions", []
    )
    states = Counter(t.get("TargetHealth", {}).get("State", "?") for t in targets)
    summary = ", ".join(f"{n} {state}" for state, n in sorted(states.items()))
    if states["healthy"] == len(targets) == desired:
        return True, f"{desired} of {desired} targets healthy in {group}"
    return False, (
        f"{states['healthy']} of {desired} desired targets healthy in {group} "
        f"({summary or 'no targets registered'})"
    )


def _output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def _fail(result: str, title: str, message: str) -> int:
    print(f"::error title={title}::{message}")
    _output(result=result)
    return 1


def shift(
    *,
    deployment_id: str,
    cluster: str,
    service: str,
    arn: str,
    deadline_seconds: float,
    interval_seconds: float,
    aws: Callable[[Sequence[str]], dict] = run_aws,
    serving: Callable[[str, str, str], tuple[int, str, str | None]] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if serving is None:

        def serving(c: str, s: str, a: str) -> tuple[int, str, str | None]:
            return api_serving.verdict(api_serving.live.run_aws, c, s, a)

    deadline = clock() + deadline_seconds
    continued = False
    last_health = ""
    status = "unknown"
    try:
        while True:
            info = aws(
                ["deploy", "get-deployment", "--deployment-id", deployment_id]
            ).get("deploymentInfo", {})
            status = info.get("status", "unknown")

            if status in TERMINAL_FAILURES:
                error = json.dumps(info.get("errorInformation") or {})
                after = (
                    "after this run approved the traffic shift; CodeDeploy's "
                    "auto-rollback puts the previous revision back"
                    if continued
                    else "before any traffic shifted; the previous revision "
                    "keeps serving"
                )
                return _fail(
                    "failed",
                    f"Deployment {status}",
                    f"CodeDeploy deployment {deployment_id} is {status} {after}. "
                    f"{error}",
                )

            if status == "Ready" and not continued:
                healthy, why = replacement_ready(aws, cluster, service, arn)
                if healthy:
                    print(f"deployment is Ready and {why}: approving the traffic shift")
                    aws(
                        [
                            "deploy",
                            "continue-deployment",
                            "--deployment-id",
                            deployment_id,
                            "--deployment-wait-type",
                            "READY_WAIT",
                        ]
                    )
                    continued = True
                    # Written the moment the approval is sent: from here on the
                    # new revision may be serving, whatever happens next.
                    _output(approved="true")
                elif why != last_health:
                    print(f"Ready, not yet approved: {why}")
                    last_health = why

            code, sentence, colour = serving(cluster, service, arn)
            sentence = sentence.rstrip(".")
            if code == api_serving.SERVING:
                print(f"serving: {sentence} (deployment {status})")
                _output(result="serving", live_target_group=str(colour))
                return 0
            if code == api_serving.WRONG:
                return _fail(
                    "wrong-route",
                    "API route is not on the new revision",
                    f"{sentence}. The deployment was not stopped. Roll back with "
                    "the line in this run's summary, and read "
                    f"{WRONG_ROUTE_DOC} before the next cdk deploy.",
                )
            if code == api_serving.UNKNOWN:
                return _fail(
                    "unknown",
                    "Could not tell whether the API is serving",
                    f"{sentence}. Deployment {deployment_id} is {status} and was "
                    "not stopped; check it by hand: python3 scripts/api_serving.py "
                    f"{cluster} {service} {arn}",
                )
            if status == "Succeeded":
                return _fail(
                    "failed",
                    "Deployment succeeded, API not serving it",
                    f"CodeDeploy reports {deployment_id} Succeeded, but {sentence}.",
                )

            if clock() >= deadline:
                if continued:
                    return _fail(
                        "timeout",
                        "Traffic shift not confirmed",
                        f"Deployment {deployment_id} was approved and is {status}; "
                        f"after {deadline_seconds:.0f}s {sentence}. It was NOT "
                        "stopped: stopping it now could roll back a release that "
                        "is succeeding. Watch it (aws deploy get-deployment "
                        f"--deployment-id {deployment_id}); if the release is "
                        "bad, use the rollback line in this run's summary.",
                    )
                reason = last_health or f"the deployment is {status}, not Ready"
                return _fail(
                    "unhealthy" if last_health else "timeout",
                    "Traffic shift not approved",
                    f"Deployment {deployment_id} was not approved within "
                    f"{deadline_seconds:.0f}s: {reason}. Nothing has shifted; the "
                    "previous revision keeps serving. CodeDeploy stops the "
                    "deployment when its 30-minute approval wait ends, and the "
                    "next deploy is refused until then.",
                )
            sleep(interval_seconds)
    except (AwsError, ValueError, KeyError) as exc:
        return _fail(
            "unknown",
            "Could not tell whether the API is serving",
            f"{exc}. Deployment {deployment_id} was last {status}; it was not stopped.",
        )
    except Exception as exc:  # any other crash is "could not tell" too
        return _fail(
            "unknown",
            "Could not tell whether the API is serving",
            f"{type(exc).__name__}: {exc}. Deployment {deployment_id} was last "
            f"{status}; it was not stopped.",
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--task-definition", required=True)
    parser.add_argument("--deadline-seconds", type=float, required=True)
    parser.add_argument("--interval-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    return shift(
        deployment_id=args.deployment_id,
        cluster=args.cluster,
        service=args.service,
        arn=args.task_definition,
        deadline_seconds=args.deadline_seconds,
        interval_seconds=args.interval_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())
