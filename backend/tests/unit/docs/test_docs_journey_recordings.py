"""The launch walkthroughs R1-R8: the registry, the journeys that record them,
and what keeps a credential off them (QA plan UX D11.4, V12 and V13).

``tests/acceptance/docs/recordings.toml`` names each walkthrough a counting
docs-journeys run must keep (T138: "recordings R1-R8 in that run's
artifacts"); the journeys under ``journeys/`` declare which of them they
record and over which steps; the runner records them with ``page.screencast``
(``execute.Walkthrough``), checks every page it records for the values the run
keeps (``redaction.on_screen``), and reports each with its guide's verdict
(``report.walkthrough_rows``). The presence check that fails a run missing one
is ``scripts/docs_journeys_report.py recordings``
(``backend/tests/unit/scripts/test_docs_journeys_recordings.py``).

Pure parts only, as in ``test_docs_journey_runner.py``: no browser, no network,
temporary files.
"""

from __future__ import annotations

import datetime
import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER_ROOT = REPO_ROOT / "tests" / "acceptance" / "docs"
if str(RUNNER_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNNER_ROOT))

from docs_runner import loader, redaction, report
from docs_runner.log import Record
from docs_runner.model import Journey

REGISTRY_PATH = RUNNER_ROOT / "recordings.toml"
JOURNEYS = RUNNER_ROOT / "journeys"
TODAY = datetime.date(2026, 10, 7)

#: QA plan UX D11.4: each walkthrough, its guide and its longest length. R5 is
#: two halves of a minute each (its two minutes), the SRM half pending until
#: the journey that seeds a sample-ratio mismatch lands (EM v1.3 condition 3).
EXPECTED = {
    "R1-quick-start": ("R1", "getting-started/quick-start.md", 180),
    "R2-docker-guide": ("R2", "getting-started/docker-guide.md", 90),
    "R3-experiment-wizard": ("R3", "guides/experiment-wizard.md", 120),
    "R4-power-analysis": ("R4", "statistics/power-analysis.md", 60),
    "R5-reading-results": ("R5", "guides/user-guide.md", 60),
    "R5-srm-warning": ("R5", "guides/user-guide.md", 60),
    "R6-feature-flag": ("R6", "feature-flags/create.md", 120),
    "R7-docs-site": ("R7", "README.md", 60),
    "R8-onboarding": ("R8", "auth/auth-user-guide.md", 90),
}
PENDING = {"R5-srm-warning"}


def registry() -> Dict[str, Dict[str, Any]]:
    return tomllib.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
def test_the_registry_is_the_eight_walkthroughs():
    found = registry()
    assert {
        name: (e["walkthrough"], e["guide"], e["max_seconds"])
        for name, e in found.items()
    } == EXPECTED
    assert {name for name, e in found.items() if e.get("pending")} == PENDING
    for name, entry in found.items():
        assert set(entry) <= {"walkthrough", "guide", "max_seconds", "shows", "pending"}
        assert entry["shows"].strip(), f"{name} says nothing about what it shows"
        assert name.startswith(entry["walkthrough"] + "-")


def test_every_walkthrough_guide_is_a_journey_in_the_inventory():
    pages = loader.read_inventory(RUNNER_ROOT / "inventory.toml")["pages"]
    for name, entry in registry().items():
        page = pages.get(entry["guide"])
        assert page is not None, f"{name}: {entry['guide']} is not a nav page"
        assert page.get("class") == "journey", f"{name}: {entry['guide']}"


def test_the_presence_check_asks_for_the_same_walkthroughs():
    scripts = REPO_ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import docs_journeys_report as check
    finally:
        sys.path.remove(str(scripts))
    assert check.WALKTHROUGHS == tuple(f"R{n}" for n in range(1, 9))
    assert check.RECORDINGS_TOML == REGISTRY_PATH
    assert check.FRAME == (1280, 720)


# ---------------------------------------------------------------------------
# The real journeys record exactly the registry's walkthroughs
# ---------------------------------------------------------------------------
def _real_journeys() -> Dict[str, Journey]:
    context = loader.context_for(REPO_ROOT)
    return {path.stem: loader.load(path, context) for path in JOURNEYS.glob("*.yaml")}


