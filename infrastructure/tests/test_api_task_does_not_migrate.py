"""The API task never writes the schema; the deploy's migration task does (#298).

``backend/docker-entrypoint.sh`` defaults to ``RUN_MIGRATIONS=true``: every
container start runs ``python -m backend.app.db.bootstrap`` before uvicorn.
In ECS that made every API task a schema writer. Worse, the bootstrap of an
older release refuses a database a newer release has migrated, so once a
Deploy's migration task had run, any task started from an older revision -- a
replacement, a scale-out, a rollback -- exited 1 instead of serving.

The API task definition therefore sets ``RUN_MIGRATIONS=false`` and ``SEED=``
(empty), and the only thing that writes the schema is the migration task
``deploy.yml`` runs before CodeDeploy (``stacks/migration_task_stack.py``).

The values are pinned EXACTLY. The entry point happens to compare against
``"true"``, so ``"False"`` or ``"0"`` would also skip the bootstrap there --
but anything else that reads the stored task definition to decide whether a
revision is safe must be able to compare one literal, so this test accepts one
literal. It runs on a real ``app.synth()``, for staging and prod, for a full
checkout and for a core one (a copy of the CDK app with no ``modules/`` beside
it, the same construction ``test_app_profiles.test_synth_completes`` uses).
"""

from __future__ import annotations

import runpy
import shutil
from pathlib import Path

import pytest

from .test_app_profiles import CDK_DIR, _app_environment, modules_present

ENVIRONMENTS = ("staging", "prod")
PROFILES = ("core", "full")
CASES = [
    pytest.param(
        (environment, profile),
        id=f"{environment}-{profile}",
        marks=[modules_present] if profile == "full" else [],
    )
    for environment in ENVIRONMENTS
    for profile in PROFILES
]


@pytest.fixture(scope="module")
def core_checkout(tmp_path_factory) -> Path:
    """A copy of the CDK app with no ``modules/`` beside it."""
    root = tmp_path_factory.mktemp("core-checkout-298")
    shutil.copytree(CDK_DIR, root / "infrastructure" / "cdk")
    return root / "infrastructure" / "cdk"


def _synth(cdk_dir: Path, environment: str):
    with _app_environment(cdk_dir, ENVIRONMENT=environment):
        namespace = runpy.run_path(str(cdk_dir / "app.py"), run_name="__main__")
    profile = "full" if namespace["ENABLE_MODULE_STACKS"] else "core"
    return namespace["app"].synth(), profile


def _api_backend_container(assembly, environment: str) -> dict:
    """The ``backend`` container of the API service's task definition.

    Exactly one, found by its family: an empty scan must fail here rather than
    make every assertion below vacuous.
    """
    family = f"experimentation-backend-{environment}"
    containers = [
        container
        for stack in assembly.stacks
        for resource in stack.template.get("Resources", {}).values()
        if resource["Type"] == "AWS::ECS::TaskDefinition"
        and resource["Properties"].get("Family") == family
        for container in resource["Properties"].get("ContainerDefinitions", [])
        if container["Name"] == "backend"
    ]
    assert len(containers) == 1, (
        f"expected one 'backend' container in task family {family}, "
        f"found {len(containers)}"
    )
    return containers[0]


@pytest.fixture(scope="module", params=CASES)
def api_container(request, core_checkout):
    environment, profile = request.param
    cdk_dir = core_checkout if profile == "core" else CDK_DIR
    assembly, synthesised = _synth(cdk_dir, environment)
    assert synthesised == profile, (
        f"asked for the {profile} profile, app.py built {synthesised}"
    )
    container = _api_backend_container(assembly, environment)
    return {
        "label": f"{environment}/{profile}",
        "profile": profile,
        "environment": {
            e["Name"]: e["Value"] for e in container.get("Environment", [])
        },
        "secrets": {s["Name"] for s in container.get("Secrets", [])},
    }


@pytest.mark.unit
@pytest.mark.regression
def test_the_api_task_does_not_run_migrations(api_container):
    env = api_container["environment"]
    assert "RUN_MIGRATIONS" in env, (
        f"{api_container['label']}: the API task sets no RUN_MIGRATIONS, so the "
        "entry point defaults to true and every task start bootstraps the "
        "schema; an older revision then refuses to start against a newer "
        "schema (#298)"
    )
    assert env["RUN_MIGRATIONS"] == "false", (
        f"{api_container['label']}: RUN_MIGRATIONS must be exactly 'false', "
        f"got {env['RUN_MIGRATIONS']!r}"
    )


@pytest.mark.unit
@pytest.mark.regression
def test_the_api_task_does_not_seed(api_container):
    env = api_container["environment"]
    assert "SEED" in env, (
        f"{api_container['label']}: the API task does not set SEED; it must be "
        "set, and empty, so that no seed runs at task start"
    )
    assert env["SEED"] == "", (
        f"{api_container['label']}: SEED must be empty, got {env['SEED']!r}"
    )


@pytest.mark.unit
def test_each_profile_really_was_synthesised(api_container):
    """Guard: the core and full parameters did not build the same app.

    The full profile gives the API task an AUDIT_HMAC_KEY secret and the core
    profile does not; without this, a profile switch that silently selected
    nothing would test one profile twice under two names.
    """
    has_audit_key = "AUDIT_HMAC_KEY" in api_container["secrets"]
    assert has_audit_key == (api_container["profile"] == "full"), (
        f"{api_container['label']}: AUDIT_HMAC_KEY present={has_audit_key}"
    )
