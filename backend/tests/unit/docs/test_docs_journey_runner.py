"""The docs-journey runner's pure parts: the model, the loader, the log, the reports.

The runner lives in ``tests/acceptance/docs/`` (#939) and drives a browser,
which does not belong in the unit job. Its schema, its load-time refusals, its
results log and its report renderer import neither Playwright nor ``backend``,
so they are tested here, on every pull request, including one that changes only
documentation: a guide edit that removes an anchor or a label a journey uses
fails ``test_every_journey_file_loads`` in the "Docs content tests" step,
through this directory.

Each refusal is shown firing on a small journey with one planted defect, in a
temporary docs tree. The compose stack runs against a fake ``docker``, and the
runner's own pytest session (no skip passes, no retry plugin loads) runs in a
subprocess on a copy of its conftest. Temporary files only; no git, no network.
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import tomllib
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER_ROOT = REPO_ROOT / "tests" / "acceptance" / "docs"
if str(RUNNER_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNNER_ROOT))

from docs_runner import checks, loader, log, registry, report
from docs_runner import guide as guides
from docs_runner.model import Journey

TODAY = datetime.date(2026, 10, 6)

GUIDE = """# Sample guide

Some words about the guide.

## Sign in

Open the dashboard and click **Sign in**. Fill **Email** and **Password** with
the account the seed creates, then choose **Production** in **Environment**.
Its settings live in `settings.json` and `.env`; the **.NET** tab is for C#.

```bash
# Not a heading: a comment in a shell block
ls docs
```

## Create an experiment {#create}

Click **New experiment**. The page shows the heading "Experiments" and the
total sample size.

```{.bash exec}
curl -fsS http://localhost:8000/health
```

## Create an experiment

