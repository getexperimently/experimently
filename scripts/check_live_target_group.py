#!/usr/bin/env python3
"""Refuse a `cdk deploy` that would point the API's routes at an empty target group.

Run this before every `cdk deploy` that includes `experimentation-fargate-<env>`
on an environment that is already running. It reads which of the API's two
target groups (blue, green) is LIVE, and refuses unless that is the one the
deploy will write into the HTTPS listener's API rules -- the CDK context value
`api_live_target_group` (default `blue`).

Why this exists: CodeDeploy swaps blue and green on every deployment, outside
CloudFormation. After an odd number of deployments green is live and blue is
empty. The listener rules in `fargate_service_stack.py` send `/api/*`,
`/health`, `/health/*` and `/metrics` to the target group the context names;
naming blue then sends every API request to a target group with no targets
(503), while `/` and the dashboard's probes stay green. The next CodeDeploy
deployment then fails too.

The live target group is read two ways, and the two must agree:

* the load balancer: the target group the HTTPS listener's `/api/*` rule
  forwards to -- or, on a stack from before the dashboard, the listener's
  default action;
* ECS: the target group of the API service's PRIMARY task set, i.e. where the
  tasks serving the current release are registered.

If they disagree, the API route is already not where the tasks are and no
value of the context is safe: it refuses and says so. A forward action that
splits traffic across both groups is a CodeDeploy deployment in progress; it
refuses that too.

READ-ONLY. It runs exactly four AWS CLI operations, all describe calls:
`cloudformation describe-stack-resources`, `elbv2 describe-listeners`,
`elbv2 describe-rules`, `ecs describe-services`. Anything else is refused by
`run_aws` before a process is started.

    python3 scripts/check_live_target_group.py --env staging [--expect blue]
    # then, with the value it printed:
    cdk deploy experimentation-fargate-staging -c api_live_target_group=<blue|green>

Exit status: 0 safe to deploy with --expect; 1 refused; 2 could not tell
(an AWS call failed, the stack does not look like this repository's, or the
script itself raised -- a missing `aws` binary, a malformed rule; a crash is
never 1, "refused").
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence

#: The CDK context key and its default. `infrastructure/cdk/stacks/names.py`
#: holds the same two values; a unit test asserts they agree.
CONTEXT_KEY = "api_live_target_group"
DEFAULT_EXPECT = "blue"

#: The only AWS CLI operations this script may run. All of them read.
READ_ONLY_OPERATIONS = frozenset(
    {
        ("cloudformation", "describe-stack-resources"),
        ("elbv2", "describe-listeners"),
        ("elbv2", "describe-rules"),
        ("ecs", "describe-services"),
    }
)

#: Logical-ID prefixes of the resources this reads, in
#: `experimentation-fargate-<env>`. CDK appends an 8-character hash to each;
#: a CDK test asserts every prefix matches exactly one resource of the stack
#: as synthesised.
LOGICAL_ID_PREFIXES = {
    "blue": ("BlueTargetGroup", "AWS::ElasticLoadBalancingV2::TargetGroup"),
    "green": ("GreenTargetGroup", "AWS::ElasticLoadBalancingV2::TargetGroup"),
    "listener": ("BackendALBHttpsListener", "AWS::ElasticLoadBalancingV2::Listener"),
    "service": ("BackendService", "AWS::ECS::Service"),
}

#: The listener rule this checks. Its sibling (`/health`, `/health/*`,
#: `/metrics`) must forward to the same target group.
API_PATH = "/api/*"

OK, REFUSED, UNKNOWN = 0, 1, 2


class Unknown(Exception):
    """The answer cannot be determined; exit 2."""


class Refused(Exception):
    """Deploying would be unsafe, or already is; exit 1."""


class Shifting(Refused):
    """The API rule splits traffic across blue and green: a CodeDeploy traffic
    shift is in progress. Still exit 1 here; `scripts/api_serving.py` tells it
    apart from the other refusals, because to a deploy waiting for its own
    shift it means "not yet", not "wrong"."""


Runner = Callable[[Sequence[str]], dict]


def run_aws(argv: Sequence[str]) -> dict:
    """Run one read-only AWS CLI call and return its JSON output."""
    if tuple(argv[:2]) not in READ_ONLY_OPERATIONS:
        raise ValueError(f"not a read-only operation this script may run: {argv[:2]}")
    proc = subprocess.run(
        ["aws", *argv, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AwsError(proc.stderr.strip() or f"aws exited {proc.returncode}")
    return json.loads(proc.stdout or "{}")


class AwsError(Exception):
    """An AWS CLI call failed; the message is its stderr."""


def _one(resources: list[dict], key: str) -> str:
    prefix, rtype = LOGICAL_ID_PREFIXES[key]
    hits = [
        r
        for r in resources
        if r.get("ResourceType") == rtype
        and r.get("LogicalResourceId", "").startswith(prefix)
        and r.get("LogicalResourceId", "")[len(prefix) :].isalnum()
        and len(r.get("LogicalResourceId", "")) == len(prefix) + 8
    ]
    if len(hits) != 1:
        raise Unknown(
            f"expected exactly one {rtype} named {prefix}<hash> in the stack, "
            f"found {len(hits)}: is this experimentation-fargate-<env>?"
        )
    physical = hits[0].get("PhysicalResourceId")
    if not physical:
        raise Unknown(f"{hits[0]['LogicalResourceId']} has no physical id yet")
    return physical


def _forward_targets(actions: list[dict]) -> set[str]:
    """Target groups a rule's forward action sends traffic to (weight > 0)."""
    targets: set[str] = set()
    for action in actions:
        if action.get("Type") != "forward":
            continue
        weighted = (action.get("ForwardConfig") or {}).get("TargetGroups")
        if weighted:
            targets |= {t["TargetGroupArn"] for t in weighted if t.get("Weight", 1) > 0}
        elif action.get("TargetGroupArn"):
            targets.add(action["TargetGroupArn"])
    return targets


