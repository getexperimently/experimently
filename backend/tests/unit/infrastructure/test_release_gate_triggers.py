"""The Release Gate runs on every commit on main, and a push is never cancelled (#137).

`deploy`'s gate requires a `Release Gate Summary` on the commit a release tag
points at. With only `pull_request` and `workflow_dispatch`, no commit on main
ever had one, so no tag could deploy. And with the concurrency group keyed on
`github.ref` and `cancel-in-progress: true`, a burst of merges would cancel the
gate of the commit a release is cut from.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression]

WORKFLOW = (
    Path(__file__).resolve().parents[4] / ".github" / "workflows" / "release-gate.yml"
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    if not WORKFLOW.exists():
        pytest.skip("this tree has no .github/workflows")
    return yaml.safe_load(WORKFLOW.read_text())


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


def test_the_gate_runs_on_every_push_to_main(workflow):
    push = _triggers(workflow).get("push")
    assert push == {"branches": ["main"]}, (
        "Release Gate Summary never runs on a commit on main, so no tag can pass "
        f"deploy's gate (#137); push trigger is {push!r}"
    )


def test_a_push_to_main_is_keyed_by_its_commit_and_never_cancelled(workflow):
    concurrency = workflow["concurrency"]
    assert concurrency["group"] == (
        "release-gate-${{ github.event_name == 'pull_request' && github.ref || github.sha }}"
    ), "a push to main must not share a concurrency group with other pushes"
    assert (
        concurrency["cancel-in-progress"]
        == "${{ github.event_name == 'pull_request' }}"
    ), "a push to main can cancel the gate on the release commit"