The same title again: the first one has an id of its own, so this one keeps its slug.
"""

INVENTORY: Dict[str, Any] = {
    "pages": {
        "guides/sample.md": {
            "class": "journey",
            "journey": "sample",
            "reason": "walked",
        },
        "guides/other.md": {"class": "reference", "reason": "nothing to walk"},
        "guides/later.md": {
            "class": "journey",
            "journey": "later",
            "pending": True,
            "reason": "to be walked",
        },
    },
    "flow": [
        {
            "text": "Quick Start, end to end",
            "journeys": ["sample", "later"],
            "note": "walked in a browser",
        }
    ],
}

GOOD: Dict[str, Any] = {
    "guide": "guides/sample.md",
    "stack": "compose-dev",
    "profile": "core",
    "video": False,
    "written": TODAY,
    "steps": [
        {
            "id": "open",
            "doc": "sign-in",
            "do": {"goto": "/login"},
            "expect": {
                "status": 200,
                "visible": [{"role": "button", "name": "Sign in"}],
                "aria": '- button "Sign in"',
            },
            "fail": "the sign-in page does not answer",
        },
        {
            "id": "email",
            "doc": "sign-in",
            "do": {"fill": {"label": "Email", "value": "admin@demo.com"}},
            "expect": {"aria": '- textbox "Email"'},
            "fail": "there is no Email field",
        },
        {
            "id": "environment",
            "doc": "sign-in",
            "do": {"select": {"label": "Environment", "option": "Production"}},
            "expect": {"text": "Production"},
            "snapshot": False,
            "snapshot_reason": "the select is checked by its chosen text",
            "fail": "the environment cannot be chosen",
        },
        {
            "id": "sign-in",
            "doc": "sign-in",
            "do": {"click": {"role": "button", "name": "Sign in"}},
            "expect": {
                "url": "/experiments",
                "aria": '- heading "Experiments" [level=1]',
            },
            "fail": "the sign-in form is shown again",
            "snapshot": True,
        },
        {
            "id": "health",
            "doc": "create",
            "do": {"ref": "doc-examples"},
            "fail": "Doc Examples reports the block red",
        },
        {
            "id": "list",
            "doc": "create",
            "do": {
                "api": {"method": "GET", "path": "/api/v1/experiments/", "as": "admin"}
            },
            "expect": {"status": 200, "json": {"total": 3}},
            "fail": "the list does not answer 200",
        },
        {
            "id": "size",
            "doc": "create-an-experiment",
            "do": {"click": {"role": "button", "name": "New experiment"}},
            "expect": {
                "number": {
                    "locator": {
                        "role": "status",
                        "name": "Total",
                        "quote": False,
                        "reason": "the guide calls it the total sample size",
                    },
                    "oracle": {"name": "double", "args": {"x": 2}},
                },
                "aria": '- status "Total"',
            },
            "fail": "the number differs from the oracle",
            "not_run": "waived #123",
        },
    ],
}


def _context(tmp_path: Path, **overrides: Any) -> loader.Context:
    docs = tmp_path / "docs"
    (docs / "guides").mkdir(parents=True, exist_ok=True)
    (docs / "guides" / "sample.md").write_text(GUIDE, encoding="utf-8")
    values: Dict[str, Any] = {
        "docs_root": docs,
        "inventory": INVENTORY,
        "doc_examples": {"guides/sample.md": 1},
        "oracles": {"double": lambda x: 2 * x},
        "today": TODAY,
    }
    values.update(overrides)
    return loader.Context(**values)


def _load(tmp_path: Path, data: Any, name: str = "sample", **overrides: Any) -> Journey:
    path = tmp_path / "journeys" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return loader.load(path, _context(tmp_path, **overrides))


def _refusals(
    tmp_path: Path, data: Any, name: str = "sample", **overrides: Any
) -> List[str]:
    with pytest.raises(loader.Refused) as refused:
        _load(tmp_path, data, name, **overrides)
    return refused.value.problems


def _step(data: Dict[str, Any], step_id: str) -> Dict[str, Any]:
    return next(step for step in data["steps"] if step["id"] == step_id)


def _with(change: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    data = copy.deepcopy(GOOD)
    change(data)
    return data


# ---------------------------------------------------------------------------
# The good journey loads
# ---------------------------------------------------------------------------
def test_the_good_journey_loads(tmp_path):
    journey = _load(tmp_path, GOOD)
    assert [step.do.kind for step in journey.steps] == [
        "goto",
        "fill",
        "select",
        "click",
        "ref",
        "api",
        "click",
    ]
    assert journey.steps[5].do.api.as_ == "admin"
    assert journey.steps[5].expect.json_ == {"total": 3}


# ---------------------------------------------------------------------------
# Each refusal, on one planted defect
# ---------------------------------------------------------------------------
def _on_step(step_id: str, change: Callable[[Dict[str, Any]], None]):
    return lambda data: change(_step(data, step_id))


def _drop(step_id: str, key: str):
    return _on_step(step_id, lambda step: step.pop(key))


PLANTS = [
    pytest.param(
        _on_step("sign-in", lambda s: s["do"]["click"].update(name="css=#submit")),
        {},
        "'css=#submit' is a CSS or XPath selector",
        id="css-selector-as-a-name",
    ),
    pytest.param(
        _on_step(
            "open",
            lambda s: s["expect"].update(
                visible=[{"role": "button", "name": "//button[1]"}]
            ),
        ),
        {},
        "'//button[1]' is a CSS or XPath selector",
        id="xpath-as-a-name",
    ),
    pytest.param(
        _on_step(
            "sign-in", lambda s: s["do"].update(click={"selector": "button.primary"})
        ),
        {},
        "selector is a CSS or XPath selector",
        id="selector-key",
    ),
    pytest.param(
        _on_step(
            "size",
            lambda s: s["expect"]["number"].update(locator="css=.total"),
        ),
        {},
        "locator is a CSS or XPath selector",
        id="string-locator",
    ),
    pytest.param(
        _on_step("email", lambda s: s["do"]["fill"].update(label="form >> Email")),
        {},
        "'form >> Email' is a CSS or XPath selector",
        id="chained-selector-as-a-label",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s.update(do={"sleep": 2})),
        {},
        "sleep is a sleep",
        id="sleep-action",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s["expect"].update(wait_for_timeout=500)),
        {},
        "wait_for_timeout is a sleep",
        id="wait-in-expect",
    ),
    pytest.param(
        _drop("sign-in", "fail"),
        {},
        "step 4 (sign-in): no fail; write what failure looks like before the run",
        id="step-without-fail",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s.update(fail="  ")),
        {},
        "fail must be one non-empty line",
        id="empty-fail",
    ),
    pytest.param(
        lambda data: data.update(stack="staging"),
        {},
        "unknown stack 'staging'",
        id="unknown-stack",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s.update(doc="step-9")),
        {},
        "the guide has no anchor #step-9",
        id="anchor-the-page-lacks",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s["do"]["click"].update(name="Log in")),
        {},
        "click.name 'Log in' is not in the guide's text",
        id="name-the-guide-does-not-say",
    ),
    pytest.param(
        _on_step("email", lambda s: s["do"]["fill"].update(label="E-mail")),
        {},
        "fill.label 'E-mail' is not in the guide's text",
        id="label-the-guide-does-not-say",
    ),
    pytest.param(
        _on_step(
            "size",
            lambda s: s["expect"]["number"]["locator"].pop("reason"),
        ),
        {},
        "quote: false needs a one-line reason",
        id="unquoted-without-reason",
    ),
    pytest.param(
        lambda data: data.update(guide="guides/later.md"),
        {},
        "names 'later' as the journey of 'guides/later.md', not 'sample'",
        id="another-journeys-guide",
    ),
    pytest.param(
        lambda data: None,
        {
            "inventory": {
                "pages": {
                    "guides/sample.md": {
                        "class": "journey",
                        "journey": "sample",
                        "pending": True,
                        "reason": "x",
                    }
                }
            }
        },
        "journey 'sample' is pending = true in inventory.toml",
        id="pending-journey",
    ),
    pytest.param(
        lambda data: data.update(guide="guides/other.md"),
        {},
        "is classified 'reference' in inventory.toml, not journey",
        id="inventory-class-not-journey",
    ),
    pytest.param(
        lambda data: data.update(guide="guides/missing.md"),
        {},
        "is not a page in inventory.toml",
        id="guide-not-in-inventory",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s.update(expect={"json": {"a": 1}})),
        {},
        "step 4 (sign-in): a step on one screen needs expect.aria",
        id="screen-step-with-only-json",
    ),
    pytest.param(
        _drop("environment", "expect"),
        {},
        "step 3 (environment): a step with snapshot: false needs a structural expect",
        id="screen-step-with-no-expect",
    ),
    pytest.param(
        _on_step("open", lambda s: s["expect"].pop("aria")),
        {},
        "step 1 (open): a step on one screen needs expect.aria, its ARIA snapshot"
        " written before the run, beside any structural expect",
        id="screen-step-without-aria",
    ),
    pytest.param(
        _drop("environment", "snapshot_reason"),
        {},
        "step 3 (environment): snapshot: false needs a one-line snapshot_reason",
        id="no-snapshot-without-a-reason",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s.update(snapshot_reason="because")),
        {},
        "snapshot_reason is only for snapshot: false",
        id="snapshot-reason-with-a-snapshot",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s["expect"].update(aria="heading: [unclosed")),
        {},
        "step 4 (sign-in).expect.aria: aria must be an ARIA snapshot template",
        id="aria-that-is-not-yaml",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s["expect"].update(aria="Experiments")),
        {},
        "step 4 (sign-in).expect.aria: aria must be an ARIA snapshot template",
        id="aria-that-is-not-a-list",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s["do"]["click"].update(name="Sign\nin")),
        {},
        "step 4 (sign-in).do.click.name: must be one line",
        id="multi-line-name",
    ),
    pytest.param(
        _on_step("email", lambda s: s["do"]["fill"].update(label="Email\naddress")),
        {},
        "step 2 (email).do.fill.label: must be one line",
        id="multi-line-label",
    ),
    pytest.param(
        _on_step("environment", lambda s: s["expect"].update(text="Pro\nduction")),
        {},
        "step 3 (environment).expect.text: must be one line",
        id="multi-line-text",
    ),
    pytest.param(
        _on_step("open", lambda s: s["do"].update(goto="/login\n/other")),
        {},
        "step 1 (open).do.goto: must be one line",
        id="multi-line-goto",
    ),
    pytest.param(
        lambda data: data.update(
            steps=[
                _step(data, "health"),
                {**_step(data, "list"), "not_run": "needs-aws"},
            ]
        ),
        {},
        "no step is run by this runner: every step is ref: doc-examples or"
        " declares not_run",
        id="no-step-run-here",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s["expect"].update(status=200)),
        {},
        "status is the answer to a goto; click has none",
        id="status-on-a-click",
    ),
    pytest.param(
        _on_step("list", lambda s: s.update(expect={"text": "Experiments"})),
        {},
        "an api step needs status or json in expect",
        id="api-step-without-status-or-json",
    ),
    pytest.param(
        lambda data: data.update(stack="docs-local"),
        {},
        "an api step needs a stack with an API; docs-local has none",
        id="api-step-on-a-docs-stack",
    ),
    pytest.param(
        _on_step("health", lambda s: s.update(doc="sign-in")),
        {},
        "the section #sign-in has no {.bash exec} block",
        id="ref-without-exec-block",
    ),
    pytest.param(
        lambda data: None,
        {"doc_examples": {}},
        "enrols no exec block of guides/sample.md",
        id="ref-on-a-guide-not-enrolled",
    ),
    pytest.param(
        _on_step(
            "size", lambda s: s["expect"]["number"]["oracle"].update(name="triple")
        ),
        {},
        "no oracle named 'triple'",
        id="unknown-oracle",
    ),
    pytest.param(
        _on_step("size", lambda s: s.update(not_run="earlier-step-failed")),
        {},
        "not_run 'earlier-step-failed' is not a reason a journey may give",
        id="runtime-reason-declared",
    ),
    pytest.param(
        _on_step("size", lambda s: s.update(not_run="flaky")),
        {},
        "not_run 'flaky' is not a reason a journey may give",
        id="unregistered-reason",
    ),
    pytest.param(
        lambda data: data.update(written=TODAY + datetime.timedelta(days=1)),
        {},
        "is after today",
        id="written-in-the-future",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s.update(retries=3)),
        {},
        "step 4 (sign-in).retries: Extra inputs are not permitted",
        id="unknown-field",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s["do"].update(goto="/login")),
        {},
        "do must be exactly one of",
        id="two-actions",
    ),
    pytest.param(
        _on_step("open", lambda s: s["do"].update(goto="https://example.com/login")),
        {},
        "goto is a path on the stack",
        id="goto-a-url",
    ),
    pytest.param(
        _on_step("sign-in", lambda s: s["do"]["click"].update(role="btn")),
        {},
        "step 4 (sign-in).do.click.role: 'btn' is not one of the values allowed here",
        id="unknown-role",
    ),
    pytest.param(
        _on_step("health", lambda s: s.update(expect={"status": 200})),
        {},
        "ref: doc-examples is checked by Doc Examples; it has no expect here",
        id="ref-with-expect",
    ),
    pytest.param(
        _on_step("list", lambda s: s.update(snapshot=True)),
        {},
        "an api step has no screen to snapshot",
        id="api-step-snapshot",
    ),
    pytest.param(
        lambda data: data["steps"].append(copy.deepcopy(data["steps"][0])),
        {},
        "step id 'open' is used twice",
        id="duplicate-step-id",
    ),
    pytest.param(
        lambda data: data.update(video="yes"),
        {},
        "video: Input should be a valid boolean",
        id="quoted-bool",
    ),
]


@pytest.mark.parametrize("change, overrides, expected", PLANTS)
def test_planted_defect_is_refused(tmp_path, change, overrides, expected):
    problems = _refusals(tmp_path, _with(change), **overrides)
    assert any(expected in problem for problem in problems), problems


def test_a_file_name_that_is_not_a_slug_is_refused(tmp_path):
    problems = _refusals(tmp_path, GOOD, name="Sample_Journey")
    assert any("is not a lower-case slug" in problem for problem in problems), problems


def test_the_inventory_names_the_journey_by_file(tmp_path):
    inventory = copy.deepcopy(INVENTORY)
    inventory["pages"]["guides/sample.md"]["journey"] = "another"
    problems = _refusals(tmp_path, GOOD, inventory=inventory)
    assert any(
        "names 'another' as the journey of 'guides/sample.md', not 'sample'" in problem
        for problem in problems
    ), problems


def test_an_unquoted_name_with_a_reason_is_accepted(tmp_path):
    data = _with(
        _on_step(
            "sign-in",
            lambda s: s["do"]["click"].update(
                name="Log in", quote=False, reason="the button says Log in"
            ),
        )
    )
    assert _load(tmp_path, data).steps[3].do.click.name == "Log in"


def test_a_waiver_names_its_issue(tmp_path):
    assert _load(tmp_path, GOOD).steps[6].not_run == "waived #123"
    for reason in ("waived", "waived #", "waived #0", "waived 123"):
        data = _with(_on_step("size", lambda s, r=reason: s.update(not_run=r)))
        problems = _refusals(tmp_path, data)
        assert any("is not a reason a journey may give" in p for p in problems), reason


def test_a_raw_problem_is_not_repeated_by_the_model(tmp_path):
    """A missing fail, a sleep and an unknown stack, each said once."""
    data = _with(_drop("sign-in", "fail"))
    _step(data, "open")["do"] = {"wait": 1}
    data["stack"] = "nope"
    problems = _refusals(tmp_path, data)
    assert len(problems) == 3, problems


def test_every_stage_reports_in_one_file(tmp_path):
    """A raw problem, a model problem and a semantic one, all three at once."""
    data = _with(_on_step("open", lambda s: s["expect"].update(pause=1)))
    _step(data, "email")["retries"] = 2
    _step(data, "sign-in")["doc"] = "step-9"
    problems = _refusals(tmp_path, data)
    assert problems == [
        "step 1 (open).expect: pause is a sleep; a step waits for what it expects,"
        " never for a time",
        "step 2 (email).retries: Extra inputs are not permitted",
        "step 4 (sign-in): the guide has no anchor #step-9",
    ], problems


def test_names_that_look_like_files_are_names(tmp_path):
    """settings.json, .env and .NET are what a reader sees, not selectors."""
    visible = [
        {"role": "link", "name": "settings.json"},
        {"role": "link", "name": ".env"},
        {"role": "tab", "name": ".NET"},
    ]
    data = _with(_on_step("open", lambda s: s["expect"].update(visible=visible)))
    names = [named.name for named in _load(tmp_path, data).steps[0].expect.visible]
    assert names == ["settings.json", ".env", ".NET"]


def test_the_model_docstring_example_loads():
    """The example in model.py's docstring is a journey the loader accepts."""
    from docs_runner import model

    doc = model.__doc__
    block = doc[doc.index("without ``pending``)::") :].split("\n\n", 2)[1]
    data = yaml.safe_load(textwrap.dedent(block))
    real = loader.context_for(REPO_ROOT)
    inventory = copy.deepcopy(real.inventory)
    inventory["pages"]["README.md"].pop("pending", None)
    context = loader.Context(
        docs_root=real.docs_root,
        inventory=inventory,
        doc_examples=real.doc_examples,
        oracles=real.oracles,
        today=real.today,
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "docs-site.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        journey = loader.load(path, context)
    assert [step.id for step in journey.steps] == [
        "home",
        "open-quick-start",
        "deploy-guide",
    ]


# ---------------------------------------------------------------------------
# What a step's log line says, and how it compares
# ---------------------------------------------------------------------------
def test_actions_and_expectations_are_described_for_the_log(tmp_path):
    steps = _load(tmp_path, GOOD).steps
    assert [checks.describe_action(step) for step in steps] == [
        "open /login",
        'fill "Email"',
        'choose "Production" in "Environment"',
        'click the button "Sign in"',
        "its shell blocks, run by Doc Examples",
        "GET /api/v1/experiments/ as admin",
        'click the button "New experiment"',
    ]
    assert checks.describe_expect(steps[0]) == (
        'status 200; button "Sign in" visible; the screen matches its ARIA snapshot'
        " (1 lines)"
    )
    assert checks.describe_expect(steps[3]) == (
        "at /experiments; the screen matches its ARIA snapshot (1 lines)"
    )
    assert checks.describe_expect(steps[4]) == "Doc Examples runs this section's blocks"
    assert checks.describe_expect(steps[5]) == "status 200; json total = 3"
    assert checks.describe_expect(steps[6]) == (
        'the number in status "Total" equals double(x=2); the screen matches its'
        " ARIA snapshot (1 lines)"
    )


def test_a_fill_value_is_never_described():
    """A password typed into a form must not reach the public log."""
    data = _with(_on_step("email", lambda s: s["do"]["fill"].update(value="Demo1234!")))
    step = Journey.model_validate(data).steps[1]
    assert "Demo1234!" not in checks.describe_action(step)
    assert "Demo1234!" not in checks.describe_expect(step)


def test_json_paths_and_values():
    document = {"items": [{"key": "a", "on": True}], "total": 1}
    assert checks.json_at(document, "items.0.key") == "a"
    assert checks.json_at(document, "total") == 1
    for missing in ("items.1.key", "items.x", "nope", "total.x"):
        with pytest.raises(KeyError):
            checks.json_at(document, missing)
    assert checks.same_json(1, 1.0)
    assert checks.same_json(True, True)
    assert not checks.same_json(True, 1)
    assert not checks.same_json(0, False)


def test_numbers_shown_on_a_screen():
    assert checks.parse_number("Sample size: 31,234 per variant") == 31234
    assert checks.parse_number("-0.5 pp") == -0.5
    with pytest.raises(checks.StepFailed):
        checks.parse_number("no number here")


def test_an_error_is_cut_to_one_line_before_the_call_log():
    error = "Timeout 10000ms exceeded.\n  waiting for x\nCall log:\n  - secret detail"
    assert checks.one_line(error) == "Timeout 10000ms exceeded.; waiting for x"
    assert len(checks.one_line("x" * 1000)) == checks.OBSERVED_CHARS


# ---------------------------------------------------------------------------
# The guide's anchors
# ---------------------------------------------------------------------------
def test_anchors_follow_toc():
    guide = guides.parse("guides/sample.md", GUIDE)
    assert [(h.level, h.text, h.anchor) for h in guide.headings] == [
        (1, "Sample guide", "sample-guide"),
        (2, "Sign in", "sign-in"),
        (2, "Create an experiment", "create"),
        (2, "Create an experiment", "create-an-experiment"),
    ]
    assert guide.title == "Sample guide"
    assert guide.has_exec_block("create")
    assert not guide.has_exec_block("sign-in")


@pytest.mark.parametrize(
    "heading, anchor",
    [
        ("Step 1: Start Services", "step-1-start-services"),
        ("`docker compose up` -- the stack", "docker-compose-up-the-stack"),
        ("**Bold** and [a link](x.md)", "bold-and-a-link"),
        ("Café — résumé", "cafe-resume"),
        ("What's new? (v2)", "whats-new-v2"),
        ("Explicit {: #chosen }", "chosen"),
        ("GET /api/v1/drafts/{draft_id}", "get-apiv1draftsdraft_id"),
        (
            "Every EXPERIMENT_SCHEDULER_INTERVAL_MINUTES",
            "every-experiment_scheduler_interval_minutes",
        ),
        ("`trackBatch(events: List<TrackEvent>)`", "trackbatchevents-listtrackevent"),
        ("`platform-<env>` (metrics)", "platform-env-metrics"),
        ("Developers &amp; *Integration* _Guides_", "developers-integration-guides"),
    ],
)
def test_slugs(heading, anchor):
    assert guides.parse("x.md", f"## {heading}\n").headings[0].anchor == anchor


def test_repeated_and_taken_slugs_are_numbered_as_toc_numbers_them():
    text = "## A\n\n## A\n\n## A_1 {#a_1}\n\n## A\n"
    anchors = [h.anchor for h in guides.parse("x.md", text).headings]
    assert anchors == ["a", "a_2", "a_1", "a_3"]


def test_html_ids_are_anchors_and_fenced_hashes_are_not():
    text = '<a id="top"></a>\n\n~~~\n# not a heading\n~~~\n\n## Real\n'
    guide = guides.parse("x.md", text)
    assert set(guide.anchors) == {"top", "real"}


# ---------------------------------------------------------------------------
# The results log
# ---------------------------------------------------------------------------
def _record(**changes: Any) -> log.Record:
    values: Dict[str, Any] = {
        "run": "1",
        "sha": "abc",
        "stack": "compose-dev",
        "guide": "guides/sample.md",
        "step": 1,
        "step_id": "open",
        "heading": "Sign in",
        "action": "open /login",
        "expected": "status 200",
        "failure_signature": "the sign-in page does not answer",
        "result": "PASS",
        "reason": "",
        "observed": "at /login (status 200)",
        "snapshot": "",
        "expected_snapshot": "structural only",
        "ms": 12,
    }
    values.update(changes)
    return log.Record(**values)


def test_the_log_keys_are_fixed():
    """The keys every line carries, in order; a change here is a change of contract."""
    assert log.KEYS == (
        "run",
        "sha",
        "stack",
        "guide",
        "step",
        "step_id",
        "heading",
        "action",
        "expected",
        "failure_signature",
        "result",
        "reason",
        "observed",
        "snapshot",
        "expected_snapshot",
        "ms",
    )
    assert tuple(json.loads(_record().line())) == log.KEYS


def test_the_log_round_trips_and_refuses_other_shapes(tmp_path):
    path = tmp_path / "results.jsonl"
    writer = log.Log(path)
    writer.write(_record())
    writer.write(_record(step=2, result="NOT RUN", reason="earlier-step-failed"))
    assert [r.step for r in log.read(path)] == [1, 2]

    line = json.loads(_record().line())
    del line["reason"]
    with pytest.raises(log.BadRecord, match="are not the log's keys"):
        log.parse_line(json.dumps(line))
    line = json.loads(_record().line())
    line["extra"] = 1
    with pytest.raises(log.BadRecord):
        log.parse_line(json.dumps(line))


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"result": "SKIPPED"}, "is not one of"),
        ({"result": "NOT RUN", "reason": ""}, "is not in the registry"),
        ({"result": "NOT RUN", "reason": "flaky"}, "is not in the registry"),
        ({"result": "PASS", "reason": "needs-aws"}, "has no reason"),
        ({"observed": "two\nlines"}, "more than one line"),
        ({"step": 0}, "is not a step number"),
    ],
)
def test_a_bad_record_is_refused(changes, message):
    with pytest.raises(log.BadRecord, match=message):
        _record(**changes)