def _path_values(rule: dict) -> set[str]:
    values: set[str] = set()
    for condition in rule.get("Conditions", []):
        if condition.get("Field") != "path-pattern":
            continue
        values |= set((condition.get("PathPatternConfig") or {}).get("Values") or [])
        values |= set(condition.get("Values") or [])
    return values


def _name(arn: str, groups: dict[str, str], where: str) -> str:
    for name, group_arn in groups.items():
        if arn == group_arn:
            return name
    raise Refused(
        f"{where} forwards to {arn}, which is neither the blue nor the green "
        "target group of this stack"
    )


def live_from_listener(aws: Runner, listener_arn: str, groups: dict[str, str]) -> str:
    """The API's live target group, as the HTTPS listener routes it."""
    listeners = aws(
        ["elbv2", "describe-listeners", "--listener-arns", listener_arn]
    ).get("Listeners", [])
    if len(listeners) != 1:
        raise Unknown(f"describe-listeners returned {len(listeners)} listeners")
    rules = aws(["elbv2", "describe-rules", "--listener-arn", listener_arn]).get(
        "Rules", []
    )

    api_rules = [
        r for r in rules if not r.get("IsDefault") and API_PATH in _path_values(r)
    ]
    if len(api_rules) > 1:
        raise Unknown(f"{len(api_rules)} listener rules match {API_PATH}")
    if api_rules:
        where = f"the {API_PATH} rule"
        targets = _forward_targets(api_rules[0].get("Actions", []))
        siblings = [
            rule
            for rule in rules
            if rule is not api_rules[0]
            and not rule.get("IsDefault")
            and ("/health" in _path_values(rule) or "/metrics" in _path_values(rule))
        ]
        # A split in EITHER rule is a traffic shift in progress, and is said
        # so before the two are compared: CodeDeploy may rewrite them in
        # separate calls, and "api split, health not yet" is still shifting,
        # not wrong (PE B3b C1).
        for rule, name in [(api_rules[0], where)] + [
            (s, "the /health rule") for s in siblings
        ]:
            split = _forward_targets(rule.get("Actions", []))
            if len(split) > 1:
                raise Shifting(
                    f"{name} forwards to {len(split)} target groups with weight: "
                    "a CodeDeploy traffic shift is in progress. Wait for it to "
                    "finish."
                )
        # The sibling rule must go to the same place.
        for rule in siblings:
            if _forward_targets(rule.get("Actions", [])) != targets:
                raise Refused(
                    "the /health and /api/* rules forward to different "
                    "target groups; one of them is already wrong"
                )
    else:
        # A stack from before the dashboard: the API is the default action.
        where = "the listener's default action"
        targets = _forward_targets(listeners[0].get("DefaultActions", []))

    if len(targets) > 1:
        raise Shifting(
            f"{where} forwards to {len(targets)} target groups with weight: a "
            "CodeDeploy traffic shift is in progress. Wait for it to finish."
        )
    if not targets:
        raise Refused(f"{where} forwards to no target group with weight")
    return _name(targets.pop(), groups, where)


