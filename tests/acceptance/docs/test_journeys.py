"""One test per journey file: walk the guide, fail on the first step that fails.

The outcome of every journey, passed, failed or refused, goes into the run's
reports (``conftest.py``); the assertion here is what makes pytest's own exit
status red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docs_runner import report


def test_journey(journey_file: Path, walk_journey) -> None:
    outcome = walk_journey(journey_file)
    result = report.verdict(outcome)
    if result.word == "FAIL":
        pytest.fail(
            f"{outcome.journey}: {result.line}. {result.sentence}", pytrace=False
        )


def test_planted_skip(journey_file: Path) -> None:
    pytest.skip("planted")
