"""Centred sums through the whole wire: SQL -> 17-digit strings -> floats.

The per-arm mean and variance, and the difference of the centred means, are
derived from what the metric statement returns (``k``, ``sum_d``,
``sum_d2``) and compared with the exact reference on each fixture, at that
fixture's own tolerance (``numeric_fixtures``).  DuckDB's summation order
depends on its thread count, so both 1 and 8 threads are run.

The estimator that turns these sums into a p-value is core
(``mean_metric_result``, W1b); this test covers what the builder and the wire
contribute, which is where the naive form and a short serialisation lose
precision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd
import pytest

from modules.backend.app.services.warehouse_query_builder import (
    AnalysisWindow,
    AssignmentMapping,
    MetricMapping,
    build_metric_query,
)
from modules.backend.app.services.warehouse_sufficient_stats import parse_metric_rows
from modules.backend.tests.unit.warehouse import numeric_fixtures as nf
from modules.backend.tests.unit.warehouse.duckdb_adapter import (
    DUCKDB_SQL,
    DuckDBWarehouse,
)

pytestmark = pytest.mark.unit

UTC = timezone.utc
EXPOSED = pd.Timestamp("2026-09-02 00:00:00", tz="UTC")
EVENT = pd.Timestamp("2026-09-02 01:00:00", tz="UTC")
WINDOW = AnalysisWindow(
    datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 10, tzinfo=UTC)
)
ASSIGNMENT = AssignmentMapping(
    ("main", "exposures"), "user_id", "experiment_key", "variant", "exposed_at"
)
METRIC = MetricMapping(("main", "events"), "user_id", "event_at", "mean", "amount")


@lru_cache(maxsize=None)
def _fixture(name: str):
    fixture = nf.load(name)
    return fixture, nf.exact_arm(fixture.control), nf.exact_arm(fixture.treatment)


def _warehouse(fixture: nf.MeanFixture, threads: int) -> DuckDBWarehouse:
    wh = DuckDBWarehouse(threads=threads)
    arms = [("control", fixture.control), ("treatment", fixture.treatment)]
    ids = [f"{arm[0]}-{i}" for arm in arms for i in range(len(arm[1]))]
    wh.create_from_frame(
        "exposures",
        pd.DataFrame(
            {
                "user_id": ids,
                "experiment_key": "mean-fixture",
                "variant": [arm for arm, values in arms for _ in range(len(values))],
                "exposed_at": EXPOSED,
            }
        ),
    )
    values = [v for _, arm_values in arms for v in arm_values.tolist()]
    wh.create_from_frame(
        "events",
        pd.DataFrame({"user_id": ids, "event_at": EVENT, "amount": values}),
    )
    return wh


@pytest.mark.parametrize("threads", [1, 8])
@pytest.mark.parametrize("name", sorted(nf.FIXTURES))
def test_centred_sums_match_exact_reference(name: str, threads: int) -> None:
    fixture, exact_c, exact_t = _fixture(name)
    wh = _warehouse(fixture, threads)
    rows = wh.fetch(
        build_metric_query(DUCKDB_SQL, ASSIGNMENT, METRIC, "mean-fixture", WINDOW)
    )
    stats = parse_metric_rows(rows)
    arms = {v.variant: v for v in stats.variants}
    c, t = arms["control"], arms["treatment"]
    assert (c.n, t.n) == (exact_c.n, exact_t.n)

    def mean(arm):
        return stats.k + arm.sum_d / arm.n

    def variance(arm):
        return (arm.sum_d2 - arm.sum_d * arm.sum_d / arm.n) / (arm.n - 1)

    errors = {
        "mean_control": nf.relative_error(mean(c), exact_c.mean),
        "mean_treatment": nf.relative_error(mean(t), exact_t.mean),
        "variance_control": nf.relative_error(variance(c), exact_c.variance),
        "variance_treatment": nf.relative_error(variance(t), exact_t.variance),
        # The difference of the CENTRED means: k cancels and never re-enters.
        "difference": nf.relative_error(
            t.sum_d / t.n - c.sum_d / c.n, exact_t.mean - exact_c.mean
        ),
    }
    worst = max(errors.values())
    assert worst <= fixture.tolerance, (name, threads, errors)


def test_the_wire_probe_value_round_trips() -> None:
    """``0.1 + 0.2`` must come back as exactly ``0.30000000000000004``."""
    wh = DuckDBWarehouse()
    text = wh.con.execute(
        "SELECT " + DUCKDB_SQL.serialise("CAST(0.1 AS DOUBLE) + CAST(0.2 AS DOUBLE)")
    ).fetchone()[0]
    assert float(text) == 0.1 + 0.2
    assert text == "0.30000000000000004"
