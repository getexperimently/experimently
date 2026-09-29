"""Per-dialect golden SQL: byte-equal, parseable, offset-carrying, 17 digits.

The goldens in ``golden/`` were read line by line against each warehouse's
own SQL reference when they were written; they are not transpiled from the
DuckDB statements the semantics tests run.  A change to a dialect's tokens
shows up here as a diff, which is the point: the new text has to be read
again, in that dialect, before the golden is replaced.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

from modules.backend.app.core.warehouse_identifiers import SourceFilter
from modules.backend.app.services.warehouse_query_builder import (
    ASSIGNMENT_PREVIEW_CTES,
    DIAGNOSTICS_CTES,
    METRIC_CTES,
    METRIC_PREVIEW_CTES,
    SQL_DIALECTS,
    AnalysisWindow,
    AssignmentMapping,
    MetricMapping,
    build_assignment_preview_query,
    build_diagnostics_query,
    build_metric_preview_query,
    build_metric_query,
)

pytestmark = pytest.mark.unit

GOLDEN_DIR = Path(__file__).parent / "golden"
WINDOW = AnalysisWindow(
    datetime(2026, 9, 1, tzinfo=timezone.utc),
    datetime(2026, 9, 27, 12, 30, tzinfo=timezone.utc),
)
KEY = "checkout-v2"

#: Canonical names as each warehouse's metadata would return them.
TABLES = {
    "snowflake": {
        "exposures": ("ANALYTICS", "PUBLIC", "EXPOSURES"),
        "orders": ("ANALYTICS", "PUBLIC", "ORDERS"),
        "columns": (
            "USER_ID",
            "EXPERIMENT_KEY",
            "VARIANT",
            "EXPOSED_AT",
            "PLATFORM",
            "EVENT_AT",
            "AMOUNT",
            "STATUS",
            "IS_TEST",
        ),
    },
    "bigquery": {
        "exposures": ("acme-prod", "analytics", "exposures"),
        "orders": ("acme-prod", "analytics", "orders"),
        "columns": (
            "user_id",
            "experiment_key",
            "variant",
            "exposed_at",
            "platform",
            "event_at",
            "amount",
            "status",
            "is_test",
        ),
    },
    "athena": {
        "exposures": ("analytics", "exposures"),
        "orders": ("analytics", "orders"),
        "columns": (
            "user_id",
            "experiment_key",
            "variant",
            "exposed_at",
            "platform",
            "event_at",
            "amount",
            "status",
            "is_test",
        ),
    },
}

KINDS = (
    "metric_mean",
    "metric_proportion",
    "diagnostics",
    "preview_assignment",
    "preview_metric",
)
#: The CTE names each kind defines, and which of the two tables it reads.
CTES = {
    "metric_mean": METRIC_CTES,
    "metric_proportion": METRIC_CTES,
    "diagnostics": DIAGNOSTICS_CTES,
    "preview_assignment": ASSIGNMENT_PREVIEW_CTES,
    "preview_metric": METRIC_PREVIEW_CTES,
}
READS = {
    "metric_mean": ("exposures", "orders"),
    "metric_proportion": ("exposures", "orders"),
    "diagnostics": ("exposures",),
    "preview_assignment": ("exposures",),
    "preview_metric": ("orders",),
}
CASES = [(dialect, kind) for dialect in sorted(SQL_DIALECTS) for kind in KINDS]


def build_case(dialect_name: str, kind: str):
    dialect = SQL_DIALECTS[dialect_name]
    t = TABLES[dialect_name]
    unit, key, variant, exposed, platform, event_at, amount, status, is_test = t[
        "columns"
    ]
    assignment = AssignmentMapping(
        table=t["exposures"],
        unit_id=unit,
        experiment_key=key,
        variant=variant,
        exposed_at=exposed,
        filters=(SourceFilter(platform, "in", ("web", "ios")),),
    )
    if kind == "diagnostics":
        return build_diagnostics_query(dialect, assignment, KEY, WINDOW)
    if kind == "preview_assignment":
        return build_assignment_preview_query(dialect, assignment, WINDOW, KEY)
    mean = kind in ("metric_mean", "preview_metric")
    metric = MetricMapping(
        table=t["orders"],
        unit_id=unit,
        event_at=event_at,
        metric_type="mean" if mean else "proportion",
        value=amount if mean else None,
        conversion_window_hours=168,
        cap_value=500.0 if mean else None,
        filters=(
            SourceFilter(status, "eq", "paid"),
            SourceFilter(is_test, "ne", True),
            SourceFilter(amount, "is_not_null"),
        ),
    )
    if kind == "preview_metric":
        return build_metric_preview_query(dialect, metric, WINDOW)
    return build_metric_query(dialect, assignment, metric, KEY, WINDOW)


def golden_path(dialect: str, kind: str) -> Path:
    return GOLDEN_DIR / f"{dialect}_{kind}.sql"


@pytest.mark.parametrize(("dialect", "kind"), CASES)
def test_golden_sql(dialect: str, kind: str) -> None:
    built = build_case(dialect, kind)
    assert built.sql == golden_path(dialect, kind).read_text(encoding="utf-8")


def test_every_golden_is_a_case() -> None:
    assert sorted(p.name for p in GOLDEN_DIR.glob("*.sql")) == sorted(
        golden_path(d, k).name for d, k in CASES
    )


@pytest.mark.parametrize(("dialect", "kind"), CASES)
def test_golden_parses_as_one_select_with_no_unknown_function(
    dialect: str, kind: str
) -> None:
    sql = golden_path(dialect, kind).read_text(encoding="utf-8")
    statements = sqlglot.parse(sql, read=dialect)
    assert len(statements) == 1
    root = statements[0]
    assert isinstance(root, exp.Select)
    assert [a.sql() for a in root.find_all(exp.Anonymous)] == []
    ctes = CTES[kind]
    read = {
        tuple(p for p in (t.catalog, t.db, t.name) if p)
        for t in root.find_all(exp.Table)
    }
    read = {parts for parts in read if not (len(parts) == 1 and parts[0] in ctes)}
    assert read == {TABLES[dialect][name] for name in READS[kind]}


_TIMESTAMP_TEXT = re.compile(r"'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d{6})?)([^']*)'")
_OFFSET_SUFFIX = {"snowflake": " +00:00", "bigquery": "+00:00", "athena": " UTC"}


def _golden_and_built(dialect: str, kind: str) -> list[str]:
    """The committed golden and what the builder produces now: the property
    tests below hold for both, so they fire on a builder change even before
    anyone looks at the byte-equality diff."""
    return [
        golden_path(dialect, kind).read_text(encoding="utf-8"),
        build_case(dialect, kind).sql,
    ]


@pytest.mark.parametrize(("dialect", "kind"), CASES)
def test_golden_literals_carry_utc_offset(dialect: str, kind: str) -> None:
    for sql in _golden_and_built(dialect, kind):
        literals = _TIMESTAMP_TEXT.findall(sql)
        # start and end on the exposures; start, end and the event cut on metrics.
        assert len(literals) >= (5 if kind.startswith("metric") else 2), literals
        assert {suffix for _, suffix in literals} == {_OFFSET_SUFFIX[dialect]}


_SERIALISED = {
    "snowflake": re.compile(
        r"^  CAST\(CAST\(.+ AS DECFLOAT\) AS VARCHAR\) AS (k|sum_d|sum_d2),$"
    ),
    "bigquery": re.compile(r"^  FORMAT\('%\.(\d+)g', .+\) AS (k|sum_d|sum_d2),$"),
    "athena": re.compile(r"^  format\('%\.(\d+)g', .+\) AS (k|sum_d|sum_d2),$"),
}


@pytest.mark.parametrize("dialect", sorted(SQL_DIALECTS))
@pytest.mark.parametrize("kind", ["metric_mean", "metric_proportion"])
def test_every_float_is_serialised_with_17_digits(dialect: str, kind: str) -> None:
    """k, sum_d and sum_d2 each leave the warehouse as our 17-digit string."""
    for sql in _golden_and_built(dialect, kind):
        lines = sql.splitlines()
        projected = [ln for ln in lines if re.search(r" AS (k|sum_d|sum_d2),$", ln)]
        assert len(projected) == 3, projected
        for line in projected:
            match = _SERIALISED[dialect].match(line)
            assert match, line
            if dialect != "snowflake":
                assert int(match.group(1)) >= 17, line


def test_snowflake_statements_report_the_session_offset() -> None:
    for kind in KINDS:
        for sql in _golden_and_built("snowflake", kind):
            assert "TO_CHAR(CURRENT_TIMESTAMP(), 'TZH:TZM')" in sql
            assert "AS session_offset" in sql


_STRING_TYPE = {"snowflake": "VARCHAR", "bigquery": "STRING", "athena": "VARCHAR"}


@pytest.mark.parametrize(("dialect", "kind"), CASES)
def test_unit_ids_are_cast_to_a_string_on_both_sides(dialect: str, kind: str) -> None:
    quote = SQL_DIALECTS[dialect].identifiers.quote_open
    unit = TABLES[dialect]["columns"][0]
    cast = f"CAST({quote}{unit}{quote} AS {_STRING_TYPE[dialect]}) AS unit_id"
    for sql in _golden_and_built(dialect, kind):
        assert sql.count(cast) == (2 if kind.startswith("metric") else 1), sql


_EPOCH = {
    "snowflake": "DATE_PART(EPOCH_SECOND, ",
    "bigquery": "UNIX_SECONDS(",
    "athena": "CAST(floor(to_unixtime(",
}


@pytest.mark.parametrize("dialect", sorted(SQL_DIALECTS))
@pytest.mark.parametrize("kind", ["preview_assignment", "preview_metric"])
def test_previews_return_aggregates_and_whole_epoch_seconds(
    dialect: str, kind: str
) -> None:
    """A preview selects counts, MIN/MAX of the time as epoch seconds and, for
    an assignment source, at most 51 labels -- never a column value itself."""
    for sql in _golden_and_built(dialect, kind):
        assert sql.count(_EPOCH[dialect]) == 2, sql
        root = sqlglot.parse_one(sql, read=dialect)
        outer = [e.alias_or_name for e in root.expressions]
        if kind == "preview_metric":
            expected = [
                "total_rows",
                "null_unit_rows",
                "null_value_rows",
                "earliest",
                "latest",
            ]
        else:
            expected = [
                "total_rows",
                "null_unit_rows",
                "null_variant_rows",
                "earliest",
                "latest",
                "variant",
                "units",
            ]
            assert "LIMIT 51" in sql
        if dialect == "snowflake":
            expected.append("session_offset")
        assert outer == expected
