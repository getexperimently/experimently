"""Every name the deploy workflows address exists in that environment's synth (QA 4b).

`deploy.yml`, `rollback.yml` and `db-migrate.yml` build their AWS names from
the `environment` input -- `experimentation-${{ inputs.environment }}` and so
on -- because the CDK builds them the same way (stacks/names.py). The old
workflows spelled them for one environment and got them wrong in ways no test
saw: `--cluster experimentation-prod` (every environment's cluster was
`experimentation-dev`, #142), `experimentation-production` (an environment the
CDK does not build), a migration family shared by all environments.

So each workflow's names are rendered for staging and prod and looked up in a
real synth of that environment: the physical name must be on a resource of the
right type, a stack must be one the app creates, and a stack output a workflow
reads must be one that stack publishes. An environment value this file does
not classify fails, so a new name cannot slip past unexamined.
"""

from __future__ import annotations

import json
import re

import pytest
import yaml

from .test_app_profiles import REPO_ROOT
from .test_dashboard_service import _synth

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
NAMES = ("deploy.yml", "rollback.yml", "db-migrate.yml")
ENVIRONMENTS = ("staging", "prod")
PLACEHOLDER = "${{ inputs.environment }}"

#: Job env var -> (resource type, name property) it must name.
RESOURCE_NAMES = {
    "ECS_CLUSTER": ("AWS::ECS::Cluster", "ClusterName"),
    "ECS_BACKEND_SERVICE": ("AWS::ECS::Service", "ServiceName"),
    "ECS_BACKEND_TASK_FAMILY": ("AWS::ECS::TaskDefinition", "Family"),
    # The dashboard's rolling service and its family (#69).
    "ECS_DASHBOARD_SERVICE": ("AWS::ECS::Service", "ServiceName"),
    "ECS_DASHBOARD_TASK_FAMILY": ("AWS::ECS::TaskDefinition", "Family"),
    "MIGRATE_TASK_FAMILY": ("AWS::ECS::TaskDefinition", "Family"),
    "MIGRATE_LOG_GROUP": ("AWS::Logs::LogGroup", "LogGroupName"),
    "CODEDEPLOY_APPLICATION": ("AWS::CodeDeploy::Application", "ApplicationName"),
    "CODEDEPLOY_DEPLOYMENT_GROUP": (
        "AWS::CodeDeploy::DeploymentGroup",
        "DeploymentGroupName",
    ),
}
#: Job env vars naming a stack.
STACK_NAMES = {"FARGATE_STACK", "DATABASE_STACK"}
#: Job env vars that are a prefix every imported secret must start with.
SECRET_PREFIXES = {"SECRETS_PREFIX"}
#: Env vars that carry the environment but name nothing in AWS.
NOT_A_NAME = {"TARGET_ENV"}


@pytest.fixture(scope="module")
def synths():
    return {env: _synth(env) for env in ENVIRONMENTS}


def _bound_job(name: str) -> dict:
    document = yaml.safe_load((WORKFLOWS / name).read_text())
    (job,) = [j for j in document["jobs"].values() if "environment" in j]
    return job


def _named(assembly, resource_type: str, prop: str) -> set[str]:
    """Literal names only: a name built from a token is not one a workflow can spell."""
    names = (
        resource.get("Properties", {}).get(prop)
        for stack in assembly.stacks
        for resource in stack.template.get("Resources", {}).values()
        if resource["Type"] == resource_type
    )
    return {name for name in names if isinstance(name, str)}


@pytest.mark.regression
@pytest.mark.parametrize("env", ENVIRONMENTS)
@pytest.mark.parametrize("workflow", NAMES)
def test_workflow_names_exist_in_that_environment(synths, workflow, env):
    assembly = synths[env]
    job_env = _bound_job(workflow)["env"]
    templated = {k: v for k, v in job_env.items() if PLACEHOLDER in str(v)}
    unclassified = (
        set(templated)
        - set(RESOURCE_NAMES)
        - STACK_NAMES
        - SECRET_PREFIXES
        - NOT_A_NAME
    )
    assert not unclassified, (
        f"{workflow} builds {sorted(unclassified)} from the environment and this "
        "test does not know what AWS resource each names; classify it"
    )
    checked = 0
    stacks = {s.stack_name for s in assembly.stacks}
    for key, value in templated.items():
        name = str(value).replace(PLACEHOLDER, env)
        if key in RESOURCE_NAMES:
            resource_type, prop = RESOURCE_NAMES[key]
            names = _named(assembly, resource_type, prop)
            assert name in names, (
                f"{workflow}: {key}={name} names no {resource_type} in the {env} "
                f"synth (it has {sorted(n for n in names if isinstance(n, str))})"
            )
            checked += 1
        elif key in STACK_NAMES:
            assert name in stacks, (
                f"{workflow}: {key}={name} is not a stack of the {env} app"
            )
            checked += 1
        elif key in SECRET_PREFIXES:
            blob = json.dumps([s.template for s in assembly.stacks])
            assert f"secret:{name}/jwt-secret" in blob, (
                f"{workflow}: no stack imports a secret under {name}"
            )
            checked += 1
    # Exact, per workflow: a name dropped from a job's env (or never read
    # because a key was renamed) changes the count and fails here (QA 4c).
    assert checked == NAMES_CHECKED[workflow], (
        f"{workflow}: {checked} names checked, expected {NAMES_CHECKED[workflow]}"
    )


