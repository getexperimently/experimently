"""
Two API replicas starting at once both run ``python -m backend.app.db.bootstrap``
(``backend/docker-entrypoint.sh``).  The bootstrap serialises itself on a
PostgreSQL advisory lock, so on a fresh database exactly one process creates
the schema and the first administrator and the other finds the work done.

Runs the real module in two subprocesses against a scratch schema of the
per-process test database (``backend/tests/conftest.py`` exports its name as
``POSTGRES_DB``, which is what the bootstrap reads).
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)


def _run_bootstrap(schema: str) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("APP_ENV", "TESTING", "ENVIRONMENT")
    }
    env.update(
        {
            "PYTHONPATH": REPO_ROOT,
            "POSTGRES_SCHEMA": schema,
            "FIRST_SUPERUSER": "race@example.com",
            "FIRST_SUPERUSER_PASSWORD": "Race-Passw0rd",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "backend.app.db.bootstrap"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.integration
def test_concurrent_bootstraps_on_a_fresh_schema_do_not_race(test_db):
    engine = test_db
    schema = f"boot_race_{uuid.uuid4().hex[:8]}"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(_run_bootstrap, [schema, schema]))

        for proc in results:
            assert proc.returncode == 0, proc.stderr[-2000:]
        outcomes = sorted(
            "created" if "(created)" in p.stdout else "upgraded" for p in results
        )
        assert outcomes == ["created", "upgraded"], [p.stdout for p in results]

        with engine.connect() as conn:
            users = (
                conn.execute(text(f'SELECT email FROM "{schema}".users'))
                .scalars()
                .all()
            )
            assert users == ["race@example.com"]
            head = conn.execute(
                text(f'SELECT count(*) FROM "{schema}".alembic_version')
            ).scalar()
            assert head == 1
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
