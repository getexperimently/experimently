"""One container repository, named the same in all three trees (#211).

`docs/deployment/deployment-guide.md` told operators to create
`experimentation-backend` and `experimentation-migrations` before the first
deployment. Nothing used either name. Every producer and consumer says
`experimentation-platform/backend`:

    .github/workflows/deploy.yml        ECR_BACKEND_REPO
    infrastructure/cdk/.../fargate_service_stack.py
    infrastructure/cdk/.../migration_task_stack.py

So an operator who followed the guide exactly created two repositories nothing
would ever use, and the first `Deploy to Production` failed at `docker push`
with "name unknown: The repository with name ... does not exist", taking
`run-migrations` and `deploy` with it.

**Nothing in the CDK creates it**, and that is deliberate -- see
`stacks/names.py`. A registry is account-scoped while these stacks are
per-environment, so a fixed name owned by one of them means a second
environment in the same account cannot deploy. It is created once per account
by the command in `docs/deployment/deployment-guide.md` §1.3, which makes that
guide the only instruction there is -- so this file checks that the guide
names the live repository, that the deploy workflow pushes to it, that the
stacks reference it, and that no deployment document still names a dead one.

Since #69 there is a second, `experimentation-platform/web`, for the
dashboard's image, imported and created the same way. The stacks, the guide
and the deploy workflow (which pushes both) are each checked against the exact
pair. Only the dashboard's `bootstrap` image, for the first `cdk deploy`, is
pushed by hand (guide section 1.3).

(An earlier version of this docstring said `compute_stack` creates it. That
was true of a version of the change that was reverted for the reason above,
and the sentence survived the revert -- twelve lines above a test docstring
saying the opposite.)
"""

from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

import pytest

from .test_app_profiles import CDK_DIR, _app_environment

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"


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


#: Every repository the stacks import: the backend's and, since #69, the
#: dashboard's. Also read from the CDK. The set is compared EXACTLY -- a third
#: repository, or either one misspelt, is a repository an operator has to
#: create by hand and would not know about.
def _repository_names() -> set[str]:
    import sys

    sys.path.insert(0, str(CDK_DIR))
    try:
        from stacks.names import BACKEND_ECR_REPOSITORY, DASHBOARD_ECR_REPOSITORY

        return {BACKEND_ECR_REPOSITORY, DASHBOARD_ECR_REPOSITORY}
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
                image = container.get("Image")
                # Only OUR registry. A plain string is an external image
                # (`public.ecr.aws/...`, `ghcr.io/...`) and names no
                # repository this project has to create; an `Fn::Join` around
                # `{"Ref": "AWS::URLSuffix"}` is what an imported
                # `ecr.Repository` synthesises to, and is ours.
                if not isinstance(image, dict):
                    continue
                blob = json.dumps(image)
                if "dkr.ecr" not in blob:
                    continue
                for match in re.finditer(r"/([a-z0-9][a-z0-9._/-]*):", blob):
                    names.add(match.group(1))
    return names


@pytest.mark.regression
def test_every_referenced_repository_is_the_one_we_name(assembly):
    """The stacks import repositories by name; exactly the two we name.

    Nothing in the CDK *creates* them, deliberately -- see `stacks/names.py`.
    A registry is account-scoped and these stacks are per-environment, so a
    fixed name owned by one of them means a second environment in the same
    account cannot deploy.

    Exact, in both directions: a name referenced but not in `names.py` is a
    repository nobody is told to create, and a name in `names.py` that nothing
    references is a guide telling operators to create a dead one.
    """
    referenced = _referenced_repositories(assembly)
    assert referenced, (
        "no container image refers to a repository at all, so nothing below "
        "examined anything"
    )
    expected = _repository_names()
    assert referenced == expected, (
        f"referenced but not named in stacks/names.py: "
        f"{sorted(referenced - expected)}; named but referenced by nothing: "
        f"{sorted(expected - referenced)}"
    )


@pytest.mark.skipif(
    not DEPLOY_WORKFLOW.is_file(), reason="this tree has no .github/workflows"
)
@pytest.mark.regression
def test_the_deploy_workflow_pushes_to_that_repository():
    """The half that lives in a different tree, and drifted.

    Compared against `stacks/names.py`, not against a synthesised app: the
    app is synthesised for `dev` and this is the deploy workflow, so
    comparing the two would fail the moment anyone environment-scoped the
    name -- a gate pinning in the defect it was written to prevent.
    """
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^\s*ECR_BACKEND_REPO:\s*(\S+)\s*$", text, re.M)
    assert match, "deploy.yml no longer sets ECR_BACKEND_REPO"
    # Strip a quoted scalar: `ECR_BACKEND_REPO: "experimentation-platform/backend"`
    # is the same YAML value and used to fail with a diff that showed two
    # identical-looking strings.
    pushed = match.group(1).strip().strip("\"'")
    assert pushed == _repository_name(), (
        f"the deploy workflow pushes to {pushed!r}, but the CDK names "
        f"{_repository_name()!r}"
    )
    # Every repository the workflow names, exactly the pair the stacks import
    # (#69: it builds and pushes the dashboard's too).
    named = {
        value.strip().strip("\"'")
        for value in re.findall(r"^\s*ECR_[A-Z]+_REPO:\s*(\S+)\s*$", text, re.M)
    }
    assert named == _repository_names(), (
        f"deploy.yml pushes to {sorted(named)}, but the stacks import "
        f"{sorted(_repository_names())}"
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
    docs = sorted(DEPLOYMENT_DOCS.rglob("*.md"))
    assert len(docs) >= 5, (
        f"only {len(docs)} deployment document(s) found -- a renamed directory "
        "or a change of extension would leave this scanning nothing and "
        "passing for ever"
    )
    offenders = []
    for doc in docs:
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


#: `aws ecr create-repository --repository-name <name>`, in either spelling
#: and across a `\`-continued line.
_CREATE_REPOSITORY = re.compile(
    r"aws\s+ecr\s+create-repository\b[\s\\]*(?:--[a-z-]+(?:[= ]\S+)?[\s\\]*)*?"
    r"--repository-name[= ]\s*(\S+)"
)


@pytest.mark.regression
def test_the_guide_creates_the_repository_the_deployment_uses():
    """The positive half, and the one that actually guards #211.

    The first version of this asserted two independent substrings -- that the
    guide contains `aws ecr create-repository` somewhere, and the live name
    somewhere -- which the architecture diagram already satisfied. Changing
    the create command to a third wrong name (`experimentation-platform/api`)
    passed all four tests: the guide told an operator to create a repository
    nothing would ever push to, and the gate said fine.

    A blacklist of names we have already stopped using cannot catch the next
    wrong one. This reads the argument the command actually carries.
    """
    guide = DEPLOYMENT_DOCS / "deployment-guide.md"
    if not guide.is_file():
        pytest.skip("this tree has no deployment guide")

    created = set(_CREATE_REPOSITORY.findall(guide.read_text(encoding="utf-8")))
    assert created, (
        "the guide gives no `aws ecr create-repository` command. Nothing in "
        "the CDK creates the repository either, so nothing would"
    )
    assert created == _repository_names(), (
        f"the guide tells an operator to create {sorted(created)}, but the "
        f"stacks run from {sorted(_repository_names())}"
    )
