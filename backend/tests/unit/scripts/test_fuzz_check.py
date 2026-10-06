"""scripts/fuzz_check.py decides an API fuzzing pass; these pin how.

The reach check is the part that keeps a fuzz run honest: Schemathesis exits 0
on a run whose every request was refused (a bad token, a filter that selected
the wrong operations), so a pass is red unless every operation it selects was
reached or is listed, with a reason, in tests/fuzz/unreached.toml. Fixture
reports below are ndjson in the shape Schemathesis 4.29 writes
(``ScenarioFinished.recorder.interactions``), cut down to the fields read.

Also pinned: the exclusion list (tests/fuzz/exclusions.toml) operation by
operation, the SDK pass's selection against the rate limiter's SDK routes,
the counts line and step summary as the only public output, and `make fuzz`'s
refusals that need neither git nor Docker.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = REPO_ROOT / "scripts"
FULL_SNAPSHOT = REPO_ROOT / "docs" / "api" / "openapi-v1.full.json"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fuzz_check

DOCUMENT = {
    "openapi": "3.1.0",
    "paths": {
        "/api/v1/items": {
            "get": {"security": [{"OAuth2PasswordBearer": []}]},
            "post": {"security": [{"OAuth2PasswordBearer": []}]},
        },
        "/api/v1/items/{item_id}": {
            "delete": {"security": [{"OAuth2PasswordBearer": []}]},
        },
        "/api/v1/open": {"get": {}},
        "/api/v1/tracking/track": {"post": {"security": [{"APIKeyHeader": []}]}},
        "/api/v1/maybe": {"get": {"security": [{"OAuth2PasswordBearer": []}, {}]}},
    },
}
ALL = {
    "GET /api/v1/items",
    "POST /api/v1/items",
    "DELETE /api/v1/items/{item_id}",
    "GET /api/v1/open",
    "POST /api/v1/tracking/track",
    "GET /api/v1/maybe",
}

EXCLUSIONS = """
[[exclude]]
operation = "DELETE /api/v1/items/{item_id}"
passes = ["superuser", "viewer", "sdk"]
reason = "Deletes the item the pass needs."
"""

Interactions = Dict[str, List[Tuple[str, Optional[int]]]]


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _report(
    tmp_path: Path, interactions: Interactions, selected: Optional[int] = 5
) -> Path:
    """An ndjson report in Schemathesis 4.29's shape, in its own directory."""
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    events: List[dict] = [{"Initialize": {"schemathesis_version": "4.29.3"}}]
    if selected is not None:
        events.append(
            {
                "LoadingFinished": {
                    "statistic": {"operations": {"total": 6, "selected": selected}}
                }
            }
        )
    for label, items in interactions.items():
        recorded = {}
        for index, (method, status) in enumerate(items):
            recorded[f"{label}-{index}"] = {
                "request": {"method": method, "uri": "http://127.0.0.1:8000/x"},
                "response": None if status is None else {"status_code": status},
            }
        events.append(
            {
                "ScenarioFinished": {
                    "phase": "coverage",
                    "status": "success",
                    "recorder": {"label": label, "interactions": recorded},
                }
            }
        )
    events.append({"EngineFinished": {}})
    _write(
        report_dir / "ndjson-20261006T000000Z.ndjson",
        "".join(json.dumps(e) + "\n" for e in events),
    )
    return report_dir


#: Every selected operation of the superuser pass reached once.
REACHED_ALL: Interactions = {
    "GET /api/v1/items": [("GET", 200)],
    "POST /api/v1/items": [("POST", 201)],
    "GET /api/v1/open": [("GET", 200)],
    "POST /api/v1/tracking/track": [("POST", 202)],
    "GET /api/v1/maybe": [("GET", 200)],
}


