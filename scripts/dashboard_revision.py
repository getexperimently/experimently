#!/usr/bin/env python3
"""What the dashboard is serving, and whether a revision may be rolled onto it (#69).

    python3 scripts/dashboard_revision.py serving --cluster C --service S \\
        [--family F --refuse-unsteady] [--github-output FILE]
    python3 scripts/dashboard_revision.py target --cluster C --service S \\
        --family F --api-family A [--github-output FILE] <revision>

`serving` reads the dashboard service's PRIMARY *deployment* (a rolling
service has no task sets) and the image of its `dashboard` container. It
writes, to FILE:

    arn=<the PRIMARY deployment's task-definition ARN>
    image=<that revision's dashboard image>
    release_arn=<the ARN again, if the image is a release; else empty>
    digest=<the image's digest, if it is a release; else empty>

With `--refuse-unsteady` it is the deploy's refusal, run before anything
changes: the service must exist, be ACTIVE, be deployed by the ECS rolling
controller, want at least one task, have exactly one deployment and that
one COMPLETED, and the family's newest revision must have exactly one
`dashboard` container (the one `register_task_definition.sh` replaces).

`target` is rollback.yml's check of `dashboard_task_definition_arn`, run
before anything changes. The revision must name a revision number (a bare
family is refused), be ACTIVE, belong to FAMILY (an API revision, or another
environment's, is refused by name), have exactly one `dashboard` container,
and run a release image. It also records what the service is serving now,
for the rollout's `--expect-primary`:

    arn=<the resolved target ARN>   image=<its image>
    expect=<the service's PRIMARY deployment's ARN, read now>

**A release image** is `is_release_image()`: an image in
`experimentation-platform/web` named by digest and nothing else. It is the ONE
predicate that decides both whether a deploy's summary prints a dashboard
rollback value (`release_arn`) and whether rollback.yml accepts one, so the
line a summary prints is always a line rollback accepts (PE v1 C6). A
`:bootstrap` revision, or one CloudFormation registered from a tag after a
`cdk deploy`, is not a release.

READ-ONLY: `check_dashboard_image.run_aws`, which runs only `ecs
describe-services` and `ecs describe-task-definition`.

Exit status: 0 read (and, with a refusal flag or `target`, acceptable);
1 refused; 2 could not tell (an AWS call failed); 64 usage.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

# The sibling script, from the same checkout (as api_serving.py does).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_dashboard_image as dash

OK, REFUSED, UNKNOWN = 0, 1, 2
BOOTSTRAP_TAG = "bootstrap"


class Refused(Exception):
    """Exit 1, with a message that says nothing was changed."""


class Unknown(Exception):
    """Exit 2."""


def is_release_image(image: str | None) -> bool:
    """The one release predicate: `<registry>/experimentation-platform/web@sha256:<hex>`."""
    if not image:
        return False
    repo, tag, digest = dash.split_image(image)
    return (
        repo == dash.REPOSITORY
        and tag is None
        and digest is not None
        and dash.DIGEST.fullmatch(digest) is not None
    )


def _describe_service(aws: dash.Runner, cluster: str, service: str) -> dict | None:
    try:
        answer = aws(
            ["ecs", "describe-services", "--cluster", cluster, "--services", service]
        )
    except dash.AwsError as exc:
        if "ClusterNotFoundException" in str(exc):
            return None
        raise Unknown(f"describe-services failed: {exc}") from exc
    services = [s for s in answer.get("services", []) if s.get("status") == "ACTIVE"]
    if not services:
        return None
    if len(services) != 1:
        raise Unknown(f"describe-services returned {len(services)} active services")
    return services[0]


def _task_definition(aws: dash.Runner, name: str) -> dict:
    try:
        answer = aws(["ecs", "describe-task-definition", "--task-definition", name])
    except dash.AwsError as exc:
        raise Unknown(f"describe-task-definition {name} failed: {exc}") from exc
    return answer.get("taskDefinition", {})


def _dashboard_images(task_definition: dict) -> list[str]:
    return [
        str(c.get("image", ""))
        for c in task_definition.get("containerDefinitions", [])
        if c.get("name") == dash.CONTAINER
    ]


def _names(task_definition: dict) -> str:
    return ", ".join(
        str(c.get("name")) for c in task_definition.get("containerDefinitions", [])
    )


def _primary(service: dict) -> tuple[list[dict], dict | None]:
    deployments = list(service.get("deployments", []))
    primaries = [d for d in deployments if d.get("status") == "PRIMARY"]
    return deployments, primaries[0] if len(primaries) == 1 else None


def _image_of(aws: dash.Runner, arn: str) -> str:
    images = _dashboard_images(_task_definition(aws, arn))
    if len(images) != 1 or not images[0]:
        raise Unknown(
            f"{arn} has {len(images)} containers named {dash.CONTAINER!r} with an "
            "image: is this the dashboard's task definition?"
        )
    return images[0]


def serving(
    aws: dash.Runner,
    cluster: str,
    service_name: str,
    family: str | None,
    refuse_unsteady: bool,
) -> tuple[dict[str, str], list[str]]:
    """Return (outputs, notices) or raise Refused / Unknown."""
    nothing = " Nothing has been built or changed."
    service = _describe_service(aws, cluster, service_name)
    if service is None:
        if not refuse_unsteady:
            return {"arn": "", "image": "", "release_arn": "", "digest": ""}, [
                f"{service_name}: no ACTIVE service in {cluster}"
            ]
        stack = "experimentation-fargate-" + cluster.removeprefix("experimentation-")
        raise Refused(
            f"No ACTIVE ECS service {service_name} in {cluster}: these stacks "
            "predate the dashboard service (v0.4.0). Deploy "
            f"{stack} with the pins in docs/deployment/deployment-guide.md "
            f"section 1.6 first.{nothing}"
        )
    deployments, primary = _primary(service)
    if refuse_unsteady:
        controller = (service.get("deploymentController") or {}).get("type", "ECS")
        if controller != "ECS":
            raise Refused(
                f"{service_name} is deployed by {controller}, not the ECS rolling "
                f"controller this deploy rolls it out with.{nothing}"
            )
        wanted = service.get("desiredCount", 0)
        if not isinstance(wanted, int) or wanted < 1:
            raise Refused(
                f"{service_name} wants {wanted} tasks: a rollout to no tasks would "
                f"look complete with nothing running.{nothing}"
            )
        if (
            len(deployments) != 1
            or primary is None
            or (primary.get("rolloutState") != "COMPLETED")
        ):
            listing = "; ".join(
                f"{d.get('id')} {d.get('status')} {d.get('rolloutState', '-')} "
                f"{str(d.get('taskDefinition', '')).rsplit('/', 1)[-1]}"
                for d in deployments
            )
            raise Refused(
                f"a dashboard deployment is in progress ({listing or 'none listed'}): "
                f"wait for it to finish, or roll it back, first.{nothing}"
            )
        if family:
            newest = _task_definition(aws, family)
            images = _dashboard_images(newest)
            if len(images) != 1:
                raise Refused(
                    f"{family}'s newest revision has {len(images)} containers named "
                    f"{dash.CONTAINER!r} (it has: {_names(newest)}); the deploy "
                    f"replaces the image of exactly one.{nothing}"
                )
    if primary is None or not primary.get("taskDefinition"):
        raise Unknown(
            f"{service_name} does not have exactly one PRIMARY deployment with a "
            "task definition"
        )
    arn = str(primary["taskDefinition"])
    image = _image_of(aws, arn)
    release = is_release_image(image)
    notices = [f"{service_name} is serving {arn.rsplit('/', 1)[-1]} ({image})"]
    repo, tag, _ = dash.split_image(image)
    if not release and not (repo == dash.REPOSITORY and tag == BOOTSTRAP_TAG):
        # EM v1 condition 4: a revision CloudFormation registered from a tag --
        # a `cdk deploy` without the digest pin after a release reverted it.
        notices.append(
            f"::warning title=Dashboard not on a release::{service_name} is serving "
            f"{image}, which is neither a release (a digest) nor the bootstrap "
            "placeholder. A `cdk deploy` without `-c dashboard_image_tag=sha256:"
            "<digest>` re-points the dashboard at a tag; check it with "
            "`python3 scripts/check_dashboard_image.py` before the next one "
            "(docs/deployment/deployment-guide.md section 1.6). This run records "
            "no dashboard rollback value."
        )
    outputs = {
        "arn": arn,
        "image": image,
        "release_arn": arn if release else "",
        "digest": (dash.split_image(image)[2] or "") if release else "",
    }
    return outputs, notices


def target(
    aws: dash.Runner,
    cluster: str,
    service_name: str,
    family: str,
    api_family: str,
    revision: str,
) -> tuple[dict[str, str], list[str]]:
    """Return (outputs, notices) or raise Refused / Unknown."""
    nothing = " Nothing has been rolled back."
    if not revision:
        raise Refused(f"no dashboard revision was given.{nothing}")
    try:
        answer = aws(["ecs", "describe-task-definition", "--task-definition", revision])
    except dash.AwsError as exc:
        raise Refused(
            f"{revision} is not a task definition revision ECS knows here "
            f"({exc}).{nothing}"
        ) from exc
    task_definition = answer.get("taskDefinition", {})
    arn = str(task_definition.get("taskDefinitionArn", ""))
    short = arn.rsplit("/", 1)[-1]
    if not revision.rsplit("/", 1)[-1].partition(":")[2].isdigit():
        raise Refused(
            f"{revision} names a family with no revision. It would resolve to the "
            "newest ACTIVE revision, which during an incident may be the one you "
            f"are rolling back from. Pass {short} instead.{nothing}"
        )
    status = task_definition.get("status")
    if status != "ACTIVE":
        raise Refused(
            f"{arn} is {status}, not ACTIVE. A deregistered revision cannot be "
            f"deployed.{nothing}"
        )
    got = str(task_definition.get("family", ""))
    if got != family:
        env = family.removeprefix("experimentation-dashboard-")
        api_prefix = api_family.removesuffix(env)
        if got == api_family:
            raise Refused(
                f"{short} is an API revision; it goes in task_definition_arn, not "
                f"dashboard_task_definition_arn.{nothing}"
            )
        if got.startswith("experimentation-dashboard-"):
            other = got.removeprefix("experimentation-dashboard-")
            raise Refused(
                f"You chose environment={env} but {short} is a {other} dashboard "
                f"revision. Re-run with environment={other}.{nothing}"
            )
        if got.startswith(api_prefix):
            raise Refused(
                f"{short} is an API revision of another environment; it does not "
                f"go in dashboard_task_definition_arn.{nothing}"
            )
        raise Refused(f"{arn} belongs to family {got}, not {family}.{nothing}")
    images = _dashboard_images(task_definition)
    if len(images) != 1:
        raise Refused(
            f"{arn} has no container named '{dash.CONTAINER}' (it has: "
            f"{_names(task_definition)}).{nothing}"
        )
    (image,) = images
    if not is_release_image(image):
        raise Refused(
            f"{arn} runs {image}, which is not a release: a deploy registers the "
            f"dashboard by digest ({dash.REPOSITORY}@sha256:...). A tag, or "
            "`:bootstrap`, is a revision CloudFormation registered. Pick a "
            "revision a deploy registered; docs/deployment/rollback-runbook.md "
            f"Step 1 lists them with their images.{nothing}"
        )
    service = _describe_service(aws, cluster, service_name)
    if service is None:
        raise Refused(f"No ACTIVE ECS service {service_name} in {cluster}.{nothing}")
    _, primary = _primary(service)
    if primary is None or not primary.get("taskDefinition"):
        raise Refused(
            f"{service_name} does not have exactly one PRIMARY deployment, so this "
            f"run cannot tell what it would replace.{nothing}"
        )
    expect = str(primary["taskDefinition"])
    notices = [
        f"dashboard: rolling back to {short} ({image}); it is serving "
        f"{expect.rsplit('/', 1)[-1]} now"
    ]
    return {"arn": arn, "image": image, "expect": expect}, notices


def main(argv: Sequence[str] | None = None, aws: dash.Runner = dash.run_aws) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("serving", "target"):
        p = sub.add_parser(name)
        p.add_argument("--cluster", required=True)
        p.add_argument("--service", required=True)
        p.add_argument("--github-output", default=None)
        p.add_argument("--family", required=name == "target", default=None)
        if name == "serving":
            p.add_argument("--refuse-unsteady", action="store_true")
        else:
            p.add_argument("--api-family", required=True)
            p.add_argument("revision")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 64 if exc.code else 0
    if args.command == "serving" and args.refuse_unsteady and not args.family:
        print("usage: --refuse-unsteady needs --family", file=sys.stderr)
        return 64
    try:
        if args.command == "serving":
            outputs, notices = serving(
                aws, args.cluster, args.service, args.family, args.refuse_unsteady
            )
        else:
            outputs, notices = target(
                aws,
                args.cluster,
                args.service,
                args.family,
                args.api_family,
                args.revision,
            )
    except Refused as exc:
        print(f"::error::{exc}")
        return REFUSED
    except (Unknown, dash.Unknown, dash.AwsError) as exc:
        print(f"::error::could not tell what the dashboard is serving: {exc}")
        return UNKNOWN
    for line in notices:
        print(line)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as out:
            for key, value in outputs.items():
                # One line per value: an image or ARN has no newline, and a
                # value that did would forge a second output.
                out.write(f"{key}={value.splitlines()[0] if value else ''}\n")
    return OK


if __name__ == "__main__":
    sys.exit(main())
