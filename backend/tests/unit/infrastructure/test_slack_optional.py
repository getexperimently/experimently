"""Deploy and Rollback without a Slack token: the Slack steps are skipped (#779).

Each workflow has two ``slackapi/slack-github-action`` steps. With no
``SLACK_BOT_TOKEN`` they used to run anyway and go red under
``continue-on-error`` ("Need to provide at least one botToken or
webhookUrl"), so every self-hosted run showed two failed steps in front of
the one that mattered.

The contract pinned here:

* the job's env carries ``SLACK_ON: ${{ secrets.SLACK_BOT_TOKEN != '' }}``
  ('true' or 'false', never the token), because a step's ``if:`` cannot read
  ``secrets``;
* the started step runs on ``env.SLACK_ON == 'true'``; the result step on
  ``always() && env.SLACK_ON == 'true'``, so a failed run still announces its
  ending when the token is set;
* both keep ``continue-on-error: true`` and the token in their own env, so a
  token that is set but wrong still shows red;
* the run summary carries exactly one line saying Slack was not notified,
  written by the job's last step and only when the token is unset;
* no ``if:`` in any workflow names ``secrets.`` (GitHub refuses to load it).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DEPLOY = WORKFLOWS / "deploy.yml"
ROLLBACK = WORKFLOWS / "rollback.yml"

if not DEPLOY.is_file() or not ROLLBACK.is_file():
    pytest.skip("this tree has no deploy workflows", allow_module_level=True)

#: Each workflow, the job that posts to Slack, and its two Slack steps.
CASES = [
    pytest.param(
        DEPLOY,
        "deploy",
        "Notify deployment started",
        "Notify deployment result",
        id="deploy",
    ),
    pytest.param(
        ROLLBACK,
        "rollback",
        "Notify rollback started",
        "Notify rollback result",
        id="rollback",
    ),
]

SLACK_ON = "${{ secrets.SLACK_BOT_TOKEN != '' }}"
STARTED_IF = "env.SLACK_ON == 'true'"
RESULT_IF = "always() && env.SLACK_ON == 'true'"
NOTE_IF = "always() && env.SLACK_ON != 'true'"
NOTE = (
    "Slack: not notified -- SLACK_BOT_TOKEN is not set "
    "(optional; docs/deployment/README.md)."
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _steps(path: Path, job: str) -> list[dict]:
    return _load(path)["jobs"][job]["steps"]


def _slack_steps(path: Path, job: str) -> list[dict]:
    return [
        s
        for s in _steps(path, job)
        if str(s.get("uses", "")).startswith("slackapi/slack-github-action@")
    ]


def _ifs(node: Any, where: str = "") -> Iterator[tuple[str, str]]:
    """Every `if:` value in a parsed workflow, with where it is."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{where}/{key}"
            if key == "if":
                yield here, str(value)
            yield from _ifs(value, here)
    elif isinstance(node, list):
        for i in range(len(node)):
            yield from _ifs(node[i], f"{where}[{i}]")


@pytest.mark.parametrize(("path", "job", "started", "result"), CASES)
def test_the_job_derives_slack_on_from_the_secret(path, job, started, result):
    env = _load(path)["jobs"][job]["env"]
    assert env.get("SLACK_ON") == SLACK_ON, env.get("SLACK_ON")


@pytest.mark.parametrize(("path", "job", "started", "result"), CASES)
def test_each_slack_step_is_gated_and_the_result_keeps_always(
    path, job, started, result
):
    steps = {s["name"]: s for s in _slack_steps(path, job)}
    assert sorted(steps) == sorted([started, result]), sorted(steps)
    assert str(steps[started].get("if", "")).strip() == STARTED_IF, steps[started]
    # always() first: without it a failed run never announces its ending.
    assert str(steps[result].get("if", "")).strip() == RESULT_IF, steps[result]


@pytest.mark.parametrize(("path", "job", "started", "result"), CASES)
def test_a_set_but_wrong_token_still_shows_red(path, job, started, result):
    """continue-on-error keeps the job going; the step itself still fails."""
    for step in _slack_steps(path, job):
        assert step.get("continue-on-error") is True, step["name"]
        assert step.get("env") == {
            "SLACK_BOT_TOKEN": "${{ secrets.SLACK_BOT_TOKEN }}"
        }, step["name"]
        assert set(step["with"]) == {"channel-id", "slack-message"}, step["name"]


@pytest.mark.parametrize(("path", "job", "started", "result"), CASES)
def test_the_summary_says_once_that_slack_was_not_notified(
    path, job, started, result, tmp_path
):
    assert path.read_text().count(NOTE) == 1
    steps = _steps(path, job)
    notes = [s for s in steps if NOTE in str(s.get("run", ""))]
    assert len(notes) == 1, [s.get("name") for s in notes]
    (note,) = notes
    # The job's last step, so the line ends the summary; only when unset.
    assert note is steps[-1], note.get("name")
    assert str(note.get("if", "")).strip() == NOTE_IF, note.get("if")
    # Run it as the runner would: exactly one line lands in the summary.
    summary = tmp_path / "summary.md"
    summary.write_text("before\n")
    proc = subprocess.run(
        ["bash", "-e", "-c", note["run"]],
        env={**os.environ, "GITHUB_STEP_SUMMARY": str(summary)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert summary.read_text() == f"before\n\n{NOTE}\n"


def test_no_if_in_any_workflow_names_secrets():
    """GitHub refuses to load a workflow whose `if:` reads `secrets`."""
    offenders = [
        f"{path.name}{where}: {value}"
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        for where, value in _ifs(_load(path))
        if "secrets." in value
    ]
    assert not offenders, offenders