def test_every_registry_reason_is_accepted():
    for reason in (*registry.DECLARED, *registry.RUNTIME, "waived #939"):
        assert _record(result="NOT RUN", reason=reason).reason == reason
    assert not registry.is_declarable(registry.EARLIER_STEP_FAILED)
    assert not registry.is_declarable(registry.DOC_EXAMPLES)


def test_the_run_directory_is_never_in_the_tree(tmp_path):
    with pytest.raises(ValueError, match="inside the repository"):
        log.run_directory({"DOCS_JOURNEY_RUN_DIR": str(REPO_ROOT / "out")}, REPO_ROOT)
    with pytest.raises(ValueError, match="inside the repository"):
        log.run_directory({"DOCS_JOURNEY_RUN_DIR": str(REPO_ROOT)}, REPO_ROOT)
    chosen = tmp_path / "run"
    assert log.run_directory({"DOCS_JOURNEY_RUN_DIR": str(chosen)}, REPO_ROOT) == chosen
    assert chosen.is_dir()


# ---------------------------------------------------------------------------
# The reports
# ---------------------------------------------------------------------------
EXPECTED_ARIA = '- heading "Experiments" [level=1]'
OBSERVED_ARIA = '- heading "Sign in" [level=1]\n- textbox "Email"'


def _failed_run(run_dir: Path) -> report.GuideRun:
    """A run whose second step failed, with both its snapshots on disk."""
    (run_dir / "sample").mkdir(parents=True)
    (run_dir / "sample" / "02-sign-in.expected.aria.yml").write_text(
        EXPECTED_ARIA + "\n"
    )
    (run_dir / "sample" / "02-sign-in.png").write_bytes(b"\x89PNG\r\n")
    (run_dir / "sample" / "02-sign-in.aria.yml").write_text(OBSERVED_ARIA + "\n")
    return report.GuideRun(
        journey="sample",
        guide="guides/sample.md",
        title="Sample guide",
        stack="compose-dev",
        records=(
            _record(),
            _record(
                step=2,
                step_id="sign-in",
                action='click the button "Sign in"',
                expected="at /experiments; the screen matches its ARIA snapshot (1 lines)",
                failure_signature="the sign-in form is shown again",
                result="FAIL",
                observed="Locator expected to match the ARIA snapshot",
                snapshot="sample/02-sign-in.png",
                expected_snapshot="sample/02-sign-in.expected.aria.yml",
            ),
            _record(
                step=3, step_id="size", result="NOT RUN", reason="earlier-step-failed"
            ),
        ),
    )


