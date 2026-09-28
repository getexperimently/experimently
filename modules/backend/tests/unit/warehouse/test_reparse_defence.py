"""The second line: every generated statement is parsed again before use.

The gate means a bad value never reaches SQL; this checks the SQL anyway, so
a future template edit that reads another table, adds a statement or calls an
unknown function is refused rather than sent.  With sqlglot missing, nothing
is sent at all.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modules.backend.app.core.warehouse_identifiers import WarehouseQueryRefused
from modules.backend.app.services import warehouse_query_builder as builder
from modules.backend.app.services.warehouse_query_builder import (
    METRIC_CTES,
    SQL_DIALECTS,
    AnalysisWindow,
    AssignmentMapping,
    MetricMapping,
    build_diagnostics_query,
    build_metric_query,
    verify_generated_sql,
)
from modules.backend.tests.unit.warehouse.test_golden_sql import build_case

pytestmark = pytest.mark.unit

WINDOW = AnalysisWindow(
    datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 2, tzinfo=timezone.utc)
)


def _refused(built, ctes=METRIC_CTES) -> str:
    with pytest.raises(WarehouseQueryRefused) as refused:
        verify_generated_sql(built, ctes)
    return refused.value.code


@pytest.mark.parametrize("dialect", sorted(SQL_DIALECTS))
def test_generated_sql_is_one_select_over_exactly_the_rendered_tables(dialect):
    built = build_case(dialect, "metric_mean")
    verify_generated_sql(built, METRIC_CTES)  # the real statement passes
    quote = SQL_DIALECTS[dialect].identifiers.quote_open
    other = ".".join(
        f"{quote}{p}{quote}"
        for p in ("otherdb", "secret", "t")[-len(next(iter(built.tables))) :]
    )
    sql = built.sql.rstrip("\n")
    tampered = [
        # an extra table read
        built.sql.replace(
            "FROM y CROSS JOIN k", f"FROM y CROSS JOIN {other} CROSS JOIN k"
        ),
        # a second statement
        sql + ";\nSELECT 1",
        # a statement that is not a SELECT
        "DELETE FROM " + other,
        # an unqualified name that is not one of our CTEs
        built.sql.replace(
            "FROM y CROSS JOIN k", "FROM y CROSS JOIN secrets CROSS JOIN k"
        ),
        # a function sqlglot does not know
        built.sql.replace("COUNT(*) AS n,", "COUNT(*) AS n, mystery_fn(1) AS m,"),
        # nothing parseable
        "SELECT (((",
        "",
    ]
    for sql_text in tampered:
        assert sql_text != built.sql
        assert _refused(replace(built, sql=sql_text)) == "internal", sql_text


def test_a_table_named_like_a_cte_is_still_a_table():
    """``p.d.k`` is the customer's table ``k``, not our CTE ``k``."""
    built = build_case("bigquery", "metric_proportion")
    tampered = built.sql.replace(
        "FROM y CROSS JOIN k",
        "FROM y CROSS JOIN `acme-prod`.`analytics`.`k` CROSS JOIN k",
    )
    assert _refused(replace(built, sql=tampered)) == "internal"


def test_missing_a_rendered_table_is_refused():
    built = build_case("athena", "metric_proportion")
    assert (
        _refused(replace(built, tables=built.tables | {("analytics", "extra")}))
        == "internal"
    )


def test_sqlglot_absent_refuses_all(monkeypatch):
    monkeypatch.setattr(builder, "sqlglot", None)
    monkeypatch.setattr(builder, "sqlglot_exp", None)
    for dialect in SQL_DIALECTS.values():
        a = AssignmentMapping(
            ("analytics", "e")
            if dialect.name == "athena"
            else (
                ("acme-prod", "a", "e")
                if dialect.name == "bigquery"
                else ("A", "B", "E")
            ),
            "u",
            "k",
            "v",
            "t",
        )
        m = MetricMapping(a.table, "u", "t", "proportion")
        for build in (
            lambda: build_metric_query(dialect, a, m, "key", WINDOW),
            lambda: build_diagnostics_query(dialect, a, "key", WINDOW),
        ):
            with pytest.raises(WarehouseQueryRefused) as refused:
                build()
            assert refused.value.code == "internal"


@pytest.mark.parametrize("error", [RecursionError, MemoryError, ValueError, TypeError])
def test_any_parser_failure_refuses(monkeypatch, error):
    built = build_case("snowflake", "diagnostics")

    def boom(*args, **kwargs):
        raise error("parser failure")

    monkeypatch.setattr(builder.sqlglot, "parse", boom)
    assert _refused(built, builder.DIAGNOSTICS_CTES) == "internal"


def test_recursion_limit_is_never_changed():
    root = Path(builder.__file__).parents[1]
    for path in root.rglob("*.py"):
        assert "setrecursionlimit" not in path.read_text(encoding="utf-8"), path


def test_the_builder_never_transpiles():
    """Each dialect's SQL is written for it; sqlglot only reads it back."""
    tree = ast.parse(Path(builder.__file__).read_text(encoding="utf-8"))
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "sqlglot"
    }
    assert used == {"parse"}
