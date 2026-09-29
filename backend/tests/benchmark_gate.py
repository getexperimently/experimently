"""The ``benchmark`` marker: absolute wall-clock checks that no required job runs.

A test that asserts an absolute timing ("under 1 ms", "over 1000 ops/s")
measures the machine as much as the code. On a shared CI runner the same code
comes back 10-100x slower with nothing changed (#409: an average-latency
ceiling failed a pull request that did not touch the rules engine, with 6057
other tests passing). The required suites therefore assert the deterministic
property each timing stood for -- a compile count, a cache-hit count, the
number of conditions evaluated -- and the absolute numbers live in tests
marked ``@pytest.mark.benchmark``.

Those are skipped unless ``RUN_BENCHMARKS=1``. Nothing in the pull-request
gate sets it; the nightly ``benchmarks`` job does, and a red night files an
issue rather than blocking a merge. To run them by hand:

    RUN_BENCHMARKS=1 python -m pytest -m benchmark backend/tests/unit

Loaded by the repository-root conftest for every session rooted there, the
Lambda suites included. It must stay importable with only pytest installed
(tests/sdk-contract runs that way).
"""

from __future__ import annotations

import os

import pytest

ENV_VAR = "RUN_BENCHMARKS"


def benchmarks_enabled() -> bool:
    """True only for the exact value ``1``: anything else leaves them skipped."""
    return os.environ.get(ENV_VAR, "") == "1"


def pytest_collection_modifyitems(config, items):
    if benchmarks_enabled():
        return
    # `-m benchmark` without the variable would skip every selected test and
    # exit 0 having measured nothing -- the nightly job misconfigured would
    # look green for ever. Refuse it instead.
    if (config.getoption("markexpr", "") or "").strip() == "benchmark":
        raise pytest.UsageError(
            f"-m benchmark selects only benchmarks, and they run only with "
            f"{ENV_VAR}=1; without it every one would be skipped"
        )
    skip = pytest.mark.skip(
        reason=f"absolute-timing benchmark; set {ENV_VAR}=1 to run it"
    )
    for item in items:
        if item.get_closest_marker("benchmark") is not None:
            item.add_marker(skip)