def test_each_walkthrough_is_recorded_by_exactly_one_journey_of_its_guide():
    declared: Dict[str, List[str]] = {}
    journeys = _real_journeys()
    for stem, journey in journeys.items():
        if journey.recording is not None:
            declared.setdefault(journey.recording.name, []).append(stem)
    entries = registry()
    required = {name for name, e in entries.items() if not e.get("pending")}
    assert set(declared) == required, (
        "a walkthrough no journey records, or one too many"
    )
    for name, stems in declared.items():
        assert len(stems) == 1, f"{name} is recorded by {stems}"
        assert journeys[stems[0]].guide == entries[name]["guide"]


def test_the_walkthrough_segments_are_the_ones_planned():
    journeys = _real_journeys()
    segments = {
        j.recording.name: (j.steps[j.recorded[0]].id, j.steps[j.recorded[1]].id)
        for j in journeys.values()
        if j.recording is not None
    }
    # R7 stops before the crawls; R8 starts after the last one-time password.
    assert segments["R7-docs-site"] == ("home", "api-page")
    assert segments["R8-onboarding"] == ("demo-admin-log-out", "viewer-new-accepted")
    for name in ("R1-quick-start", "R5-reading-results", "R6-feature-flag"):
        journey = next(
            j for j in journeys.values() if j.recording and j.recording.name == name
        )
        assert journey.recorded == (0, len(journey.steps) - 1), name


def test_no_journey_is_recorded_whole_and_for_a_walkthrough():
    for stem, journey in _real_journeys().items():
        assert not (journey.video and journey.recording), stem


# ---------------------------------------------------------------------------
# The loader's refusals, each on one planted defect
# ---------------------------------------------------------------------------
GUIDE = """# Sample guide

## Sign in

Open the dashboard and click **Sign in**. Fill **Email** and **Password**, then
click **New experiment** and copy the one-time password from the **Sign in**
dialog.
"""
INVENTORY = {
    "pages": {
        "guides/sample.md": {"class": "journey", "journey": "sample", "reason": "x"},
        "guides/other.md": {"class": "journey", "journey": "other", "reason": "x"},
    }
}
REGISTRY = {
    "R1-sample": {"walkthrough": "R1", "guide": "guides/sample.md", "max_seconds": 60},
    "R2-other": {"walkthrough": "R2", "guide": "guides/other.md", "max_seconds": 60},
    "R3-later": {
        "walkthrough": "R3",
        "guide": "guides/sample.md",
        "max_seconds": 60,
        "pending": "not yet",
    },
}
STEPS: List[Dict[str, Any]] = [
    {
        "id": "open",
        "doc": "sign-in",
        "do": {"goto": "/login"},
        "expect": {"status": 200, "aria": '- button "Sign in"'},
        "fail": "the sign-in page does not answer",
    },
    {
        "id": "password",
        "doc": "sign-in",
        "do": {"fill": {"label": "Password", "secret": "new-password"}},
        "expect": {"visible": [{"role": "button", "name": "Sign in"}]},
        "snapshot": False,
        "snapshot_reason": "it types a password the run makes up",
        "fail": "there is no Password field",
    },
    {
        "id": "invite",
        "doc": "sign-in",
        "do": {"click": {"role": "button", "name": "New experiment"}},
        "expect": {"visible": [{"role": "dialog", "name": "Sign in"}]},
        "snapshot": False,
        "snapshot_reason": "its screen shows the one-time password",
        "fail": "no dialog opens",
    },
    {
        "id": "one-time",
        "doc": "sign-in",
        "do": {
            "keep": {
                "secret": "one-time",
                "role": "code",
                "within": {"role": "dialog", "name": "Sign in"},
            }
        },
        "fail": "the dialog shows no one-time password",
    },
    {
        "id": "close",
        "doc": "sign-in",
        "do": {"click": {"role": "button", "name": "Sign in"}},
        "expect": {"aria": '- heading "Experiments" [level=1]'},
        "fail": "the dialog does not close",
    },
    {
        "id": "key",
        "doc": "sign-in",
        "do": {
            "api": {
                "method": "POST",
                "path": "/api/v1/api-keys",
                "as": "admin",
                "body": {"name": "sample"},
            }
        },
        "expect": {"status": 201},
        "save": {"sdk-key": {"path": "key", "secret": True}},
        "fail": "no key is made",
    },
    {
        "id": "after",
        "doc": "sign-in",
        "do": {"goto": "/experiments"},
        "expect": {"aria": '- heading "Experiments" [level=1]'},
        "fail": "the experiments page does not answer",
    },
]