def test_a_fail_shows_both_snapshots_side_by_side(tmp_path):
    """For each FAIL, the expected and the observed snapshot, side by side."""
    run = _failed_run(tmp_path)
    for text in (
        report.guide_markdown(run, tmp_path, date="2026-10-06", sha="abc"),
        report.guide_html(run, tmp_path, date="2026-10-06", sha="abc"),
    ):
        assert "Expected (written before the run)" in text
        assert "heading &quot;Experiments&quot; [level=1]" in text
        assert 'src="sample/02-sign-in.png"' in text
        assert "heading &quot;Sign in&quot; [level=1]" in text
        assert "the sign-in form is shown again" in text
        expected_at = text.index("heading &quot;Experiments&quot;")
        observed_at = text.index("heading &quot;Sign in&quot;")
        assert expected_at < observed_at


def test_the_guide_report_opens_with_its_verdict(tmp_path):
    text = report.guide_markdown(
        _failed_run(tmp_path), tmp_path, date="2026-10-06", sha="abc"
    )
    lines = text.splitlines()
    assert lines[0] == (
        "# Sample guide (guides/sample.md), 2026-10-06, commit abc: FAIL at step 2"
    )
    assert lines[2] == (
        'A reader following this guide cannot finish it. First failing step: 2, "Sign in".'
    )
    assert "| 3 | Sign in: open /login |" in text
    assert "NOT RUN (earlier-step-failed)" in text


