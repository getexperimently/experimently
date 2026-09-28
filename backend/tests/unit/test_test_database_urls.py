"""The test modules that open their own engine use the configured database.

`test_rollout_schedules_api.py` once hard-coded
``postgresql://postgres:postgres@localhost:5432/experimentation_test_<pid>``,
so a local run with ``POSTGRES_PORT``/``POSTGRES_SERVER`` pointing at a
throwaway container still connected to whatever listened on 5432 (#283).

The URLs are computed at import time, so each check imports the module in a
fresh interpreter with a planted environment and reads the URL back. Nothing
connects to a database.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

PLANTED = {
    "POSTGRES_SERVER": "db.planted.invalid",
    "POSTGRES_PORT": "54999",
    "POSTGRES_USER": "planted_user",
    "POSTGRES_PASSWORD": "planted_pw",
}

_PROBE = """
import json, os
from sqlalchemy.engine import make_url
import {module} as m
u = make_url(m.{attr})
print(json.dumps({{"host": u.host, "port": u.port, "user": u.username,
                   "password": u.password, "database": u.database,
                   "pid": os.getpid()}}))
"""


def _url_parts(module: str, attr: str) -> dict:
    env = {**os.environ, **PLANTED, "APP_ENV": "test", "TESTING": "true"}
    env.pop("POSTGRES_HOST", None)
    env.pop("TEST_DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE.format(module=module, attr=attr)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.unit
@pytest.mark.regression
def test_rollout_schedule_api_tests_use_the_configured_database():
    parts = _url_parts(
        "backend.tests.integration.api.test_rollout_schedules_api", "DB_URL"
    )
    assert parts["host"] == PLANTED["POSTGRES_SERVER"]
    assert parts["port"] == int(PLANTED["POSTGRES_PORT"])
    assert parts["user"] == PLANTED["POSTGRES_USER"]
    assert parts["password"] == PLANTED["POSTGRES_PASSWORD"]
    # Still the per-process database the root conftest creates and drops.
    assert parts["database"] == f"experimentation_test_{parts['pid']}"
