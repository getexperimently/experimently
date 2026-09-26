"""A production task definition must carry every secret the image needs to boot.

The image ships no ``.env`` file -- ``.dockerignore`` keeps ``.env.*`` out of the
build context -- so the ECS task definition is the *only* thing that can supply
one.  Two secrets were missing from both task definitions, and each one is a
container that never serves a request:

* ``FIRST_SUPERUSER_PASSWORD`` defaults to ``"admin"``, which
  ``Settings.validate_superuser_password`` rejects in staging/production.
  ``import backend.app.core.config`` therefore raised, on **both** profiles, so
  uvicorn never bound and every ``python -m alembic`` died at import.
* ``AUDIT_HMAC_KEY`` defaults to ``dev-audit-key-change-in-production``, which
  ``ModulesSettings``' validator rejects the same way.  ``modules.register``
  builds those settings as its first step, so on a **full** image the modules
  fail to register -- ``abort_if_modules_broken()`` refuses to start the API,
  and ``migrations/env.py``'s ``require_modules_or_absent()`` refuses every
  alembic command.

The check is derived rather than typed: the environment is read out of the CDK
stacks and handed to the real settings classes in a clean subprocess.  A secret
that stops being injected fails this test with the field that rejected its
default, whatever that field turns out to be.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
STACKS_DIR = REPO_ROOT / "infrastructure" / "cdk" / "stacks"
STACKS = {
    "fargate": STACKS_DIR / "fargate_service_stack.py",
    "migration": STACKS_DIR / "migration_task_stack.py",
}

#: Secrets only module code reads.  The stacks gate them on ``include_modules``
#: because ECS cannot start a task whose definition names a secret that was
#: never created, and a core deployment creates none of these.
MODULE_ONLY_SECRETS = {"AUDIT_HMAC_KEY"}

#: Values a production deployment would really hold.  Anything not named here
#: gets a long random-looking string, which is what every hardening validator
#: asks for (>= 32 characters, not a known placeholder).
_STRONG = "f" * 64
_REALISTIC = {
    # `"APP_ENV": env_name`, and env_name is "prod" in production.
    "APP_ENV": "prod",
    # The Redis stack's primary endpoint and port (CloudFormation tokens in
    # the stack, so not literals the AST can read).
    "REDIS_HOST": "master.cache.example.internal",
    "REDIS_PORT": "6379",
    "POSTGRES_SERVER": "aurora.example.internal",
    # Not a secret and not a random string: the settings validator requires an
    # absolute http(s) origin with no path, and ALLOWED_HOSTS derives its host.
    "PUBLIC_BASE_URL": "https://api.example.com",
}

pytestmark = pytest.mark.skipif(
    not STACKS_DIR.is_dir(), reason="this tree has no infrastructure/cdk"
)


def _add_container_call(stack: Path) -> ast.Call:
    for node in ast.walk(ast.parse(stack.read_text())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_container"
        ):
            return node
    raise AssertionError(f"no add_container(...) call in {stack.name}")


def _keyword(stack: Path, name: str) -> ast.AST:
    for keyword in _add_container_call(stack).keywords:
        if keyword.arg == name:
            return keyword.value
    raise AssertionError(f"{stack.name}: add_container(...) has no {name}=")


def _all_names(stack: Path, kwarg: str) -> set[str]:
    """Every literal string key under ``kwarg``, nested dicts included."""
    return {
        key.value
        for mapping in ast.walk(_keyword(stack, kwarg))
        if isinstance(mapping, ast.Dict)
        for key in mapping.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _unconditional_names(stack: Path, kwarg: str) -> set[str]:
    """The keys of the top-level ``kwarg`` dict only.

    The profile-dependent entries sit in a nested dict behind
    ``**({...} if ... else {})``, so they are exactly the difference between
    this and :func:`_all_names`.
    """
    mapping = _keyword(stack, kwarg)
    return {
        key.value
        for key in mapping.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _literal_values(stack: Path, kwarg: str) -> dict[str, str]:
    mapping = _keyword(stack, kwarg)
    return {
        key.value: value.value
        for key, value in zip(mapping.keys, mapping.values)
        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
    }


def container_environment(stack: Path, profile: str) -> dict[str, str]:
    """The environment the container really receives, as name -> value."""
    names = _all_names(stack, "environment") | _all_names(stack, "secrets")
    if profile == "core":
        names -= MODULE_ONLY_SECRETS
    literals = _literal_values(stack, "environment")
    return {name: literals.get(name, _REALISTIC.get(name, _STRONG)) for name in names}


def _run(environment: dict[str, str], script: str) -> subprocess.CompletedProcess:
    """Run *script* with exactly *environment* (plus what python itself needs).

    A clean environment on purpose: the test process runs with ``TESTING=true``,
    which switches every hardening validator off -- the container does not.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(REPO_ROOT),
        **environment,
    }
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