@pytest.mark.parametrize(
    "plant, message",
    [
        (
            lambda d: (d / "sample" / "02-sign-in.expected.aria.yml").unlink(),
            "expected snapshot",
        ),
        (lambda d: (d / "sample" / "02-sign-in.png").unlink(), "observed snapshot"),
    ],
    ids=["expected-snapshot-file-dropped", "observed-snapshot-file-dropped"],
)
def test_a_fail_without_both_snapshots_is_refused(tmp_path, plant, message):
    run = _failed_run(tmp_path)
    plant(tmp_path)
    with pytest.raises(report.ReportError, match=message):
        report.guide_markdown(run, tmp_path, date="2026-10-06", sha="abc")
    with pytest.raises(report.ReportError, match=message):
        report.guide_html(run, tmp_path, date="2026-10-06", sha="abc")


@pytest.mark.parametrize("field", ["expected_snapshot", "snapshot"])
def test_a_fail_record_naming_no_snapshot_is_refused(tmp_path, field):
    run = _failed_run(tmp_path)
    records = list(run.records)
    records[1] = log.Record(**{**json.loads(records[1].line()), field: ""})
    broken = report.GuideRun(**{**run.__dict__, "records": tuple(records)})
    with pytest.raises(report.ReportError, match="FAIL with no"):
        report.guide_markdown(broken, tmp_path, date="2026-10-06", sha="abc")


