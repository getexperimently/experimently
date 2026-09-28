"""The statements' semantics, run on DuckDB: grain, windows, zones, join keys.

One small hand-built fixture pins each rule the builder's docstring states.
Every expected number below is worked out by hand from the rows, in the
comments beside them, not taken from a previous run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fractions import Fraction

import pytest

from modules.backend.app.core.warehouse_identifiers import SourceFilter
from modules.backend.app.services.warehouse_query_builder import (
    AnalysisWindow,
    AssignmentMapping,
    MetricMapping,
    build_diagnostics_query,
    build_metric_query,
)
from modules.backend.app.services.warehouse_sufficient_stats import (
    WarehouseResultRefused,
    parse_diagnostics_rows,
    parse_metric_rows,
)
from modules.backend.tests.unit.warehouse.duckdb_adapter import (
    DUCKDB_SQL,
    DuckDBWarehouse,
)

pytestmark = pytest.mark.unit

UTC = timezone.utc
WINDOW = AnalysisWindow(
    datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 10, tzinfo=UTC)
)
KEY = "checkout-v2"

EXPOSURE_COLUMNS = [
    ("user_id", "VARCHAR"),
    ("experiment_key", "VARCHAR"),
    ("variant", "VARCHAR"),
    ("exposed_at", "TIMESTAMPTZ"),
    ("platform", "VARCHAR"),
]
EVENT_COLUMNS = [
    ("user_id", "VARCHAR"),
    ("event_at", "TIMESTAMPTZ"),
    ("amount", "DOUBLE"),
    ("status", "VARCHAR"),
]

# fmt: off
EXPOSURES = [
    # u1: exposed twice to control; the first exposure (10:00) is the one used.
    ("u1", KEY, "control",   "2026-09-02 10:00:00+00", "web"),
    ("u1", KEY, "control",   "2026-09-02 12:00:00+00", "web"),
    ("u2", KEY, "treatment", "2026-09-03 00:00:00+00", "web"),
    # u3: seen in both variants -> excluded from both, counted as multi-variant.
    ("u3", KEY, "control",   "2026-09-02 00:00:00+00", "web"),
    ("u3", KEY, "treatment", "2026-09-04 00:00:00+00", "web"),
    # NULL variant and NULL unit rows -> excluded, counted as NULL-key rows.
    ("u4", KEY, None,        "2026-09-02 00:00:00+00", "web"),
    (None, KEY, "control",   "2026-09-02 00:00:00+00", "web"),
    # u5: one second before the window -> not exposed at all.
    ("u5", KEY, "control",   "2026-08-31 23:59:59+00", "web"),
    # u6: exactly at window_start -> included ([start, end)).
    ("u6", KEY, "treatment", "2026-09-01 00:00:00+00", "web"),
    # u7: exactly at window_end -> excluded.
    ("u7", KEY, "treatment", "2026-09-10 00:00:00+00", "web"),
    # u8: another experiment -> excluded.
    ("u8", "other-exp", "control", "2026-09-02 00:00:00+00", "web"),
    # u9: treatment, no events -> y = 0.
    ("u9", KEY, "treatment", "2026-09-05 00:00:00+00", "web"),
    # u10: filtered out by platform = 'web'.
    ("u10", KEY, "control",  "2026-09-02 00:00:00+00", "ios"),
]
EVENTS = [
    # u1: one second before its first exposure -> not counted.
    ("u1", "2026-09-02 09:59:59+00", 100.0, "paid"),
    # u1: exactly at first exposure -> counted.
    ("u1", "2026-09-02 10:00:00+00", 10.0, "paid"),
    # u1: exactly first exposure + 24 h -> not counted (half-open window).
    ("u1", "2026-09-03 10:00:00+00", 1000.0, "paid"),
    # u1: filtered out by status = 'paid'.
    ("u1", "2026-09-02 11:00:00+00", 50.0, "refunded"),
    ("u2", "2026-09-03 23:59:59+00", 5.0, "paid"),
    # u2: an event with a NULL value: it converts, the value is ignored and counted.
    ("u2", "2026-09-03 01:00:00+00", None, "paid"),
    ("u6", "2026-09-01 23:00:00+00", 7.0, "paid"),
    # u3 is multi-variant: its event is matched to a unit but never counted.
    ("u3", "2026-09-04 01:00:00+00", 9.0, "paid"),
    # zzz was never exposed: in the window, matched to no unit.
    ("zzz", "2026-09-02 00:00:00+00", 3.0, "paid"),
]
# fmt: on

ASSIGNMENT = AssignmentMapping(
    table=("main", "exposures"),
    unit_id="user_id",
    experiment_key="experiment_key",
    variant="variant",
    exposed_at="exposed_at",
    filters=(SourceFilter("platform", "eq", "web"),),
)


def _metric(metric_type: str, cap: float | None = None) -> MetricMapping:
    return MetricMapping(
        table=("main", "events"),
        unit_id="user_id",
        event_at="event_at",
        metric_type=metric_type,  # type: ignore[arg-type]
        value="amount" if metric_type == "mean" else None,
        conversion_window_hours=24,
        cap_value=cap,
        filters=(SourceFilter("status", "eq", "paid"),),
    )


@pytest.fixture()
def warehouse() -> DuckDBWarehouse:
    wh = DuckDBWarehouse()
    wh.create("exposures", EXPOSURE_COLUMNS, EXPOSURES)
    wh.create("events", EVENT_COLUMNS, EVENTS)
    return wh


def _stats(wh: DuckDBWarehouse, metric: MetricMapping, window: AnalysisWindow = WINDOW):
    return parse_metric_rows(
        wh.fetch(build_metric_query(DUCKDB_SQL, ASSIGNMENT, metric, KEY, window))
    )


def _by_variant(stats) -> dict:
    return {v.variant: v for v in stats.variants}


def test_grain_proportion_counts(warehouse):
    stats = _stats(warehouse, _metric("proportion"))
    got = {v.variant: (v.n, v.n_converted) for v in stats.variants}
    # control: u1 (converted). treatment: u2, u6 (converted), u9 (not).
    assert got == {"control": (1, 1), "treatment": (3, 2)}


def test_grain_mean_values(warehouse):
    stats = _stats(warehouse, _metric("mean"))
    v = _by_variant(stats)
    # y: u1 = 10; u2 = 5 (NULL ignored); u6 = 7; u9 = 0.  k = 22 / 4.
    k = Fraction(22, 4)
    assert Fraction(stats.k_text) == k
    assert Fraction(v["control"].sum_d_text) == 10 - k
    assert Fraction(v["treatment"].sum_d_text) == (5 - k) + (7 - k) + (0 - k)
    assert Fraction(v["treatment"].sum_d2_text) == (5 - k) ** 2 + (7 - k) ** 2 + k**2
    assert stats.null_value_rows == 1


def test_grain_duplicate_exposure_uses_first(warehouse):
    # u1's event at 10:00 counts only because the FIRST exposure (10:00, not
    # 12:00) starts the unit's window.
    stats = _stats(warehouse, _metric("mean"))
    assert _by_variant(stats)["control"].n == 1
    assert Fraction(stats.k_text) == Fraction(22, 4)


def test_grain_multi_variant_units_are_excluded_and_counted(warehouse):
    stats = _stats(warehouse, _metric("proportion"))
    assert sum(v.n for v in stats.variants) == 4  # u3 is in neither
    diag = parse_diagnostics_rows(
        warehouse.fetch(build_diagnostics_query(DUCKDB_SQL, ASSIGNMENT, KEY, WINDOW))
    )
    assert diag.multi_variant_units == 1


def test_grain_pre_exposure_events_do_not_count(warehouse):
    # u1's 100.0 at 09:59:59 is before its first exposure; its 1000.0 at
    # exactly +24 h is outside [first, first + 24 h).  Only 10.0 remains.
    stats = _stats(warehouse, _metric("mean"))
    control = _by_variant(stats)["control"]
    assert Fraction(stats.k_text) + Fraction(control.sum_d_text) == 10


def test_grain_window_half_open(warehouse):
    stats = _stats(warehouse, _metric("proportion"))
    # u6 at exactly window_start is in; u7 at exactly window_end is out.
    assert _by_variant(stats)["treatment"].n == 3


def test_grain_event_window_is_cut_at_window_end():
    wh = DuckDBWarehouse()
    wh.create(
        "exposures",
        EXPOSURE_COLUMNS,
        [
            ("a", KEY, "control", "2026-09-09 12:00:00+00", "web"),
            ("b", KEY, "control", "2026-09-09 12:00:00+00", "web"),
        ],
    )
    # a's event is inside first + 24 h but at window_end, so it does not count;
    # b's event is one second earlier and does.
    wh.create(
        "events",
        EVENT_COLUMNS,
        [
            ("a", "2026-09-10 00:00:00+00", 1.0, "paid"),
            ("b", "2026-09-09 23:59:59+00", 1.0, "paid"),
        ],
    )
    stats = _stats(wh, _metric("proportion"))
    assert [(v.variant, v.n, v.n_converted) for v in stats.variants] == [
        ("control", 2, 1)
    ]


def test_grain_conservation(warehouse):
    stats = _stats(warehouse, _metric("proportion"))
    diag = parse_diagnostics_rows(
        warehouse.fetch(build_diagnostics_query(DUCKDB_SQL, ASSIGNMENT, KEY, WINDOW))
    )
    # Rows in the window for this key and platform: u1 x2, u2, u3 x2, u4,
    # the NULL unit, u6, u9 = 9; two have a NULL key; five distinct units.
    assert diag.exposure_rows == 9
    assert diag.null_key_rows == 2
    assert diag.units == 5
    assert diag.variant_values == 2
    assert sum(v.n for v in stats.variants) + diag.multi_variant_units == diag.units


def test_grain_metric_diagnostics(warehouse):
    stats = _stats(warehouse, _metric("mean"))
    # paid events in [start, end): u1 x3, u2 x2, u6, u3, zzz = 8; all but zzz
    # belong to an exposed unit (u3 included: matching ignores the variant rule).
    assert stats.metric_rows_in_window == 8
    assert stats.metric_rows_matched == 7


def test_grain_mean_cap_applies_to_each_units_sum(warehouse):
    stats = _stats(warehouse, _metric("mean", cap=6.0))
    # y: u1 = min(10, 6) = 6; u2 = 5; u6 = min(7, 6) = 6; u9 = 0.  k = 17 / 4.
    assert Fraction(stats.k_text) == Fraction(17, 4)


def test_grain_utc_boundaries_with_offsets_and_a_non_utc_session():
    """Stored offsets and the session zone do not move the window.

    The exposure at 05:30 +05:30 is exactly window_start (00:00 UTC) and is
    in; the one at 17:00 -07:00 on 09-09 is exactly window_end and is out.
    The session runs in Los Angeles to show that our literals carry their
    offset: without it they would be read in the session's zone and move by
    seven hours.
    """
    wh = DuckDBWarehouse(timezone="America/Los_Angeles")
    wh.create(
        "exposures",
        EXPOSURE_COLUMNS,
        [
            ("in", KEY, "control", "2026-09-01 05:30:00+05:30", "web"),
            ("out", KEY, "control", "2026-09-09 17:00:00-07:00", "web"),
            ("late", KEY, "control", "2026-08-31 20:00:00-07:00", "web"),
        ],
    )
    wh.create("events", EVENT_COLUMNS, [])
    stats = parse_metric_rows(
        wh.fetch(
            build_metric_query(
                DUCKDB_SQL, ASSIGNMENT, _metric("proportion"), KEY, WINDOW
            )
        )
    )
    # "late" is 2026-09-01 03:00 UTC: inside.  "out" is 2026-09-10 00:00 UTC.
    assert [(v.variant, v.n) for v in stats.variants] == [("control", 2)]


def test_grain_window_given_in_another_zone_is_converted_to_utc(warehouse):
    ist = timezone(timedelta(hours=5, minutes=30))
    shifted = AnalysisWindow(
        datetime(2026, 9, 1, 5, 30, tzinfo=ist),
        datetime(2026, 9, 10, 5, 30, tzinfo=ist),
    )
    assert _stats(warehouse, _metric("mean"), shifted) == _stats(
        warehouse, _metric("mean")
    )


def test_unit_ids_are_compared_as_strings():
    """An integer unit id matches the same id stored as text, and only it.

    Both sides are cast to a string, so ``123`` matches ``'123'`` and not
    ``'0123'``; an engine's implicit text-to-integer cast would match both.
    """
    wh = DuckDBWarehouse()
    wh.create(
        "exposures",
        [
            ("user_id", "BIGINT"),
            ("experiment_key", "VARCHAR"),
            ("variant", "VARCHAR"),
            ("exposed_at", "TIMESTAMPTZ"),
            ("platform", "VARCHAR"),
        ],
        [(123, KEY, "control", "2026-09-02 00:00:00+00", "web")],
    )
    wh.create(
        "events",
        EVENT_COLUMNS,
        [
            ("123", "2026-09-02 01:00:00+00", 1.0, "paid"),
            ("0123", "2026-09-02 01:00:00+00", 10.0, "paid"),
        ],
    )
    stats = _stats(wh, _metric("mean"))
    assert [(v.n, v.n_converted) for v in stats.variants] == [(1, 1)]
    assert Fraction(stats.k_text) == 1
    assert stats.metric_rows_matched == 1


def test_join_key_mismatch_is_refused():
    """Events exist but none has an exposed unit's id: refuse, don't report 0."""
    wh = DuckDBWarehouse()
    wh.create(
        "exposures",
        [
            ("user_id", "BIGINT"),
            ("experiment_key", "VARCHAR"),
            ("variant", "VARCHAR"),
            ("exposed_at", "TIMESTAMPTZ"),
            ("platform", "VARCHAR"),
        ],
        [(123, KEY, "control", "2026-09-02 00:00:00+00", "web")],
    )
    wh.create(
        "events", EVENT_COLUMNS, [("123.0", "2026-09-02 01:00:00+00", 1.0, "paid")]
    )
    with pytest.raises(WarehouseResultRefused) as refused:
        _stats(wh, _metric("proportion"))
    assert refused.value.code == "join_key_mismatch"


def test_wrong_variant_column_refused():
    """60 distinct values: the statement returns 51 rows, and 51 is refused."""
    wh = DuckDBWarehouse()
    wh.create(
        "exposures",
        EXPOSURE_COLUMNS,
        [
            (f"u{i}", KEY, f"v{i:02d}", "2026-09-02 00:00:00+00", "web")
            for i in range(60)
        ],
    )
    wh.create("events", EVENT_COLUMNS, [])
    rows = wh.fetch(
        build_metric_query(DUCKDB_SQL, ASSIGNMENT, _metric("proportion"), KEY, WINDOW)
    )
    assert len(rows) == 51
    with pytest.raises(WarehouseResultRefused) as refused:
        parse_metric_rows(rows)
    assert refused.value.code == "too_many_variant_values"
    diag_rows = wh.fetch(build_diagnostics_query(DUCKDB_SQL, ASSIGNMENT, KEY, WINDOW))
    with pytest.raises(WarehouseResultRefused) as refused:
        parse_diagnostics_rows(diag_rows)
    assert refused.value.code == "too_many_variant_values"


def test_fifty_variants_are_accepted():
    wh = DuckDBWarehouse()
    wh.create(
        "exposures",
        EXPOSURE_COLUMNS,
        [
            (f"u{i}", KEY, f"v{i:02d}", "2026-09-02 00:00:00+00", "web")
            for i in range(50)
        ],
    )
    wh.create("events", EVENT_COLUMNS, [])
    stats = _stats(wh, _metric("proportion"))
    assert len(stats.variants) == 50


def test_variant_labels_truncated_in_sql():
    wh = DuckDBWarehouse()
    wh.create(
        "exposures",
        EXPOSURE_COLUMNS,
        [("u1", KEY, "x" * 70, "2026-09-02 00:00:00+00", "web")],
    )
    wh.create("events", EVENT_COLUMNS, [])
    rows = wh.fetch(
        build_metric_query(DUCKDB_SQL, ASSIGNMENT, _metric("proportion"), KEY, WINDOW)
    )
    assert [len(r["variant"]) for r in rows] == [64]


def test_no_units_refused():
    wh = DuckDBWarehouse()
    wh.create("exposures", EXPOSURE_COLUMNS, [])
    wh.create("events", EVENT_COLUMNS, [])
    with pytest.raises(WarehouseResultRefused) as refused:
        _stats(wh, _metric("proportion"))
    assert refused.value.code == "no_units"


def test_every_float_leaves_duckdb_as_a_17_digit_string(warehouse):
    rows = warehouse.fetch(
        build_metric_query(DUCKDB_SQL, ASSIGNMENT, _metric("mean"), KEY, WINDOW)
    )
    for row in rows:
        for column in ("k", "sum_d", "sum_d2"):
            assert isinstance(row[column], str), column