def _verdict(
    tmp_path: Path,
    interactions: Interactions,
    unreached: str = "",
    pass_name: str = "superuser",
    selected: Optional[int] = 5,
) -> fuzz_check.Verdict:
    operations = fuzz_check.load_operations(DOCUMENT)
    excluded = fuzz_check.load_exclusions(
        _write(tmp_path / "exclusions.toml", EXCLUSIONS), operations
    )
    listed = fuzz_check.load_unreached(
        _write(tmp_path / "unreached.toml", unreached),
        pass_name,
        operations,
        excluded,
    )
    chosen = fuzz_check.selection(pass_name, operations, excluded)
    report = fuzz_check.read_report(_report(tmp_path, interactions, selected))
    return fuzz_check.decide(report, operations, chosen, listed)


# ---------------------------------------------------------------------------
# The reach check
# ---------------------------------------------------------------------------


def test_every_operation_reached_is_green(tmp_path):
    verdict = _verdict(tmp_path, REACHED_ALL)
    assert verdict.green
    assert verdict.reached == ALL - {"DELETE /api/v1/items/{item_id}"}
    assert not verdict.unreached


def test_an_operation_that_only_answered_refusals_is_unreached_and_red(tmp_path):
    """The planted UNREACHED: every answer was a refusal of some kind."""
    interactions = dict(REACHED_ALL)
    interactions["POST /api/v1/items"] = [
        ("POST", status) for status in sorted(fuzz_check.NOT_REACHED)
    ]
    verdict = _verdict(tmp_path, interactions)
    assert verdict.unreached == {"POST /api/v1/items"}
    assert verdict.unlisted == {"POST /api/v1/items"}
    assert not verdict.green


def test_a_listed_unreached_operation_is_green(tmp_path):
    interactions = dict(REACHED_ALL)
    interactions["POST /api/v1/items"] = [("POST", 422), ("POST", 404)]
    listed = """
[[unreached]]
pass = "superuser"
operation = "POST /api/v1/items"
reason = "Every generated body fails validation."
"""
    verdict = _verdict(tmp_path, interactions, unreached=listed)
    assert verdict.unreached == {"POST /api/v1/items"}
    assert not verdict.unlisted
    assert verdict.green


def test_a_listed_operation_that_was_reached_is_stale_and_red(tmp_path):
    listed = """
[[unreached]]
pass = "superuser"
operation = "GET /api/v1/open"
reason = "Listed as unreached, but it answers 200 now."
"""
    verdict = _verdict(tmp_path, REACHED_ALL, unreached=listed)
    assert verdict.stale == {"GET /api/v1/open"}
    assert not verdict.green


def test_a_listed_entry_counts_only_for_its_own_pass(tmp_path):
    interactions = dict(REACHED_ALL)
    interactions["POST /api/v1/items"] = [("POST", 403)]
    listed = """
[[unreached]]
pass = "viewer"
operation = "POST /api/v1/items"
reason = "A VIEWER may not create items."
"""
    verdict = _verdict(tmp_path, interactions, unreached=listed)
    assert verdict.unlisted == {"POST /api/v1/items"}
    assert not verdict.green


def test_a_method_probe_does_not_count(tmp_path):
    """The coverage phase sends other methods to the same path; their answers
    (405, or whatever another route on that path answers) say nothing about
    this operation."""
    interactions = dict(REACHED_ALL)
    interactions["GET /api/v1/items"] = [
        ("GET", 404),
        ("TRACE", 405),
        ("PUT", 405),
        ("POST", 201),
    ]
    verdict = _verdict(tmp_path, interactions)
    assert "GET /api/v1/items" in verdict.unreached
    assert not verdict.green


def test_an_operation_missing_from_the_report_is_unreached(tmp_path):
    """One operation filtered out of the command: no interaction at all."""
    interactions = dict(REACHED_ALL)
    del interactions["GET /api/v1/maybe"]
    verdict = _verdict(tmp_path, interactions, selected=4)
    assert verdict.unlisted == {"GET /api/v1/maybe"}
    assert verdict.selection_mismatch
    assert not verdict.green


def test_a_request_with_no_answer_does_not_reach(tmp_path):
    interactions = dict(REACHED_ALL)
    interactions["GET /api/v1/open"] = [("GET", None)]
    verdict = _verdict(tmp_path, interactions)
    assert "GET /api/v1/open" in verdict.unreached
    assert verdict.no_answer == {"GET /api/v1/open"}


