#!/usr/bin/env python3
"""Decide an API fuzzing pass from its Schemathesis report.

The fuzz arm of ``.github/workflows/_platform.yml`` and ``make fuzz`` both run
Schemathesis against a running API and then ask this script for the verdict.
Schemathesis's own exit status is never the verdict: it is 1 on any server
error, listed or not, and 0 on a run that reached nothing at all.

Two subcommands, both reading the served OpenAPI document and the two lists
under ``tests/fuzz/``:

``args``
    The Schemathesis filter arguments for one pass, one argument per line: the
    ``sdk`` pass is restricted to the SDK routes, and every pass leaves out the
    operations ``tests/fuzz/exclusions.toml`` names for it.

``evaluate``
    Read the pass's ndjson report and decide it. The pass selects the served
    document's operations, minus its exclusions (and, for ``sdk``, only the SDK
    routes). For each one, only the interactions whose method is the
    operation's own count, so the coverage phase's method probes (answered
    405) do not. An operation is REACHED when one counted interaction answered
    a status outside ``NOT_REACHED``; otherwise, or when the report has no
    interaction for it, it is UNREACHED. The pass is green only when:

    * no operation answered a 5xx (there is no known list yet, so every one
      counts);
    * every UNREACHED operation is listed for this pass in
      ``tests/fuzz/unreached.toml``, and no listed operation was reached (a
      stale entry);
    * Schemathesis selected exactly the operations this pass selects, and
      fuzzed nothing else;
    * the report exists and holds at least one interaction.

Everything this script prints, and the step summary it renders (through
``scripts/qa_render.py`` from ``.github/qa-templates/fuzz-*.tmpl``), is counts,
the pass, the date, the commit and the seed. Which operations failed or were
not reached goes only to the ``--details`` file, which ``make fuzz`` writes into
its reproduction directory and the workflow never asks for. Nothing here ever
reads a request or response body.

Exit status: 0 green, 1 red, 2 a list or an argument it refuses.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
EXCLUSIONS = ROOT / "tests" / "fuzz" / "exclusions.toml"
UNREACHED = ROOT / "tests" / "fuzz" / "unreached.toml"

PASSES = ("superuser", "viewer", "sdk")

#: The SDK routes, the ``sdk`` pass's whole selection. The same prefixes the
#: rate limiter gives the SDK limit (``SDK_PATH_PREFIXES`` in
#: ``backend/app/middleware/rate_limiter.py``); a test holds the two equal.
SDK_PATH_PREFIXES = (
    "/api/v1/tracking/",
    "/api/v1/feature-flags/evaluate/",
    "/api/v1/feature-flags/user/",
    "/api/v1/sdk/",
)
SDK_PATH_REGEX = "^(?:" + "|".join(re.escape(p) for p in SDK_PATH_PREFIXES) + ")"

#: Answers that say the request never got past validation, authentication,
#: routing or the rate limiter: an operation that only ever answered these
#: was not reached.
NOT_REACHED = frozenset({400, 401, 403, 404, 405, 422, 429})

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
LABEL = re.compile(r"(GET|PUT|POST|DELETE|OPTIONS|HEAD|PATCH|TRACE) /\S*")


class ListError(ValueError):
    """``exclusions.toml`` or ``unreached.toml`` holds something refused."""


class ReportError(ValueError):
    """The report cannot be read, or holds no interaction at all."""


@dataclass(frozen=True)
class Operation:
    method: str  # upper case
    path: str
    has_auth: bool  # the served document lists an auth scheme for it

    @property
    def label(self) -> str:
        """The operation's name, as Schemathesis labels it."""
        return f"{self.method} {self.path}"


def _requires_a_scheme(requirements: Any) -> bool:
    """True when an OpenAPI requirement list names at least one auth scheme
    (``[{}]`` names none: the operation may be called without one)."""
    return isinstance(requirements, list) and any(
        isinstance(requirement, dict) and requirement for requirement in requirements
    )


