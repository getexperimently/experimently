#!/usr/bin/env python3
"""The verdict of one Rollback run: one word, one headline, one exit status (#759).

    python3 scripts/rollback_verdict.py

rollback.yml's "Run summary" step runs this with its inputs in the
environment (``INPUTS``) and prints, on success, exactly three lines:

    verdict=<WORD>
    exit=<0|1>
    slack=<env>: <WORD>: <what happened, and what to do>

The script itself exits 0 whenever it printed them. The step reads the three
lines, writes ``slack=`` to its outputs and the headline to the run summary,
and then exits with ``exit=``: 0 only for ROLLED BACK. When this script
prints no ``verdict=`` line (it crashed, or the checkout is missing), the
step's own guard writes an OUTCOME UNKNOWN headline instead, in bash.

The verdict is decided in one place, ``decide()``: a pure function over an
ordered list of rows, the first matching row wins. Row 0 checks every input
against its closed set first, so a value this script does not recognise
decides nothing (fail closed). The table, its overlap winners and the cell
counts are the plan's (verdict-759 plan v2, section 2), and the expected word
for every reachable cell is a committed table that ``decide()`` did not
produce: backend/tests/unit/infrastructure/fixtures/rollback_verdict/cells.json.

Free text (the dashboard step's result, what scripts/api_serving.py said, the
refused deployment's id and revision) is only placed, never interpreted: it
is put on one line, every run of twelve digits is replaced
(``public_text.redact``), and it is cut to 300 characters. The target is
named by ``family:revision`` (``public_text.short_arn``), never by its ARN.
A value outside its set is named by its variable, never by its value.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from string import Template

# scripts/ is already sys.path[0]; imported from a test, it may not be.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_text import redact, short_arn

#: Every environment name this script reads. The summary step's env maps the
#: step outputs among them; the read results it passes on the command line
#: (test_rollback_verdict.py pins where each one comes from).
INPUTS = (
    "TARGET_ENV",
    "TARGET_ARN",
    "REFUSED",
    "REFUSED_ID",
    "REFUSED_PRIMARY",
    "ALREADY_SERVING",
    "STOPPED",
    "STOP_WAIT",
    "DEPLOYMENT_ID",
    "API_VERIFY",
    "DASHBOARD_INPUT",
    "DASHBOARD_OUTCOME",
    "DASHBOARD_RESULT",
    "SERVING_RC",
    "SERVING_WORD",
    "SERVING_SAID",
    "ACTIVE_RC",
    "ACTIVE",
    "ECS_CLUSTER",
    "ECS_BACKEND_SERVICE",
)

#: Every value is cut to this before anything reads it.
MAX_INPUT = 4096
#: Free text in the headline, after redaction.
MAX_FREE = 300

ID = re.compile(r"d-[A-Z0-9]{1,20}")
IDS = re.compile(r"d-[A-Z0-9]{1,20}( d-[A-Z0-9]{1,20})*")
#: (scripts/api_serving.py's exit, its `explain:` word): the only pairs it
#: prints. ("", "") is "not read". An exit of 1 with no word is a crash at
#: import, which Python exits 1 for, and it is not "not yet".
PAIRS = {
    ("", ""),
    ("0", "serving"),
    ("1", "primary-other"),
    ("1", "listener-split"),
    ("2", "unknown"),
    ("3", "listener-other"),
}
#: How the stop step's waits ended (its `stop_wait` output); "" is absent:
#: nothing was stopped, or a stop call failed.
STOP_WAITS = ("ok", "timeout", "unreadable")
#: A step's outcome; "" is a step that was not reached.
OUTCOMES = {"success", "failure", "cancelled", "skipped", ""}

#: The per-id sentence (T32), one literal for both creators: a user or
#: Rollback deployment is stopped and reverted by a new Rollback, and
#: CodeDeploy's own rollback makes a new Rollback refuse.
T32_ID = Template(
    "Do not dispatch Rollback again while deployment ${id} is active: a new Rollback stops any deployment that is not CodeDeploy's own rollback, with auto-rollback, which reverts what it shifted, and it refuses while CodeDeploy's own rollback is active."
)

DIFF = (
    ", so the API and dashboard are on different releases: put the dashboard "
    "back with docs/deployment/rollback-runbook.md Method 2, the dashboard block"
)


def active(v: Mapping[str, str]) -> str:
    """The deployment group's active list as the summary read it: notread,
    none, ids or unreadable; "?" for a value outside its set."""
    rc = v["ACTIVE_RC"]
    text = " ".join(v["ACTIVE"].split())
    if rc == "":
        return "notread" if text == "" else "?"
    if not rc.isdigit():
        return "?"
    if rc != "0":
        return "unreadable"
    if text in ("", "None"):
        return "none"
    if IDS.fullmatch(text):
        return "ids"
    return "?"


def invalid(v: Mapping[str, str]) -> str | None:
    """Row 0: the first input outside its set, by name, or None."""
    if v["REFUSED"] not in ("", "codeDeployRollback", "unreadable"):
        return "REFUSED"
    if v["ALREADY_SERVING"] not in ("", "true"):
        return "ALREADY_SERVING"
    if v["STOPPED"] and not IDS.fullmatch(v["STOPPED"]):
        return "STOPPED"
    if v["STOP_WAIT"] not in ("", *STOP_WAITS):
        return "STOP_WAIT"
    if v["STOP_WAIT"] and not v["STOPPED"]:
        return "STOP_WAIT"
    if v["DEPLOYMENT_ID"] and not ID.fullmatch(v["DEPLOYMENT_ID"]):
        return "DEPLOYMENT_ID"
    if v["API_VERIFY"] not in OUTCOMES:
        return "API_VERIFY"
    if v["DASHBOARD_OUTCOME"] not in OUTCOMES:
        return "DASHBOARD_OUTCOME"
    if v["SERVING_RC"] not in ("", "0", "1", "2", "3"):
        return "SERVING_RC"
    if (v["SERVING_RC"], v["SERVING_WORD"]) not in PAIRS:
        return "SERVING_WORD"
    if active(v) == "?":
        return "ACTIVE"
    return None


Row = tuple[str, str, Callable[[Mapping[str, str]], bool]]

#: The plan's table, in order; the first row whose test holds wins.
ROWS: list[Row] = [
    ("0", "OUTCOME UNKNOWN", lambda v: invalid(v) is not None),
    (
        "1",
        "REFUSED",
        lambda v: v["REFUSED"] != "" or v["ALREADY_SERVING"] == "true",
    ),
    (
        "2",
        "NOTHING CHANGED",
        lambda v: v["STOPPED"] == "" and v["DEPLOYMENT_ID"] == "",
    ),
    (
        "3",
        "ROLLED BACK",
        lambda v: (
            v["API_VERIFY"] == "success"
            and (v["DASHBOARD_INPUT"] == "" or v["DASHBOARD_OUTCOME"] == "success")
        ),
    ),
    (
        "4",
        "API BACK, DASHBOARD NOT",
        lambda v: (
            v["DASHBOARD_INPUT"] != ""
            and (v["API_VERIFY"] == "success" or v["SERVING_RC"] == "0")
        ),
    ),
    ("5", "API BACK, RUN FAILED", lambda v: v["SERVING_RC"] == "0"),
    ("6", "NOT FINISHED", lambda v: v["STOP_WAIT"] in ("timeout", "unreadable")),
    (
        "7",
        "OUTCOME UNKNOWN",
        lambda v: v["SERVING_RC"] == "2" or active(v) == "unreadable",
    ),
    (
        "8",
        "STILL MOVING",
        lambda v: (
            v["SERVING_RC"] in ("1", "3")
            and (active(v) == "ids" or v["SERVING_WORD"] == "listener-split")
        ),
    ),
    (
        "9",
        "NOT ROLLED BACK",
        lambda v: v["SERVING_RC"] in ("1", "3") and active(v) == "none",
    ),
]

#: Reached by no cell the plan counts; it reads as OUTCOME UNKNOWN.
FALLBACK = ("fallback", "OUTCOME UNKNOWN")


def decide(v: Mapping[str, str], rows: list[Row] | None = None) -> tuple[str, str]:
    """(row, verdict word) for one run's inputs, keyed by ``INPUTS`` names."""
    for row, word, holds in ROWS if rows is None else rows:
        if holds(v):
            return row, word
    return FALLBACK


