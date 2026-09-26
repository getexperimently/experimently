"""Deploy, Rollback and Database Migration: one path for staging and prod.

Static reads of the three workflows that act on AWS (`deploy.yml`,
`rollback.yml`, `db-migrate.yml`) and the composite action they share. None of
them has ever run against AWS from this repository, and none can run in CI
without an account -- so the properties the Stream B plan signed off on are
pinned here, each with the defect it exists to catch:

* one vocabulary, ``staging|prod``, as a closed choice, and no literal
  environment name anywhere else (D6, QA 4a);
* the account variable read only inside the environment-bound job's first
  step, never in a job-level ``if:`` or a workflow ``env:`` (PE v1 C9);
* no ``${{ }}`` interpolation inside any ``run:`` (PE v1 C11);
* tooling from the dispatch ref, which must be main; the release checked out
  into ``./release`` for the build only (PE v1 C6);
* a secret-free preflight and ONE environment-bound deploy job whose refusals
  all come before its first AWS mutation;
* the image pushed once as ``:<tag>-<profile>``, labelled with the commit
  actually built, and named by digest in every task definition registered
  (#71, #70, #138, QA 1c/2/10/11);
* no forward-deploy wait that can roll back a successful deployment (#143;
  the forward loop itself is B3b);
* the smoke test a real request through the public origin, inside the deploy
  job, with nothing installed (#144, PE v2 C10).

Unlike the older workflow tests these do NOT skip when a file is missing: a
tree that ships `.github/workflows` must ship these three, so a rename fails
here rather than turning into green skips (QA 4d).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACTIONS = REPO_ROOT / ".github" / "actions"
DEPLOY = WORKFLOWS / "deploy.yml"
ROLLBACK = WORKFLOWS / "rollback.yml"
DB_MIGRATE = WORKFLOWS / "db-migrate.yml"
AWS_WORKFLOWS = (DEPLOY, ROLLBACK, DB_MIGRATE)
IDS = [p.name for p in AWS_WORKFLOWS]

pytestmark = pytest.mark.skipif(
    not WORKFLOWS.is_dir(), reason="this tree has no .github/workflows"
)

TAG_PATTERN = r"^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$"


def _load(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is missing"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML parses the bare `on:` key as the boolean True.
    document["on"] = document.pop(True, document.get("on"))
    return document


def _jobs(path: Path) -> dict[str, dict[str, Any]]:
    return _load(path)["jobs"]


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job.get("steps", [])


def _all_steps(path: Path) -> Iterator[tuple[str, int, dict[str, Any]]]:
    for name, job in _jobs(path).items():
        for index, step in enumerate(_steps(job)):
            yield name, index, step


def _code(script: str) -> str:
    """A `run:` script without its shell comment lines."""
    return "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )


def _runs(path: Path) -> list[str]:
    return [
        _code(step["run"])
        for _, _, step in _all_steps(path)
        if isinstance(step.get("run"), str)
    ]


def _environment_jobs(path: Path) -> dict[str, dict[str, Any]]:
    return {n: j for n, j in _jobs(path).items() if "environment" in j}


def _step_index(steps: list[dict[str, Any]], predicate) -> list[int]:
    return [i for i, s in enumerate(steps) if predicate(s)]


def _run_of(step: dict[str, Any]) -> str:
    return _code(step["run"]) if isinstance(step.get("run"), str) else ""


# --- one vocabulary (D6, QA 4a) -----------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=IDS)
def test_the_environment_is_a_closed_choice_of_staging_and_prod(path):
    inputs = _load(path)["on"]["workflow_dispatch"]["inputs"]
    environment = inputs.get("environment")
    assert environment, f"{path.name} takes no environment input"
    assert environment["type"] == "choice", (
        "a free-text environment auto-creates an unprotected GitHub environment "
        "on a typo (QA SILENT 7)"
    )
    assert environment["options"] == ["staging", "prod"]
    assert environment["default"] == "staging"


def _strings(node: Any, path: tuple = ()) -> Iterator[tuple[tuple, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, path + (index,))
    elif isinstance(node, str):
        yield path, _code(node) if path and path[-1] == "run" else node


_ENVIRONMENT_WORDS = re.compile(r"\bprod(uction)?\b|PROD_|\bstaging\b", re.I)


@pytest.mark.regression
@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=IDS)
def test_no_environment_is_named_outside_the_choice_list(path):
    """Every AWS name is built from the input, never spelled for one environment.

    `experimentation-prod` (a cluster nothing created), `/prod/experimentation`,
    `PROD_AWS_ROLE_ARN` and `environment: production` were each a literal that
    made the staging rehearsal (D6) impossible.
    """
    document = _load(path)
    options = ("on", "workflow_dispatch", "inputs", "environment")
    offenders = [
        f"{'.'.join(map(str, where))}: {line.strip()}"
        for where, text in _strings(document)
        if where[: len(options)] != options
        for line in text.splitlines()
        if _ENVIRONMENT_WORDS.search(line)
    ]
    assert not offenders, (
        f"{path.name} names an environment outside its choice list:\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


# --- where the account variable is read (PE v1 C9) --------------------------


@pytest.mark.regression
@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=IDS)
def test_the_account_variable_is_read_only_in_the_first_step(path):
    """An environment-scoped variable is invisible to a job-level `if:`.

    The old `if: ... && vars.AWS_ACCOUNT_ID != ''` therefore skipped every job
    green for an environment configured the recommended way. The only read is
    the first step of the environment-bound job, which fails loudly.
    """
    document = _load(path)
    text = path.read_text(encoding="utf-8")
    assert "vars.AWS_ACCOUNT_ID" not in yaml.dump(document.get("env", {}))
    for name, job in document["jobs"].items():
        assert "vars." not in str(job.get("if", "")), f"job {name} has an if: on vars"
        assert "vars.AWS_ACCOUNT_ID" not in yaml.dump(job.get("env", {})), name

    (bound,) = _environment_jobs(path).values()
    first = _steps(bound)[0]
    reads = [
        (name, index)
        for name, index, step in _all_steps(path)
        if "vars.AWS_ACCOUNT_ID" in yaml.dump(step)
    ]
    assert reads == [(next(iter(_environment_jobs(path))), 0)], reads
    expressions = re.findall(r"\$\{\{[^}]*\bvars\.AWS_ACCOUNT_ID\b[^}]*\}\}", text)
    assert expressions == ["${{ vars.AWS_ACCOUNT_ID }}"], (
        f"vars.AWS_ACCOUNT_ID is read {len(expressions)} times; only the first "
        "step's env may read it"
    )
    assert "exit 1" in first["run"] and "Not configured" in first["run"]
    assert (
        "vars.AWS_ACCOUNT_ID is not set for the '${TARGET_ENV}' environment, so "
        "nothing was" in first["run"]
    )
    assert "Settings → Environments → ${TARGET_ENV} → Variables" in first["run"]


@pytest.mark.regression
@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=IDS)
def test_no_repository_name_decides_whether_it_runs(path):
    """The account variable is the opt-in; hard-coded repository names are gone."""
    text = path.read_text(encoding="utf-8")
    assert "github.repository ==" not in text
    assert "amarkanday/experimentation-platform" not in text


# --- injection (PE v1 C11) ---------------------------------------------------


def _run_scripts(path: Path) -> Iterator[tuple[str, str]]:
    for job, index, step in _all_steps(path):
        if isinstance(step.get("run"), str):
            yield f"{job}[{index}] {step.get('name', '')}", step["run"]


def _offenders(scripts: list[tuple[str, str]]) -> list[str]:
    return [
        f"{where}: {line.strip()}"
        for where, script in scripts
        for line in script.splitlines()
        if "${{" in line
    ]


@pytest.mark.regression
@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=IDS)
def test_nothing_is_interpolated_into_a_shell_script(path):
    """`${{ }}` inside `run:` is substituted before bash parses the line.

    `${{ inputs.target }}` in db-migrate.yml was operator text spliced into a
    shell script in a job holding the environment's AWS role. Values reach a
    script through `env:`. Stricter than `inputs.*` alone: a step output is
    just as able to carry a quote.
    """
    scripts = list(_run_scripts(path))
    assert scripts, f"{path.name} has no run: steps, so this checked nothing"
    offenders = _offenders(scripts)
    assert not offenders, (
        f"{path.name} interpolates an expression into a shell script; pass it "
        "through env: instead:\n" + "\n".join(f"  {o}" for o in offenders)
    )


#: Every composite action in the repository, by directory. Exact: a new action
#: fails here until it is looked at, and the test below covers it by glob.
COMPOSITE_ACTIONS = ["licence-environment", "stack-outputs"]
_ACTION_FILES = sorted(ACTIONS.glob("*/action.yml"))


def test_the_composite_actions_are_exactly_these():
    assert [p.parent.name for p in _ACTION_FILES] == COMPOSITE_ACTIONS


@pytest.mark.regression
@pytest.mark.parametrize(
    "path", _ACTION_FILES, ids=[p.parent.name for p in _ACTION_FILES]
)
def test_no_composite_action_interpolates_into_run(path):
    """The same rule for every composite action, found by glob.

    A composite action's `${{ inputs.* }}` is its caller's value -- for
    stack-outputs, a job holding the environment's AWS role -- and is
    substituted into `run:` before bash parses it just the same.
    """
    steps = yaml.safe_load(path.read_text())["runs"]["steps"]
    scripts = [(s.get("id", s.get("name", "?")), s["run"]) for s in steps if "run" in s]
    assert scripts, f"{path.parent.name} has no run: steps, so this checked nothing"
    offenders = _offenders(scripts)
    assert not offenders, (
        f"{path.parent.name}/action.yml interpolates an expression into a shell "
        "script; pass it through env: instead:\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


# --- checkout model (PE v1 C6) -------------------------------------------------


def _is_checkout(step: dict[str, Any]) -> bool:
    return str(step.get("uses", "")).startswith("actions/checkout@")


def _uses_tooling(step: dict[str, Any]) -> bool:
    return str(step.get("uses", "")).startswith("./") or "scripts/" in _run_of(step)


@pytest.mark.regression
@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=IDS)
def test_tooling_comes_from_the_dispatch_ref_and_the_release_only_builds(path):
    """A release tag's own scripts/ and actions are never what runs.

    Local actions resolve from the workspace. Checking the tag out at the root
    and then calling `./.github/actions/...` or `scripts/...` would load the
    TAG's copy -- absent on every tag cut before it existed (PE v1 C6).
    """
    for name, job in _jobs(path).items():
        steps = _steps(job)
        release_paths = set()
        tooling_checkout = None
        for index, step in enumerate(steps):
            with_ = step.get("with", {}) or {}
            if _is_checkout(step):
                if "ref" in with_:
                    target = str(with_.get("path", "")).strip("./")
                    assert target, (
                        f"{path.name} {name}: a checkout with ref: "
                        f"{with_['ref']} lands in the workspace root, where the "
                        "tooling is loaded from"
                    )
                    release_paths.add(target)
                elif not with_.get("path") and tooling_checkout is None:
                    tooling_checkout = index
            if _uses_tooling(step):
                assert tooling_checkout is not None and tooling_checkout < index, (
                    f"{path.name} {name}[{index}] {step.get('name')!r} uses tooling "
                    "before the dispatch ref is checked out at the root"
                )
                uses = str(step.get("uses", ""))
                code = _run_of(step)
                for release in release_paths:
                    assert not uses.startswith(f"./{release}/"), uses
                    assert f"{release}/scripts" not in code, code
                    assert f"{release}/.github" not in code, code
                assert str(step.get("working-directory", "")).strip("./") not in (
                    release_paths
                ), f"{step.get('name')} runs tooling from inside the release"


@pytest.mark.regression
@pytest.mark.parametrize("path", AWS_WORKFLOWS, ids=IDS)
def test_a_dispatch_from_any_ref_but_main_is_refused(path):
    """The dispatch ref IS the tooling, so it must be main (UX copy)."""
    refusals = [
        (job, index, step)
        for job, index, step in _all_steps(path)
        if '"$REF" != "refs/heads/main"' in _run_of(step)
    ]
    assert refusals, f"{path.name} runs from whatever ref it is dispatched on"
    job, index, step = refusals[0]
    assert step["env"]["REF"] == "${{ github.ref }}"
    assert (
        'Run this workflow from main (\\"Use workflow from\\"); you chose ${REF_NAME}.'
        in (step["run"])
    )
    # Before any tooling runs in that job.
    steps = _steps(_jobs(path)[job])
    assert not [s for s in steps[:index] if _uses_tooling(s)]


# --- deploy.yml: preflight, then one approval, refusals first ------------------


def _deploy_job() -> dict[str, Any]:
    (job,) = _environment_jobs(DEPLOY).values()
    return job


@pytest.mark.regression
def test_one_environment_bound_job_per_workflow():
    """Each environment-bound job asks its own approval; a deploy asks once."""
    for path in AWS_WORKFLOWS:
        bound = _environment_jobs(path)
        assert len(bound) == 1, f"{path.name}: {sorted(bound)}"
        ((bound_name, job),) = bound.items()
        assert job["environment"] == "${{ inputs.environment }}"
        for name, other in _jobs(path).items():
            if name == bound_name:
                continue
            text = yaml.dump(other)
            assert "configure-aws-credentials" not in text, (
                f"{path.name} job {name} assumes a role without the environment "
                "(and its approval)"
            )


@pytest.mark.regression
def test_the_preflight_holds_no_secret_and_checks_the_release():
    jobs = _jobs(DEPLOY)
    preflight = jobs["preflight"]
    text = yaml.dump(preflight)
    assert "environment" not in preflight
    assert "secrets." not in text and "vars." not in text
    assert "configure-aws-credentials" not in text
    assert preflight.get("permissions", {}).get("id-token") in (None, "none")
    assert "preflight" in str(_deploy_job()["needs"])

    runs = "\n".join(_run_of(s) for s in _steps(preflight))
    assert TAG_PATTERN in runs, "the tag shape is not the signed-off pattern"
    assert "refs/tags/${VERSION}^{commit}" in runs, "the tag's existence is not checked"
    assert 'git merge-base --is-ancestor "$SHA" HEAD' in runs, "ancestry of main"
    assert "bash scripts/verify_release_gate.sh" in runs
    assert (
        "is not a tag in this repository. Deploy a release tag (git tag --list "
        "'v*'); branch names and commit SHAs are refused." in runs
    )


@pytest.mark.parametrize(
    "version, valid",
    [
        ("v1.2.3", True),
        ("v0.3.0", True),
        ("v1.2.3-rc.1", True),
        ("1.2.3", False),
        ("v1.2", False),
        ("main", False),
        ("0123456789abcdef0123456789abcdef01234567", False),
        ("v1.2.3;id", False),
        ("v1.2.3\n", False),
    ],
)
def test_the_tag_pattern(version, valid):
    assert bool(re.fullmatch(TAG_PATTERN[1:-1], version)) is valid


#: What changes AWS. The first of these ends the read-only part of the job.
MUTATIONS = (
    "docker push",
    "create-db-cluster-snapshot",
    "register_task_definition.sh",
    "register-task-definition",
    "run_migration_task.sh",
    "run-task",
    "create-deployment",
    "continue-deployment",
    "stop-deployment",
)
#: The refusals, each a read.
REFUSALS = {
    "not configured": "Not configured",
    "wrong account": "sts get-caller-identity",
    "cluster missing": "aws ecs describe-clusters",
    "profile vs task definition": "injects no AUDIT_HMAC_KEY",
    "missing secrets": "aws secretsmanager describe-secret",
    "ECR repository": "aws ecr describe-repositories",
}


@pytest.mark.regression
def test_every_refusal_comes_before_the_first_aws_mutation():
    steps = _steps(_deploy_job())
    first_mutation = min(
        i for i, s in enumerate(steps) if any(m in _run_of(s) for m in MUTATIONS)
    )
    for what, marker in REFUSALS.items():
        (index,) = [i for i, s in enumerate(steps) if marker in _run_of(s)]
        assert index < first_mutation, (
            f"the {what} refusal runs at step {index}, after the first AWS "
            f"change at step {first_mutation}"
        )
    # The stack outputs are read (and refused) before anything changes too.
    outputs = _step_index(steps, lambda s: "stack-outputs" in str(s.get("uses", "")))
    assert len(outputs) == 2 and max(outputs) < first_mutation


@pytest.mark.regression
def test_the_refusals_say_what_to_do():
    """UX section A, verbatim where it was specified."""
    runs = "\n".join(_run_of(s) for s in _steps(_deploy_job()))
    for copy in (
        "::error title=Wrong AWS account::environment=${TARGET_ENV} expects account "
        "${EXPECTED_ACCOUNT_ID}; the assumed role is in ${actual}. Nothing has been "
        "built or changed.",
        "::error::No ECS cluster ${ECS_CLUSTER} in ${AWS_REGION} (account "
        "${EXPECTED_ACCOUNT_ID}). Run ENVIRONMENT=${TARGET_ENV} cdk deploy --all in "
        "this account and region first: docs/self-hosting/cdk.md",
        "::error::profile=full, but task definition ${family} injects no "
        "AUDIT_HMAC_KEY: the stacks were deployed as core. Deploy profile=core, or "
        "redeploy the stacks from a full checkout.",
        "the assumed role is in",
    ):
        assert copy in runs, copy
    # The account check compares with the variable read in the first step.
    assert "aws sts get-caller-identity --query Account" in runs
    assert '"$actual" != "$EXPECTED_ACCOUNT_ID"' in runs


@pytest.mark.regression
def test_the_required_secrets_are_this_environments():
    runs = "\n".join(_run_of(s) for s in _steps(_deploy_job()))
    assert '--secret-id "${SECRETS_PREFIX}/${name}"' in runs
    assert _deploy_job()["env"]["SECRETS_PREFIX"] == (
        "/${{ inputs.environment }}/experimentation"
    )


@pytest.mark.regression
def test_the_fake_checks_are_gone():
    text = DEPLOY.read_text(encoding="utf-8")
    assert "Check no active incidents" not in text
    assert '"NONE"' not in "\n".join(_runs(DEPLOY)), (
        'the backup check compared the CLI\'s `None` with "NONE" and so never '
        "snapshotted (QA SILENT 5)"
    )


# --- image identity (#71, #70, #138) ------------------------------------------


def _image_step() -> dict[str, Any]:
    (step,) = [s for s in _steps(_deploy_job()) if s.get("id") == "image"]
    return step


@pytest.mark.regression
def test_the_image_is_pushed_once_as_tag_and_profile():
    """No `:latest`, no bare `:<tag>` (#71): one tag per release and profile."""
    code = _run_of(_image_step())
    assert 'IMAGE_TAG="${VERSION}-${PROFILE}"' in code
    assert 'REF="$ECR_REGISTRY/$ECR_BACKEND_REPO:$IMAGE_TAG"' in code
    pushes = [ln.strip() for ln in code.splitlines() if "docker push" in ln]
    assert pushes == ['docker push "$REF"'], pushes
    tags = re.findall(r"^\s*-t\s+(\S+)", code, re.M)
    assert tags == ['"$REF"'], tags
    for path in AWS_WORKFLOWS:
        for script in _runs(path):
            assert ":latest" not in script, f"{path.name} pushes or names :latest"


@pytest.mark.regression
def test_an_existing_tag_is_reused_not_rebuilt():
    code = _run_of(_image_step())
    assert "aws ecr describe-images" in code and "ImageNotFoundException" in code
    assert 'if [ -n "$digest" ]; then' in code


@pytest.mark.regression
def test_the_image_is_built_from_the_release_and_labelled_with_its_commit():
    """#70: the label named the dispatch ref (`github.sha`), not the build."""
    text = DEPLOY.read_text(encoding="utf-8")
    assert "github.sha" not in text
    code = _run_of(_image_step())
    assert 'RELEASE_COMMIT="$(git -C release rev-parse HEAD)"' in code
    assert '--build-arg GIT_COMMIT="$RELEASE_COMMIT"' in code
    assert "-f release/backend/Dockerfile" in code
    assert re.search(r"^\s*release\s*$", code, re.M), (
        "the build context is not ./release"
    )
    assert "org.opencontainers.image.revision" in code
    assert '"$revision" != "$RELEASE_COMMIT"' in code
    assert "io.experimently.profile" in code


@pytest.mark.regression
def test_every_task_definition_registered_names_the_digest():
    """QA 2: registration goes through the digest-only script, fed the digest."""
    code = _run_of(_image_step())
    assert 'echo "image=$ECR_REGISTRY/$ECR_BACKEND_REPO@$digest"' in code
    assert "^sha256:[0-9a-f]{64}$" in code
    for path in AWS_WORKFLOWS:
        for script in _runs(path):
            assert "register-task-definition" not in script, (
                f"{path.name} registers a task definition without the "
                "digest-only script"
            )
    registrations = [
        s for s in _steps(_deploy_job()) if "register_task_definition.sh" in _run_of(s)
    ]
    assert len(registrations) == 2
    for step in registrations:
        assert step["env"]["IMAGE"] == "${{ steps.image.outputs.image }}"


@pytest.mark.regression
@pytest.mark.parametrize("path", [DEPLOY, DB_MIGRATE], ids=["deploy", "db-migrate"])
def test_the_migration_runs_the_revision_it_registered(path):
    """QA 1c: run-task names the ARN a preceding step registered, never a family."""
    (job,) = _environment_jobs(path).values()
    steps = _steps(job)
    for script in _runs(path):
        assert "aws ecs run-task" not in script, "run-task outside the script"
    runners = [s for s in steps if "run_migration_task.sh" in _run_of(s)]
    assert runners
    (registration,) = [
        i
        for i, s in enumerate(steps)
        if "register_task_definition.sh" in _run_of(s)
        and "$MIGRATE_TASK_FAMILY" in _run_of(s)
    ]
    step_id = steps[registration]["id"]
    for runner in runners:
        assert steps.index(runner) > registration
        assert runner["env"]["TASK_DEFINITION"] == (
            f"${{{{ steps.{step_id}.outputs.arn }}}}"
        )
    assert job["env"]["MIGRATE_TASK_FAMILY"] == (
        "experimentation-migrate-${{ inputs.environment }}"
    )


@pytest.mark.regression
def test_the_snapshot_is_taken_before_the_migration_from_the_stack_output():
    steps = _steps(_deploy_job())
    (snapshot,) = _step_index(
        steps, lambda s: "create-db-cluster-snapshot" in _run_of(s)
    )
    (migration,) = _step_index(steps, lambda s: "run_migration_task.sh" in _run_of(s))
    assert snapshot < migration
    assert steps[snapshot]["env"]["DB_CLUSTER"] == (
        "${{ fromJSON(steps.database.outputs.json).ClusterIdentifier }}"
    )
    assert "db-cluster-snapshot-available" in _run_of(steps[snapshot])


@pytest.mark.regression
@pytest.mark.parametrize("path", [DEPLOY, DB_MIGRATE], ids=["deploy", "db-migrate"])
def test_the_network_comes_from_the_stack_outputs(path):
    """Not `PROD_PRIVATE_SUBNET_IDS` secrets, which db-migrate read under other names."""
    text = path.read_text(encoding="utf-8")
    assert "SUBNET_IDS" not in text and "ECS_SG_ID" not in text
    assert "fromJSON(steps.fargate.outputs.json).TaskSubnets" in text
    assert "fromJSON(steps.fargate.outputs.json).TaskSecurityGroup" in text


# --- CodeDeploy in B3a: nothing that rolls a success back (#143) ----------------


@pytest.mark.regression
def test_the_forward_deploy_cannot_roll_back_a_successful_deployment():
    """The waiter accepts only Succeeded, an hour after the shift; on its
    timeout the old step stopped the deployment with auto-rollback -- rolling
    back a deployment that had succeeded (#143).
    """
    code = "\n".join(_runs(DEPLOY))
    assert "wait deployment-successful" not in code
    assert "stop-deployment" not in code
    assert "timeout 1200" not in code


@pytest.mark.regression
def test_the_traffic_shift_is_an_explicit_placeholder_until_b3b():
    steps = _steps(_deploy_job())
    (create,) = _step_index(steps, lambda s: "create-deployment" in _run_of(s))
    placeholder = steps[create + 1]
    assert "#143" in placeholder["name"]
    assert "exit 1" in _run_of(placeholder)
    assert "does not approve the traffic shift yet: #143" in _run_of(placeholder)
    assert "continue-deployment" not in "\n".join(_runs(DEPLOY))


# --- smoke (#144, PE v2 C10) ---------------------------------------------------


def _smoke() -> tuple[int, dict[str, Any]]:
    steps = _steps(_deploy_job())
    (index,) = _step_index(steps, lambda s: "/api/v1/experiments/" in _run_of(s))
    return index, steps[index]


@pytest.mark.regression
def test_the_smoke_test_is_a_real_request_through_the_public_origin():
    _, step = _smoke()
    code = _run_of(step)
    assert step["env"]["PUBLIC_BASE_URL"] == "${{ vars.PUBLIC_BASE_URL }}"
    assert 'url="${PUBLIC_BASE_URL%/}/api/v1/experiments/"' in code, (
        "the trailing slash matters: without it the API answers 307"
    )
    assert 'expected=\'{"detail":"Not authenticated"}\'' in code
    assert '[ "$code" = "401" ] && [ "$body" = "$expected" ]' in code
    assert "curl " in code


@pytest.mark.regression
def test_an_empty_smoke_url_fails_naming_the_environment():
    _, step = _smoke()
    code = _run_of(step)
    guard = code.index('if [ -z "$PUBLIC_BASE_URL" ]; then')
    assert "exit 1" in code[guard : guard + 300]
    assert "'${TARGET_ENV}' environment" in code[guard : guard + 300]


@pytest.mark.regression
def test_the_smoke_runs_in_the_deploy_job_and_installs_nothing():
    """The pytest smoke job could not collect (#144); nothing is installed on
    a host holding the environment's role."""
    jobs = _jobs(DEPLOY)
    assert set(jobs) == {"preflight", "deploy"}, sorted(jobs)
    text = DEPLOY.read_text(encoding="utf-8")
    assert "backend/tests/smoke" not in text
    for script in _runs(DEPLOY):
        for installer in ("pip install", "apt-get", "npm ", "setup-python"):
            assert installer not in script, installer
    index, _ = _smoke()
    steps = _steps(_deploy_job())
    (create,) = _step_index(steps, lambda s: "create-deployment" in _run_of(s))
    assert index > create


# --- db-migrate.yml -----------------------------------------------------------


@pytest.mark.regression
def test_db_migrate_runs_the_serving_image_and_refuses_when_there_is_none():
    (job,) = _environment_jobs(DB_MIGRATE).values()
    steps = _steps(job)
    (serving,) = [s for s in steps if s.get("id") == "serving"]
    code = _run_of(serving)
    assert "taskSets[?status=='PRIMARY'].taskDefinition" in code
    # The refusal itself: an error, followed at once by a failing exit.
    assert re.search(
        r'echo "::error::No release is serving[^\n]*\n\s*exit 1\n', code
    ), "db-migrate does not refuse when nothing is serving"
    (registration,) = [s for s in steps if "register_task_definition.sh" in _run_of(s)]
    assert registration["env"]["IMAGE"] == "${{ steps.serving.outputs.image }}"


@pytest.mark.regression
def test_db_migrate_refuses_the_singular_head():
    (job,) = _environment_jobs(DB_MIGRATE).values()
    code = "\n".join(_run_of(s) for s in _steps(job))
    assert 'if [ "$TARGET" = "head" ]; then' in code


# --- concurrency and the run summary ------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "path, group",
    [
        (DEPLOY, "deploy-${{ inputs.environment }}"),
        (DB_MIGRATE, "deploy-${{ inputs.environment }}"),
        (ROLLBACK, "rollback-${{ inputs.environment }}"),
    ],
    ids=IDS,
)
def test_concurrency_is_per_environment_and_never_cancels(path, group):
    concurrency = _load(path)["concurrency"]
    assert concurrency["group"] == group
    assert concurrency["cancel-in-progress"] is False


