"""One container repository, named the same in all three trees (#211).

`docs/deployment/deployment-guide.md` told operators to create
`experimentation-backend` and `experimentation-migrations` before the first
deployment. Nothing used either name. Every producer and consumer says
`experimentation-platform/backend`:

    .github/workflows/deploy-prod.yml   ECR_BACKEND_REPO
    infrastructure/cdk/.../fargate_service_stack.py
    infrastructure/cdk/.../migration_task_stack.py

So an operator who followed the guide exactly created two repositories nothing
would ever use, and the first `Deploy to Production` failed at `docker push`
with "name unknown: The repository with name ... does not exist", taking
`run-migrations` and `deploy` with it.

Two halves to the fix and this file holds the second: something now *creates*
the repository (`compute_stack`, which deploys before the service that needs
it), and the name is asserted identical wherever it appears. A rename that
misses a caller fails here rather than at 3am.
"""

from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

import pytest

from .test_app_profiles import CDK_DIR, _app_environment

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml"


@pytest.fixture(scope="module")
def assembly():
    with _app_environment(CDK_DIR):
        namespace = runpy.run_path(str(CDK_DIR / "app.py"), run_name="__main__")
    return namespace["app"].synth()


#: The one name. Read from the CDK rather than retyped here, so this file
#: cannot be the copy that goes stale.
def _repository_name() -> str:
    import sys

    sys.path.insert(0, str(CDK_DIR))
    try:
        from stacks.names import BACKEND_ECR_REPOSITORY

        return BACKEND_ECR_REPOSITORY
    finally:
        sys.path.remove(str(CDK_DIR))


def _referenced_repositories(assembly) -> set[str]:
    """Every repository name an ECS container image refers to.

    Matched against the account's own registry host, not "anything with a
    slash before a colon" -- a sidecar from `public.ecr.aws/docker/library/
    redis:7` would otherwise be reported as a repository this project must
    create.
    """
    names = set()
    for stack in assembly.stacks:
        for resource in stack.template.get("Resources", {}).values():
            if resource["Type"] != "AWS::ECS::TaskDefinition":
                continue
            for container in resource["Properties"].get("ContainerDefinitions", []):
                blob = json.dumps(container.get("Image"))
                for match in re.finditer(
                    r"dkr\.ecr[^\"]*?amazonaws\.com[^\"]*?/([a-z0-9][a-z0-9._/-]*):",
                    blob,
                ):
                    names.add(match.group(1))
                # The synthesised form splits the host across an Fn::Join, so
                # also take a repository path that directly follows one.
                for match in re.finditer(
                    r"/([a-z0-9][a-z0-9._/-]*/[a-z0-9._-]+):", blob
                ):
                    names.add(match.group(1))
    return names


@pytest.mark.regression
def test_every_referenced_repository_is_the_one_we_name(assembly):
    """The stacks import a repository by name; they must import the same one.

    Nothing in the CDK *creates* it, deliberately -- see `stacks/names.py`.
    A registry is account-scoped and these stacks are per-environment, so a
    fixed name owned by one of them means a second environment in the same
    account cannot deploy.
    """
    referenced = _referenced_repositories(assembly)
    assert referenced, (
        "no container image refers to a repository at all, so nothing below "
        "examined anything"
    )
    wrong = referenced - {_repository_name()}
    assert not wrong, (
        f"these repositories are referenced but are not {_repository_name()!r}: "
        f"{sorted(wrong)}"
    )


@pytest.mark.skipif(
    not DEPLOY_WORKFLOW.is_file(), reason="this tree has no .github/workflows"
)
@pytest.mark.regression
def test_the_deploy_workflow_pushes_to_that_repository():
    """The half that lives in a different tree, and drifted.

    Compared against `stacks/names.py`, not against a synthesised app: the
    app is synthesised for `dev` and this is the production workflow, so
    comparing the two would fail the moment anyone environment-scoped the
    name -- a gate pinning in the defect it was written to prevent.
    """
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^\s*ECR_BACKEND_REPO:\s*(\S+)\s*$", text, re.M)
    assert match, "deploy-prod.yml no longer sets ECR_BACKEND_REPO"
    assert match.group(1) == _repository_name(), (
        f"the deploy workflow pushes to {match.group(1)!r}, but the CDK names "
        f"{_repository_name()!r}"
    )


#: Every name this repository has ever been called and is not. A dead name in
#: an operator document is not a typo -- `rollback-runbook.md` used two of
#: these in the commands you run during an incident, where
#: `batch-get-image` returns nothing and `put-image` then gets an empty
#: manifest.
DEAD_REPOSITORY_NAMES = ("experimentation-backend", "experimentation-migrations")

DEPLOYMENT_DOCS = REPO_ROOT / "docs" / "deployment"


@pytest.mark.regression
def test_no_deployment_document_names_a_dead_repository():
    """Every document, and every form -- not one file and one flag.

    The first version of this grepped `--repository-name(s)<space>` in
    `deployment-guide.md` alone. It therefore passed over five live sites:
    two bare `repo:tag` mentions in that same file, an image URI in its
    architecture diagram, a launch-checklist item that could never be ticked,
    and the two rollback-runbook commands above. It also missed the
    `--repository-name=NAME` spelling entirely.

    So: a word-boundary search for the dead names, across every deployment
    document, in any syntax.
    """
    if not DEPLOYMENT_DOCS.is_dir():
        pytest.skip("this tree has no docs/deployment")

    live = _repository_name()
    offenders = []
    for doc in sorted(DEPLOYMENT_DOCS.rglob("*.md")):
        for number, line in enumerate(
            doc.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for dead in DEAD_REPOSITORY_NAMES:
                # `experimentation-backend-prod` is the ECS service and task
                # family, a different thing that legitimately starts the same
                # way; the boundary is what separates them.
                if re.search(rf"\b{re.escape(dead)}\b(?![-/])", line):
                    offenders.append(
                        f"{doc.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
                    )
    assert not offenders, (
        f"these name a repository nothing pushes to or reads (it is {live!r}):\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


@pytest.mark.regression
def test_the_deployment_guide_tells_you_to_create_the_right_one():
    """And the positive half: the guide must still say how to create it.

    Nothing in the CDK does, so the guide is the only instruction there is --
    which is exactly the position that made #211 fatal rather than untidy.
    """
    guide = DEPLOYMENT_DOCS / "deployment-guide.md"
    if not guide.is_file():
        pytest.skip("this tree has no deployment guide")

    text = guide.read_text(encoding="utf-8")
    assert "aws ecr create-repository" in text, (
        "the guide no longer tells an operator to create the repository, and "
        "no CDK stack creates it either -- so nothing does"
    )
    assert _repository_name() in text, f"the guide never names {_repository_name()!r}"