def exit_status(row: str) -> int:
    """0 if and only if the run rolled back (row 3)."""
    return 0 if row == "3" else 1


def _free(text: str, limit: int = MAX_FREE) -> str:
    """Free text on one line, without an account, cut."""
    return redact(" ".join(str(text).split()))[:limit]


def _dash(v: Mapping[str, str]) -> str:
    if v["DASHBOARD_INPUT"] == "":
        return "dashboard left as it is"
    outcome = v["DASHBOARD_OUTCOME"]
    result = _free(v["DASHBOARD_RESULT"])
    if outcome == "success":
        return f"dashboard {result or 'rolled back'}"
    if outcome == "failure":
        return f"dashboard NOT rolled back ({result or 'no result'})"
    if outcome == "cancelled":
        return "dashboard NOT rolled back (its step was cancelled while it ran)"
    return "dashboard NOT rolled back (not reached)"


def _next(v: Mapping[str, str], row: str) -> str:
    """ " " and the per-id sentence for each deployment that may be active:
    this run's own for a verified rollback, every listed one, and this run's
    own when nothing could be listed."""
    ids: list[str] = []
    d = v["DEPLOYMENT_ID"] if ID.fullmatch(v["DEPLOYMENT_ID"]) else ""
    listed = active(v)
    if row in ("3", "4a") and d:
        ids.append(d)
    if listed == "ids":
        ids.extend(v["ACTIVE"].split())
    if listed in ("unreadable", "notread", "?") and d:
        ids.append(d)
    unique = list(dict.fromkeys(ids))
    return "".join(" " + T32_ID.substitute(id=i) for i in unique)