def test_a_structural_fail_shows_its_expectation_and_what_was_seen(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "01-list.api.json").write_text('{"status": 500}\n')
    run = report.GuideRun(
        journey="s",
        guide="guides/sample.md",
        title="Sample guide",
        stack="compose-dev",
        records=(
            _record(
                result="FAIL",
                observed="status 500, expected 200",
                snapshot="s/01-list.api.json",
                expected_snapshot="structural only",
            ),
        ),
    )
    text = report.guide_markdown(run, tmp_path, date="2026-10-06", sha="abc")
    assert "Expected (structural only): status 200" in text
    assert "Seen: status 500, expected 200" in text
    assert "&quot;status&quot;: 500" in text


def test_verdicts():
    def run(*records):
        return report.GuideRun("s", "g.md", "G", "docs-local", records=records)

    assert report.verdict(run(_record())).line == "PASS"
    assert (
        report.verdict(
            run(_record(), _record(step=2, result="NOT RUN", reason="doc-examples"))
        ).line
        == "PASS"
    )
    partial = report.verdict(
        run(_record(), _record(step=2, result="NOT RUN", reason="needs-aws"))
    )
    assert partial.line == "PARTIAL: 1 not run"
    assert "needs-aws" in partial.sentence
    for reasons in (["doc-examples"], ["doc-examples", "needs-aws"], ["waived #9"]):
        nothing_ran = report.verdict(
            run(
                *(
                    _record(step=n, result="NOT RUN", reason=reason)
                    for n, reason in enumerate(reasons, 1)
                )
            )
        )
        assert nothing_ran.word == "PARTIAL", reasons
        assert nothing_ran.line == f"PARTIAL: {len(reasons)} not run"
        assert nothing_ran.sentence.startswith("No step of this guide ran here")
    assert report.verdict(run()).word == "FAIL"
    refused = report.GuideRun("s", "g.md", "G", "docs-local", refused=("x",))
    assert report.verdict(refused).line == "FAIL: the journey file was refused"
    down = report.GuideRun(
        "s", "g.md", "G", "docs-local", error="mkdocs build exited 1"
    )
    assert report.verdict(down).word == "FAIL"