def test_a_5xx_is_red_even_on_a_reached_operation(tmp_path):
    interactions = dict(REACHED_ALL)
    interactions["GET /api/v1/items"] = [("GET", 200), ("GET", 500)]
    verdict = _verdict(tmp_path, interactions)
    assert verdict.server_errors == {"GET /api/v1/items"}
    assert "GET /api/v1/items" in verdict.reached
    assert not verdict.green


def test_an_excluded_operation_in_the_report_is_red(tmp_path):
    interactions = dict(REACHED_ALL)
    interactions["DELETE /api/v1/items/{item_id}"] = [("DELETE", 204)]
    verdict = _verdict(tmp_path, interactions, selected=6)
    assert verdict.outside == {"DELETE /api/v1/items/{item_id}"}
    assert not verdict.green


def test_schemathesis_selecting_a_different_number_is_red(tmp_path):
    verdict = _verdict(tmp_path, REACHED_ALL, selected=6)
    assert verdict.selection_mismatch
    assert not verdict.green


def test_a_bogus_token_leaves_reached_only_what_declares_no_auth(tmp_path):
    """Tamper (i) in miniature: every operation with an auth scheme answers
    401, and only the ones that declare none are reached."""
    interactions = {
        "GET /api/v1/items": [("GET", 401)],
        "POST /api/v1/items": [("POST", 401)],
        "GET /api/v1/open": [("GET", 200)],
        "POST /api/v1/tracking/track": [("POST", 401)],
        "GET /api/v1/maybe": [("GET", 401)],
    }
    verdict = _verdict(tmp_path, interactions)
    assert verdict.reached == {"GET /api/v1/open"}
    assert verdict.auth_declared & verdict.reached == set()
    assert verdict.unreached == verdict.auth_declared
    assert not verdict.green


def test_an_empty_report_fails(tmp_path):
    with pytest.raises(fuzz_check.ReportError, match="no interactions"):
        fuzz_check.read_report(_report(tmp_path, {"GET /api/v1/items": []}))


def test_a_missing_or_second_report_fails(tmp_path):
    (tmp_path / "none").mkdir()
    with pytest.raises(fuzz_check.ReportError, match="found 0"):
        fuzz_check.read_report(tmp_path / "none")
    report_dir = _report(tmp_path, REACHED_ALL)
    _write(report_dir / "ndjson-second.ndjson", "")
    with pytest.raises(fuzz_check.ReportError, match="found 2"):
        fuzz_check.read_report(report_dir)


def test_a_report_line_that_is_not_json_fails(tmp_path):
    report_dir = _report(tmp_path, REACHED_ALL)
    path = next(report_dir.glob("*.ndjson"))
    path.write_text(path.read_text() + "{not json\n")
    with pytest.raises(fuzz_check.ReportError, match="not JSON"):
        fuzz_check.read_report(report_dir)


# ---------------------------------------------------------------------------
# The lists
# ---------------------------------------------------------------------------