def _journey(recording: Any, steps: List[Dict[str, Any]] = STEPS, **top: Any):
    data: Dict[str, Any] = {
        "guide": "guides/sample.md",
        "stack": "compose-dev",
        "profile": "core",
        "video": False,
        "written": TODAY,
        "passwords": ["new-password"],
    }
    data.update(top)
    if recording is not None:
        data["recording"] = recording
    data["steps"] = [dict(step) for step in steps]
    return data


def _load(tmp_path: Path, data: Dict[str, Any], **context: Any) -> Journey:
    docs = tmp_path / "docs" / "guides"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "sample.md").write_text(GUIDE, encoding="utf-8")
    (docs / "other.md").write_text(GUIDE, encoding="utf-8")
    path = tmp_path / "journeys" / "sample.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    values: Dict[str, Any] = {
        "docs_root": tmp_path / "docs",
        "inventory": INVENTORY,
        "doc_examples": {},
        "oracles": {},
        "today": TODAY,
        "recordings": REGISTRY,
    }
    values.update(context)
    return loader.load(path, loader.Context(**values))


def _refused(tmp_path: Path, data: Dict[str, Any]) -> str:
    with pytest.raises(loader.Refused) as refused:
        _load(tmp_path, data)
    return "\n".join(refused.value.problems)


def test_a_walkthrough_after_the_last_kept_value_loads(tmp_path):
    journey = _load(tmp_path, _journey({"name": "R1-sample", "start": "key"}))
    assert journey.recorded == (5, 6)
    # The api step that makes a key is in the segment: the key never reaches
    # the browser, and the runner checks the page after it all the same.
    assert journey.has_secrets


def test_a_password_typed_into_a_password_field_may_be_recorded(tmp_path):
    steps = [STEPS[0], STEPS[1], STEPS[4]]
    journey = _load(tmp_path, _journey({"name": "R1-sample"}, steps))
    assert journey.recorded == (0, 2)


PLANTS = [
    pytest.param(
        _journey({"name": "R9-nothing", "start": "key"}),
        "recording 'R9-nothing' is not a table of recordings.toml",
        id="unknown-walkthrough",
    ),
    pytest.param(
        _journey({"name": "R3-later", "start": "key"}),
        "recording 'R3-later' is pending in recordings.toml",
        id="pending-walkthrough",
    ),
    pytest.param(
        _journey({"name": "R2-other", "start": "key"}),
        "recording 'R2-other' is recorded from 'guides/other.md' in"
        " recordings.toml, not from 'guides/sample.md'",
        id="another-guides-walkthrough",
    ),
    pytest.param(
        _journey({"name": "R1-sample", "start": "key"}, video=True),
        "a journey is recorded whole (video) or for its walkthrough (recording)",
        id="video-and-recording",
    ),
    pytest.param(
        _journey({"name": "R1-sample", "start": "nope"}),
        "recording.start 'nope' is not a step of the journey",
        id="start-names-no-step",
    ),
    pytest.param(
        _journey({"name": "R1-sample", "start": "after", "end": "key"}),
        "recording.end 'key' comes before recording.start 'after'",
        id="end-before-start",
    ),
    pytest.param(
        _journey({"name": "R1-sample"}),
        "step 4 (one-time): the recording holds a keep step",
        id="segment-holds-a-keep",
    ),
    pytest.param(
        _journey({"name": "R1-sample", "end": "invite"}),
        "step 3 (invite): the recording holds the screen the next step keeps",
        id="segment-holds-the-screen-before-a-keep",
    ),
    pytest.param(
        _journey({"name": "R1-sample", "start": "close"}),
        "step 5 (close): the recording starts right after a keep step",
        id="segment-starts-on-the-kept-screen",
    ),
    pytest.param(
        _journey(
            {"name": "R1-sample", "end": "password"},
            [
                STEPS[0],
                {
                    **STEPS[1],
                    "do": {"fill": {"label": "Email", "secret": "new-password"}},
                },
            ],
        ),
        "the recording types the secret 'new-password' into 'Email', which is"
        " not a password field",
        id="secret-typed-where-it-is-drawn",
    ),
    pytest.param(
        _journey({"name": "r1-sample", "start": "key"}),
        "recording.name: String should match pattern",
        id="name-not-a-walkthrough-name",
    ),
]


