"""The production migration path must name a file that exists in the image.

``MigrationTaskStack`` bakes the command the one-off ECS migration task runs,
and two workflows override it with the same command by hand.  All three used to
say ``-c app/db/alembic.ini``, which resolves to ``/app/app/db/alembic.ini``
(``backend/Dockerfile`` sets ``WORKDIR /app`` and copies the repository layout
under it) and does not exist -- and the stack also said the singular ``upgrade
head``, which alembic refuses outright on a full-profile image because the
``modules`` branch gives it two heads.  Nothing executed any of it before a
deploy, so the whole production migration path was dead.

The command is only half of it: ``command=`` on ``add_container`` sets the
container's **CMD**, and the image's ``ENTRYPOINT`` still runs first.  That
entry point bootstraps the schema (prune + ``upgrade heads`` + reconcile +
``ensure_first_superuser``) before it ``exec``s the command, so
``db-migrate.yml``'s ``downgrade`` override upgraded to heads and then undid
exactly that -- and, with no ``POSTGRES_SERVER`` in the task definition, it
spent ``DB_WAIT_TIMEOUT`` seconds waiting for a database on localhost first.
So the environment is checked here too.

These are cheap text checks on purpose: they need neither ``aws-cdk-lib`` (the
stack is read with :mod:`ast`, not imported) nor Docker nor AWS, so they run in
the ordinary unit job and fail the moment the three copies drift apart again.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
STACK = REPO_ROOT / "infrastructure" / "cdk" / "stacks" / "migration_task_stack.py"
CDK_APP = REPO_ROOT / "infrastructure" / "cdk" / "app.py"
ENTRYPOINT = REPO_ROOT / "backend" / "docker-entrypoint.sh"
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
WORKFLOWS = (
    REPO_ROOT / ".github" / "workflows" / "db-migrate.yml",
    REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml",
)

#: A distribution that ships neither the CDK stacks nor the workflows has
#: nothing here to check; one that ships them must keep them in agreement.
pytestmark = pytest.mark.skipif(
    not STACK.is_file(), reason="this tree has no infrastructure/cdk"
)


class _ResolveNames(ast.NodeTransformer):
    """Replace references to constants already read with their value."""

    def __init__(self, known: dict[str, object]) -> None:
        self.known = known

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.known:
            return ast.copy_location(ast.Constant(self.known[node.id]), node)
        return node


def _stack_constants() -> dict[str, object]:
    """Module-level literal assignments of the CDK stack, without importing it.

    Read rather than imported so the check does not need ``aws-cdk-lib``.
    Constants that refer to earlier ones (MIGRATION_COMMAND holds
    ALEMBIC_CONFIG) are resolved as they are read, top to bottom.
    """
    tree = ast.parse(STACK.read_text())
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                resolved = _ResolveNames(values).visit(
                    ast.parse(ast.unparse(node.value), mode="eval")
                )
                values[target.id] = ast.literal_eval(resolved)
            except (ValueError, SyntaxError):
                pass
    return values


def _add_container_call() -> ast.Call:
    """The stack's single ``...add_container(...)`` call, as AST."""
    for node in ast.walk(ast.parse(STACK.read_text())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_container"
        ):
            return node
    raise AssertionError(f"no add_container(...) call in {STACK.name}")


def _keyword(name: str) -> ast.AST:
    for keyword in _add_container_call().keywords:
        if keyword.arg == name:
            return keyword.value
    raise AssertionError(f"add_container(...) has no {name}= argument")


