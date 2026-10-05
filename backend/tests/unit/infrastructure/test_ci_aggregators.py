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

The summary jobs are found, not listed: every job with such an ``if:`` that
REPORTS a required check name (R1). A job with no ``name:`` reports under its
id, so a selector reading ``job["name"]`` never saw an unnamed summary, and
none of the checks below applied to it.

And a required name produced by a job with ``needs`` must be one of those
summaries with ``if:`` exactly ``always()``, or a classified job that needs
only the classifier (R2). Otherwise a summary that lost its ``if:``, or gained
a docs-only lane in it, is skipped -- and branch protection accepts a skipped
check -- while simply dropping out of every check here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest
import yaml

from backend.tests.unit.infrastructure import _workflow_graph as wg
from backend.tests.unit.infrastructure.test_ci_classification import CLASSIFIED

pytestmark = [pytest.mark.unit, pytest.mark.regression]

if not wg.CONFIGURE_REPO.is_file() or not wg.WORKFLOWS.is_dir():
    pytest.skip("this tree has no .github/workflows", allow_module_level=True)

#: The summaries this test must find; if the selector stops finding one, the
#: test is no longer checking it.
EXPECTED = {
    "Release Gate Summary",
    "Security Scan Summary",
    "SDK Unit Tests",
    "integration-tests",
}

TYPED_RESULT = re.compile(r"needs\.[A-Za-z_][\w-]*\.result")

_needs = wg.needs_of


def _is_classified_work(workflow: str, job_id: str, job: Dict[str, Any]) -> bool:
    """A job that runs after a FAILED classifier so that it does its work.

    ``!cancelled() && (needs.changes.result != 'success' || ...)`` matches
    RUNS_AFTER_FAILURE but reads no results: it is a work job, not a summary.
    test_ci_classification.py pins its exact `if:` and its `needs:` to the
    classifier alone, so it has no other ancestor to miss.
    """
    row = CLASSIFIED.get(workflow, {}).get(job_id)
    return row is not None and row[1] == "changes" and _needs(job) == ["changes"]


def _summaries() -> List[wg.Summary]:
    return wg.select_summaries(
        wg.workflow_files(), wg.required_checks(), _is_classified_work
    )


SUMMARIES = _summaries()
IDS = [f"{w}:{j}" for w, j, _, _ in SUMMARIES]


def _reported(workflow: str, job_id: str) -> Set[str]:
    return wg.reported_names(wg.WORKFLOWS / workflow)[job_id]


def test_the_summaries_are_found():
    required = set(wg.required_checks())
    found = set()
    for workflow, job_id, _, _ in SUMMARIES:
        found |= _reported(workflow, job_id) & required
    assert found == EXPECTED


@pytest.mark.regression
def test_every_required_name_with_needs_runs_after_failure():
    """R2 on the real workflows."""
    problems = wg.unguarded_required_names(
        wg.workflow_files(), wg.required_checks(), _is_classified_work
    )
    assert not problems, "\n".join(problems)


@pytest.mark.regression
def test_every_job_after_a_failed_need_is_a_summary():
    """R3 in every workflow with a classifier or a required summary, not only
    pr-qa-gate.yml, and for any `if:` that can run after a failed need
    (`failure()`, `cancelled()`, `success() || failure()`), not only
    `always()` and `!cancelled()`."""
    required = wg.required_checks()
    scope = wg.r3_workflows(wg.workflow_files(), required, _is_classified_work)
    names = {p.name for p in scope}
    assert {
        "pr-qa-gate.yml",
        "sdk-unit-tests.yml",
        "integration-tests.yml",
        "release-gate.yml",
        "security-scan.yml",
    } <= names, sorted(names)
    problems = []
    for path in scope:
        problems += wg.unselected_runs_after_failure(
            path, required, _is_classified_work
        )
    assert not problems, "\n".join(problems)


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


# R1 and R2 against the defects they exist for, on synthetic workflows: an
# unnamed summary (QA E5), a summary with no `if:`, and one whose `if:` adds a
# docs-only lane.

UNNAMED_TYPED = """\
on: pull_request
jobs:
  shard:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        shard: [1, 2]
    steps:
      - run: pytest
  integration-tests:
    needs: shard
{if_line}    runs-on: ubuntu-latest
    steps:
      - run: test "${{{{ needs.shard.result }}}}" = success
"""