OPERATIONS = fuzz_check.load_operations(DOCUMENT)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[[exclude]]\noperation = "GET /api/v1/nope"\npasses = ["sdk"]\n'
            'reason = "No such operation here."\n',
            "not an operation",
        ),
        (
            '[[exclude]]\noperation = "GET /api/v1/open"\npasses = ["admin"]\n'
            'reason = "Not a pass of this suite."\n',
            "passes must be",
        ),
        (
            '[[exclude]]\noperation = "GET /api/v1/open"\npasses = []\n'
            'reason = "No pass at all is named."\n',
            "passes must be",
        ),
        (
            '[[exclude]]\noperation = "GET /api/v1/open"\npasses = ["sdk"]\n',
            "reason",
        ),
        (
            '[[exclude]]\noperation = "GET /api/v1/open"\npasses = ["sdk"]\n'
            'reason = "First time it is listed."\n'
            '[[exclude]]\noperation = "GET /api/v1/open"\npasses = ["viewer"]\n'
            'reason = "Second time it is listed."\n',
            "listed twice",
        ),
        (
            '[[exclude]]\noperation = "/api/v1/open"\npasses = ["sdk"]\n'
            'reason = "No method in the operation."\n',
            "METHOD /path",
        ),
        (
            '[[exclude]]\noperation = "GET /api/v1/open"\npasses = ["sdk"]\n'
            'reason = "An extra key is refused."\nmethod = "GET"\n',
            "unknown keys",
        ),
        ("[[excluded]]\n", "unknown top-level"),
        ("[[exclude]\n", "cannot be read"),
    ],
)
def test_the_exclusion_list_refuses(tmp_path, text, message):
    with pytest.raises(fuzz_check.ListError, match=message):
        fuzz_check.load_exclusions(_write(tmp_path / "x.toml", text), OPERATIONS)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[[unreached]]\npass = "superuser"\noperation = "GET /api/v1/nope"\n'
            'reason = "No such operation here."\n',
            "not an operation",
        ),
        (
            '[[unreached]]\npass = "nobody"\noperation = "GET /api/v1/open"\n'
            'reason = "Not a pass of this suite."\n',
            "pass must be",
        ),
        (
            '[[unreached]]\npass = "superuser"\noperation = "GET /api/v1/open"\n'
            'reason = "short"\n',
            "reason",
        ),
        (
            '[[unreached]]\npass = "superuser"\n'
            'operation = "DELETE /api/v1/items/{item_id}"\n'
            'reason = "Excluded, so it cannot be unreached."\n',
            "does not select",
        ),
        (
            '[[unreached]]\npass = "sdk"\noperation = "GET /api/v1/open"\n'
            'reason = "Not an SDK route at all."\n',
            "does not select",
        ),
        (
            '[[unreached]]\npass = "viewer"\noperation = "GET /api/v1/open"\n'
            'reason = "First time it is listed."\n'
            '[[unreached]]\npass = "viewer"\noperation = "GET /api/v1/open"\n'
            'reason = "Second time it is listed."\n',
            "listed twice",
        ),
    ],
)
def test_the_unreached_list_refuses_for_every_pass(tmp_path, text, message):
    """A broken entry fails all three passes, not only its own."""
    excluded = fuzz_check.load_exclusions(
        _write(tmp_path / "exclusions.toml", EXCLUSIONS), OPERATIONS
    )
    path = _write(tmp_path / "unreached.toml", text)
    for pass_name in fuzz_check.PASSES:
        with pytest.raises(fuzz_check.ListError, match=message):
            fuzz_check.load_unreached(path, pass_name, OPERATIONS, excluded)


def test_the_sdk_pass_selects_only_the_sdk_routes(tmp_path):
    excluded = fuzz_check.load_exclusions(
        _write(tmp_path / "exclusions.toml", EXCLUSIONS), OPERATIONS
    )
    assert fuzz_check.selection("sdk", OPERATIONS, excluded) == {
        "POST /api/v1/tracking/track"
    }
    args = fuzz_check.filter_args("sdk", excluded)
    assert args[:2] == ["--include-path-regex", fuzz_check.SDK_PATH_REGEX]
    assert args[2:] == ["--exclude-name", "DELETE /api/v1/items/{item_id}"]
    assert fuzz_check.filter_args("viewer", excluded) == args[2:]


def test_auth_is_read_from_the_operation_or_the_document():
    document = {
        "security": [{"OAuth2PasswordBearer": []}],
        "paths": {"/a": {"get": {}, "post": {"security": []}}},
    }
    operations = fuzz_check.load_operations(document)
    assert operations["GET /a"].has_auth
    assert not operations["POST /a"].has_auth
    assert OPERATIONS["GET /api/v1/maybe"].has_auth  # optional, but it names one
    assert not OPERATIONS["GET /api/v1/open"].has_auth


# ---------------------------------------------------------------------------
# The real lists, against the full profile's API document
# ---------------------------------------------------------------------------