def _declared_names(kwarg: str) -> set[str]:
    """Every literal string key under ``kwarg``, nested dicts included.

    ``environment=`` and ``secrets=`` both hold entries behind a ``**{...} if
    ... else {}``, which is not a literal, so the dicts are walked rather than
    evaluated.
    """
    return {
        key.value
        for mapping in ast.walk(_keyword(kwarg))
        if isinstance(mapping, ast.Dict)
        for key in mapping.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _literal_environment() -> dict[str, str]:
    """The ``environment=`` entries whose key *and* value are literals."""
    mapping = _keyword("environment")
    return {
        key.value: value.value
        for key, value in zip(mapping.keys, mapping.values)
        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
    }


def _workflow_alembic_commands(path: Path) -> list[list[str]]:
    """Every ``["python","-m","alembic",...]`` array in a workflow file."""
    text = path.read_text().replace('\\"', '"')
    return [
        json.loads(match)
        for match in re.findall(r'\["python","-m","alembic".*?\]', text)
    ]


@pytest.mark.unit
@pytest.mark.regression
def test_migration_command_config_exists_in_the_image_layout():
    constants = _stack_constants()
    config = constants["ALEMBIC_CONFIG"]
    workdir = constants["IMAGE_WORKDIR"]

    dockerfile = DOCKERFILE.read_text()
    # The layout the path is relative to: WORKDIR, and the repository copied
    # under it unchanged.  If either moves, this path has to move with it.
    assert re.search(rf"^WORKDIR {re.escape(str(workdir))}$", dockerfile, re.M)
    assert f"COPY --chown=appuser:appgroup backend/ {workdir}/backend/" in dockerfile

    assert (REPO_ROOT / str(config)).is_file(), (
        f"{config} is what the migration task passes to `alembic -c`; inside "
        f"the image that is {workdir}/{config}, and the image mirrors the "
        "repository, so it must exist here too"
    )


@pytest.mark.unit
@pytest.mark.regression
def test_migration_command_is_the_plural_heads():
    constants = _stack_constants()
    command = list(constants["MIGRATION_COMMAND"])

    assert command == [
        "python",
        "-m",
        "alembic",
        "-c",
        constants["ALEMBIC_CONFIG"],
        "upgrade",
        "heads",
    ]
    # `upgrade head` fails on a full-profile image: two heads are present.
    assert command[-1] != "head"


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_overrides_match_the_task_definition(workflow: Path):
    if not workflow.parent.is_dir():
        pytest.skip("this tree ships no GitHub workflows")
    config = _stack_constants()["ALEMBIC_CONFIG"]
    commands = _workflow_alembic_commands(workflow)
    assert commands, f"no alembic command found in {workflow.name}"

    for command in commands:
        assert "-c" in command, command
        assert command[command.index("-c") + 1] == config, command
        assert "head" not in command, (
            f"{workflow.name} passes the singular 'head'; a full-profile image "
            "has two heads and alembic refuses it"
        )


@pytest.mark.unit
@pytest.mark.regression
def test_the_task_does_not_run_the_entry_points_bootstrap_first():
    """`command=` is the CMD; the image ENTRYPOINT runs before it.

    backend/docker-entrypoint.sh bootstraps the schema whenever RUN_MIGRATIONS
    is not "false", so every run of this task did an `upgrade heads` before it
    reached the command it was given -- and db-migrate.yml's `downgrade
    <target>` override therefore re-applied exactly what it had been asked to
    undo.
    """
    # The image really does gate its bootstrap on this variable, and really
    # does run before the command: if either stops being true, the environment
    # below stops being the fix.
    entrypoint = ENTRYPOINT.read_text()
    assert ': "${RUN_MIGRATIONS:=true}"' in entrypoint
    assert 'if [ "$RUN_MIGRATIONS" = "true" ]; then' in entrypoint
    assert 'exec "$@"' in entrypoint
    assert 'ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]' in DOCKERFILE.read_text()

    environment = _literal_environment()
    assert environment.get("RUN_MIGRATIONS") == "false", (
        "the migration task must run ONE alembic command -- the one in "
        f"MIGRATION_COMMAND, or a workflow's override of it. Got: {environment}"
    )
    # Same reasoning for the seeds: a migration task is not a seeding task.
    assert environment.get("SEED") == "", environment


@pytest.mark.unit
@pytest.mark.regression
def test_the_task_is_told_where_the_database_is():
    """No POSTGRES_SERVER meant localhost: a 120 s wait, then exit 1.

    `pg_isready -h localhost` inside a Fargate task can never succeed, so the
    entry point hit DB_WAIT_TIMEOUT and the task failed before alembic ran at
    all; had it got past that, alembic's own URL would have pointed at the same
    place.
    """
    assert "POSTGRES_SERVER" in _declared_names("environment"), (
        "the migration container has no database host"
    )
    # ...and the app hands it the real endpoint rather than a literal.
    assert re.search(r"^\s*db_host=", CDK_APP.read_text(), re.M), (
        "infrastructure/cdk/app.py does not pass db_host= to MigrationTaskStack"
    )
