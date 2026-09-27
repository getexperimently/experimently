# SPDX-FileCopyrightText: 2026 Experimently contributors
# SPDX-License-Identifier: Apache-2.0
"""The demo seeds run only in development and test.

Two paths start them, and each is checked on its own:

* ``backend/docker-entrypoint.sh`` with ``SEED=demo,shoplab,streampulse`` --
  refused before anything else runs, including the database wait;
* the scripts themselves (``seed_demo_data.py``, ``seed_shoplab.py``,
  ``seed_streampulse.py``) -- refused at the top of ``main()``, before the
  first database session.

``sdk-contract`` is not a demo seed; Docker Smoke runs
``ENVIRONMENT=development SEED=demo,sdk-contract`` and that keeps working.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
ENTRYPOINT = REPO_ROOT / "backend" / "docker-entrypoint.sh"
BASH = shutil.which("bash")

SCRIPTS = [
    ("backend.scripts.seed_demo_data", "demo"),
    ("backend.scripts.seed_shoplab", "shoplab"),
    ("backend.scripts.seed_streampulse", "streampulse"),
]

REFUSED_ENVIRONMENTS = ["staging", "production"]
ALLOWED_ENVIRONMENTS = ["development", "test"]


def _entrypoint_message(seed: str, environment: str) -> str:
    return (
        f"[entrypoint] SEED={seed} is for development and is refused when "
        f"ENVIRONMENT={environment}. Remove SEED."
    )


# ---------------------------------------------------------------------------
# The seed scripts
# ---------------------------------------------------------------------------


class _ReachedTheDatabase(Exception):
    """Raised by the stand-in for SessionLocal: main() got past the guard."""


def _no_database(*_args, **_kwargs):
    raise _ReachedTheDatabase()


def _prepare(
    monkeypatch, module_name: str, environment: str | None, app_env: str | None = None
):
    """Import the script with its database replaced, and set the environment."""
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "SessionLocal", _no_database)
    monkeypatch.setattr(sys, "argv", [module_name.rsplit(".", 1)[-1] + ".py"])
    if environment is None:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("ENVIRONMENT", environment)
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    return module


def _run_main(module):
    # seed_demo_data.main() reads sys.argv; the other two take argv.
    if module.__name__.endswith("seed_demo_data"):
        return module.main()
    return module.main([])


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("environment", REFUSED_ENVIRONMENTS)
@pytest.mark.parametrize("module_name,seed", SCRIPTS)
def test_script_refuses_outside_development(
    monkeypatch, capsys, module_name, seed, environment
):
    module = _prepare(monkeypatch, module_name, environment)

    with pytest.raises(SystemExit) as exc:
        _run_main(module)

    assert exc.value.code == 78
    err = capsys.readouterr().err
    assert (
        f"[seed] the '{seed}' seed is for development and is refused when "
        f"ENVIRONMENT={environment}." in err
    )


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("module_name,seed", SCRIPTS)
def test_script_refuses_the_legacy_app_env_spelling(
    monkeypatch, capsys, module_name, seed
):
    """No ENVIRONMENT, APP_ENV=prod: the shape of an older task definition."""
    module = _prepare(monkeypatch, module_name, None, app_env="prod")

    with pytest.raises(SystemExit) as exc:
        _run_main(module)

    assert exc.value.code == 78
    assert "ENVIRONMENT=prod." in capsys.readouterr().err


@pytest.mark.unit
@pytest.mark.parametrize("environment", ALLOWED_ENVIRONMENTS)
@pytest.mark.parametrize("module_name,seed", SCRIPTS)
def test_script_runs_in_development_and_test(
    monkeypatch, module_name, seed, environment
):
    """Allowed: main() gets past the guard to its first database session."""
    module = _prepare(monkeypatch, module_name, environment)

    with pytest.raises(_ReachedTheDatabase):
        _run_main(module)


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("module_name,seed", SCRIPTS)
def test_script_run_as_a_program_refuses_production(module_name, seed, tmp_path):
    """The way the entrypoint and the docs run it: ``python backend/scripts/<name>.py``.

    POSTGRES_SERVER points at a port nothing listens on, so a script that got
    past the guard would fail on the connection with a different exit status.
    """
    script = REPO_ROOT / (module_name.replace(".", "/") + ".py")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AWS_", "POSTGRES_"))
        and key not in ("ENVIRONMENT", "APP_ENV")
    }
    env.update(
        ENVIRONMENT="production",
        TESTING="true",  # placeholder secrets are fine here; this is not a deployment
        POSTGRES_SERVER="127.0.0.1",
        POSTGRES_PORT="1",
        AWS_CONFIG_FILE=os.devnull,
        AWS_SHARED_CREDENTIALS_FILE=os.devnull,
        SHOPLAB_DEMO_DIR=str(tmp_path),
        STREAMPULSE_DEMO_DIR=str(tmp_path),
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 78, result.stderr[-2000:]
    assert f"the '{seed}' seed is for development" in result.stderr


# ---------------------------------------------------------------------------
# The container entrypoint
# ---------------------------------------------------------------------------

_STUB_PYTHON = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$*" in
    *"seed_markers check"*) exit 1 ;;
esac
exit 0
"""