#: The exclusion list, pinned: (operation, passes). Change it with
#: tests/fuzz/exclusions.toml.
ALL_PASSES = ("superuser", "viewer", "sdk")
EXCLUDED = {
    # signing in and out, and the caller's own credentials
    "POST /api/v1/auth/login": ALL_PASSES,
    "POST /api/v1/auth/token": ALL_PASSES,
    "POST /api/v1/auth/logout": ALL_PASSES,
    "POST /api/v1/users/me/password": ALL_PASSES,
    "DELETE /api/v1/api-keys/{key_id}": ALL_PASSES,
    "DELETE /api/v1/users/{user_id}": ("viewer",),
    # /api/v1/export/*: one counter of 10 a minute
    "GET /api/v1/export/experiments": ALL_PASSES,
    "GET /api/v1/export/feature-flags": ALL_PASSES,
    "GET /api/v1/export/reports/experiments/{experiment_id}": ALL_PASSES,
    "GET /api/v1/export/reports/overview": ALL_PASSES,
    "GET /api/v1/export/variants": ALL_PASSES,
    # outbound connections
    "POST /api/v1/warehouse/analysis/connections/test": ALL_PASSES,
    "POST /api/v1/warehouse/analysis/connections/{connection_id}/test": ALL_PASSES,
    "POST /api/v1/warehouse/analysis/sources/{source_id}/validate": ALL_PASSES,
    "POST /api/v1/warehouse/analysis/sources/{source_id}/preview": ALL_PASSES,
    "POST /api/v1/warehouse/analysis/experiments/{experiment_id}/runs": ALL_PASSES,
    "POST /api/v1/notifications/test": ALL_PASSES,
    "POST /api/v1/scheduler/notify/test": ALL_PASSES,
    "POST /api/v1/llm-experiments/{experiment_id}/complete": ALL_PASSES,
    "POST /api/v1/llm-experiments/{experiment_id}/judge": ALL_PASSES,
    "POST /api/v1/ai/design": ALL_PASSES,
    "POST /api/v1/ai/interpret/{experiment_id}": ALL_PASSES,
    "POST /api/v1/auth/sso/configs": ALL_PASSES,
    "PUT /api/v1/auth/sso/configs/{config_id}": ALL_PASSES,
    "GET /api/v1/auth/sso/oidc/{provider}/callback": ALL_PASSES,
}


@pytest.fixture(scope="module")
def full_operations():
    if not FULL_SNAPSHOT.is_file():
        pytest.skip("this tree has no docs/api/openapi-v1.full.json")
    return fuzz_check.load_operations(json.loads(FULL_SNAPSHOT.read_text()))


def test_the_exclusion_list_is_exactly_the_pinned_one(full_operations):
    excluded = fuzz_check.load_exclusions(fuzz_check.EXCLUSIONS, full_operations)
    actual = {
        label: tuple(p for p in ALL_PASSES if label in excluded[p])
        for label in set().union(*excluded.values())
    }
    assert actual == EXCLUDED


def test_both_warehouse_connection_tests_are_excluded_in_every_pass(
    full_operations,
):
    excluded = fuzz_check.load_exclusions(fuzz_check.EXCLUSIONS, full_operations)
    for label in (
        "POST /api/v1/warehouse/analysis/connections/test",
        "POST /api/v1/warehouse/analysis/connections/{connection_id}/test",
    ):
        assert all(label in excluded[p] for p in fuzz_check.PASSES), label


def test_the_unreached_list_holds_for_every_pass(full_operations):
    excluded = fuzz_check.load_exclusions(fuzz_check.EXCLUSIONS, full_operations)
    for pass_name in fuzz_check.PASSES:
        fuzz_check.load_unreached(
            fuzz_check.UNREACHED, pass_name, full_operations, excluded
        )


def test_the_sdk_prefixes_are_the_rate_limiters():
    from backend.app.middleware.rate_limiter import SDK_PATH_PREFIXES

    assert fuzz_check.SDK_PATH_PREFIXES == tuple(SDK_PATH_PREFIXES)