@pytest.mark.parametrize("data, fragment", PLANTS)
def test_each_recording_refusal_fires(tmp_path, data, fragment):
    assert fragment in _refused(tmp_path, data)


# ---------------------------------------------------------------------------
# The page check: what the runner reads after every recorded step (V13)
# ---------------------------------------------------------------------------
KEY = "eptk_Planted0Key9xyz"


@pytest.mark.parametrize(
    "text, fields, where",
    [
        pytest.param(f"Your key: {KEY}", [], "the page's text", id="in-the-text"),
        pytest.param(
            "Planted key\nshown", [], "the page's text", id="split-by-a-line-break"
        ),
        pytest.param(
            "", [("text", f"x {KEY} y")], "a field of type text", id="in-a-text-field"
        ),
        pytest.param(
            "", [("textarea", KEY)], "a field of type textarea", id="in-a-text-area"
        ),
        pytest.param("", [("password", KEY)], None, id="dots-in-a-password-field"),
        pytest.param("Nothing kept here", [("text", "hello")], None, id="clean"),
    ],
)
def test_the_page_check_finds_a_kept_value_wherever_it_is_drawn(text, fields, where):
    assert redaction.on_screen(text, fields, {KEY, "Planted key shown"}) == where


def test_the_page_check_names_the_place_never_the_value():
    where = redaction.on_screen(KEY, [], {KEY})
    assert where is not None and KEY not in where


# ---------------------------------------------------------------------------
# The end-of-run scan removes a journey's walkthrough with its files
# ---------------------------------------------------------------------------
PLANT = "Planted0Value9xyz"


def _run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "recordings").mkdir(parents=True)
    (run / "invite").mkdir()
    (run / "recordings" / "R8-onboarding.webm").write_bytes(b"webm")
    (run / "recordings" / "R7-docs-site.webm").write_bytes(b"webm")
    return run


OWNERS = {
    "recordings/R8-onboarding.webm": "invite",
    "recordings/R7-docs-site.webm": "docs-site",
}


def test_a_journey_file_holding_a_value_takes_its_walkthrough_with_it(tmp_path):
    run = _run_dir(tmp_path)
    (run / "invite" / "03-dialog.aria.yml").write_text(f"- code: {PLANT}\n")
    record = redaction.clear(run, {PLANT}, owners=OWNERS)
    assert record["removed"] == ["invite/03-dialog.aria.yml"]
    assert record["screens_removed"] == ["recordings/R8-onboarding.webm"]
    assert (run / "recordings" / "R7-docs-site.webm").is_file()
    removed = list(record["removed"])
    assert redaction.journeys_of(removed, ["invite", "docs-site"], OWNERS) == {"invite"}


def test_a_shared_file_holding_a_value_takes_every_walkthrough(tmp_path):
    run = _run_dir(tmp_path)
    (run / "results.jsonl").write_text(f'{{"observed": "{PLANT}"}}\n')
    record = redaction.clear(run, {PLANT}, owners=OWNERS)
    assert record["screens_removed"] == [
        "recordings/R7-docs-site.webm",
        "recordings/R8-onboarding.webm",
    ]


def test_a_walkthrough_holding_a_value_fails_its_own_journey(tmp_path):
    run = _run_dir(tmp_path)
    (run / "recordings" / "R8-onboarding.webm").write_bytes(PLANT.encode())
    record = redaction.clear(run, {PLANT}, owners=OWNERS)
    assert record["removed"] == ["recordings/R8-onboarding.webm"]
    removed = list(record["removed"])
    assert redaction.journeys_of(removed, ["invite", "docs-site"], OWNERS) == {"invite"}
    assert redaction.files_of(removed, "invite", OWNERS) == tuple(removed)
    assert redaction.files_of(removed, "docs-site", OWNERS) == ()


