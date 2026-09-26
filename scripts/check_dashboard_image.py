#!/usr/bin/env python3
"""Print the dashboard's running image digest, and refuse a `cdk deploy` that would replace it.

Run this before every `cdk deploy` that includes `experimentation-fargate-<env>`
on an environment that is already running, next to
`check_live_target_group.py`. It reads the image the dashboard service is
running -- the `dashboard` container of the task definition its PRIMARY
deployment runs -- and prints the CDK context value that keeps it:

    -c dashboard_image_tag=sha256:<hex>

Why this exists: the dashboard service uses the ECS deployment controller, and
releases are meant to reach it outside CloudFormation (#69: the deploy workflow
registers a task definition revision by digest and points the service at it;
until that lands the dashboard runs `:bootstrap`). A `cdk deploy` that
changes the dashboard's task definition in any way re-points the service at
CloudFormation's own revision, whose image is `web:<dashboard_image_tag>` --
`web:bootstrap` when the context is not given. The service rolls back to the
placeholder image and every probe stays green. Passing the running digest
makes CloudFormation's revision name the same bytes that are already serving.

With `--expect sha256:<hex>` -- the value the deploy will pass -- it refuses
unless the dashboard is running exactly that digest.

A dashboard that runs a tag rather than a digest (`:bootstrap` before the first
release, or anything registered by hand) is printed as a tag: there is no
digest to pin, and `--expect` refuses.

READ-ONLY. It runs exactly two AWS CLI operations, both describe calls:
`ecs describe-services`, `ecs describe-task-definition`. Anything else is
refused by `run_aws` before a process is started.

    python3 scripts/check_dashboard_image.py --env staging [--expect sha256:<hex>]
    # then, with the value it printed:
    cdk deploy experimentation-fargate-staging -c dashboard_image_tag=sha256:<hex> ...

Exit status: 0 printed (and, with --expect, it matches); 1 refused; 2 could
not tell (an AWS call failed, or the service does not look like this
repository's).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence

#: The CDK context key `infrastructure/cdk/stacks/dashboard_service.py` reads.
CONTEXT_KEY = "dashboard_image_tag"

#: Names the CDK gives these resources; a CDK test asserts they agree with the
#: synthesised stack (`stacks/names.py`, `stacks/dashboard_service.py`).
CLUSTER = "experimentation-{env}"
SERVICE = "experimentation-dashboard-{env}"
CONTAINER = "dashboard"
REPOSITORY = "experimentation-platform/web"

#: The only AWS CLI operations this script may run. Both read.
READ_ONLY_OPERATIONS = frozenset(
    {
        ("ecs", "describe-services"),
        ("ecs", "describe-task-definition"),
    }
)

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

OK, REFUSED, UNKNOWN = 0, 1, 2


class Unknown(Exception):
    """The answer cannot be determined; exit 2."""


class Refused(Exception):
    """Deploying with the given pin would replace what is running; exit 1."""


class AwsError(Exception):
    """An AWS CLI call failed; the message is its stderr."""


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


def split_image(image: str) -> tuple[str, str | None, str | None]:
    """`<registry>/<repo>[:tag][@sha256:<hex>]` -> (repo, tag, digest)."""
    name, _, digest = image.partition("@")
    last = name.rsplit("/", 1)[-1]
    tag = None
    if ":" in last:
        name, tag = name.rsplit(":", 1)
    # Drop the registry host (`<account>.dkr.ecr.<region>.amazonaws.com/`).
    first, _, rest = name.partition("/")
    repo = rest if rest and ("." in first or ":" in first) else name
    return repo, tag, digest or None


def running_image(aws: Runner, env: str) -> str | None:
    """The dashboard container's image in the PRIMARY deployment, or None."""
    cluster, service = CLUSTER.format(env=env), SERVICE.format(env=env)
    try:
        answer = aws(
            ["ecs", "describe-services", "--cluster", cluster, "--services", service]
        )
    except AwsError as exc:
        if "ClusterNotFoundException" not in str(exc):
            raise
        return None  # a new environment: no cluster, so no service either
    failures = [f for f in answer.get("failures", []) if f.get("reason") != "MISSING"]
    if failures:
        raise Unknown(f"describe-services failed: {failures}")
    services = [s for s in answer.get("services", []) if s.get("status") == "ACTIVE"]
    if not services:
        # MISSING (never created), or INACTIVE (deleted): nothing is running.
        return None
    if len(services) != 1:
        raise Unknown(f"describe-services returned {len(services)} active services")
    deployments = services[0].get("deployments", [])
    if len(deployments) != 1:
        raise Refused(
            f"{service} has {len(deployments)} deployments: a rollout is in "
            "progress, so what will be running is not decided yet. Wait for it "
            "to finish and run this again."
        )
    (primary,) = deployments
    if primary.get("status") != "PRIMARY" or not primary.get("taskDefinition"):
        raise Unknown(
            f"{service}'s only deployment is not a PRIMARY with a task definition"
        )

    task_definition = aws(
        [
            "ecs",
            "describe-task-definition",
            "--task-definition",
            primary["taskDefinition"],
        ]
    ).get("taskDefinition", {})
    containers = [
        c
        for c in task_definition.get("containerDefinitions", [])
        if c.get("name") == CONTAINER
    ]
    if len(containers) != 1 or not containers[0].get("image"):
        raise Unknown(
            f"{primary['taskDefinition']} has {len(containers)} containers named "
            f"{CONTAINER!r} with an image: is this the dashboard's task definition?"
        )
    return containers[0]["image"]


