"""Unit tests for the arithmetic of the SDK evaluation ceilings.

The database half (the atomic upserts, the parallel reports) is in
``backend/tests/integration/api/test_flag_evaluations_api.py``.
"""

from datetime import datetime, timedelta

import pytest

from backend.app.services import sdk_evaluation_service as svc

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("total_after", "added", "ceiling", "expected"),
    [
        (10, 10, 100, 10),  # first report, well under
        (100, 100, 100, 100),  # exactly the ceiling
        (150, 150, 100, 100),  # first report over the ceiling
        (160, 60, 100, 0),  # the counter was already full
        (120, 60, 100, 40),  # straddles the ceiling
        (100, 40, 100, 40),  # lands exactly on it
        (1_100_000, 100_000, 1_000_000, 0),
    ],
)
def test_newly_accepted(total_after, added, ceiling, expected):
    assert svc._newly_accepted(total_after, added, ceiling) == expected


def test_the_ceilings_are_the_specified_values():
    assert svc.KEY_MINUTE_CEILING == 100_000
    assert svc.FLAG_MINUTE_CEILING == 1_000_000


def test_minute_of_drops_seconds():
    assert svc.minute_of(datetime(2026, 9, 27, 12, 34, 56, 789)) == datetime(
        2026, 9, 27, 12, 34
    )


def test_reports_are_merged_per_flag_and_sorted_by_key():
    t0 = datetime(2026, 9, 27, 12, 0)
    reports = [
        svc.EvaluationReport("b", 5, 1, t0, t0 + timedelta(seconds=30)),
        svc.EvaluationReport("a", 2, 0, t0, t0 + timedelta(seconds=10)),
        svc.EvaluationReport(
            "b", 7, 3, t0 - timedelta(seconds=5), t0 + timedelta(seconds=60)
        ),
    ]
    merged = svc.merge_reports(reports)
    assert [r.flag_key for r in merged] == ["a", "b"]
    assert merged[1] == svc.EvaluationReport(
        "b", 12, 4, t0 - timedelta(seconds=5), t0 + timedelta(seconds=60)
    )


def test_nothing_to_reserve_touches_no_counter():
    class _NoDb:
        def execute(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("reserve(0) must not write a counter")

    assert svc.reserve(_NoDb(), None, "flag", datetime(2026, 1, 1), 0) == 0
