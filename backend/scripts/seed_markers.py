#!/usr/bin/env python3
"""
Seed markers: remember which ``backend/scripts/seed_*.py`` scripts have run.

The API container's entrypoint (``backend/docker-entrypoint.sh``) applies the
seeds listed in ``SEED=demo,shoplab,...`` exactly once per database. This
module keeps that bookkeeping in a tiny ``seed_markers`` table inside the
application schema so a container restart (or a second replica) does not
re-seed.

Usage::

    python -m backend.scripts.seed_markers check demo   # exit 0 if applied, 1 if not
    python -m backend.scripts.seed_markers mark demo    # record the seed as applied
    python -m backend.scripts.seed_markers list         # print applied seeds
    python -m backend.scripts.seed_markers clear demo   # forget a seed (forces re-run)

Connection settings come from the ``POSTGRES_*`` environment variables, the
same ones ``backend.app.db.bootstrap`` reads.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema

from backend.app.db.bootstrap import database_url, schema_name
from backend.app.models.seed_marker import SeedMarker

TABLE_NAME = SeedMarker.__tablename__


def seed_markers_table(schema: str) -> Table:
    """
    The ``seed_markers`` table bound to an explicit *schema*.

    Derived from the ``SeedMarker`` model (the single definition, on
    ``Base.metadata``) so the bootstrap's ``create_all`` and Alembic
    autogenerate see the same table this script reads and writes.
    """
    return SeedMarker.__table__.to_metadata(MetaData(), schema=schema)



def ensure_table(engine: Engine, schema: str) -> Table:
    """Create the schema and the marker table when they do not exist yet."""
    table = seed_markers_table(schema)
    with engine.begin() as conn:
        conn.execute(CreateSchema(schema, if_not_exists=True))
        table.create(conn, checkfirst=True)
    return table


def is_applied(engine: Engine, name: str, schema: Optional[str] = None) -> bool:
    """True when *name* has a marker row."""
    schema = schema or schema_name()
    table = ensure_table(engine, schema)
    with engine.connect() as conn:
        row = conn.execute(select(table.c.name).where(table.c.name == name)).first()
    return row is not None


def mark_applied(
    engine: Engine, name: str, source: Optional[str] = None, schema: Optional[str] = None
) -> None:
    """Record *name* as applied (idempotent)."""
    schema = schema or schema_name()
    table = ensure_table(engine, schema)
    with engine.begin() as conn:
        exists = conn.execute(select(table.c.name).where(table.c.name == name)).first()
        if exists is None:
            conn.execute(
                table.insert().values(
                    name=name, applied_at=datetime.now(timezone.utc), source=source
                )
            )


def clear(engine: Engine, name: str, schema: Optional[str] = None) -> None:
    """Remove the marker for *name* so the seed runs again."""
    schema = schema or schema_name()
    table = ensure_table(engine, schema)
    with engine.begin() as conn:
        conn.execute(table.delete().where(table.c.name == name))


def applied(engine: Engine, schema: Optional[str] = None) -> list[tuple[str, datetime]]:
    """All markers as ``(name, applied_at)`` tuples, oldest first."""
    schema = schema or schema_name()
    table = ensure_table(engine, schema)
    with engine.connect() as conn:
        rows = conn.execute(
            select(table.c.name, table.c.applied_at).order_by(table.c.applied_at)
        ).all()
    return [(r[0], r[1]) for r in rows]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Track applied seed scripts.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="exit 0 when the seed was applied, 1 otherwise")
    p_check.add_argument("name")
    p_mark = sub.add_parser("mark", help="record the seed as applied")
    p_mark.add_argument("name")
    p_mark.add_argument("--source", default=None, help="free-form note (script path, image tag)")
    p_clear = sub.add_parser("clear", help="forget the seed so it runs again")
    p_clear.add_argument("name")
    sub.add_parser("list", help="print applied seeds")
    args = parser.parse_args(list(argv) if argv is not None else None)

    engine = create_engine(database_url())
    try:
        if args.command == "check":
            return 0 if is_applied(engine, args.name) else 1
        if args.command == "mark":
            mark_applied(engine, args.name, source=args.source)
            return 0
        if args.command == "clear":
            clear(engine, args.name)
            return 0
        for name, when in applied(engine):
            print(f"{name}\t{when.isoformat()}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
