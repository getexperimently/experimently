"""`scripts/restore_probe.py` against a real PostgreSQL (T143).

`scripts/restore_repoint.sh` decides whether the stack's hostname reaches the
restored database by this probe alone: it marks the restored database, then
asks for the mark through the hostname the API tasks use. A green /health
proves nothing here (it is `SELECT 1`, true on either cluster), so the probe's
answers are the gate, and the fake `aws` of test_restore_repoint.py only
models them. This file runs the probe's own text, the way the script hands it
to the migration task (`python -c`), against a throwaway database:

* `expect-marked` fails (3) before the mark and `expect-unmarked` passes;
* `mark` passes and prints `alembic_version`; then `expect-marked` passes and
  `expect-unmarked` fails (3);
* another restore's mark is not this one's;
* a wrong password, and a host that does not resolve, are neither 0 nor 3.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.regression]

PROBE = Path(__file__).resolve().parents[3] / "scripts" / "restore_probe.py"
USER = os.environ.get("POSTGRES_USER", "postgres")
PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")
HOST = (
    os.environ.get("POSTGRES_SERVER") or os.environ.get("POSTGRES_HOST") or "localhost"
)
PORT = os.environ.get("POSTGRES_PORT", "5432")


def _admin():
    conn = psycopg2.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD, dbname="postgres"
    )
    conn.autocommit = True
    return conn


@pytest.fixture
def database():
    """A throwaway database with an `experimentation.alembic_version` row."""
    name = f"restore_probe_{uuid.uuid4().hex[:12]}"
    admin = _admin()
    try:
        with admin.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{name}"')
        conn = psycopg2.connect(
            host=HOST, port=PORT, user=USER, password=PASSWORD, dbname=name
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA experimentation")
            cur.execute(
                "CREATE TABLE experimentation.alembic_version (version_num varchar(32))"
            )
            cur.execute(
                "INSERT INTO experimentation.alembic_version VALUES ('37dcb2969766')"
            )
        conn.close()
        yield name
    finally:
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


def probe(database: str, mode: str, restore_id: str = "20261006120000", **env):
    """The probe's text run as the migration task runs it: `python -c`."""
    values = {
        "PATH": os.environ.get("PATH", ""),
        "POSTGRES_SERVER": HOST,
        "POSTGRES_PORT": PORT,
        "POSTGRES_DB": database,
        "POSTGRES_SCHEMA": "experimentation",
        "POSTGRES_USER": USER,
        "POSTGRES_PASSWORD": PASSWORD,
        "PROBE_MODE": mode,
        "RESTORE_ID": restore_id,
        **env,
    }
    return subprocess.run(
        [sys.executable, "-c", PROBE.read_text()],
        env=values,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_probe_tells_a_marked_database_from_an_unmarked_one(database):
    assert probe(database, "expect-marked").returncode == 3
    assert probe(database, "expect-unmarked").returncode == 0

    marked = probe(database, "mark")
    assert marked.returncode == 0, marked.stdout + marked.stderr
    assert "PROBE alembic_version 37dcb2969766" in marked.stdout
    assert "PROBE verdict PASS mark" in marked.stdout

    assert probe(database, "expect-marked").returncode == 0
    unmarked = probe(database, "expect-unmarked")
    assert unmarked.returncode == 3, unmarked.stdout + unmarked.stderr
    assert "PROBE verdict FAIL expect-unmarked" in unmarked.stdout
    # Another restore's mark is not this one's.
    assert probe(database, "expect-marked", restore_id="20261007000000").returncode == 3


def test_a_probe_that_cannot_ask_is_neither_pass_nor_fail(database):
    unknown = probe(database, "mark-everything")
    assert unknown.returncode not in (0, 3), unknown.stdout
    nowhere = probe(database, "mark", POSTGRES_SERVER="restore-probe.invalid")
    assert nowhere.returncode not in (0, 3), nowhere.stdout
    admin = _admin()
    try:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT shobj_description(oid, 'pg_database') FROM pg_database"
                " WHERE datname = %s",
                (database,),
            )
            assert cur.fetchone()[0] is None, "a probe that could not ask marked it"
    finally:
        admin.close()


def test_a_wrong_password_is_not_a_pass(database):
    try:
        psycopg2.connect(
            host=HOST, port=PORT, user=USER, password=PASSWORD + "-not", dbname=database
        ).close()
    except psycopg2.OperationalError:
        pass
    else:
        pytest.skip("this server does not check passwords (trust authentication)")
    wrong = probe(database, "mark", POSTGRES_PASSWORD=PASSWORD + "-not")
    assert wrong.returncode == 1, wrong.stdout + wrong.stderr
    assert "password authentication failed" in wrong.stderr
