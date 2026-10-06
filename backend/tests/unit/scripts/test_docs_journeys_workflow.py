"""``docs-journeys.yml`` runs the docs journeys nightly and by hand, holds only
what each job needs, uploads only its run directory, and posts only rendered
text, only from a scheduled run on ``main``.

The workflow runs in a public repository and posts issues, so its shape is
pinned rather than reviewed once:

* triggers: a daily cron on a minute other than :00 and :30, and a manual
  dispatch whose one input is the boolean ``record_video`` (default false);
  nothing a pull request or a push can start;
* ``permissions: {contents: read}`` at the top; the journeys job adds only
  ``deployments: read`` (which commit the live docs site was built from), the
  report job only ``issues: write`` and ``actions: read`` (earlier runs'
  verdicts); no ``id-token``, no ``secrets``; one concurrency group per ref,
  never cancelled;
* the journeys job installs the runner's pinned requirements and Chromium,
  checks out the deployed site's source by the commit
  ``docs_journeys_report.py deployed`` names, and runs the runner's own pytest
  root with its run directory, that source, the ref it was taken from (the
  crawls say which they compared the site with) and the video switch; every
  upload is of the run directory or a file in it, kept 14 days (90 on a
  release tag);
* the report job runs only after verdicts were written; it posts only on a
  scheduled run on ``main``, and every step of the workflow whose script posts
  (``gh issue create|comment``, ``gh api``) is that one step with that
  condition; everything posted goes through ``--body-file`` from a rendered
  file, the issue title is the rendered title file's first line, and no script
  holds an expression, prints a file other than the summary or annotates with
  non-literal text.

Every rule is also planted against the real workflow below, so a rule that
stops firing fails here.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

from backend.tests.unit.infrastructure.test_docs_only_gate import _load

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs-journeys.yml"

RUN_DIR = "${{ runner.temp }}/docs-journeys-run"
SOURCE = "${{ runner.temp }}/published-source"
JOB_PERMISSIONS = {
    "journeys": {"contents": "read", "deployments": "read"},
    "report": {"contents": "read", "issues": "write", "actions": "read"},
}
WALK = "Walk the journeys"
WALK_RUN = "python -m pytest -c tests/acceptance/docs/pytest.ini tests/acceptance/docs"
WALK_ENV = {
    "DOCS_JOURNEY_RUN_DIR": RUN_DIR,
    "DOCS_JOURNEY_PUBLISHED_SOURCE": SOURCE,
    "DOCS_JOURNEY_PUBLISHED_REF": "${{ steps.source.outputs.ref }}",
    "DOCS_JOURNEY_RECORD_VIDEO": "${{ inputs.record_video && '1' || '0' }}",
    "PYTHONDONTWRITEBYTECODE": "1",
}
SOURCE_STEP = "Check out the source of the published site"
SOURCE_LINES = [
    "set -euo pipefail",
    'python3 scripts/docs_journeys_report.py deployed --out "$RUNNER_TEMP/deployed"',
    'SHA="$(head -n 1 "$RUNNER_TEMP/deployed/sha")"',
    r'''printf 'ref=%s\n' "$(head -n 1 "$RUNNER_TEMP/deployed/ref")" >> "$GITHUB_OUTPUT"''',
    'git fetch --no-tags --depth=1 origin "$SHA"',
    'mkdir -p "$RUNNER_TEMP/published-source"',
    'git archive "$SHA" mkdocs.yml docs | tar -x -C "$RUNNER_TEMP/published-source"',
]
INSTALL_LINES = [
    "set -euo pipefail",
    "python -m pip install -r tests/acceptance/requirements.txt",
    "python -m playwright install --with-deps chromium",
]
POST = "Post to the docs-journey-failure issues"
POST_IF = "github.event_name == 'schedule' && github.ref == 'refs/heads/main'"
REPORT_IF = "always() && needs.journeys.outputs.verdicts == 'true'"
RENDERED_BODY = '"$DIR/body.md"'
RENDERED_TITLE = '"$(head -n 1 "$DIR/title.txt")"'
SUMMARY_LINE = (
    'cat "$RUNNER_TEMP/docs-journeys-run/summary.md" >> "$GITHUB_STEP_SUMMARY"'
)
CLOSE_LINE = (
    'gh api --method PATCH "repos/$GITHUB_REPOSITORY/issues/$ISSUE" '
    "-f state=closed -f state_reason=completed > /dev/null"
)
RETENTION = "${{ startsWith(github.ref, 'refs/tags/v') && 90 || 14 }}"
POSTS = re.compile(
    r"\bgh\s+(?:issue|pr)\s+(?:create|comment|edit|close|reopen|review)\b"
)


def _condition(node: Dict[str, Any]) -> str:
    return " ".join(str(node.get("if") or "").split())


def triggers(doc: Dict[Any, Any]) -> Dict[str, Any]:
    on = doc.get("on", doc.get(True))
    return on if isinstance(on, dict) else dict.fromkeys(on)


def steps_of(doc) -> List[Dict[str, Any]]:
    return [step for job in doc["jobs"].values() for step in job.get("steps") or []]


def script_lines(doc) -> List[str]:
    lines = []
    for step in steps_of(doc):
        if isinstance(step.get("run"), str):
            lines += step["run"].replace("\\\n", " ").splitlines()
    return lines


def _lines(step: Dict[str, Any]) -> List[str]:
    return [
        line.strip() for line in str(step.get("run") or "").splitlines() if line.strip()
    ]


#: Any ``gh`` command at all. The posting rule fails closed: a step that runs
#: one is treated as posting, whatever its verb (``gh label create``,
#: ``gh pr merge``, ``gh  api`` with two spaces: an allowlist of verbs let each
#: of those through), so it must be the POST step with POST_IF.
GH_COMMAND = re.compile(r"(?:^|[\s;&|(`])gh\s+[a-z]")


def _posts(step: Dict[str, Any]) -> bool:
    """True when the step's script runs any ``gh`` command (comment lines aside)."""
    script = str(step.get("run") or "").replace("\\\n", " ")
    return any(
        GH_COMMAND.search(line)
        for line in script.splitlines()
        if not line.lstrip().startswith("#")
    )


