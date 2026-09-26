"""The production migration path, which no deploy has ever exercised.

``MigrationTaskStack`` bakes the command the one-off ECS migration task runs,
and ``deploy.yml`` overrides it with the same command by hand.  Three
separate things have been wrong with it, each fatal on its own:

1. ``-c app/db/alembic.ini``, which resolves to ``/app/app/db/alembic.ini``
   (``backend/Dockerfile`` sets ``WORKDIR /app`` and copies the repository
   layout under it) and does not exist.
2. The singular ``upgrade head``, which alembic refuses on a full-profile
   image because the ``modules`` branch gives it two heads.
3. Raw ``alembic upgrade heads`` at all.  The historical chain cannot be
   replayed from an empty database -- rehearsed in the built image against a
   real PostgreSQL, it gets two revisions in and dies with
   ``DuplicateTable: relation "permissions" already exists``.  ``deploy``
   needs ``run-migrations``, so this task runs before anything that would have
   created the schema, and the first production deploy meets exactly that.

Nothing executed any of it before a deploy, so the whole path was dead.

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
ENTRYPOINT = REPO_ROOT / "backend" / "docker-entrypoint.sh"
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
#: The two workflows that run a migration, and they do NOT run the same thing:
#: deploy.yml is the automatic path and must bootstrap, db-migrate is the
#: manual targeted path and must stay on raw alembic. A test each, below.
DEPLOY = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
DB_MIGRATE = REPO_ROOT / ".github" / "workflows" / "db-migrate.yml"

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


def _literal_environment() -> dict[str, str]:
    """The ``environment=`` entries whose key *and* value are literals."""
    mapping = _keyword("environment")
    return {
        key.value: value.value
        for key, value in zip(mapping.keys, mapping.values)
        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
    }


def _workflow_alembic_commands(path: Path) -> list[list[str]]:
    """Every ``["python","-m","alembic",...]`` array in a workflow file.

    Both the JSON literal form and the jq form db-migrate.yml builds its
    operator-driven command with (``["python", "-m", "alembic", ...,
    $direction, $target]``); a jq variable is read as the placeholder
    ``<name>``, since its value is the operator's.
    """
    text = path.read_text().replace('\\"', '"')
    commands = []
    for match in re.findall(r'\["python",\s*"-m",\s*"alembic".*?\]', text):
        literal = re.sub(r"\$([a-z_]+)", r'"<\1>"', match)
        commands.append(json.loads(literal))
    return commands


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
def test_the_migration_task_bootstraps_rather_than_replaying_the_chain():
    """Raw `alembic upgrade heads` cannot build a database from nothing.

    Rehearsed in the built full image against a real PostgreSQL: two revisions
    in, it dies with `psycopg2.errors.DuplicateTable: relation "permissions"
    already exists`, because the historical chain is not replayable from empty
    (which is why `db/bootstrap.py` exists at all).

    `deploy.yml`'s deploy job runs this task before it creates the CodeDeploy
    deployment, so it runs *before* anything that would have created the
    schema -- and the first deployment therefore meets an empty database. Bootstrap handles
    both states: schema from the models plus stamped heads when empty,
    `alembic upgrade heads` when not.
    """
    command = list(_stack_constants()["MIGRATION_COMMAND"])

    assert command == ["python", "-m", "backend.app.db.bootstrap"], command
    # The specific regression: the task must not run alembic directly.
    assert "alembic" not in command, command


@pytest.mark.unit
@pytest.mark.regression
def test_the_deploy_bootstraps_too():
    """The automatic path agrees end to end.

    The override exists rather than inheriting the task definition's command
    because nothing in `deploy.yml` runs `cdk deploy`, so the
    `experimentation-migrate-<env>` revision it registers from can be older
    than this repository. It therefore has to be kept in step by hand, which
    is what this checks.
    """
    workflow = DEPLOY
    if not workflow.parent.is_dir():
        pytest.skip("this tree ships no GitHub workflows")
    command = list(_stack_constants()["MIGRATION_COMMAND"])

    assert json.dumps(command, separators=(",", ":")) in workflow.read_text(), (
        "deploy.yml's containerOverrides must run MIGRATION_COMMAND, "
        f"which is {command}"
    )
    assert not _workflow_alembic_commands(workflow), (
        "deploy.yml still runs alembic directly; the historical chain "
        "cannot be replayed from the empty database a first deploy meets"
    )


@pytest.mark.unit
@pytest.mark.regression
def test_db_migrate_keeps_raw_alembic_and_names_the_right_config():
    """`db-migrate.yml` is the *manual* path and deliberately stays on alembic.

    `current`, and `upgrade`/`downgrade <target>`, are targeted operations on a
    database that already exists; bootstrap cannot express a target. What it
    must not do is drift on the config path or ask for the singular `head`.
    """
    workflow = DB_MIGRATE
    if not workflow.parent.is_dir():
        pytest.skip("this tree ships no GitHub workflows")
    config = _stack_constants()["ALEMBIC_CONFIG"]
    commands = _workflow_alembic_commands(workflow)
    # `current`, and the operator's `<direction> <target>`: if either form
    # stopped being recognised, the checks below would pass on the other alone.
    assert [c[5:] for c in commands] == [["current"], ["<direction>", "<target>"]], (
        commands
    )

    for command in commands:
        assert "-c" in command, command
        assert command[command.index("-c") + 1] == config, command
        assert "head" not in command, (
            "db-migrate.yml passes the singular 'head'; a full-profile image "
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


# Where the database IS -- POSTGRES_SERVER, and the credentials that go with it
# -- used to be checked here by reading this stack's source. That check passed
# with `db_host=None` (the entry was conditional), so it was replaced by
# infrastructure/tests/test_database_wiring.py, which synthesises the staging
# and prod apps and resolves the imported value back to the Aurora writer
# endpoint (#78). It needs aws-cdk-lib, so it runs in the CDK job, not here.
