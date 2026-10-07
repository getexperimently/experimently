"""The database probe of scripts/restore_repoint.sh.

restore_repoint.sh runs this file's text with `python -c` in a one-off task of
the migration task definition, so it connects from the API tasks' subnets with
the credentials the tasks get from the database stack's secret. The script sets
POSTGRES_SERVER, PROBE_MODE and RESTORE_ID; the task definition sets the rest.

PROBE_MODE is one of:

    mark             write the marker on the database, then read it back
    expect-marked    the marker is there
    expect-unmarked  the marker is not there

Exit status: 0 the mode holds; 3 it does not; anything else (1 for a name that
does not resolve, a refused connection or a wrong password) means the database
could not be asked. Every line it prints starts with PROBE.
"""

import os
import socket
import sys

import psycopg2
from psycopg2 import sql

MODES = ("mark", "expect-marked", "expect-unmarked")

host = os.environ["POSTGRES_SERVER"]
mode = os.environ["PROBE_MODE"]
if mode not in MODES:
    sys.exit(f"PROBE unknown mode {mode!r}: one of {', '.join(MODES)}")
dbname = os.environ.get("POSTGRES_DB", "experimentation")
schema = os.environ.get("POSTGRES_SCHEMA", "experimentation")
marker = "experimently-restore " + os.environ["RESTORE_ID"]

print("PROBE host", host, "->", socket.gethostbyname(host), flush=True)
conn = psycopg2.connect(
    host=host,
    port=int(os.environ.get("POSTGRES_PORT", "5432")),
    dbname=dbname,
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
    connect_timeout=10,
)
conn.autocommit = True
cur = conn.cursor()
if mode == "mark":
    cur.execute(
        sql.SQL("COMMENT ON DATABASE {} IS %s").format(sql.Identifier(dbname)),
        (marker,),
    )
cur.execute(
    "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
    (dbname,),
)
found = cur.fetchone()[0]
cur.execute("SELECT pg_is_in_recovery()")
print("PROBE marker", repr(found), "in_recovery", cur.fetchone()[0], flush=True)
try:
    cur.execute("SELECT aurora_db_instance_identifier()")
    print("PROBE instance", cur.fetchone()[0], flush=True)
except psycopg2.Error as exc:
    print("PROBE instance unavailable:", type(exc).__name__, flush=True)
table = sql.Identifier(schema, "alembic_version")
cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table.as_string(conn),))
if cur.fetchone()[0]:
    cur.execute(
        sql.SQL(
            "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM {}"
        ).format(table)
    )
    print("PROBE alembic_version", cur.fetchone()[0], flush=True)
ok = found != marker if mode == "expect-unmarked" else found == marker
print("PROBE verdict", "PASS" if ok else "FAIL", mode, flush=True)
sys.exit(0 if ok else 3)