#: How many environment-built names each workflow's bound job carries.
NAMES_CHECKED = {"deploy.yml": 12, "rollback.yml": 7, "db-migrate.yml": 6}


README = REPO_ROOT / "docs" / "deployment" / "README.md"

#: The name property of each resource type the README's Names table uses.
NAME_PROPERTY = {
    "AWS::ECS::Cluster": "ClusterName",
    "AWS::ECS::Service": "ServiceName",
    "AWS::ECS::TaskDefinition": "Family",
    "AWS::Logs::LogGroup": "LogGroupName",
    "AWS::CodeDeploy::Application": "ApplicationName",
    "AWS::CodeDeploy::DeploymentGroup": "DeploymentGroupName",
    "AWS::ElastiCache::ReplicationGroup": "ReplicationGroupId",
    "AWS::SecretsManager::Secret": "Name",
}


def _names_table() -> list[tuple[str, str, str]]:
    """``(what, name, type)`` for each row of the README's Names table."""
    section = README.read_text().split("\n## Names\n", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("What", "") or set(cells[0]) <= {"-"}:
            continue
        rows.append((cells[0], cells[1].strip("`"), cells[2].strip("`")))
    return rows


@pytest.mark.regression
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_the_documented_names_exist(synths, env):
    """UX CHECK 3: the operator's Names table against a synth of each environment."""
    assembly = synths[env]
    stacks = {s.stack_name for s in assembly.stacks}
    checked = 0
    for what, name, kind in _names_table():
        if kind == "—":
            continue
        rendered = name.replace("<env>", env)
        if kind == "stack":
            assert rendered in stacks, (
                f"README Names: {what} `{rendered}` is not a stack"
            )
        else:
            assert kind in NAME_PROPERTY, f"README Names: unknown type {kind} ({what})"
            names = _named(assembly, kind, NAME_PROPERTY[kind])
            assert rendered in names, (
                f"README Names: {what} `{rendered}` is no {kind} in the {env} synth"
            )
        checked += 1
    assert checked >= 12, f"only {checked} rows checked: the table was not read"


@pytest.mark.regression
@pytest.mark.parametrize("env", ENVIRONMENTS)
@pytest.mark.parametrize("workflow", NAMES)
def test_the_stack_outputs_a_workflow_reads_exist(synths, workflow, env):
    """`fromJSON(steps.<id>.outputs.json).<Key>` must be an output of that stack."""
    assembly = synths[env]
    job = _bound_job(workflow)
    stacks_by_step = {}
    for step in job["steps"]:
        if str(step.get("uses", "")).startswith("./.github/actions/stack-outputs"):
            stack_var = re.fullmatch(
                r"\$\{\{ env\.(\w+) \}\}", step["with"]["stack"]
            ).group(1)
            stack = job["env"][stack_var].replace(PLACEHOLDER, env)
            stacks_by_step[step["id"]] = stack
            required = step["with"]["keys"].split()
            outputs = {
                s.stack_name: set(s.template.get("Outputs", {}))
                for s in assembly.stacks
            }[stack]
            assert set(required) <= outputs, (
                f"{workflow} requires {sorted(set(required) - outputs)} from {stack}, "
                f"which outputs {sorted(outputs)}"
            )
    text = (WORKFLOWS / workflow).read_text()
    used = re.findall(r"fromJSON\(steps\.([\w-]+)\.outputs\.json\)\.(\w+)", text)
    for step_id, key in used:
        stack = stacks_by_step[step_id]
        required = next(
            s["with"]["keys"].split() for s in job["steps"] if s.get("id") == step_id
        )
        assert key in required, (
            f"{workflow} reads {key} from {stack} without requiring it, so a stack "
            "without it would pass the refusal and fail later"
        )