def _named(doc, name):
    return next((s for s in steps_of(doc) if s.get("name") == name), None)


def workflow_problems(doc: Dict[Any, Any], text: str) -> List[str]:
    found: List[str] = []
    on = triggers(doc)
    if set(on) != {"schedule", "workflow_dispatch"}:
        found.append(f"triggers are {sorted(on)}, not schedule and workflow_dispatch")
    crons = [entry.get("cron", "") for entry in on.get("schedule") or []]
    if len(crons) != 1 or not re.fullmatch(r"[0-9]{1,2} [0-9]{1,2} \* \* \*", crons[0]):
        found.append(f"the schedule {crons} is not one daily cron at a fixed minute")
    elif int(crons[0].split()[0]) in (0, 30):
        found.append(f"cron {crons[0]!r} starts on :00 or :30")
    inputs = ((on.get("workflow_dispatch") or {}).get("inputs")) or {}
    video = inputs.get("record_video") or {}
    if (
        set(inputs) != {"record_video"}
        or video.get("type") != "boolean"
        or (video.get("default") is not False)
    ):
        found.append(
            "the dispatch's inputs are not exactly record_video, a boolean, default false"
        )
    if doc.get("permissions") != {"contents": "read"}:
        found.append(f"permissions are {doc.get('permissions')}, not contents read")
    if "id-token" in text:
        found.append("id-token appears in the workflow")
    if "secrets." in text or "secrets: inherit" in text:
        found.append("the workflow reads a secret")
    if doc.get("concurrency") != {
        "group": "docs-journeys-${{ github.ref }}",
        "cancel-in-progress": False,
    }:
        found.append("concurrency is not one group per ref, never cancelled")

    jobs = doc["jobs"]
    if set(jobs) != set(JOB_PERMISSIONS):
        found.append(f"jobs are {sorted(jobs)}, not {sorted(JOB_PERMISSIONS)}")
    for job_id, job in jobs.items():
        if job.get("permissions") != JOB_PERMISSIONS.get(job_id):
            found.append(f"{job_id}'s permissions are {job.get('permissions')}")
        if "environment" in job or "uses" in job or "secrets" in job:
            found.append(f"{job_id} is bound to an environment or calls a workflow")
    if _condition(jobs.get("report") or {}) != REPORT_IF:
        found.append("the report job does not run only after verdicts were written")
    if (jobs.get("report") or {}).get("needs") != "journeys":
        found.append("the report job does not wait for the journeys")

    install = _named(doc, "Install the runner and Chromium")
    if install is None or _lines(install) != INSTALL_LINES:
        found.append(
            "the runner is not installed from tests/acceptance/requirements.txt with"
            " Chromium"
        )
    source = _named(doc, SOURCE_STEP)
    if source is None or _lines(source) != SOURCE_LINES or source.get("id") != "source":
        found.append(
            "the site's source is not the commit of its live deployment"
            " (docs_journeys_report.py deployed)"
        )
    walk = _named(doc, WALK)
    if walk is None or walk.get("run") != WALK_RUN or walk.get("env") != WALK_ENV:
        found.append(
            "the journeys do not run the runner's pytest root with its run directory,"
            " the deployed source, its ref and the video switch"
        )

    for step in steps_of(doc):
        uses = str(step.get("uses") or "")
        settings = step.get("with") or {}
        if "upload-artifact" in uses:
            path = str(settings.get("path", ""))
            if path != RUN_DIR and not path.startswith(RUN_DIR + "/"):
                found.append(f"uploads {path!r}, which is outside the run directory")
            if "\n" in path or "*" in path or ".." in path:
                found.append(f"uploads more than one path or a pattern: {path!r}")
            if path == RUN_DIR and settings.get("retention-days") != RETENTION:
                found.append("the run directory is not kept 14 days (90 on a tag)")
        for name, value in (step.get("env") or {}).items():
            if name == "GH_TOKEN" and value != "${{ github.token }}":
                found.append("GH_TOKEN is not the workflow's own token")
    post = _named(doc, POST)
    if post is None or _condition(post) != POST_IF:
        found.append("posting is not limited to a scheduled run on main")
    for step in steps_of(doc):
        if _posts(step) and (step.get("name") != POST or _condition(step) != POST_IF):
            found.append(
                f"a step that posts is not the {POST!r} step with its condition:"
                f" {step.get('name')!r}"
            )

    for line in script_lines(doc):
        stripped = line.strip()
        if "${{" in line:
            found.append(f"an expression inside a script: {stripped}")
        if re.search(r"(^|[\s;|&(])(echo|set -x|env|printenv)\b", line):
            found.append(f"prints from the shell: {stripped}")
        if re.search(r"::(error|warning|notice)", line) and "$" in line:
            found.append(f"an annotation with non-literal text: {stripped}")
        if POSTS.search(line):
            if (
                re.search(r"(?<!\S)(--body|-b)(?=[\s=])", line)
                or f"--body-file {RENDERED_BODY}" not in line
            ):
                found.append(f"posts without --body-file {RENDERED_BODY}: {stripped}")
            if "--title" in line and f"--title {RENDERED_TITLE}" not in line:
                found.append(
                    f"a title that is not the rendered title's first line: {stripped}"
                )
            if re.search(r"\bgh\s+issue\s+(close|edit|reopen)\b|\bgh\s+pr\b", line):
                found.append(f"posts other than create or comment: {stripped}")
        if "gh api" in line and stripped != CLOSE_LINE:
            found.append(f"a gh api call other than closing an issue: {stripped}")
        if "GITHUB_STEP_SUMMARY" in line and stripped != SUMMARY_LINE:
            found.append(f"writes the step summary other than summary.md: {stripped}")
        if re.search(r"\bcat\b", line) and stripped != SUMMARY_LINE:
            found.append(f"prints a file: {stripped}")
    return found