def test_the_sdk_regex_selects_what_the_evaluation_selects(full_operations):
    """Schemathesis selects by --include-path-regex, the evaluation by prefix;
    over the whole document they must agree."""
    pattern = re.compile(fuzz_check.SDK_PATH_REGEX)
    by_regex = {
        label for label, op in full_operations.items() if pattern.search(op.path)
    }
    by_prefix = fuzz_check.selection(
        "sdk", full_operations, {p: set() for p in fuzz_check.PASSES}
    )
    assert by_regex == by_prefix
    assert len(by_prefix) >= 10


# ---------------------------------------------------------------------------
# What a run prints and posts
# ---------------------------------------------------------------------------

COUNTS_LINE = re.compile(
    r"fuzz pass (superuser|viewer|sdk), \d{4}-\d{2}-\d{2}, commit [0-9a-f]{7,40},"
    r" seed \d{1,10}: (GREEN|RED)"
    r" \| operations selected \d+ \(Schemathesis (\d+|none)\), fuzzed \d+,"
    r" outside the selection \d+"
    r" \| 5xx operations \d+"
    r" \| reached \d+, unreached \d+ \(not listed \d+, listed but reached \d+\)"
    r" \| declaring an auth scheme \d+, of them reached \d+"
    r" \| with a request that got no answer \d+"
)


def _run_main(tmp_path, interactions, *extra, unreached=""):
    schema = _write(tmp_path / "openapi.json", json.dumps(DOCUMENT))
    exclusions = _write(tmp_path / "exclusions.toml", EXCLUSIONS)
    listed = _write(tmp_path / "unreached.toml", unreached)
    report_dir = (
        _report(tmp_path, interactions)
        if interactions is not None
        else tmp_path / "empty"
    )
    report_dir.mkdir(exist_ok=True)
    return fuzz_check.main(
        [
            "evaluate",
            "--pass",
            "superuser",
            "--schema",
            str(schema),
            "--exclusions",
            str(exclusions),
            "--unreached",
            str(listed),
            "--report-dir",
            str(report_dir),
            "--seed",
            "20261006",
            "--sha",
            "0123456789abcdef0123456789abcdef01234567",
            "--date",
            "2026-10-06",
            *extra,
        ]
    )


def test_the_only_printed_line_is_counts(tmp_path, capsys):
    interactions = dict(REACHED_ALL)
    interactions["GET /api/v1/items"] = [("GET", 500)]
    assert _run_main(tmp_path, interactions) == 1
    out = capsys.readouterr()
    assert out.err == ""
    lines = out.out.splitlines()
    assert len(lines) == 1 and COUNTS_LINE.fullmatch(lines[0]), lines
    assert "/api/" not in out.out


def test_a_missing_report_is_red_and_says_only_that(tmp_path, capsys):
    assert _run_main(tmp_path, None) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "fuzz_check: expected one ndjson report, found 0"
    assert COUNTS_LINE.fullmatch(lines[1]), lines


def test_a_refused_list_exits_2(tmp_path, capsys):
    bad = '[[unreached]]\npass = "superuser"\noperation = "GET /api/v1/nope"\n'
    bad += 'reason = "No such operation here."\n'
    assert _run_main(tmp_path, REACHED_ALL, unreached=bad) == 2
    assert "refused" in capsys.readouterr().err


@pytest.fixture
def qa_render():
    if not (SCRIPTS / "qa_render.py").is_file():
        pytest.skip("this tree has no scripts/qa_render.py")


@pytest.mark.usefixtures("qa_render")
def test_the_green_summary_is_the_green_template(tmp_path, capsys):
    summary = tmp_path / "summary.md"
    assert _run_main(tmp_path, REACHED_ALL, "--summary", str(summary)) == 0
    text = summary.read_text()
    assert text.startswith(
        "API fuzzing (superuser pass), 2026-10-06, commit "
        "0123456789abcdef0123456789abcdef01234567: GREEN"
    )
    assert "Operations fuzzed: 5 of the 5 this pass selects." in text
    assert "make fuzz FUZZ_SEED=20261006" in text