def _run_entrypoint(
    tmp_path: Path, **env_vars: str
) -> tuple[subprocess.CompletedProcess, str]:
    """Run the real entrypoint with ``python`` stubbed out and ``cd /app`` redirected.

    The stub records every python invocation, so the test can see which seed
    scripts would have run -- and that nothing ran at all when a seed is refused.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python"
    stub.write_text(_STUB_PYTHON)
    stub.chmod(0o755)
    log = tmp_path / "python.log"
    log.write_text("")

    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "STUB_LOG": str(log),
        "APP_DIR_FOR_TEST": str(tmp_path),
        "WAIT_FOR_DB": "false",
        "RUN_MIGRATIONS": "false",
        "OPENSSL_armcap": "0",
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
    }
    env.update(env_vars)
    # `cd /app` is the container's working directory; a bash function exported
    # to the child shell takes precedence over the builtin.
    driver = (
        'cd() { builtin cd "$APP_DIR_FOR_TEST"; }; export -f cd; exec bash "$0" true'
    )
    result = subprocess.run(
        [BASH, "-c", driver, str(ENTRYPOINT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, log.read_text()


entrypoint_only = pytest.mark.skipif(
    BASH is None or not ENTRYPOINT.is_file(),
    reason="needs bash and backend/docker-entrypoint.sh",
)


@entrypoint_only
@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize(
    "seed,env_vars,shown",
    [
        ("demo", {"ENVIRONMENT": "production"}, "production"),
        ("demo", {"ENVIRONMENT": "staging"}, "staging"),
        ("shoplab", {"ENVIRONMENT": "production"}, "production"),
        ("streampulse", {"ENVIRONMENT": "staging"}, "staging"),
        ("sdk-contract,demo", {"ENVIRONMENT": "production"}, "production"),
        ("demo, shoplab", {"ENVIRONMENT": "Production"}, "Production"),
        ("demo", {"ENVIRONMENT": "prod"}, "prod"),
        ("demo", {"APP_ENV": "prod"}, "prod"),
    ],
)
def test_entrypoint_refuses_demo_seeds_outside_development(
    tmp_path, seed, env_vars, shown
):
    result, python_calls = _run_entrypoint(tmp_path, SEED=seed, **env_vars)

    assert result.returncode == 78, result.stderr
    assert _entrypoint_message(seed, shown) in result.stderr.splitlines()
    # Refused before anything ran: no seed, no bootstrap, no database wait.
    assert python_calls == ""
    assert "waiting for PostgreSQL" not in result.stderr


@entrypoint_only
@pytest.mark.unit
@pytest.mark.parametrize(
    "seed,env_vars,expected_scripts",
    [
        # Docker Smoke's own configuration.
        (
            "demo,sdk-contract",
            {"ENVIRONMENT": "development"},
            ["seed_demo_data.py", "seed_sdk_contract.py"],
        ),
        (
            "demo,shoplab,streampulse",
            {"ENVIRONMENT": "test"},
            ["seed_demo_data.py", "seed_shoplab.py", "seed_streampulse.py"],
        ),
        ("demo", {"ENVIRONMENT": "dev"}, ["seed_demo_data.py"]),
        ("demo", {}, ["seed_demo_data.py"]),  # unset means development
        # sdk-contract is not a demo seed.
        ("sdk-contract", {"ENVIRONMENT": "production"}, ["seed_sdk_contract.py"]),
    ],
)
def test_entrypoint_allows_the_seeds_it_should(
    tmp_path, seed, env_vars, expected_scripts
):
    env_vars = {"ENVIRONMENT": "", "APP_ENV": "", **env_vars}
    result, python_calls = _run_entrypoint(tmp_path, SEED=seed, **env_vars)

    assert result.returncode == 0, result.stderr
    assert "is refused" not in result.stderr
    for script in expected_scripts:
        assert f"backend/scripts/{script}" in python_calls, python_calls


@pytest.mark.unit
@pytest.mark.regression
def test_compose_lets_an_empty_seed_apply_none():
    """``SEED=`` in ``.env`` must clear the compose default, not fall back to demo.

    ``${SEED:-demo}`` treats an empty value as unset, so a stack run with
    ENVIRONMENT=staging could not turn the demo seed off. ``${SEED-demo}``
    substitutes only when SEED is absent. (docs/getting-started/docker-compose-file.md)
    """
    compose = REPO_ROOT / "docker-compose.yml"
    if not compose.is_file():
        pytest.skip("this tree has no docker-compose.yml")
    seed_lines = [
        line.split("#", 1)[0].strip()
        for line in compose.read_text().splitlines()
        if line.strip().startswith("SEED:")
    ]
    assert seed_lines == ["SEED: ${SEED-demo}"], seed_lines


@entrypoint_only
@pytest.mark.unit
def test_entrypoint_without_seed_is_unaffected(tmp_path):
    result, _ = _run_entrypoint(tmp_path, SEED="", ENVIRONMENT="production")
    assert result.returncode == 0, result.stderr
    assert "is refused" not in result.stderr