def check(aws: Runner, env: str, expect: str | None) -> str:
    """Return the line to print, or raise Refused / Unknown."""
    service = SERVICE.format(env=env)
    image = running_image(aws, env)
    if image is None:
        if expect:
            raise Refused(
                f"{service} does not exist, so nothing is running to match "
                f"{expect}. On a new environment deploy without --expect."
            )
        return (
            f"ok: {service} does not exist yet; nothing is running and there is "
            f"nothing to pin"
        )

    repo, tag, digest = split_image(image)
    if repo != REPOSITORY:
        raise Refused(
            f"the dashboard is running {image}, which is not from {REPOSITORY}. "
            f"No value of {CONTEXT_KEY} reproduces it: a cdk deploy that "
            "changes the dashboard's task definition replaces it."
        )

    if digest:
        if not DIGEST.fullmatch(digest):
            raise Unknown(
                f"the dashboard's image has a digest this does not read: {image}"
            )
        pin = f"-c {CONTEXT_KEY}={digest}"
        if expect and expect != digest:
            raise Refused(
                f"the dashboard is running {REPOSITORY}@{digest}, but this deploy "
                f"would pass {expect}. Deploy with:  {pin}"
            )
        return f"ok: the dashboard is running {REPOSITORY}@{digest}; deploy with {pin}"

    # A tag, not a digest.
    what = (
        f"the dashboard is running {REPOSITORY}:{tag}, a TAG, not a digest"
        if tag
        else f"the dashboard is running {image}, with neither a tag nor a digest"
    )
    if expect:
        raise Refused(f"{what}, so it cannot match {expect}.")
    if tag == "bootstrap":
        return (
            f"ok: {what}. That is the placeholder, from before the first release: "
            f"deploy without {CONTEXT_KEY} (it defaults to bootstrap)."
        )
    return (
        f"ok: {what}. There is no digest to pin; -c {CONTEXT_KEY}={tag} names "
        "the same tag, which may since have moved to other bytes."
    )


def _digest(value: str) -> str:
    if not DIGEST.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"expected sha256:<64 lowercase hex>, got {value!r}"
        )
    return value


def main(argv: Sequence[str] | None = None, aws: Runner = run_aws) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    # A closed set, as in check_live_target_group.py: a typo would otherwise
    # reach the "service does not exist" branch and report nothing to pin.
    parser.add_argument(
        "--env",
        required=True,
        choices=["dev", "staging", "prod", "demo"],
        help="the ENVIRONMENT the stack was deployed with",
    )
    parser.add_argument(
        "--expect",
        type=_digest,
        default=None,
        help=f"the {CONTEXT_KEY} value the deploy will pass (sha256:<hex>)",
    )
    args = parser.parse_args(argv)
    try:
        line = check(aws, args.env, args.expect)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return REFUSED
    except (Unknown, AwsError) as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        return UNKNOWN
    print(line)
    return OK


if __name__ == "__main__":
    sys.exit(main())