def test_the_summary_lists_every_page_not_covered_and_every_flow(tmp_path):
    passed = report.GuideRun(
        "sample",
        "guides/sample.md",
        "Sample guide",
        "compose-dev",
        records=(_record(),),
    )
    text = report.summary_markdown([passed], INVENTORY, date="2026-10-06", sha="abc")
    lines = text.splitlines()
    assert lines[0] == "# Docs journeys, 2026-10-06, commit abc: PASS, 1 guide(s) run"
    assert lines[1] == (
        "Guides: 1 pass, 0 fail, 0 partial of 3 in the nav. Not covered: 2 page(s),"
        " listed below."
    )
    assert "| guides/other.md | reference | nothing to walk |" in text
    assert (
        "| guides/later.md | journey | journey later: pending, expectations not"
        " written yet; to be walked |"
    ) in text
    assert "guides/sample.md | journey |" not in text
    assert "| Quick Start, end to end | sample (PASS), later (not run) |" in text


def test_the_summary_of_an_empty_run_is_red():
    text = report.summary_markdown([], INVENTORY, date="2026-10-06", sha="abc")
    assert text.splitlines()[0].startswith(
        "# Docs journeys, 2026-10-06, commit abc: FAIL"
    )


# ---------------------------------------------------------------------------
# The compose stack, against a fake docker
# ---------------------------------------------------------------------------
FAKE_DOCKER = """#!/bin/sh
here="$(dirname "$0")"
printf '%s\\n' "$*" >> "$here/calls.log"
case " $* " in
  *" up "*) exit "$(cat "$here/up_exit")" ;;
esac
exit 0
"""
DOWN = "compose -p docs-journeys down -v --remove-orphans"
UP = "compose -p docs-journeys up -d --wait --build"


def _fake_docker(tmp_path: Path, up_exit: int) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    (bin_dir / "up_exit").write_text(str(up_exit))
    return bin_dir


def _compose(tmp_path: Path, bin_dir: Path):
    from docs_runner import stacks

    environ = {"PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"}
    return stacks, stacks.ComposeDev(tmp_path, tmp_path / "logs", environ)


def _calls(bin_dir: Path) -> List[str]:
    return (bin_dir / "calls.log").read_text().splitlines()


def test_compose_dev_clears_its_project_then_builds(tmp_path, monkeypatch):
    bin_dir = _fake_docker(tmp_path, 0)
    stacks, stack = _compose(tmp_path, bin_dir)
    monkeypatch.setattr(stack, "_served_profile", lambda api_url: "core")
    running = stack.up("core")
    assert running.base_url == "http://127.0.0.1:23000/"
    assert _calls(bin_dir) == [DOWN, UP]
    stack.down()
    assert _calls(bin_dir) == [DOWN, UP, DOWN]