def headline(v: Mapping[str, str], row: str) -> str:
    """What follows ``"<env>: <VERDICT>: "``: the plan's literal for ``row``."""
    target = _free(short_arn(v["TARGET_ARN"]))
    verify = v["API_VERIFY"] or "not reached"
    if verify not in OUTCOMES | {"not reached"}:
        verify = "not recognised"
    dash = _dash(v)
    x = v["SERVING_RC"]
    said = _free(v["SERVING_SAID"]) or "no output"
    d = v["DEPLOYMENT_ID"]
    stopped = v["STOPPED"]
    listed = active(v)
    if row == "0":
        return (
            f"this run's summary got a value of {invalid(v)} it does not "
            f"recognise, so it decides nothing (its verify step: {verify}); read "
            f"the run's steps.{_next(v, row)}"
        )
    if row == "1":
        if v["REFUSED"] == "codeDeployRollback":
            refused = _free(v["REFUSED_ID"]) or "(id not recorded)"
            primary = (
                _free(v["REFUSED_PRIMARY"]) or "a revision this run could not read"
            )
            return (
                f"CodeDeploy's own rollback {refused} is still active, so this run "
                f"stopped nothing and created no deployment (the API is on "
                f"{primary}); {dash}"
            )
        if v["REFUSED"] == "unreadable":
            refused = _free(v["REFUSED_ID"]) or "(id not recorded)"
            return (
                f"the creator of in-flight deployment {refused} could not be read, "
                f"so this run stopped nothing and created no deployment; {dash}"
            )
        return (
            f"the API was already on {target} with nothing in flight, so this run "
            f"stopped nothing and created no deployment; {dash}"
        )
    if row == "2":
        if v["TARGET_ARN"] == "":
            return (
                "the target revision was not resolved, so this run stopped nothing "
                f"and created no deployment; {dash}"
            )
        return (
            "this run stopped nothing and created no deployment, so the API is as "
            f"it was before the run; {dash}"
        )
    if row == "3":
        return (
            f"API rolled back to {target} (CodeDeploy deployment {d}, verified); "
            f"{dash}.{_next(v, '3')}"
        )
    if row == "4" and v["API_VERIFY"] == "success":
        return (
            f"API rolled back to {target} (CodeDeploy deployment {d}, verified); "
            f"{dash}{DIFF}.{_next(v, '4a')}"
        )
    if row in ("4", "5"):
        diff = DIFF if row == "4" else ""
        return (
            f"API is serving {target}, read at the end of the run, but this run did "
            f"not finish its own steps (its verify step: {verify}); "
            f"{dash}{diff}.{_next(v, row)}"
        )
    if row == "6":
        why = (
            "the deployment group was still busy after about 5 minutes"
            if v["STOP_WAIT"] == "timeout"
            else "the deployment group could not be read"
        )
        return (
            f"this run stopped {stopped} with auto-rollback and {why}, so it "
            f"created no rollback deployment; the API at the end of the run: "
            f"{said} (scripts/api_serving.py exit {x}); {dash}.{_next(v, row)}"
        )
    if row == "7" and x == "2":
        return (
            f"this run could not tell what the API is serving "
            f"(scripts/api_serving.py exit 2: {said}); its verify step: {verify}; "
            f"{dash}.{_next(v, row)}"
        )
    if row == "7":
        return (
            f"the API is not confirmed on {target} (scripts/api_serving.py exit "
            f"{x}: {said}), and this run could not list the deployment group's "
            f"active deployments, so check them before any dispatch; "
            f"{dash}.{_next(v, row)}"
        )
    if row == "8" and listed == "ids":
        ids = " ".join(v["ACTIVE"].split())
        are = (
            f"deployments {ids} are active"
            if " " in ids
            else f"deployment {ids} is active"
        )
        return (
            f"the API is not yet on {target} (scripts/api_serving.py exit {x}: "
            f"{said}) while {are}; {dash}.{_next(v, row)}"
        )
    if row == "8":
        cluster = _free(v["ECS_CLUSTER"], 100)
        service = _free(v["ECS_BACKEND_SERVICE"], 100)
        return (
            f"the API is not yet on {target} (scripts/api_serving.py exit 1: "
            f"{said}): no deployment is active, but the /api/* rule still splits "
            f"traffic. Read it again: python3 scripts/api_serving.py {cluster} "
            f"{service} {target}. If it still shows a split with no active "
            "deployment, the listener is stuck and needs a person: "
            "docs/deployment/rollback-runbook.md#reading-the-result, the STILL "
            f"MOVING row; {dash}"
        )
    if row == "9":
        text = (
            f"the API is not on {target} (scripts/api_serving.py exit {x}: {said}), "
            "and no deployment is active"
        )
        if stopped:
            text += f"; this run stopped {stopped} with auto-rollback"
        if d:
            text += f"; CodeDeploy deployment {d} is no longer active"
        return f"{text}; {dash}"
    # The fallback: no row matched, which no counted cell does.
    return (
        "no row of the verdict table matched this run's inputs, so it decides "
        f"nothing (its verify step: {verify}); read the run's steps."
        f"{_next(v, row)}"
    )


def read_inputs(environ: Mapping[str, str]) -> dict[str, str]:
    """Every name in ``INPUTS``, absent as "", each cut before it is read."""
    return {name: str(environ.get(name, ""))[:MAX_INPUT] for name in INPUTS}


def main(environ: Mapping[str, str] | None = None) -> int:
    v = read_inputs(os.environ if environ is None else environ)
    row, word = decide(v)
    env = _free(v["TARGET_ENV"], 40) or "this environment"
    line = f"{env}: {word}: {headline(v, row)}"
    # One line, whatever the inputs held: GITHUB_OUTPUT refuses a value
    # spread over two lines with no delimiter.
    line = line.replace("\r", " ").replace("\n", " ")
    print(f"verdict={word}")
    print(f"exit={exit_status(row)}")
    print(f"slack={line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
