"""What comes back is checked before anything is computed from it."""

from __future__ import annotations

import pytest

from modules.backend.app.services.warehouse_sufficient_stats import (
    SCHEMA_ID,
    WarehouseResultRefused,
    parse_diagnostics_rows,
    parse_metric_rows,
)

pytestmark = pytest.mark.unit


def _row(**overrides):
    row = {
        "variant": "control",
        "n": "10",
        "n_converted": "4",
        "k": "0.45000000000000001",
        "sum_d": "-0.5",
        "sum_d2": "2.4750000000000001",
        "metric_rows_in_window": "12",
        "metric_rows_matched": "9",
        "null_value_rows": "0",
    }
    row.update(overrides)
    return row


def _two(**treatment):
    return [
        _row(),
        _row(variant="treatment", n="10", n_converted="5", sum_d="0.5", **treatment),
    ]


def _code(rows, **kwargs) -> str:
    with pytest.raises(WarehouseResultRefused) as refused:
        parse_metric_rows(rows, **kwargs)
    return refused.value.code


def test_valid_rows_parse_and_keep_the_exact_text():
    stats = parse_metric_rows(_two())
    assert [v.variant for v in stats.variants] == ["control", "treatment"]
    assert stats.k_text == "0.45000000000000001"
    assert stats.variants[0].sum_d2_text == "2.4750000000000001"
    stored = stats.to_json()
    assert stored["schema"] == SCHEMA_ID
    assert stored["k"] == "0.45000000000000001"
    assert stored["variants"][1]["n"] == 10


def test_counts_may_arrive_as_integers():
    stats = parse_metric_rows(
        [
            _row(
                n=10,
                n_converted=4,
                metric_rows_in_window=12,
                metric_rows_matched=9,
                null_value_rows=0,
            )
        ]
    )
    assert stats.variants[0].n == 10


@pytest.mark.parametrize(
    "overrides",
    [
        {"n": "-1"},
        {"n": "1.5"},
        {"n": "1e3"},
        {"n": True},
        {"n": -3},
        {"n": " 10"},
        {"n": "10\n"},
        {"n_converted": "11"},
        {"sum_d2": "-0.0000001"},
        {"sum_d": "nan"},
        {"sum_d": "inf"},
        {"sum_d": "Infinity"},
        {"sum_d": "1e999"},
        {"sum_d": 0.5},  # a float that our SQL did not serialise
        {"sum_d": ""},
        {"sum_d": "0x1p3"},
        {"k": None},
        {"variant": None},
    ],
)
def test_invalid_values_refused(overrides):
    assert _code([_row(**overrides)]) == "result_invalid"


def test_duplicate_variant_refused():
    assert _code([_row(), _row()]) == "result_invalid"


def test_grand_mean_must_agree_between_rows():
    assert _code(_two(k="0.5")) == "result_invalid"


def test_diagnostic_counts_must_agree_between_rows():
    assert _code(_two(metric_rows_matched="3")) == "result_invalid"


def test_more_than_fifty_variants_refused():
    rows = [_row(variant=f"v{i}") for i in range(51)]
    assert _code(rows) == "too_many_variant_values"
    assert len(parse_metric_rows(rows[:50]).variants) == 50


def test_no_rows_is_no_units():
    assert _code([]) == "no_units"


def test_join_key_mismatch():
    assert _code([_row(metric_rows_matched="0")]) == "join_key_mismatch"
    # No metric rows at all is not a mismatch: nobody converted.
    stats = parse_metric_rows(
        [_row(metric_rows_in_window="0", metric_rows_matched="0")]
    )
    assert stats.metric_rows_in_window == 0


def test_labels_are_cut_to_64_characters_in_python_too():
    stats = parse_metric_rows([_row(variant="x" * 70)])
    assert stats.variants[0].variant == "x" * 64
    # Two labels equal in their first 64 characters are one label.
    assert (
        _code([_row(variant="x" * 64 + "a"), _row(variant="x" * 64 + "b")])
        == "result_invalid"
    )


def test_snowflake_session_must_be_utc():
    good = [_row(session_offset="+00:00")]
    assert (
        parse_metric_rows(good, expect_session_offset=True).session_offset == "+00:00"
    )
    for offset in ("-07:00", "+01:00", None, "+0000", "-00:00", "z", "Z ", "UTC", ""):
        assert (
            _code([_row(session_offset=offset)], expect_session_offset=True)
            == "timezone_not_utc"
        )


def _diag(**overrides):
    row = {
        "exposure_rows": "9",
        "null_key_rows": "2",
        "units": "5",
        "multi_variant_units": "1",
        "variant_values": "2",
    }
    row.update(overrides)
    return [row]


def test_diagnostics_parse():
    diag = parse_diagnostics_rows(_diag())
    assert (diag.units, diag.multi_variant_units) == (5, 1)


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        (_diag(units="0", multi_variant_units="0"), "no_units"),
        (_diag(variant_values="51"), "too_many_variant_values"),
        (_diag(multi_variant_units="6"), "result_invalid"),
        (_diag(null_key_rows="10"), "result_invalid"),
        (_diag(units="-1"), "result_invalid"),
        (_diag() + _diag(), "result_invalid"),
        ([], "result_invalid"),
    ],
)
def test_diagnostics_refusals(rows, code):
    with pytest.raises(WarehouseResultRefused) as refused:
        parse_diagnostics_rows(rows)
    assert refused.value.code == code


@pytest.mark.regression
def test_snowflake_writes_utc_as_z():
    """A real Snowflake UTC session reports ``Z``; metric and diagnostics rows accept it."""
    stats = parse_metric_rows([_row(session_offset="Z")], expect_session_offset=True)
    assert stats.session_offset == "Z"
    diag = parse_diagnostics_rows(_diag(session_offset="Z"), expect_session_offset=True)
    assert diag.session_offset == "Z"


def test_diagnostics_session_offset():
    with pytest.raises(WarehouseResultRefused) as refused:
        parse_diagnostics_rows(
            _diag(session_offset="-07:00"), expect_session_offset=True
        )
    assert refused.value.code == "timezone_not_utc"
