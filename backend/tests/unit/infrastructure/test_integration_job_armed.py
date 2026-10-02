"""The integration-tests job keeps the Redis-backed tests armed.

The Redis-backed tests under ``backend/tests/integration/`` (the experiment
cache, and the flag reads after every writer, #630) skip when no Redis answers, unless ``EXPERIMENTLY_REQUIRE_REDIS=1`` turns that
skip into a failure. The ``integration-tests`` workflow provides the ``redis``
service and sets the variable on the step that runs the suite, and nothing
pinned either: deleting the env line, the service, or narrowing the run with
``-m``/``-k`` would leave every cache test skipping green.

The same pattern as ``test_the_integration_job_is_armed`` in
``backend/tests/integration/database/test_core_tree_isolation.py``, which pins
the editable install for the core-tree tests. The workflow is read with the
duplicate-key-refusing loader from ``test_docs_only_gate.py``, so a second
``env:`` or ``run:`` key cannot hide the one GitHub reads.
"""

from __future__ import annotations

import shlex
from typing import Any, Dict, List

import pytest

from backend.tests.unit.infrastructure import _workflow_graph as wg

pytestmark = [pytest.mark.unit, pytest.mark.regression]

WORKFLOW = wg.WORKFLOWS / "integration-tests.yml"
JOB = "integration-tests"
SUITE = "backend/tests/integration/"


def _job() -> Dict[str, Any]:
    workflow = wg.load(WORKFLOW)
    jobs = workflow.get("jobs") or {}
    assert JOB in jobs, f"{WORKFLOW.name} has no `{JOB}` job: {sorted(jobs)}"
    return jobs[JOB]


def _tokens(run: str) -> List[str]:
    """The shell words of a ``run:`` block, comments and continuations removed."""
    return shlex.split(run.replace("\\\n", " "), comments=True)


def _pytest_args(tokens: List[str]) -> List[str]:
    """The words after ``pytest`` up to the end of that command."""
    assert "pytest" in tokens, tokens
    args: List[str] = []
    for token in tokens[tokens.index("pytest") + 1 :]:
        if token in {";", "&&", "||", "|"}:
            break
        args.append(token)
    return args


def _narrowing_flags(tokens: List[str]) -> List[str]:
    """Tokens that select a subset by marker or keyword: ``-m``, ``-k``, also
    attached (``-munit``) or bundled with other short flags (``-vk``)."""
    return [
        token
        for token in tokens
        if token.startswith("-")
        and not token.startswith("--")
        and ("m" in token[1:] or "k" in token[1:])
    ]


def _suite_steps(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        step
        for step in job.get("steps") or []
        if "run" in step
        and "pytest" in _tokens(step["run"])
        and any(t.rstrip("/") + "/" == SUITE for t in _tokens(step["run"]))
    ]


def _suite_step() -> Dict[str, Any]:
    steps = _suite_steps(_job())
    assert len(steps) == 1, (
        f"expected exactly one step that runs pytest on {SUITE}, found "
        f"{[s.get('name') for s in steps]}"
    )
    return steps[0]


def test_the_job_has_the_redis_service():
    services = _job().get("services") or {}
    assert "redis" in services, (
        f"the `{JOB}` job lost its `redis` service; with "
        "EXPERIMENTLY_REQUIRE_REDIS=1 every cache test fails, without it they "
        f"all skip: services are {sorted(services)}"
    )
    redis = services["redis"]
    assert str(redis.get("image", "")).startswith("redis:"), redis
    assert "6379:6379" in [str(p) for p in redis.get("ports") or []], redis


def test_the_suite_step_requires_redis():
    env = _suite_step().get("env") or {}
    assert env.get("EXPERIMENTLY_REQUIRE_REDIS") == "1", (
        "the step that runs the integration suite must set "
        'EXPERIMENTLY_REQUIRE_REDIS: "1", otherwise a missing Redis makes the '
        f"cache tests skip green; env is {env}"
    )


def test_the_suite_step_runs_the_whole_suite():
    step = _suite_step()
    tokens = _pytest_args(_tokens(step["run"]))
    assert SUITE in tokens, f"the step must run `{SUITE}` itself: {tokens}"
    assert not _narrowing_flags(tokens), (
        f"the step selects a subset with {_narrowing_flags(tokens)}; the "
        "Redis-backed tests carry no marker and would be deselected"
    )
    addopts = (step.get("env") or {}).get("PYTEST_ADDOPTS")
    if addopts is not None:
        assert not _narrowing_flags(shlex.split(str(addopts))), addopts


@pytest.mark.parametrize(
    "tokens, narrowed",
    [
        (["-v", "--tb=short"], False),
        (["--junit-xml=x.xml", "-x"], False),
        (["-m", "unit"], True),
        (["-munit"], True),
        (["-k", "x"], True),
        (["-vk", "x"], True),
    ],
)
def test_narrowing_flags_are_recognised(tokens, narrowed):
    assert bool(_narrowing_flags(tokens)) is narrowed