@pytest.mark.regression
def test_the_summary_hands_over_the_rollback_line():
    steps = _steps(_deploy_job())
    (summary,) = [s for s in steps if s.get("name") == "Run summary"]
    assert summary["if"] == "always()"
    code = _run_of(summary)
    assert "GITHUB_STEP_SUMMARY" in code
    assert (
        "Rollback: Actions → Rollback → environment=${TARGET_ENV}, "
        "task_definition_arn=${PREVIOUS##*/}" in code
    )
    for field in (
        "Account / region",
        "Release",
        "Profile",
        "Image",
        "Migration",
        "New API revision",
        "Serving before this run",
    ):
        assert f"| {field} |" in code, field
    (previous,) = [s for s in steps if s.get("id") == "previous"]
    assert "taskSets[?status=='PRIMARY'].taskDefinition" in _run_of(previous)
    assert summary["env"]["PREVIOUS"] == "${{ steps.previous.outputs.arn }}"


@pytest.mark.regression
def test_rollback_refuses_the_other_environments_revision():
    code = "\n".join(_runs(ROLLBACK))
    assert (
        "You chose environment=${TARGET_ENV} but ${ARN##*/} is a ${other} "
        "revision. Re-run with environment=${other}." in code
    )


@pytest.mark.regression
def test_one_region():
    regions = {_load(path)["env"]["AWS_REGION"] for path in AWS_WORKFLOWS}
    assert len(regions) == 1, regions
    for path in AWS_WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert "aws-region: ${{ env.AWS_REGION }}" in text
        assert "aws-region: us-" not in text
