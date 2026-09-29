"""The warehouse analysis page says what operators and source authors must know.

Each sentence below is a statement people act on -- what the connection's
role controls, what a run and a day can cost, what the daily limit does not
count -- and each is pinned so that it cannot be edited away unnoticed.  The
behaviour behind each is pinned by the modules' warehouse integration tests
(the daily limit, the capacity refusal, previews, connection tests).

Reads only docs/api/warehouse-analytics.md: no git and no `modules` import,
so it runs the same in `scripts/core_build.sh`'s copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PAGE = Path(__file__).resolve().parents[4] / "docs" / "api" / "warehouse-analytics.md"


def _text() -> str:
    # Joined into one line so a sentence may wrap anywhere.
    return re.sub(r"\s+", " ", PAGE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "claim",
    [
        # The role grant is the control.
        "Anyone who can author a source can compute aggregates, and read short "
        "text such as variant labels, over anything the connection's role can read.",
        # The cost of a run and of a day.
        "A run can cost at most (1 + metrics) × the per-query limit.",
        "The worst case for a day is `max_runs_per_day` × 11 × the per-query limit.",
        "analyses **and previews** on the connection per UTC day, whatever their outcome.",
        # What the daily limit does not count.
        "Connection tests and source validation are not counted by the daily limit.",
        "A refusal for capacity does not use a slot of the daily limit.",
        # No row of data leaves the warehouse.
        "No row of your data.",
    ],
)
def test_the_warehouse_page_states(claim):
    assert claim in _text()