def test_a_failed_compose_up_clears_its_project(tmp_path):
    bin_dir = _fake_docker(tmp_path, 3)
    stacks, stack = _compose(tmp_path, bin_dir)
    with pytest.raises(stacks.StackError, match=r"docker compose up \(core\) exited 3"):
        stack.up("core")
    assert _calls(bin_dir) == [DOWN, UP, DOWN]


def test_the_wrong_profile_clears_the_project(tmp_path, monkeypatch):
    bin_dir = _fake_docker(tmp_path, 0)
    stacks, stack = _compose(tmp_path, bin_dir)
    monkeypatch.setattr(stack, "_served_profile", lambda api_url: "core")
    with pytest.raises(stacks.StackError, match="serves the core profile, not full"):
        stack.up("full")
    assert _calls(bin_dir) == [DOWN, UP, DOWN]
    assert stack.running is None


def test_a_program_that_cannot_start_is_a_stack_error(tmp_path):
    """No docker, no npm: the journey gets a FAIL before step 1, not a crash."""
    from docs_runner import stacks

    empty = tmp_path / "empty"
    empty.mkdir()
    (tmp_path / "frontend").mkdir()
    environ = {"PATH": str(empty)}
    compose = stacks.ComposeDev(tmp_path, tmp_path / "logs", environ)
    with pytest.raises(stacks.StackError, match="docker could not be started"):
        compose.up("core")
    marketing = stacks.MarketingLocal(tmp_path, tmp_path / "logs", environ)
    with pytest.raises(stacks.StackError, match="npm could not be started"):
        marketing.up()


# ---------------------------------------------------------------------------
# The runner's own session: no skip passes, no retry plugin loads
# ---------------------------------------------------------------------------
def _runner_copy(tmp_path: Path, test_body: str) -> Path:
    """A tree holding the runner's conftest, ini and package, with one test of ours."""
    root = tmp_path / "repo"
    here = root / "tests" / "acceptance" / "docs"
    here.mkdir(parents=True)
    for name in ("conftest.py", "pytest.ini", "inventory.toml"):
        shutil.copy(RUNNER_ROOT / name, here / name)
    shutil.copytree(
        RUNNER_ROOT / "docs_runner",
        here / "docs_runner",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (here / "test_journeys.py").write_text(test_body)
    (root / "scripts").mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "doc_examples.toml", root / "scripts")
    (root / "backend" / "tests").mkdir(parents=True)
    (root / "backend" / "__init__.py").write_text("")
    (root / "backend" / "tests" / "__init__.py").write_text("")
    shutil.copy(
        REPO_ROOT / "backend" / "tests" / "no_real_aws.py", root / "backend" / "tests"
    )
    return root


def _run_runner(
    root: Path, tmp_path: Path, *args: str, **extra_env: str
) -> subprocess.CompletedProcess:
    env = {**os.environ, "DOCS_JOURNEY_RUN_DIR": str(tmp_path / "run"), **extra_env}
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "tests/acceptance/docs/pytest.ini",
            "tests/acceptance/docs",
            *args,
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


PASSING = "def test_planted():\n    assert True\n"
SKIPPING = (
    "import pytest\n\n\ndef test_planted():\n"
    '    getattr(pytest, "skip")("planted past the lint")\n'
)


def test_the_runner_session_passes_a_passing_test(tmp_path):
    """The control: the copy itself runs green, so a red below is the plant."""
    result = _run_runner(_runner_copy(tmp_path, PASSING), tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_a_skip_in_the_runner_fails_the_run(tmp_path):
    result = _run_runner(_runner_copy(tmp_path, SKIPPING), tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 skipped" in result.stdout
    assert "was skipped; nothing here may skip, so the run fails" in result.stdout


def test_a_retry_plugin_stops_the_runner(tmp_path):
    root = _runner_copy(tmp_path, PASSING)
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "rerunfailures.py").write_text("")
    result = _run_runner(
        root, tmp_path, "-p", "rerunfailures", PYTHONPATH=str(tmp_path / "plugins")
    )
    assert result.returncode == 4, result.stdout + result.stderr
    assert "the rerunfailures plugin is loaded" in result.stderr


# ---------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------
def test_every_journey_file_loads():
    """Every journey file in the tree loads against today's docs and inventory."""
    context = loader.context_for(REPO_ROOT)
    problems = []
    for path in sorted((RUNNER_ROOT / "journeys").glob("*.yaml")):
        try:
            loader.load(path, context)
        except loader.Refused as refused:
            problems.append(str(refused))
    assert not problems, "\n".join(problems)


def test_the_runner_bans_skips_and_writes_nothing_into_the_tree():
    """The lint ban and the pytest settings the runner's no-skip rule rests on."""
    ruff = tomllib.loads((RUNNER_ROOT / "ruff.toml").read_text(encoding="utf-8"))
    assert ruff["extend"] == "../../../pyproject.toml"
    assert "TID251" in ruff["lint"]["extend-select"]
    assert set(ruff["lint"]["flake8-tidy-imports"]["banned-api"]) == {
        "pytest.skip",
        "pytest.xfail",
        "pytest.importorskip",
        "pytest.mark.skip",
        "pytest.mark.skipif",
        "pytest.mark.xfail",
    }
    ini = (RUNNER_ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "empty_parameter_set_mark = fail_at_collect" in ini
    assert "-p no:cacheprovider" in ini
