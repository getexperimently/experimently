"""Read and check what a warehouse statement returned.

The statements built by
:mod:`modules.backend.app.services.warehouse_query_builder` return aggregates
only.  This module turns the rows into typed values and refuses anything that
cannot be right, rather than analysing it:

* a count that is not a non-negative integer, ``n_converted > n``,
  ``sum_d2 < 0``, a duplicate variant row, a non-finite or unparseable number,
  or a grand mean that differs between rows -> ``result_invalid``;
* more than 50 variant rows -> ``too_many_variant_values`` (the variant column
  is probably mapped to the wrong column);
* metric rows in the window but none matched to an exposed unit ->
  ``join_key_mismatch``;
* zero units -> ``no_units``;
* a Snowflake session whose UTC offset is not ``+00:00`` ->
  ``timezone_not_utc``.

Floats arrive as the strings our SQL produced (at least 17 significant
digits) and are parsed with ``float(Decimal(text))``; the text is kept as
returned so a stored result can be checked against it later.  Counts may
arrive as integers or as digit strings, depending on the connector's wire.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Mapping, Optional, Sequence

from modules.backend.app.services.warehouse_query_builder import (
    LABEL_MAX_CHARS,
    MAX_VARIANT_VALUES,
)

SCHEMA_ID: Final = "experimently.warehouse.sufficient_statistics/v2"

_COUNT_TEXT: Final = re.compile(r"[0-9]{1,19}")
_FLOAT_TEXT: Final = re.compile(
    r"[+-]?(?:[0-9]{1,400}(?:\.[0-9]{0,400})?|\.[0-9]{1,400})(?:[eE][+-]?[0-9]{1,4})?"
)
UTC_OFFSET: Final = "+00:00"


class WarehouseResultRefused(ValueError):
    """The returned rows were refused; ``code`` is from a fixed set."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid(message: str) -> WarehouseResultRefused:
    return WarehouseResultRefused("result_invalid", message)