def real():
    return _load(WORKFLOW), WORKFLOW.read_text(encoding="utf-8")


def test_the_docs_journeys_workflow_keeps_its_shape():
    doc, text = real()
    assert len(steps_of(doc)) >= 12, "found almost no steps: the reader is broken"
    assert workflow_problems(doc, text) == []


# ---------------------------------------------------------------------------
# Planted defects
# ---------------------------------------------------------------------------
def _set(path, value):
    def plant(doc, text):
        target = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return doc, text

    return plant


def _schedule(cron):
    def plant(doc, text):
        triggers(doc)["schedule"] = [{"cron": cron}]
        return doc, text

    return plant


def _add_trigger(name):
    def plant(doc, text):
        triggers(doc)[name] = None
        return doc, text

    return plant


def _step_set(name, key, value):
    def plant(doc, text):
        _named(doc, name)[key] = value
        return doc, text

    return plant


def _replace_in(name, old, new):
    """Replace the first *old* in the step's script."""

    def plant(doc, text):
        step = _named(doc, name)
        assert old in step["run"], old
        step["run"] = step["run"].replace(old, new, 1)
        return doc, text

    return plant


def _env(name, key, value):
    def plant(doc, text):
        env = dict(_named(doc, name).get("env") or {})
        env[key] = value
        _named(doc, name)["env"] = env
        return doc, text

    return plant


def _add_step(job, step):
    def plant(doc, text):
        doc["jobs"][job]["steps"].append(step)
        return doc, text

    return plant


