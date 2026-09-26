#!/usr/bin/env python3
"""Is the API serving this task-definition revision? (#143)

    python3 scripts/api_serving.py <cluster> <service> <task-definition ARN>

Exits 0 only when both of these hold:

1. the API service's PRIMARY task set runs exactly that revision (the ARN,
   compared as a string: a family or `family:n` is refused); and
2. `scripts/check_live_target_group.py`, run with `--expect` set to the
   colour of that task set's target group, passes. The colour is read from
   the task set, never defaulted (PE v2 C8). That check reads the HTTPS
   listener's `/api/*` rule and confirms that it forwards to that group and
   no other, and that its `/health` sibling agrees.

The PRIMARY task set, not `services[0].taskDefinition`: on a CODE_DEPLOY
service that field is frozen at CreateService.

This is the one "the API is serving this ARN" predicate. The forward deploy's
traffic-shift loop (`scripts/shift_traffic.py`) calls it after every poll,
and anything else that needs the same answer should call it too, rather than
write a second one.

Exit status:

    0  SERVING  both hold; prints the live group and the
                `-c api_live_target_group=<blue|green>` value for the next
                `cdk deploy` of the Fargate stack
    1  NOT_YET  the PRIMARY task set is another revision, or the /api/* rule
                splits traffic across blue and green (a CodeDeploy traffic
                shift is still in progress)
    2  UNKNOWN  an AWS call failed, or what it read does not look like this
                repository's stacks
    3  WRONG    the PRIMARY task set is this revision, but the /api/* rule
                forwards somewhere else, with no split: the API route is not
                where the tasks are

READ-ONLY: it runs only `check_live_target_group.READ_ONLY_OPERATIONS`, which
are four describe calls.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from pathlib import Path

# The sibling script, from the same checkout. Run as `python3 scripts/...`,
# scripts/ is already sys.path[0]; imported from a test, it may not be.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_live_target_group as live

SERVING, NOT_YET, UNKNOWN, WRONG = 0, 1, 2, 3

#: `infrastructure/cdk/stacks/names.py`: the cluster is `experimentation-<env>`
#: and the API service `experimentation-backend-<env>`. The environment names
#: the Fargate stack that check_live_target_group.py reads.
_CLUSTER = re.compile(r"experimentation-(dev|staging|prod|demo)")
_ARN = re.compile(
    r"arn:aws[a-z-]*:ecs:[a-z0-9-]+:[0-9]{12}:task-definition/[A-Za-z0-9_-]+:[0-9]+"
)


def verdict(
    aws: live.Runner, cluster: str, service: str, arn: str
) -> tuple[int, str, str | None]:
    """Return (status, sentence, live colour or None)."""
    match = _CLUSTER.fullmatch(cluster)
    if not match:
        return UNKNOWN, f"{cluster!r} is not an experimentation-<env> cluster", None
    env = match.group(1)
    if service != f"experimentation-backend-{env}":
        return (
            UNKNOWN,
            f"{service!r} is not the API service of {cluster} "
            f"(experimentation-backend-{env})",
            None,
        )
    if not _ARN.fullmatch(arn):
        return UNKNOWN, f"{arn!r} is not a task-definition revision ARN", None

    try:
        services = aws(
            ["ecs", "describe-services", "--cluster", cluster, "--services", service]
        ).get("services", [])
        if len(services) != 1:
            return UNKNOWN, f"describe-services returned {len(services)} services", None
        primary = [
            t for t in services[0].get("taskSets", []) if t.get("status") == "PRIMARY"
        ]
        if len(primary) != 1:
            return UNKNOWN, f"{service} has {len(primary)} PRIMARY task sets", None
        serving = primary[0].get("taskDefinition")
        if serving != arn:
            return NOT_YET, f"the PRIMARY task set runs {serving}, not {arn}", None

        stack = f"experimentation-fargate-{env}"
        resources = aws(
            ["cloudformation", "describe-stack-resources", "--stack-name", stack]
        ).get("StackResources", [])
        groups = {
            "blue": live._one(resources, "blue"),
            "green": live._one(resources, "green"),
        }
        target_groups = {
            lb["targetGroupArn"] for lb in primary[0].get("loadBalancers", [])
        }
        if len(target_groups) != 1:
            return (
                UNKNOWN,
                f"the PRIMARY task set is in {len(target_groups)} target groups",
                None,
            )
        colour = live._name(target_groups.pop(), groups, "the PRIMARY task set")
        # Derived, not defaulted: --expect is the PRIMARY task set's colour.
        live.check(aws, env, colour)
    except live.Shifting as exc:
        return NOT_YET, f"the PRIMARY task set runs {arn}; {exc}", None
    except live.Refused as exc:
        return WRONG, f"the PRIMARY task set runs {arn}, but {exc}", None
    except (live.Unknown, live.AwsError, KeyError, ValueError) as exc:
        return UNKNOWN, f"could not tell: {exc}", None
    return (
        SERVING,
        f"{arn} is the PRIMARY task set and the /api/* rule forwards to {colour} alone",
        colour,
    )


def main(argv: Sequence[str] | None = None, aws: live.Runner = live.run_aws) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print(
            "usage: api_serving.py <cluster> <service> <task-definition ARN>",
            file=sys.stderr,
        )
        return UNKNOWN
    status, sentence, colour = verdict(aws, *args)
    if status == SERVING:
        print(f"serving: {sentence}")
        print(
            f"live API target group: {colour}; the next cdk deploy of the Fargate "
            f"stack takes -c {live.CONTEXT_KEY}={colour}"
        )
    else:
        label = {NOT_YET: "NOT YET", UNKNOWN: "UNKNOWN", WRONG: "WRONG"}[status]
        print(f"{label}: {sentence}", file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main())
