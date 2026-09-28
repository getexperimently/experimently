"""A DuckDB "warehouse" for the module tests: the fourth token set, tests only.

The generated statements are the product; DuckDB is where their *semantics*
are exercised (grain, windows, time zones, centred sums) without a cloud
account.  It never ships: ``duckdb`` is pinned in
``modules/requirements-test.txt`` only, and ``test_dependencies.py`` fails if
any application module imports it or a shipped lock carries it.

The DuckDB tokens below are written for DuckDB, like the three production
token sets are written for theirs.  Nothing is transpiled.

:meth:`DuckDBWarehouse.fetch` returns rows the way a warehouse wire does:
integers become digit strings and every float must already be a string our
SQL serialised.  A float arriving unserialised raises, so a statement that
forgot the wire format fails here rather than passing on DuckDB's own float
rendering.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import duckdb

from modules.backend.app.core.warehouse_identifiers import ATHENA, IdentifierRules
from modules.backend.app.services.warehouse_query_builder import BuiltQuery, SqlDialect

DUCKDB_RULES = IdentifierRules(
    name="duckdb",
    table_parts=ATHENA.table_parts,
    table_part_names=("schema", "table"),
    column=ATHENA.column,
    quote_open='"',
    quote_close='"',
)

DUCKDB_SQL = SqlDialect(
    name="duckdb",
    identifiers=DUCKDB_RULES,
    string_type="VARCHAR",
    double_type="DOUBLE",
    timestamp_literal=lambda t: f"TIMESTAMPTZ '{t}+00:00'",
    add_hours=lambda e, h: f"({e} + INTERVAL {h} HOUR)",
    # DuckDB's fmt-style format(), not printf(): sqlglot reads printf() as an
    # unrecognised (Anonymous) function, which the re-parse refuses, and
    # format('{:.17g}') renders the same 17 significant digits.
    serialise=lambda x: f"format('{{:.17g}}', {x})",
    time_column=lambda c: c,
)


def _wire(value: Any, column: str) -> Any:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise AssertionError(f"{column}: a boolean left the warehouse")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise AssertionError(
            f"{column}: a float left the warehouse unserialised ({value!r}); every"
            " float must be rendered by our SQL with 17 significant digits"
        )
    raise AssertionError(f"{column}: unexpected type {type(value).__name__}")


class DuckDBWarehouse:
    """An in-memory DuckDB with tables in schema ``main``."""

    def __init__(self, *, threads: int = 1, timezone: str = "UTC") -> None:
        self.con = duckdb.connect(":memory:")
        self.con.execute(f"SET threads = {int(threads)}")
        self.set_timezone(timezone)

    def set_timezone(self, name: str) -> None:
        # Only fixed names from the tests reach here.
        assert name.replace("/", "").replace("_", "").isalpha(), name
        self.con.execute(f"SET TimeZone = '{name}'")

    def create(
        self, table: str, columns: Sequence[tuple[str, str]], rows: Iterable[tuple]
    ) -> None:
        cols = ", ".join(f'"{name}" {sql_type}' for name, sql_type in columns)
        self.con.execute(f'CREATE TABLE "main"."{table}" ({cols})')
        rows = list(rows)
        if rows:
            marks = ", ".join("?" for _ in columns)
            self.con.executemany(f'INSERT INTO "main"."{table}" VALUES ({marks})', rows)

    def create_from_frame(self, table: str, frame: Any) -> None:
        self.con.register("frame_in", frame)
        try:
            self.con.execute(f'CREATE TABLE "main"."{table}" AS SELECT * FROM frame_in')
        finally:
            self.con.unregister("frame_in")

    def fetch(self, built: BuiltQuery) -> list[dict[str, Any]]:
        assert built.dialect == "duckdb", built.dialect
        cursor = self.con.execute(built.sql)
        names = [d[0] for d in cursor.description]
        return [
            {name: _wire(value, name) for name, value in zip(names, row)}
            for row in cursor.fetchall()
        ]