def _workflow(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "integration-tests.yml"
    path.write_text(text, encoding="utf-8")
    return path


def _no_classified(workflow: str, job_id: str, job: Dict[str, Any]) -> bool:
    return False


@pytest.mark.regression
def test_an_unnamed_summary_is_found_by_its_check_name(tmp_path):
    """R1: the summary reports `integration-tests` under its id, with no
    `name:`; the old selector (``job.get("name") in required``) never saw it,
    so its typed list of results went unreported."""
    path = _workflow(
        tmp_path, UNNAMED_TYPED.format(if_line="    if: ${{ !cancelled() }}\n")
    )
    found = wg.select_summaries([path], ["integration-tests"], _no_classified)
    assert [(w, j) for w, j, _, _ in found] == [
        ("integration-tests.yml", "integration-tests")
    ]
    assert "name" not in found[0][2]
    assert reads_all_needs(found[0][2])


@pytest.mark.regression
@pytest.mark.parametrize(
    "if_line",
    [
        "",
        "    if: ${{ always() && needs.shard.outputs.docs_only != 'true' }}\n",
        "    if: ${{ !cancelled() }}\n",
    ],
    ids=["no-if", "always-and-docs-only", "not-cancelled"],
)
def test_a_summary_that_can_skip_is_refused(tmp_path, if_line):
    """R2: no `if:` skips the summary when a shard fails (QA E5); an `if:` that
    adds a lane to always() skips it on that lane; `!cancelled()` reports
    cancelled. Each of these is refused by name."""
    path = _workflow(tmp_path, UNNAMED_TYPED.format(if_line=if_line))
    problems = wg.unguarded_required_names(
        [path], ["integration-tests"], _no_classified
    )
    assert len(problems) == 1, problems
    assert problems[0].startswith(
        "'integration-tests' (integration-tests.yml:integration-tests)"
    )


@pytest.mark.regression
@pytest.mark.parametrize("cond", wg.SUMMARY_IF)
def test_a_summary_on_exactly_always_is_accepted(tmp_path, cond):
    path = _workflow(tmp_path, UNNAMED_TYPED.format(if_line=f"    if: {cond}\n"))
    assert (
        wg.unguarded_required_names([path], ["integration-tests"], _no_classified) == []
    )


@pytest.mark.regression
def test_only_a_classified_job_needing_changes_alone_is_exempt(tmp_path):
    text = """\
on: pull_request
jobs:
  changes:
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
  other:
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
  unit-tests:
    name: Unit Tests
    needs: NEEDS
    if: ${{ !cancelled() }}
    runs-on: ubuntu-latest
    steps: [{run: pytest}]
"""

    def classified(workflow: str, job_id: str, job: Dict[str, Any]) -> bool:
        return job_id == "unit-tests" and _needs(job) == ["changes"]

    one = _workflow(tmp_path, text.replace("NEEDS", "changes"))
    assert wg.unguarded_required_names([one], ["Unit Tests"], classified) == []
    two = _workflow(tmp_path, text.replace("NEEDS", "[changes, other]"))
    assert wg.unguarded_required_names([two], ["Unit Tests"], classified)


# R3, widened, against the defects it exists for: a job on an `if:` that
# RUNS_AFTER_FAILURE misses, and the same shape outside pr-qa-gate.yml.


@pytest.mark.regression
@pytest.mark.parametrize(
    "cond",
    [
        "${{ success() || failure() }}",
        "${{ failure() || cancelled() }}",
        "${{ failure() }}",
        "${{ !success() }}",
    ],
)
def test_a_job_after_failure_on_any_status_function_is_refused(tmp_path, cond):
    """It reads no needs and reports no required name, and it runs after a
    shard failed. RUNS_AFTER_FAILURE matches none of these conditions, so the
    old R3 passed it."""
    text = UNNAMED_TYPED.format(if_line="    if: ${{ always() }}\n") + (
        "  late:\n"
        "    needs: [shard, integration-tests]\n"
        f"    if: {cond}\n"
        "    runs-on: ubuntu-latest\n"
        "    steps: [{run: pytest}]\n"
    )
    path = _workflow(tmp_path, text)
    assert not wg.RUNS_AFTER_FAILURE.search(cond) or "cancelled" in cond
    assert wg.r3_workflows([path], ["integration-tests"], _no_classified) == [path]
    assert wg.unselected_runs_after_failure(
        path, ["integration-tests"], _no_classified
    ) == [
        f"integration-tests.yml:late runs after a failed need (if: {cond!r}) and "
        "needs ['integration-tests', 'shard'] beyond changes, but is not a "
        "required summary"
    ]


@pytest.mark.regression
def test_a_job_after_failure_in_sdk_unit_tests_is_refused(tmp_path):
    """The real sdk-unit-tests.yml with one job added: it runs after a failed
    lane and is not its summary. The old R3 read pr-qa-gate.yml alone."""
    real = wg.WORKFLOWS / "sdk-unit-tests.yml"
    path = tmp_path / real.name
    path.write_text(
        real.read_text(encoding="utf-8").rstrip("\n") + "\n\n  late:\n"
        "    needs: [changes, linux]\n"
        "    if: ${{ success() || failure() }}\n"
        "    runs-on: ubuntu-latest\n"
        '    steps: [{run: "true"}]\n',
        encoding="utf-8",
    )
    required = wg.required_checks()
    assert wg.r3_workflows([real], required, _is_classified_work) == [real]
    assert wg.unselected_runs_after_failure(real, required, _is_classified_work) == []
    assert wg.r3_workflows([path], required, _is_classified_work) == [path]
    assert wg.unselected_runs_after_failure(path, required, _is_classified_work) == [
        "sdk-unit-tests.yml:late runs after a failed need (if: "
        "'${{ success() || failure() }}') and needs ['linux'] beyond changes, "
        "but is not a required summary"
    ]


def test_a_notifier_outside_the_scope_is_left_alone(tmp_path):
    """No classifier and no required summary: nightly-qa's failure issue."""
    path = tmp_path / "nightly.yml"
    path.write_text(
        "on: schedule\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
        '    steps: [{run: "true"}]\n  issue:\n    needs: a\n'
        "    if: failure()\n    runs-on: ubuntu-latest\n"
        '    steps: [{run: "true"}]\n',
        encoding="utf-8",
    )
    assert wg.r3_workflows([path], ["integration-tests"], _no_classified) == []