def test_an_unowned_walkthrough_holding_a_value_fails_every_journey(tmp_path):
    run = _run_dir(tmp_path)
    (run / "recordings" / "R7-docs-site.webm").write_bytes(PLANT.encode())
    record = redaction.clear(run, {PLANT})
    removed = list(record["removed"])
    assert redaction.journeys_of(removed, ["invite", "docs-site"]) == {
        "invite",
        "docs-site",
    }


# ---------------------------------------------------------------------------
# The summary: a walkthrough reads PASS only when its guide passed (V12)
# ---------------------------------------------------------------------------
def _step_record(result: str, step: int = 1) -> Record:
    return Record(
        run="1",
        sha="abc",
        stack="compose-dev",
        guide="statistics/power-analysis.md",
        step=step,
        step_id=f"s{step}",
        heading="The power calculator",
        action="open /power-calculator",
        expected="status 200",
        failure_signature="it does not answer",
        result=result,
        reason="",
        observed="seen",
        snapshot="",
        expected_snapshot="structural only",
        ms=5,
    )


def _guide_run(*results: str) -> report.GuideRun:
    return report.GuideRun(
        journey="power-calculator",
        guide="statistics/power-analysis.md",
        title="Statistical Power Analysis",
        stack="compose-dev",
        records=tuple(_step_record(r, n) for n, r in enumerate(results, 1)),
    )


RECORDED = {
    "R4-power-analysis": {
        "journey": "power-calculator",
        "file": "recordings/R4-power-analysis.webm",
        "seconds": 9.5,
        "dropped": "",
    }
}


def _rows(run: report.GuideRun, present: bool = True, recorded=RECORDED):
    rows = report.walkthrough_rows(
        registry(),
        recorded,
        {run.journey: report.verdict(run)},
        lambda name: present,
    )
    return {name: (length, result) for name, _, length, result in rows}


def test_a_walkthrough_reads_pass_when_its_guide_passed():
    rows = _rows(_guide_run("PASS", "PASS"))
    assert rows["R4-power-analysis"] == (
        "9.5 s, at most 60 s",
        "PASS (power-calculator)",
    )


def test_a_walkthrough_reads_fail_when_its_guide_failed():
    """V12's planted defect: R4's guide fails, so its recording reads FAIL."""
    rows = _rows(_guide_run("PASS", "FAIL"))
    assert rows["R4-power-analysis"][1] == "FAIL at step 2 (power-calculator)"


def test_the_other_walkthrough_states_are_said():
    rows = _rows(_guide_run("PASS"))
    assert rows["R5-srm-warning"][1].startswith("pending: ")
    assert rows["R1-quick-start"][1] == "not recorded in this run"
    gone = _rows(_guide_run("PASS"), present=False)
    assert gone["R4-power-analysis"][1].startswith("removed by the end-of-run scan")
    dropped = _rows(
        _guide_run("PASS"),
        recorded={
            "R4-power-analysis": {
                **RECORDED["R4-power-analysis"],
                "file": "",
                "dropped": "a value the run keeps is drawn in the page's text",
            }
        },
    )
    assert dropped["R4-power-analysis"][1] == (
        "dropped: a value the run keeps is drawn in the page's text"
    )


def test_the_summary_has_a_walkthroughs_table():
    run = _guide_run("PASS")
    rows = report.walkthrough_rows(
        registry(), RECORDED, {run.journey: report.verdict(run)}, lambda name: True
    )
    text = report.summary_markdown(
        [run], {"pages": {}}, date="2026-10-07", sha="abc", walkthroughs=rows
    )
    assert "## Launch walkthroughs" in text
    assert (
        "| R4-power-analysis | statistics/power-analysis.md | 9.5 s, at most 60 s |"
        " PASS (power-calculator) |" in text
    )
    plain = report.summary_markdown([run], {"pages": {}}, date="2026-10-07", sha="abc")
    assert "Launch walkthroughs" not in plain