def live_from_ecs(aws: Runner, service_arn: str, groups: dict[str, str]) -> str:
    """The API's live target group, as ECS registers the PRIMARY task set."""
    # arn:aws:ecs:<region>:<account>:service/<cluster>/<service>
    parts = service_arn.split(":", 5)[-1].split("/")
    if len(parts) != 3 or parts[0] != "service":
        raise Unknown(f"cannot read the cluster from service ARN {service_arn}")
    services = aws(
        ["ecs", "describe-services", "--cluster", parts[1], "--services", service_arn]
    ).get("services", [])
    if len(services) != 1:
        raise Unknown(f"describe-services returned {len(services)} services")
    primary = [
        t for t in services[0].get("taskSets", []) if t.get("status") == "PRIMARY"
    ]
    if len(primary) != 1:
        raise Unknown(f"the API service has {len(primary)} PRIMARY task sets")
    arns = {lb["targetGroupArn"] for lb in primary[0].get("loadBalancers", [])}
    if len(arns) != 1:
        raise Unknown(f"the PRIMARY task set is in {len(arns)} target groups")
    return _name(arns.pop(), groups, "the PRIMARY task set")


def check(aws: Runner, env: str, expect: str) -> str:
    """Return the live target group's name, or raise Refused / Unknown."""
    stack = f"experimentation-fargate-{env}"
    try:
        resources = aws(
            ["cloudformation", "describe-stack-resources", "--stack-name", stack]
        ).get("StackResources", [])
    except AwsError as exc:
        if "does not exist" not in str(exc):
            raise
        # First deployment: CloudFormation creates the service in blue.
        if expect != DEFAULT_EXPECT:
            raise Refused(
                f"{stack} does not exist yet, so nothing is live; a new "
                f"environment starts in {DEFAULT_EXPECT}, not {expect}"
            ) from exc
        return DEFAULT_EXPECT

    groups = {"blue": _one(resources, "blue"), "green": _one(resources, "green")}
    from_listener = live_from_listener(aws, _one(resources, "listener"), groups)
    from_ecs = live_from_ecs(aws, _one(resources, "service"), groups)
    if from_listener != from_ecs:
        raise Refused(
            f"the load balancer sends the API to {from_listener} but the "
            f"tasks serving the current release are in {from_ecs}. The API "
            "route is already pointing at the wrong target group; no value of "
            f"{CONTEXT_KEY} is safe until that is repaired."
        )
    if from_listener != expect:
        raise Refused(
            f"{from_listener} is live, but this deploy would route the API to "
            f"{expect}. Deploy with:  -c {CONTEXT_KEY}={from_listener}"
        )
    return from_listener


def main(argv: Sequence[str] | None = None, aws: Runner = run_aws) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    # A closed set: a typo would otherwise reach the "stack does not exist"
    # branch and report the default group as live.
    parser.add_argument(
        "--env",
        required=True,
        choices=["dev", "staging", "prod", "demo"],
        help="the ENVIRONMENT the stack was deployed with",
    )
    parser.add_argument(
        "--expect",
        choices=("blue", "green"),
        default=DEFAULT_EXPECT,
        help=f"the {CONTEXT_KEY} value the deploy will pass (default {DEFAULT_EXPECT})",
    )
    args = parser.parse_args(argv)
    try:
        live = check(aws, args.env, args.expect)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return REFUSED
    except (Unknown, AwsError) as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        return UNKNOWN
    except Exception as exc:  # any crash is "could not tell", never "refused"
        print(f"UNKNOWN: could not tell: {type(exc).__name__}: {exc}", file=sys.stderr)
        return UNKNOWN
    print(f"ok: {live} is live; deploy with -c {CONTEXT_KEY}={live}")
    return OK


if __name__ == "__main__":
    sys.exit(main())
