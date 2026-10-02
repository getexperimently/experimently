"""A required summary job reads every job it needs, and needs every ancestor (C2, C3).

A summary job runs with ``if: always()`` (or ``!cancelled()``) and turns the
results of the jobs in its ``needs`` into one required check. Two ways it can
be green over a failure:

* **It reads a typed list, not ``needs``** (C2). ``Release Gate Summary``
  checked ``needs.backend-gate.result`` and two more by name; a fourth gate
  added to ``needs`` would have failed and the summary stayed green. It now
  reads ``toJSON(needs)``, as the scan workflow's summary already did after
  the same defect hid one of its jobs.
* **Its ``needs`` is not transitively closed** (C3). When an upstream job
  fails, every job below it is skipped, and a summary that accepts
  ``skipped`` (``SDK Unit Tests`` does, for SDKs a change does not touch)
  sees only the skips -- unless the failed ancestor is in its own ``needs``.

The summary jobs are found, not listed: every job with such an ``if:`` whose
name is a required check.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

import pytest
import yaml

from backend.tests.unit.infrastructure import _workflow_graph as wg

pytestmark = [pytest.mark.unit, pytest.mark.regression]

if not wg.CONFIGURE_REPO.is_file() or not wg.WORKFLOWS.is_dir():
    pytest.skip("this tree has no .github/workflows", allow_module_level=True)

#: The summaries this test must find; if the selector stops finding one, the
#: test is no longer checking it.
EXPECTED = {"Release Gate Summary", "Security Scan Summary", "SDK Unit Tests"}

RUNS_AFTER_FAILURE = re.compile(r"always\(\)|!\s*cancelled\(\)")
TYPED_RESULT = re.compile(r"needs\.[A-Za-z_][\w-]*\.result")


def _needs(job: Dict[str, Any]) -> List[str]:
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


def _summaries() -> List[Tuple[str, str, Dict[str, Any], Dict[str, Any]]]:
    required = set(wg.required_checks())
    found = []
    for path in wg.workflow_files():
        workflow = wg.load(path)
        for job_id, job in (workflow.get("jobs") or {}).items():
            if not _needs(job) or not RUNS_AFTER_FAILURE.search(str(job.get("if", ""))):
                continue
            if job.get("name") in required:
                found.append((path.name, job_id, job, workflow["jobs"]))
    return found


SUMMARIES = _summaries()
IDS = [f"{w}:{j}" for w, j, _, _ in SUMMARIES]


def test_the_summaries_are_found():
    assert {job["name"] for _, _, job, _ in SUMMARIES} == EXPECTED


def reads_all_needs(job: Dict[str, Any]) -> List[str]:
    """Problems with how a summary reads its needs; empty when it is sound."""
    problems = []
    text = yaml.safe_dump(job)
    typed = sorted(set(TYPED_RESULT.findall(text)))
    if typed:
        problems.append(f"reads a typed list of results, not toJSON(needs): {typed}")
    readers = [
        step
        for step in job.get("steps") or []
        if any(
            re.fullmatch(r"\$\{\{\s*toJSON\(needs\)\s*\}\}", str(v))
            for v in (step.get("env") or {}).values()
        )
    ]
    if not readers:
        problems.append("no step reads ${{ toJSON(needs) }}")
    return problems


def missing_ancestors(job: Dict[str, Any], jobs: Dict[str, Any]) -> Set[str]:
    direct = set(_needs(job))
    ancestors: Set[str] = set()
    todo = list(direct)
    while todo:
        for parent in _needs(jobs[todo.pop()]):
            if parent not in ancestors:
                ancestors.add(parent)
                todo.append(parent)
    return ancestors - direct


@pytest.mark.regression
@pytest.mark.parametrize("workflow, job_id, job, jobs", SUMMARIES, ids=IDS)
def test_summary_reads_all_needs(workflow, job_id, job, jobs):
    problems = reads_all_needs(job)
    assert not problems, f"{workflow} {job_id}: " + "; ".join(problems)


@pytest.mark.regression
@pytest.mark.parametrize("workflow, job_id, job, jobs", SUMMARIES, ids=IDS)
def test_needs_are_transitively_closed(workflow, job_id, job, jobs):
    missing = missing_ancestors(job, jobs)
    assert not missing, (
        f"{workflow} {job_id}: missing ancestors: {sorted(missing)}. A failure "
        "there skips the jobs this summary reads, and it never sees the failure."
    )


# The checks themselves, against the defects they exist for.


def test_a_typed_list_is_refused():
    job = {
        "needs": ["a", "b"],
        "if": "always()",
        "steps": [{"run": 'test "${{ needs.a.result }}" = success'}],
    }
    assert reads_all_needs(job)


def test_a_dropped_ancestor_is_found():
    jobs = {"changes": {}, "linux": {"needs": "changes"}, "sum": {"needs": ["linux"]}}
    assert missing_ancestors(jobs["sum"], jobs) == {"changes"}
