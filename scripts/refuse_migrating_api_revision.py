#!/usr/bin/env python3
"""Refuse to deploy an API revision whose tasks would run migrations on start (#298).

    python3 scripts/refuse_migrating_api_revision.py \\
        --task-definition <the ARN register_task_definition.sh printed> \\
        --environment <env> --fargate-stack <stack name>

The API's task definition sets `RUN_MIGRATIONS=false` on its `backend`
container (infrastructure/cdk/stacks/fargate_service_stack.py): on AWS the
Deploy workflow's migration task is the only thing that writes the schema. A
revision without it runs the bootstrap every time a task starts, and a
bootstrap refuses a database a newer release has migrated, so every task of
that revision started after a later migration -- a replacement, a scale-out, a
rollback -- would exit instead of serving.

Deploy registers the API revision from the family's newest ACTIVE revision
(scripts/register_task_definition.sh), so the revision lacks the setting when
the environment's Fargate stack was last deployed from a checkout that
predates it. This runs after that registration and before the CodeDeploy
deployment is created, and reads back what ECS STORED for the registered ARN
(`describe-task-definition`), not the JSON that was sent.

It passes only when the stored revision has exactly one container named
`backend`, and that container's `environment` names `RUN_MIGRATIONS` exactly
once, with the value exactly `false`. Anything else is refused: the variable
missing, `true`, `False`, empty, named twice, or also set from `secrets`. (An
`environmentFiles` entry cannot override it: ECS gives `environment`
precedence over an environment file.)

READ-ONLY: `OPERATIONS` is the whole allow-list, and its one call reads.

Exit status: 0 go on; 1 refused; 2 could not tell (the AWS call failed, its
answer could not be read, or it describes a different revision). 2 also stops
the deploy: "I could not read it" is not "it does not migrate".
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_text import redact, short_arn

#: Every AWS CLI operation this script may run. It reads.
OPERATIONS = frozenset({("ecs", "describe-task-definition")})

OK, REFUSED, UNKNOWN = 0, 1, 2

CONTAINER = "backend"
VARIABLE = "RUN_MIGRATIONS"
REQUIRED = "false"

RUNBOOK = (
    "docs/deployment/rollback-runbook.md"
    "#deploy-refused-an-api-revision-that-would-run-migrations-on-start"
)

#: What has already happened when this runs, and what has not.
DONE = (
    "The snapshot was taken and the migration was applied; no CodeDeploy "
    "deployment was created, so the revision serving before this run still "
    "serves."
)


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


def stored_revision(aws: Callable[[Sequence[str]], dict], arn: str) -> dict:
    """The task definition ECS stored under `arn`."""
    answer = aws(["ecs", "describe-task-definition", "--task-definition", arn])
    stored = answer.get("taskDefinition") if isinstance(answer, dict) else None
    if not isinstance(stored, dict):
        raise ValueError("describe-task-definition returned no taskDefinition")
    if stored.get("taskDefinitionArn") != arn:
        raise ValueError(
            f"asked for {short_arn(arn)}, read "
            f"{short_arn(stored.get('taskDefinitionArn') or 'no ARN')}"
        )
    return stored


def why_it_migrates(stored: dict) -> str | None:
    """Why this revision's API tasks would run migrations on start, or None."""
    containers = [
        c
        for c in stored.get("containerDefinitions") or []
        if isinstance(c, dict) and c.get("name") == CONTAINER
    ]
    if len(containers) != 1:
        return f"it has {len(containers)} containers named `{CONTAINER}`, not one"
    (container,) = containers
    values = [
        entry.get("value")
        for entry in container.get("environment") or []
        if isinstance(entry, dict) and entry.get("name") == VARIABLE
    ]
    secret = any(
        isinstance(entry, dict) and entry.get("name") == VARIABLE
        for entry in container.get("secrets") or []
    )
    if secret:
        return f"its `{CONTAINER}` container takes {VARIABLE} from a secret"
    if not values:
        return f"its `{CONTAINER}` container does not set {VARIABLE}"
    if len(values) > 1:
        return f"its `{CONTAINER}` container sets {VARIABLE} {len(values)} times"
    (value,) = values
    if value != REQUIRED:
        return (
            f"its `{CONTAINER}` container sets {VARIABLE}="
            f"{_one_line(json.dumps(value), 40)}, not exactly {json.dumps(REQUIRED)}"
        )
    return None


def main(
    argv: Sequence[str] | None = None,
    aws: Callable[[Sequence[str]], dict] = run_aws,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task-definition", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--fargate-stack", required=True)
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return UNKNOWN
    if not args.task_definition.strip():
        print("::error title=No API revision to check::--task-definition is empty.")
        return UNKNOWN
    name = short_arn(args.task_definition)

    try:
        stored = stored_revision(aws, args.task_definition)
    except (AwsError, ValueError, json.JSONDecodeError) as exc:
        print(
            "::error title=Could not read the API revision::"
            f"{_one_line(exc)}. {DONE} This deploy stops here: a check that "
            "could not read the revision is not a check that found it safe."
        )
        return UNKNOWN

    why = why_it_migrates(stored)
    if why is None:
        print(f"{name}: {VARIABLE}={REQUIRED} on `{CONTAINER}` (as stored by ECS)")
        return OK

    print(
        "::error title=This API revision would run migrations on start::"
        f"{name} was registered from the newest revision of its family, and "
        f"{why}. Its tasks would run the database bootstrap each time one "
        "starts, and would refuse to start against any newer schema. "
        f"The Fargate stack of {args.environment} was last deployed from a "
        "checkout that predates the API tasks' "
        f"{VARIABLE}={REQUIRED} (#499). Fix: run `cdk deploy "
        f"{args.fargate_stack}` for {args.environment} from a checkout that "
        "contains #499 (0.14.0 or later), pinned to what is live, then run "
        "Deploy again. "
        f"{DONE} {RUNBOOK}"
    )
    return REFUSED


if __name__ == "__main__":
    sys.exit(main())