_CORE_SETTINGS = """
import backend.app.core.config as config
assert config.settings.ENVIRONMENT == "production", config.settings.ENVIRONMENT
print("core settings built")
"""

_MODULE_SETTINGS = (
    _CORE_SETTINGS
    + """
from modules.backend.app.settings import build_modules_settings
build_modules_settings()
print("modules settings built")
"""
)


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("name", sorted(STACKS))
def test_the_task_definition_boots_the_application_in_production(name: str):
    """Every secret the settings refuse a default for is in the task definition."""
    environment = container_environment(STACKS[name], profile="full")
    result = _run(environment, _CORE_SETTINGS)
    assert result.returncode == 0, (
        f"{STACKS[name].name} gives the container "
        f"{sorted(environment)}, and the application cannot start with it:\n"
        f"{result.stderr[-2000:]}"
    )


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("name", sorted(STACKS))
def test_the_full_profile_can_register_its_modules(name: str):
    """The same, for the settings ``modules.register(hooks)`` builds first."""
    if not (REPO_ROOT / "modules" / "backend" / "app" / "settings.py").is_file():
        pytest.skip("core checkout: no modules package")
    environment = container_environment(STACKS[name], profile="full")
    assert MODULE_ONLY_SECRETS <= set(environment), sorted(environment)
    result = _run(environment, _MODULE_SETTINGS)
    assert result.returncode == 0, (
        f"{STACKS[name].name} cannot register the modules it deployed:\n"
        f"{result.stderr[-2000:]}"
    )


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("name", sorted(STACKS))
def test_the_module_secrets_are_gated_on_the_profile(name: str):
    """A core task definition must not name a secret nobody created.

    ECS fails the task at start-up when a secret in the definition does not
    resolve, so the module-only ones may only ever be conditional.
    """
    stack = STACKS[name]
    assert MODULE_ONLY_SECRETS <= _all_names(stack, "secrets"), (
        f"{stack.name} never injects {sorted(MODULE_ONLY_SECRETS)}"
    )
    assert not MODULE_ONLY_SECRETS & _unconditional_names(stack, "secrets"), (
        f"{stack.name} injects {sorted(MODULE_ONLY_SECRETS)} unconditionally; "
        "a core deployment has no such secret and ECS would refuse the task"
    )
    assert "include_modules" in stack.read_text()


DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml"


def _stack_secret_names() -> set[str]:
    """Every ``/<env>/experimentation/<name>`` secret the two stacks import."""
    pattern = re.compile(r'f"/\{env_name\}/experimentation/([a-z0-9-]+)"')
    return {
        name for stack in STACKS.values() for name in pattern.findall(stack.read_text())
    }


def _preflight_secret_names() -> tuple[set[str], set[str]]:
    """``(always, full-only)`` from the deploy pre-flight's ``required`` arrays."""
    text = DEPLOY_WORKFLOW.read_text()
    (always,) = re.findall(r"^\s*required=\(([^)]*)\)", text, re.M)
    (full,) = re.findall(r"^\s*required\+=\(([^)]*)\)", text, re.M)
    return set(always.split()), set(full.split())


@pytest.mark.unit
@pytest.mark.regression
def test_the_deploy_preflight_checks_exactly_the_secrets_the_stacks_name():
    """The pre-flight and the task definitions agree on which secrets exist.

    A secret the stacks name but the pre-flight does not check is a task ECS
    refuses to start, found twenty minutes into a deployment; one the pre-flight
    demands but nothing reads (the old Redis URL secret was that, #147) blocks every
    deployment on a secret an operator has to hand-make for nothing.
    """
    if not DEPLOY_WORKFLOW.is_file():
        pytest.skip("this tree has no deploy workflow")
    always, full_only = _preflight_secret_names()
    names = _stack_secret_names()
    module_only = {"audit-hmac-key"}
    assert always == names - module_only, (
        f"pre-flight checks {sorted(always)}; the task definitions name "
        f"{sorted(names - module_only)} unconditionally"
    )
    assert full_only == module_only & names


@pytest.mark.unit
@pytest.mark.regression
def test_without_the_audit_key_the_modules_refuse_to_register():
    """The negative control: the secret above is load-bearing, not decoration.

    This is the state every full-profile deployment was in -- the core settings
    build, and then `modules.register(hooks)` raises on AUDIT_HMAC_KEY.
    """
    if not (REPO_ROOT / "modules" / "backend" / "app" / "settings.py").is_file():
        pytest.skip("core checkout: no modules package")
    environment = container_environment(STACKS["fargate"], profile="core")
    assert "AUDIT_HMAC_KEY" not in environment

    result = _run(environment, _MODULE_SETTINGS)
    assert result.returncode != 0, result.stdout
    assert "AUDIT_HMAC_KEY" in result.stderr, result.stderr[-2000:]
    # ...while the core profile itself is perfectly happy with that same set.
    assert _run(environment, _CORE_SETTINGS).returncode == 0