def _upload(path):
    def plant(doc, text):
        doc["jobs"]["journeys"]["steps"].append(
            {"uses": "actions/upload-artifact@v7", "with": {"name": "x", "path": path}}
        )
        return doc, text

    return plant


def _text(old, new):
    def plant(doc, text):
        assert old in text, old
        return doc, text.replace(old, new)

    return plant


def _dispatch_inputs(inputs):
    def plant(doc, text):
        triggers(doc)["workflow_dispatch"] = {"inputs": inputs}
        return doc, text

    return plant


VIDEO = {"description": "x", "type": "boolean", "default": False}
#: (id, plant, a fragment the problems must contain)
PLANTS: List[tuple] = [
    ("pull-request-trigger", _add_trigger("pull_request"), "triggers are"),
    ("push-trigger", _add_trigger("push"), "triggers are"),
    ("cron-on-the-hour", _schedule("0 3 * * *"), "on :00"),
    ("cron-every-hour", _schedule("41 * * * *"), "daily"),
    (
        "video-on-by-default",
        _dispatch_inputs({"record_video": {**VIDEO, "default": True}}),
        "record_video",
    ),
    (
        "video-a-string",
        _dispatch_inputs({"record_video": {**VIDEO, "type": "string"}}),
        "record_video",
    ),
    (
        "another-input",
        _dispatch_inputs({"record_video": VIDEO, "source": {"type": "string"}}),
        "record_video",
    ),
    (
        "top-issues-write",
        _set(["permissions"], {"contents": "read", "issues": "write"}),
        "permissions are",
    ),
    (
        "id-token",
        _text("deployments: read", "deployments: read\n      id-token: write"),
        "id-token",
    ),
    (
        "a-secret",
        _text("${{ github.token }}", "${{ secrets.GITHUB_TOKEN }}"),
        "reads a secret",
    ),
    (
        "journeys-may-post",
        _set(
            ["jobs", "journeys", "permissions"], {"contents": "read", "issues": "write"}
        ),
        "journeys's permissions",
    ),
    (
        "report-writes-contents",
        _set(
            ["jobs", "report", "permissions"],
            {"contents": "write", "issues": "write", "actions": "read"},
        ),
        "report's permissions",
    ),
    ("cancelled", _set(["concurrency", "cancel-in-progress"], True), "concurrency"),
    ("one-group", _set(["concurrency", "group"], "docs-journeys"), "concurrency"),
    ("report-always", _set(["jobs", "report", "if"], "always()"), "after verdicts"),
    (
        "post-on-any-run",
        _step_set(POST, "if", "github.ref == 'refs/heads/main'"),
        "scheduled run on main",
    ),
    (
        "post-or",
        _step_set(
            POST,
            "if",
            "github.event_name == 'schedule' || github.ref == 'refs/heads/main'",
        ),
        "scheduled run on main",
    ),
    (
        "second-step-comments",
        _add_step(
            "report",
            {
                "name": "Comment again",
                "run": 'gh issue comment 1 --repo "$GITHUB_REPOSITORY"'
                ' --body-file "$DIR/body.md"',
            },
        ),
        "a step that posts",
    ),
    (
        "second-step-opens",
        _add_step(
            "report",
            {
                "name": "Open again",
                "if": POST_IF,
                "run": 'gh issue create --repo "$GITHUB_REPOSITORY"'
                ' --title "$(head -n 1 "$DIR/title.txt")"'
                ' --body-file "$DIR/body.md"',
            },
        ),
        "a step that posts",
    ),
    (
        "second-step-closes",
        _add_step("report", {"name": "Close again", "run": CLOSE_LINE}),
        "a step that posts",
    ),
    (
        "second-step-creates-a-label",
        _add_step("report", {"name": "Label again", "run": "gh label create x"}),
        "a step that posts",
    ),
    (
        "second-step-merges",
        _add_step("report", {"name": "Merge", "run": "gh pr merge 1 --squash"}),
        "a step that posts",
    ),
    (
        "second-step-api-two-spaces",
        _add_step("report", {"name": "Api again", "run": "gh  api repos/x/y/issues"}),
        "a step that posts",
    ),
    (
        "post-step-condition-dropped-in-a-copy",
        _add_step(
            "report",
            {
                "name": POST,
                "run": 'gh issue comment 1 --repo "$GITHUB_REPOSITORY"'
                ' --body-file "$DIR/body.md"',
            },
        ),
        "a step that posts",
    ),
    (
        "source-is-main",
        _replace_in(SOURCE_STEP, 'git archive "$SHA"', "git archive HEAD"),
        "live deployment",
    ),
    (
        "source-unset",
        _step_set(
            WALK, "env", {k: v for k, v in WALK_ENV.items() if "SOURCE" not in k}
        ),
        "deployed source",
    ),
    (
        "ref-not-passed",
        _step_set(WALK, "env", {k: v for k, v in WALK_ENV.items() if "REF" not in k}),
        "its ref",
    ),
    (
        "ref-not-written",
        _replace_in(SOURCE_STEP, "printf 'ref=%s", "printf 'x=%s"),
        "live deployment",
    ),
    (
        "source-step-renamed",
        _step_set(SOURCE_STEP, "id", "checkout"),
        "live deployment",
    ),
    ("video-always", _env(WALK, "DOCS_JOURNEY_RECORD_VIDEO", "1"), "video switch"),
    (
        "run-dir-in-the-tree",
        _env(WALK, "DOCS_JOURNEY_RUN_DIR", "${{ github.workspace }}/run"),
        "run directory",
    ),
    (
        "no-chromium",
        _replace_in(
            "Install the runner and Chromium",
            "python -m playwright install --with-deps chromium",
            "true",
        ),
        "Chromium",
    ),
    (
        "upload-the-checkout",
        _upload("${{ github.workspace }}"),
        "outside the run directory",
    ),
    (
        "upload-a-sibling",
        _upload("${{ runner.temp }}/docs-journeys-run-other"),
        "outside the run directory",
    ),
    (
        "upload-two-paths",
        _upload("${{ runner.temp }}/docs-journeys-run/a\n${{ runner.temp }}/deployed"),
        "more than one path",
    ),
    (
        "kept-forever",
        lambda doc, text: (
            next(
                s for s in steps_of(doc) if (s.get("with") or {}).get("path") == RUN_DIR
            )["with"].update({"retention-days": 400})
            or doc,
            text,
        ),
        "14 days",
    ),
    (
        "inline-body",
        _replace_in(POST, '--body-file "$DIR/body.md"', '--body "$X"'),
        "without --body-file",
    ),
    (
        "unrendered-title",
        _replace_in(
            POST, '--title "$(head -n 1 "$DIR/title.txt")"', '--title "$TITLE"'
        ),
        "rendered title",
    ),
    (
        "expression-in-script",
        _replace_in(POST, '"$GITHUB_REPOSITORY"', '"${{ github.repository }}"'),
        "expression inside a script",
    ),
    (
        "edit-issue",
        _replace_in(POST, 'gh issue comment "$ISSUE"', 'gh issue edit "$ISSUE"'),
        "other than create or comment",
    ),
    (
        "print-from-the-shell",
        _replace_in("Step summary", "set -euo pipefail", "set -euo pipefail\necho hi"),
        "prints from the shell",
    ),
    (
        "cat-the-results",
        _replace_in(
            "Step summary",
            "set -euo pipefail",
            'set -euo pipefail\ncat "$RUNNER_TEMP/docs-journeys-run/results.jsonl"',
        ),
        "prints a file",
    ),
    (
        "other-summary",
        _replace_in(
            "Step summary",
            'summary.md" >> "$GITHUB_STEP_SUMMARY"',
            'docs-site.md" >> "$GITHUB_STEP_SUMMARY"',
        ),
        "step summary other than summary.md",
    ),
    (
        "annotation-with-a-value",
        _replace_in(
            POST,
            "'::error title=Docs journeys::the report wrote an unknown action'",
            '"::error title=Docs journeys::$ACTION"',
        ),
        "non-literal",
    ),
]


@pytest.mark.parametrize(
    "plant, fragment", [p[1:] for p in PLANTS], ids=[p[0] for p in PLANTS]
)
def test_each_rule_fires_on_a_planted_defect(plant, fragment):
    doc, text = real()
    doc, text = plant(copy.deepcopy(doc), text)
    found = workflow_problems(doc, text)
    assert any(fragment in problem for problem in found), found


def test_the_release_checklist_dispatches_the_journeys_after_the_docs_deploy():
    """CLAUDE.md's release section runs docs-journeys.yml on the tag, after
    docs.yml; release-please.yml starts neither."""
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    docs = claude.index("gh workflow run docs.yml --ref vX.Y.Z")
    journeys = claude.index("gh workflow run docs-journeys.yml --ref vX.Y.Z")
    assert docs < journeys
    # A red right after a deploy is run once more before it is read as a defect.
    assert "dispatched once more" in claude[journeys : journeys + 1000]
    release_please = (
        REPO_ROOT / ".github" / "workflows" / "release-please.yml"
    ).read_text(encoding="utf-8")
    assert "docs-journeys" not in release_please