def load_operations(document: Mapping[str, Any]) -> Dict[str, Operation]:
    """Every operation of an OpenAPI document, by label."""
    top = document.get("security")
    operations: Dict[str, Operation] = {}
    for path, item in (document.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            requirements = operation.get("security", top)
            op = Operation(method.upper(), path, _requires_a_scheme(requirements))
            operations[op.label] = op
    return operations


def _read_toml(path: Path) -> Dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ListError(f"{path.name}: cannot be read ({type(error).__name__})")


def _entries(data: Mapping[str, Any], table: str, name: str) -> List[Dict[str, Any]]:
    unknown = sorted(set(data) - {table})
    if unknown:
        raise ListError(f"{name}: unknown top-level keys {unknown}")
    entries = data.get(table, [])
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise ListError(f"{name}: [[{table}]] must be a list of tables")
    return entries


def _reason(entry: Mapping[str, Any], where: str) -> None:
    reason = entry.get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        raise ListError(f"{where}: every entry needs a reason (a sentence)")


def _operation(
    entry: Mapping[str, Any], where: str, operations: Mapping[str, Operation]
) -> str:
    label = entry.get("operation")
    if not isinstance(label, str) or LABEL.fullmatch(label) is None:
        raise ListError(f"{where}: operation must be 'METHOD /path'")
    if label not in operations:
        raise ListError(f"{where}: {label} is not an operation of the API document")
    return label


def load_exclusions(
    path: Path, operations: Mapping[str, Operation]
) -> Dict[str, Set[str]]:
    """``{pass: {excluded label}}`` from ``exclusions.toml``, every pass present."""
    name = path.name
    excluded: Dict[str, Set[str]] = {p: set() for p in PASSES}
    seen: Set[str] = set()
    for index, entry in enumerate(_entries(_read_toml(path), "exclude", name), 1):
        where = f"{name} entry {index}"
        unknown = sorted(set(entry) - {"operation", "passes", "reason"})
        if unknown:
            raise ListError(f"{where}: unknown keys {unknown}")
        label = _operation(entry, where, operations)
        if label in seen:
            raise ListError(f"{where}: {label} is listed twice")
        seen.add(label)
        passes = entry.get("passes")
        if (
            not isinstance(passes, list)
            or not passes
            or any(p not in PASSES for p in passes)
            or len(set(passes)) != len(passes)
        ):
            raise ListError(f"{where}: passes must be a list drawn from {PASSES}")
        _reason(entry, where)
        for pass_name in passes:
            excluded[pass_name].add(label)
    return excluded


def selection(
    pass_name: str,
    operations: Mapping[str, Operation],
    excluded: Mapping[str, Set[str]],
) -> Set[str]:
    """The labels a pass selects: the document, minus its exclusions, and for
    ``sdk`` only the SDK routes."""
    chosen = set(operations) - excluded[pass_name]
    if pass_name == "sdk":
        chosen = {
            label
            for label in chosen
            if operations[label].path.startswith(SDK_PATH_PREFIXES)
        }
    return chosen


def load_unreached(
    path: Path,
    pass_name: str,
    operations: Mapping[str, Operation],
    excluded: Mapping[str, Set[str]],
) -> Set[str]:
    """The labels ``unreached.toml`` lists for *pass_name*.

    Every entry of every pass is checked, so a broken entry fails all three
    passes, not only its own."""
    name = path.name
    listed: Dict[str, Set[str]] = {p: set() for p in PASSES}
    for index, entry in enumerate(_entries(_read_toml(path), "unreached", name), 1):
        where = f"{name} entry {index}"
        unknown = sorted(set(entry) - {"operation", "pass", "reason"})
        if unknown:
            raise ListError(f"{where}: unknown keys {unknown}")
        entry_pass = entry.get("pass")
        if entry_pass not in PASSES:
            raise ListError(f"{where}: pass must be one of {PASSES}")
        label = _operation(entry, where, operations)
        if label not in selection(entry_pass, operations, excluded):
            raise ListError(f"{where}: the {entry_pass} pass does not select {label}")
        if label in listed[entry_pass]:
            raise ListError(f"{where}: {label} is listed twice for {entry_pass}")
        _reason(entry, where)
        listed[entry_pass].add(label)
    return listed[pass_name]


def filter_args(pass_name: str, excluded: Mapping[str, Set[str]]) -> List[str]:
    """The Schemathesis arguments that make it select exactly ``selection()``."""
    args: List[str] = []
    if pass_name == "sdk":
        args += ["--include-path-regex", SDK_PATH_REGEX]
    for label in sorted(excluded[pass_name]):
        args += ["--exclude-name", label]
    return args


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


@dataclass
class Report:
    #: label -> [(request method, response status or None for no answer)]
    interactions: Dict[str, List[Tuple[str, Optional[int]]]] = field(
        default_factory=dict
    )
    #: How many operations Schemathesis itself selected (None: not reported).
    selected: Optional[int] = None


def _interaction_items(interactions: Any) -> Iterable[Any]:
    if isinstance(interactions, dict):
        return interactions.values()
    if isinstance(interactions, list):
        return interactions
    return ()


def read_report(report_dir: Path) -> Report:
    """The interactions of the one ndjson report in *report_dir*."""
    files = sorted(Path(report_dir).glob("*.ndjson"))
    if len(files) != 1:
        raise ReportError(f"expected one ndjson report, found {len(files)}")
    report = Report()
    try:
        lines = files[0].read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ReportError(f"the report cannot be read ({type(error).__name__})")
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            raise ReportError(f"report line {number} is not JSON")
        if not isinstance(event, dict):
            continue
        loading = event.get("LoadingFinished")
        if isinstance(loading, dict):
            try:
                report.selected = int(loading["statistic"]["operations"]["selected"])
            except (KeyError, TypeError, ValueError):
                report.selected = None
        finished = event.get("ScenarioFinished")
        if not isinstance(finished, dict):
            continue
        recorder = finished.get("recorder") or {}
        label = recorder.get("label")
        if not isinstance(label, str):
            continue
        bucket = report.interactions.setdefault(label, [])
        for interaction in _interaction_items(recorder.get("interactions")):
            if not isinstance(interaction, dict):
                continue
            request = interaction.get("request") or {}
            response = interaction.get("response")
            status = response.get("status_code") if isinstance(response, dict) else None
            method = request.get("method") if isinstance(request, dict) else None
            bucket.append(
                (
                    str(method).upper(),
                    status if isinstance(status, int) else None,
                )
            )
    if not any(report.interactions.values()):
        raise ReportError("the report holds no interactions")
    return report


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    selected: Set[str]
    fuzzed: Set[str]
    outside: Set[str]
    reached: Set[str]
    unreached: Set[str]
    unlisted: Set[str]
    stale: Set[str]
    server_errors: Set[str]
    no_answer: Set[str]
    auth_declared: Set[str]
    schemathesis_selected: Optional[int]
    report_problem: Optional[str] = None

    @property
    def selection_mismatch(self) -> bool:
        return self.schemathesis_selected != len(self.selected)

    @property
    def green(self) -> bool:
        return not (
            self.report_problem
            or self.server_errors
            or self.unlisted
            or self.stale
            or self.outside
            or self.selection_mismatch
        )


def decide(
    report: Report,
    operations: Mapping[str, Operation],
    selected: Set[str],
    listed: Set[str],
    report_problem: Optional[str] = None,
) -> Verdict:
    interactions = report.interactions
    fuzzed = {label for label, items in interactions.items() if items}
    reached = set()
    for label in selected:
        own = operations[label].method
        if any(
            method == own and status is not None and status not in NOT_REACHED
            for method, status in interactions.get(label, [])
        ):
            reached.add(label)
    unreached = selected - reached
    return Verdict(
        selected=set(selected),
        fuzzed=fuzzed,
        outside=fuzzed - selected,
        reached=reached,
        unreached=unreached,
        unlisted=unreached - listed,
        stale=listed & reached,
        server_errors={
            label
            for label, items in interactions.items()
            if any(status is not None and 500 <= status <= 599 for _, status in items)
        },
        no_answer={
            label
            for label, items in interactions.items()
            if any(status is None for _, status in items)
        },
        auth_declared={label for label in selected if operations[label].has_auth},
        schemathesis_selected=report.selected,
        report_problem=report_problem,
    )


def counts_line(
    verdict: Verdict, pass_name: str, date: str, sha: str, seed: str
) -> str:
    """The one line a run prints: the pass, date, commit, seed and counts."""
    v = verdict
    by_tool = "none" if v.schemathesis_selected is None else v.schemathesis_selected
    return (
        f"fuzz pass {pass_name}, {date}, commit {sha}, seed {seed}:"
        f" {'GREEN' if v.green else 'RED'}"
        f" | operations selected {len(v.selected)} (Schemathesis {by_tool}),"
        f" fuzzed {len(v.fuzzed)}, outside the selection {len(v.outside)}"
        f" | 5xx operations {len(v.server_errors)}"
        f" | reached {len(v.reached)}, unreached {len(v.unreached)}"
        f" (not listed {len(v.unlisted)}, listed but reached {len(v.stale)})"
        f" | declaring an auth scheme {len(v.auth_declared)},"
        f" of them reached {len(v.auth_declared & v.reached)}"
        f" | with a request that got no answer {len(v.no_answer)}"
    )


def summary_values(
    verdict: Verdict,
    pass_name: str,
    date: str,
    sha: str,
    seed: str,
    run_link: Optional[str],
) -> Tuple[str, Dict[str, str]]:
    """The template and its values for this verdict."""
    v = verdict
    values = {
        "check": pass_name,
        "date": date,
        "sha": sha,
        "seed": seed,
        "count_fuzzed": str(len(v.fuzzed)),
        "count_operations": str(len(v.selected)),
        "count_5xx": str(len(v.server_errors)),
        "count_reached": str(len(v.reached)),
    }
    if v.green:
        values["count_unreached"] = str(len(v.unreached))
        return "fuzz-green.tmpl", values
    if run_link is None:
        raise ListError("a red summary needs --run-link")
    values.update(
        {
            # No known list until it exists: every 5xx operation is unlisted.
            "count_5xx_unlisted": str(len(v.server_errors)),
            "count_known_quiet": "0",
            "count_unreached_unlisted": str(len(v.unlisted)),
            "count_unreached_stale": str(len(v.stale)),
            "run_link": run_link,
        }
    )
    return "fuzz-red.tmpl", values


def details(verdict: Verdict) -> Dict[str, Any]:
    """Which operations, for the local reproduction directory only."""
    v = verdict
    return {
        "green": v.green,
        "report_problem": v.report_problem,
        "selected_by_schemathesis": v.schemathesis_selected,
        "selected": len(v.selected),
        "server_errors": sorted(v.server_errors),
        "unreached_unlisted": sorted(v.unlisted),
        "listed_but_reached": sorted(v.stale),
        "fuzzed_outside_the_selection": sorted(v.outside),
        "no_answer": sorted(v.no_answer),
        "unreached": sorted(v.unreached),
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _document(path: Path) -> Dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ListError(f"the API document cannot be read ({type(error).__name__})")
    if not isinstance(document, dict) or not load_operations(document):
        raise ListError("the API document has no operations")
    return document


def _render(template: str, values: Mapping[str, str]) -> str:
    """The step summary, through the one reader of .github/qa-templates/."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import qa_render

    try:
        return qa_render.render(template, values).body
    except qa_render.RenderError as error:
        # Its messages name placeholders and kinds, never a value.
        raise ListError(f"the summary was refused: {error}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("args", "evaluate"):
        p = sub.add_parser(command)
        p.add_argument("--pass", dest="pass_name", required=True, choices=PASSES)
        p.add_argument("--schema", required=True, type=Path)
        p.add_argument("--exclusions", type=Path, default=EXCLUSIONS)
        if command == "evaluate":
            p.add_argument("--unreached", type=Path, default=UNREACHED)
            p.add_argument("--report-dir", required=True, type=Path)
            p.add_argument("--seed", required=True)
            p.add_argument("--sha", required=True)
            p.add_argument("--date", default=None)
            p.add_argument("--run-link", default=None)
            p.add_argument("--summary", type=Path, default=None)
            p.add_argument("--details", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        operations = load_operations(_document(args.schema))
        excluded = load_exclusions(args.exclusions, operations)
        if args.command == "args":
            print("\n".join(filter_args(args.pass_name, excluded)))
            return 0
        if re.fullmatch(r"[0-9]{1,10}", args.seed) is None:
            raise ListError("--seed must be an integer of one to ten digits")
        if re.fullmatch(r"[0-9a-f]{7,40}", args.sha) is None:
            raise ListError("--sha must be a commit")
        listed = load_unreached(args.unreached, args.pass_name, operations, excluded)
        selected = selection(args.pass_name, operations, excluded)
        date = args.date or _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        try:
            report, problem = read_report(args.report_dir), None
        except ReportError as error:
            report, problem = Report(), str(error)
        verdict = decide(report, operations, selected, listed, problem)
        if args.summary is not None:
            template, values = summary_values(
                verdict, args.pass_name, date, args.sha, args.seed, args.run_link
            )
            args.summary.write_text(_render(template, values), encoding="ascii")
        if args.details is not None:
            args.details.write_text(
                json.dumps(details(verdict), indent=2) + "\n", encoding="utf-8"
            )
    except ListError as error:
        print(f"fuzz_check: refused: {error}", file=sys.stderr)
        return 2
    if problem:
        print(f"fuzz_check: {problem}")
    print(counts_line(verdict, args.pass_name, date, args.sha, args.seed))
    return 0 if verdict.green else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as error:
        # A traceback could quote a value from the report; the class is enough.
        print(f"fuzz_check: failed ({type(error).__name__})", file=sys.stderr)
        sys.exit(2)
