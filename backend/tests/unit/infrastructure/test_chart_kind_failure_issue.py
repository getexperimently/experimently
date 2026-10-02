"""A red chart-kind run on main, the nightly or a dispatch files an issue (PR-2').

chart-kind's ``failure-issue`` job is a copy of Doc Examples' job of that name,
which has opened real issues on red runs (#110, #112, #353). The copy is held
identical here: the two jobs are compared as parsed YAML after replacing the
few values that must differ -- ``needs``, the issue title, the workflow named
in the body, and the label and its description. Anything else that drifts (a
permission, the ``if:``, a step, the de-duplication query) fails the test, in
either file. A static pin rather than a run that fails on purpose: the pattern
has already fired in production, and identity with it is the property (EM C7b).

Every workflow is loaded with the duplicate-key-refusing loader, so a second
``if:`` or ``permissions:`` key cannot make this test read one value while
GitHub reads the other.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from backend.tests.unit.infrastructure import _workflow_graph as wg

pytestmark = [pytest.mark.unit, pytest.mark.regression]

if not wg.WORKFLOWS.is_dir():
    pytest.skip("this tree has no .github/workflows", allow_module_level=True)

DOC_EXAMPLES = wg.WORKFLOWS / "doc-examples.yml"
CHART_KIND = wg.WORKFLOWS / "chart-kind.yml"

#: (Doc Examples' text, chart-kind's text, occurrences in the run script).
#: The count is checked on Doc Examples' side, so a renamed label there cannot
#: leave half the copy pointing at the old one.
RUN_SUBSTITUTIONS = [
    (
        'TITLE="Documentation examples are red"',
        'TITLE="The Helm chart on kind is red"',
        1,
    ),
    ('BODY="Doc Examples failed on', 'BODY="Chart (kind) failed on', 1),
    ('--description "Doc Examples failed"', '--description "Chart (kind) failed"', 1),
    ("doc-examples-failure", "chart-kind-failure", 3),
]

IF = (
    "${{ github.event_name != 'pull_request' && !cancelled() && "
    "(failure() || contains(needs.*.result, 'cancelled')) }}"
)


def _job(path, name="failure-issue") -> Dict[str, Any]:
    jobs = wg.load(path).get("jobs") or {}
    assert name in jobs, f"{path.name} has no `{name}` job"
    return jobs[name]


def expected_chart_kind_job(doc_examples_job: Dict[str, Any]) -> Dict[str, Any]:
    """Doc Examples' job with only the values that must differ replaced."""
    job = copy.deepcopy(doc_examples_job)
    job["needs"] = ["chart-kind"]
    (step,) = job["steps"]
    run = step["run"]
    for old, new, count in RUN_SUBSTITUTIONS:
        assert run.count(old) == count, (
            f"Doc Examples' script has {old!r} {run.count(old)} times"
        )
        run = run.replace(old, new)
    step["run"] = run
    return job


def chart_kind_problems(chart_kind_job: Any, doc_examples_job: Dict[str, Any]) -> list:
    expected = expected_chart_kind_job(doc_examples_job)
    if chart_kind_job == expected:
        return []
    if not isinstance(chart_kind_job, dict):
        return [f"not a job: {chart_kind_job!r}"]
    keys = sorted(set(expected) | set(chart_kind_job))
    return [
        f"{key}: {chart_kind_job.get(key)!r} != {expected.get(key)!r}"
        for key in keys
        if chart_kind_job.get(key) != expected.get(key)
    ]


def test_the_chart_kind_failure_issue_job_is_doc_examples_job():
    assert chart_kind_problems(_job(CHART_KIND), _job(DOC_EXAMPLES)) == []


def test_it_waits_for_every_other_job_in_the_workflow():
    """`needs` is the one structural difference; it must cover all the work."""
    jobs = wg.load(CHART_KIND)["jobs"]
    assert set(_job(CHART_KIND)["needs"]) == set(jobs) - {"failure-issue"}


def test_it_files_on_a_red_or_timed_out_run_off_a_pull_request_only():
    """Literal, so a change made to both files at once is still seen here."""
    job = _job(CHART_KIND)
    assert job["if"] == IF
    assert job["permissions"] == {"contents": "read", "issues": "write"}


def test_it_is_the_only_job_that_can_write_issues():
    jobs = wg.load(CHART_KIND)["jobs"]
    writers = [
        name
        for name, job in jobs.items()
        if (job.get("permissions") or {}).get("issues") == "write"
    ]
    assert writers == ["failure-issue"]
    assert wg.load(CHART_KIND)["permissions"] == {"contents": "read"}


# ---------------------------------------------------------------------------
# The check catches what it claims to
# ---------------------------------------------------------------------------


def _tampered(mutate) -> Any:
    job = copy.deepcopy(_job(CHART_KIND))
    return mutate(job)


def _drop_issue_write(job):
    job["permissions"]["issues"] = "read"
    return job


def _plain_failure_if(job):
    job["if"] = "${{ github.event_name != 'pull_request' && failure() }}"
    return job


def _no_dedup(job):
    job["steps"][0]["run"] = job["steps"][0]["run"].replace(
        "--state open --label chart-kind-failure", "--state open"
    )
    return job


def _extra_step(job):
    job["steps"].append({"run": "true"})
    return job


@pytest.mark.parametrize(
    "mutate", [_drop_issue_write, _plain_failure_if, _no_dedup, _extra_step]
)
def test_a_drifted_copy_is_refused(mutate):
    assert chart_kind_problems(_tampered(mutate), _job(DOC_EXAMPLES)) != []


def test_a_missing_job_is_refused():
    assert chart_kind_problems(None, _job(DOC_EXAMPLES)) != []