@pytest.mark.usefixtures("qa_render")
def test_the_red_summary_is_the_red_template(tmp_path):
    summary = tmp_path / "summary.md"
    interactions = dict(REACHED_ALL)
    interactions["GET /api/v1/items"] = [("GET", 503)]
    interactions["POST /api/v1/items"] = [("POST", 403)]
    link = "https://github.com/getexperimently/experimently/actions/runs/123"
    assert (
        _run_main(tmp_path, interactions, "--summary", str(summary), "--run-link", link)
        == 1
    )
    text = summary.read_text()
    assert text.splitlines()[0].endswith(": RED")
    assert "Operations that answered 5xx: 1, of which 1 are not in" in text
    assert "1 unreached and not listed; 0 listed as unreached" in text
    assert f"Run: {link}" in text


@pytest.mark.usefixtures("qa_render")
def test_a_red_summary_without_a_run_link_is_refused(tmp_path):
    interactions = dict(REACHED_ALL)
    interactions["GET /api/v1/items"] = [("GET", 500)]
    summary = tmp_path / "summary.md"
    assert _run_main(tmp_path, interactions, "--summary", str(summary)) == 2
    assert not summary.exists()


# ---------------------------------------------------------------------------
# The workflow, the arm and `make fuzz` run the same command
# ---------------------------------------------------------------------------

#: The Schemathesis flags of a fuzz run (plan v1.2 section F [4]).
FLAGS = (
    "--checks not_a_server_error --phases examples,coverage,fuzzing",
    "--max-examples 5 --workers 1 --rate-limit 4/s",
    '--seed "$FUZZ_SEED" --generation-deterministic',
    "--report ndjson --report-dir",
)


def test_the_arm_and_make_fuzz_pass_the_same_flags():
    arm = (WORKFLOWS / "_platform.yml").read_text()
    local = (SCRIPTS / "fuzz_local.sh").read_text()
    for flags in FLAGS:
        assert flags in arm, flags
        assert flags.replace("$FUZZ_SEED", "$fuzz_seed") in local, flags
    for text in (arm, local):
        assert "stateful" not in text


def test_fuzz_yml_is_dispatch_only_with_three_passes():
    workflow = yaml.safe_load((WORKFLOWS / "fuzz.yml").read_text())
    assert list(workflow[True]) == ["workflow_dispatch"]  # PyYAML reads on: as True
    assert workflow["permissions"] == {"contents": "read"}
    passes = {}
    for job_id, job in workflow["jobs"].items():
        if "uses" not in job:
            continue
        assert job["uses"] == "./.github/workflows/_platform.yml", job_id
        passes[job["with"]["fuzz_pass"]] = job["with"]
    assert set(passes) == set(fuzz_check.PASSES)
    for pass_name, given in passes.items():
        assert given["suite"] == "fuzz"
        assert given["profile"] == "full"
        assert given["seed"] == ("demo,sdk-contract" if pass_name == "sdk" else "demo")
        assert given["api_env"].split() == [
            "AWS_ENDPOINT_URL=http://127.0.0.1:9",
            "AWS_ACCESS_KEY_ID=fuzz",
            "AWS_SECRET_ACCESS_KEY=fuzz",
        ]
        assert isinstance(given["timeout-minutes"], int)


FUZZ_LOCAL = SCRIPTS / "fuzz_local.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["1", "abc1234", ""], "PASS must be"),
        (["1", "abc1234", "admin"], "PASS must be"),
        (["", "abc1234", "viewer"], "FUZZ_SEED must be"),
        (["01", "abc1234", "viewer"], "FUZZ_SEED must be"),
        (["x", "abc1234", "sdk"], "FUZZ_SEED must be"),
        (["7", "", "sdk"], "SHA must name"),
    ],
)
def test_make_fuzz_refuses_bad_arguments_before_touching_anything(
    tmp_path, args, message
):
    """These refusals come before git and Docker, so they hold anywhere; the
    SHA and clean-tree refusals need a git checkout and are shown on the pull
    request that added them."""
    result = subprocess.run(
        ["bash", str(FUZZ_LOCAL), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2, result
    assert message in result.stderr
    assert "usage: make fuzz" in result.stderr