def parse_count(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{name} is not a count")
    if isinstance(value, int):
        if value < 0:
            raise _invalid(f"{name} is negative")
        return value
    if isinstance(value, str) and _COUNT_TEXT.fullmatch(value):
        return int(value)
    raise _invalid(f"{name} is not a non-negative integer")


def parse_float(value: Any, name: str) -> tuple[float, str]:
    """``(float, text)``; the text must be a plain decimal or exponent form."""
    if not isinstance(value, str) or not _FLOAT_TEXT.fullmatch(value):
        raise _invalid(f"{name} is not a number")
    try:
        exact = Decimal(value)
    except InvalidOperation:
        raise _invalid(f"{name} is not a number") from None
    if not exact.is_finite():
        raise _invalid(f"{name} is not finite")
    number = float(exact)
    if not math.isfinite(number):
        raise _invalid(f"{name} is not finite")
    return number, value


@dataclass(frozen=True)
class VariantSums:
    """One variant's sufficient statistics, centred on the grand mean ``k``."""

    variant: str
    n: int
    n_converted: int
    sum_d: float
    sum_d2: float
    sum_d_text: str
    sum_d2_text: str


@dataclass(frozen=True)
class MetricSufficientStatistics:
    k: float
    k_text: str
    variants: tuple[VariantSums, ...]
    metric_rows_in_window: int
    metric_rows_matched: int
    null_value_rows: int
    session_offset: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        """The stored form: exact strings as returned, counts as integers."""
        return {
            "schema": SCHEMA_ID,
            "k": self.k_text,
            "variants": [
                {
                    "variant": v.variant,
                    "n": v.n,
                    "n_converted": v.n_converted,
                    "sum_d": v.sum_d_text,
                    "sum_d2": v.sum_d2_text,
                }
                for v in self.variants
            ],
            "metric_rows_in_window": self.metric_rows_in_window,
            "metric_rows_matched": self.metric_rows_matched,
            "null_value_rows": self.null_value_rows,
            "session_offset": self.session_offset,
        }


def _check_offset(row: Mapping[str, Any], expect_session_offset: bool) -> Optional[str]:
    if not expect_session_offset:
        return None
    offset = row.get("session_offset")
    if offset != UTC_OFFSET:
        raise WarehouseResultRefused(
            "timezone_not_utc",
            "the warehouse session did not run in UTC; times would be compared in another zone",
        )
    return offset


def parse_metric_rows(
    rows: Sequence[Mapping[str, Any]], *, expect_session_offset: bool = False
) -> MetricSufficientStatistics:
    """Check and type the rows of one metric statement."""
    if len(rows) > MAX_VARIANT_VALUES:
        raise WarehouseResultRefused(
            "too_many_variant_values",
            f"more than {MAX_VARIANT_VALUES} variant values: a wrong column is"
            " probably mapped as the variant",
        )
    if not rows:
        raise WarehouseResultRefused("no_units", "no exposed units in the window")

    offset = None
    k_text: Optional[str] = None
    k = 0.0
    seen: set[str] = set()
    variants: list[VariantSums] = []
    diag: Optional[tuple[int, int, int]] = None
    for row in rows:
        offset = _check_offset(row, expect_session_offset)
        label = row.get("variant")
        if not isinstance(label, str):
            raise _invalid("a variant label is missing")
        label = label[:LABEL_MAX_CHARS]
        if label in seen:
            raise _invalid("a variant appears twice")
        seen.add(label)

        n = parse_count(row.get("n"), "n")
        n_converted = parse_count(row.get("n_converted"), "n_converted")
        if n_converted > n:
            raise _invalid("n_converted is larger than n")
        row_k, row_k_text = parse_float(row.get("k"), "k")
        if k_text is None:
            k, k_text = row_k, row_k_text
        elif row_k_text != k_text:
            raise _invalid("the grand mean differs between rows")
        sum_d, sum_d_text = parse_float(row.get("sum_d"), "sum_d")
        sum_d2, sum_d2_text = parse_float(row.get("sum_d2"), "sum_d2")
        if sum_d2 < 0:
            raise _invalid("sum_d2 is negative")
        row_diag = (
            parse_count(row.get("metric_rows_in_window"), "metric_rows_in_window"),
            parse_count(row.get("metric_rows_matched"), "metric_rows_matched"),
            parse_count(row.get("null_value_rows"), "null_value_rows"),
        )
        if diag is None:
            diag = row_diag
        elif row_diag != diag:
            raise _invalid("the diagnostic counts differ between rows")
        variants.append(
            VariantSums(label, n, n_converted, sum_d, sum_d2, sum_d_text, sum_d2_text)
        )

    assert diag is not None and k_text is not None
    if sum(v.n for v in variants) == 0:
        raise WarehouseResultRefused("no_units", "no exposed units in the window")
    in_window, matched, null_values = diag
    if in_window > 0 and matched == 0:
        raise WarehouseResultRefused(
            "join_key_mismatch",
            "metric rows exist in the window but none has the unit id of an exposed"
            " unit; check that both sources map the same identifier",
        )
    return MetricSufficientStatistics(
        k=k,
        k_text=k_text,
        variants=tuple(variants),
        metric_rows_in_window=in_window,
        metric_rows_matched=matched,
        null_value_rows=null_values,
        session_offset=offset,
    )


@dataclass(frozen=True)
class AssignmentDiagnostics:
    exposure_rows: int
    null_key_rows: int
    units: int
    multi_variant_units: int
    variant_values: int
    session_offset: Optional[str] = None


def parse_diagnostics_rows(
    rows: Sequence[Mapping[str, Any]], *, expect_session_offset: bool = False
) -> AssignmentDiagnostics:
    """Check and type the single row of the diagnostics statement."""
    if len(rows) != 1:
        raise _invalid("the diagnostics statement must return exactly one row")
    row = rows[0]
    offset = _check_offset(row, expect_session_offset)
    result = AssignmentDiagnostics(
        exposure_rows=parse_count(row.get("exposure_rows"), "exposure_rows"),
        null_key_rows=parse_count(row.get("null_key_rows"), "null_key_rows"),
        units=parse_count(row.get("units"), "units"),
        multi_variant_units=parse_count(
            row.get("multi_variant_units"), "multi_variant_units"
        ),
        variant_values=parse_count(row.get("variant_values"), "variant_values"),
        session_offset=offset,
    )
    if (
        result.multi_variant_units > result.units
        or result.null_key_rows > result.exposure_rows
    ):
        raise _invalid("the diagnostic counts are inconsistent")
    if result.variant_values > MAX_VARIANT_VALUES:
        raise WarehouseResultRefused(
            "too_many_variant_values",
            f"more than {MAX_VARIANT_VALUES} variant values: a wrong column is"
            " probably mapped as the variant",
        )
    if result.units == 0:
        raise WarehouseResultRefused("no_units", "no exposed units in the window")
    return result
