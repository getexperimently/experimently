#!/usr/bin/env python3
"""Prove that a sharded suite ran every collected test exactly once.

    python3 scripts/check_test_shards.py --suite backend/tests/integration \\
        [--allow-skip 'backend/tests/integration=<exact skip reason>' ...] \\
        [--any-skip <suite>] <report or directory> [...]

Each sharded pytest session writes a report (backend/tests/shard.py). A
directory is searched recursively for ``shard-*.json``; a file is read whatever
its name. Only reports whose ``suite`` is a ``--suite`` given here are checked;
a report for another suite is left alone.

For every ``--suite``, it exits 0 only when all of these hold:

* at least one report, one ``of``, and shard numbers exactly ``1..of``;
* every shard collected the same, non-empty list of node ids;
* the selected lists are non-empty, disjoint, and together equal that list;
* nothing narrowed any shard (``-m``, ``-k``, ``--deselect``, ``--ignore``,
  ``--ignore-glob``, ``--lf``, or an item another plugin deselected), and no
  collector failed;
* every selected test has exactly one ``ran`` record, nothing else ran, and
  each outcome is passed, xfailed, or skipped with an allowed reason.

Skips: none is allowed unless named. ``--allow-skip SUITE=REASON`` allows one
exact reason (repeat it); ``--any-skip SUITE`` leaves the suite's skips
unconstrained. There is no narrowing allowance.

Exit status: 0 proven; 1 a rule refused; 2 a usage error, or a report that is
unreadable, unparsable, truncated or malformed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPORT_VERSION = 1
REPORT_GLOB = "shard-*.json"
OUTCOMES = {"passed", "failed", "skipped", "xfailed", "xpassed", "error"}
EXAMPLES = 5


class BadReport(Exception):
    """A report that cannot be read as one."""


class Usage(Exception):
    """The command line is wrong."""


def _norm_suite(suite: str) -> str:
    parts = []
    for part in suite.split():
        while part.startswith("./"):
            part = part[2:]
        parts.append(part.rstrip("/") or part)
    return " ".join(sorted(parts))


def _examples(ids) -> str:
    ids = sorted(ids)
    shown = ", ".join(repr(i) for i in ids[:EXAMPLES])
    more = f" and {len(ids) - EXAMPLES} more" if len(ids) > EXAMPLES else ""
    return f"[{shown}{more}]"


def _str_list(doc: dict, key: str, where: str) -> list[str]:
    value = doc.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise BadReport(f"{where}: {key!r} is not a list of strings")
    return value


def _int(doc: dict, key: str, where: str, minimum: int) -> int:
    value = doc.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BadReport(f"{where}: {key!r} is not an integer >= {minimum}")
    return value


def load_report(path: Path) -> dict:
    where = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BadReport(f"{where}: unreadable: {exc}") from None
    if not text.strip():
        raise BadReport(f"{where}: empty (the session did not finish writing it)")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BadReport(f"{where}: not JSON, or truncated: {exc}") from None
    if not isinstance(doc, dict):
        raise BadReport(f"{where}: not a JSON object")
    if doc.get("version") != REPORT_VERSION:
        raise BadReport(
            f"{where}: version {doc.get('version')!r}, not {REPORT_VERSION}"
        )
    if not isinstance(doc.get("suite"), str) or not doc["suite"]:
        raise BadReport(f"{where}: 'suite' is missing")
    _int(doc, "shard", where, 1)
    _int(doc, "of", where, 1)
    _int(doc, "pre_deselected", where, 0)
    for key in ("collected", "selected", "deselect", "ignore", "ignore_glob"):
        _str_list(doc, key, where)
    _str_list(doc, "collect_errors", where)
    for key in ("markexpr", "keyword"):
        if not isinstance(doc.get(key), str):
            raise BadReport(f"{where}: {key!r} is not a string")
    if not isinstance(doc.get("last_failed"), bool):
        raise BadReport(f"{where}: 'last_failed' is not a boolean")
    ran = doc.get("ran")
    if not isinstance(ran, list):
        raise BadReport(f"{where}: 'ran' is not a list")
    for record in ran:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("nodeid"), str)
            or not (record.get("outcome") is None or record.get("outcome") in OUTCOMES)
            or not (
                record.get("skip_reason") is None
                or isinstance(record.get("skip_reason"), str)
            )
        ):
            raise BadReport(f"{where}: a 'ran' record is malformed: {record!r}")
    doc["_path"] = where
    return doc


def find_reports(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found.extend(sorted(p for p in path.rglob(REPORT_GLOB) if p.is_file()))
        elif path.is_file():
            found.append(path)
        else:
            raise Usage(f"{raw}: no such file or directory")
    return found


def _narrowing(doc: dict) -> list[str]:
    narrowed = []
    for key in ("markexpr", "keyword"):
        if doc[key]:
            narrowed.append(f"{key}={doc[key]!r}")
    for key in ("deselect", "ignore", "ignore_glob"):
        if doc[key]:
            narrowed.append(f"{key}={doc[key]!r}")
    if doc["last_failed"]:
        narrowed.append("last_failed=True (--lf)")
    if doc["pre_deselected"]:
        narrowed.append(
            f"pre_deselected={doc['pre_deselected']} (items another plugin deselected)"
        )
    return narrowed


def check_suite(
    suite: str, docs: list[dict], allowed: set[str] | None
) -> tuple[list[str], int]:
    """Return the problems with one suite's reports, and the tests proven."""
    if not docs:
        return [f"{suite}: no shard report for this suite"], 0
    problems: list[str] = []

    totals = sorted({d["of"] for d in docs})
    if len(totals) != 1:
        problems.append(f"{suite}: the reports disagree on the shard count: {totals}")
        return problems, 0
    total = totals[0]
    by_index: dict[int, list[dict]] = {}
    for doc in docs:
        by_index.setdefault(doc["shard"], []).append(doc)
    for index, group in sorted(by_index.items()):
        if index > total:
            problems.append(f"{suite}: shard {index} reported, but of={total}")
        if len(group) > 1:
            paths = ", ".join(d["_path"] for d in group)
            problems.append(
                f"{suite}: shard {index} reported {len(group)} times ({paths})"
            )
    missing = [i for i in range(1, total + 1) if i not in by_index]
    if missing:
        problems.append(f"{suite}: shard(s) {missing} of {total} have no report")

    collected = docs[0]["collected"]
    for doc in docs[1:]:
        if doc["collected"] != collected:
            only_here = set(doc["collected"]) - set(collected)
            only_there = set(collected) - set(doc["collected"])
            problems.append(
                f"{suite}: shard {doc['shard']} collected a different list from "
                f"shard {docs[0]['shard']} (node ids differ between processes?): "
                f"{len(only_here)} only in shard {doc['shard']} {_examples(only_here)}, "
                f"{len(only_there)} only in shard {docs[0]['shard']} "
                f"{_examples(only_there)}"
            )
    if not collected:
        problems.append(
            f"{suite}: the collected set is EMPTY: refusing to compare against nothing"
        )
    duplicated = {node for node, count in Counter(collected).items() if count > 1}
    if duplicated:
        problems.append(
            f"{suite}: collected twice in one session: {_examples(duplicated)}"
        )
    expected = set(collected)

    seen: dict[str, int] = {}
    for doc in docs:
        tag = f"{suite}: shard {doc['shard']}"
        if not doc["selected"]:
            problems.append(f"{tag} selected nothing")
        for node in set(doc["selected"]):
            seen[node] = seen.get(node, 0) + 1
        stray = set(doc["selected"]) - expected
        if stray:
            problems.append(
                f"{tag} selected {len(stray)} not collected: {_examples(stray)}"
            )
        narrowed = _narrowing(doc)
        if narrowed:
            problems.append(f"{tag}: narrowed by {', '.join(narrowed)}")
        if doc["collect_errors"]:
            problems.append(
                f"{tag}: {len(doc['collect_errors'])} collection error(s): "
                f"{_examples(doc['collect_errors'])}"
            )
        problems.extend(_check_ran(tag, doc, allowed))
    none = expected - set(seen)
    if none:
        problems.append(
            f"{suite}: {len(none)} collected but selected by no shard {_examples(none)}"
        )
    several = {n for n, c in seen.items() if c > 1}
    if several:
        problems.append(
            f"{suite}: {len(several)} selected by more than one shard {_examples(several)}"
        )
    return problems, len(expected)


def _check_ran(tag: str, doc: dict, allowed: set[str] | None) -> list[str]:
    problems: list[str] = []
    selected = set(doc["selected"])
    runs: dict[str, int] = {}
    for record in doc["ran"]:
        runs[record["nodeid"]] = runs.get(record["nodeid"], 0) + 1
    not_run = selected - set(runs)
    if not_run:
        problems.append(
            f"{tag}: {len(not_run)} selected but did not run {_examples(not_run)}"
        )
    twice = {n for n, c in runs.items() if c > 1}
    if twice:
        problems.append(f"{tag}: {len(twice)} ran more than once {_examples(twice)}")
    extra = set(runs) - selected
    if extra:
        problems.append(
            f"{tag}: {len(extra)} ran but were not selected {_examples(extra)}"
        )
    for record in doc["ran"]:
        node, outcome = record["nodeid"], record["outcome"]
        if outcome in ("passed", "xfailed"):
            continue
        if outcome == "skipped":
            reason = record["skip_reason"] or ""
            if allowed is None or reason in allowed:
                continue
            problems.append(
                f"{tag}: {node} was skipped, and its reason is not allowed: {reason!r}"
            )
        elif outcome is None:
            problems.append(f"{tag}: {node} started but never finished")
        else:
            problems.append(f"{tag}: {node} {outcome}")
    return problems


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prove a sharded suite ran every collected test exactly once."
    )
    parser.add_argument("--suite", action="append", default=[], required=True)
    parser.add_argument(
        "--allow-skip", action="append", default=[], metavar="SUITE=REASON"
    )
    parser.add_argument("--any-skip", action="append", default=[], metavar="SUITE")
    parser.add_argument("paths", nargs="+")
    try:
        return parser.parse_args(argv)
    except SystemExit as exc:
        raise Usage("bad arguments") from exc


def run(argv: list[str]) -> int:
    try:
        args = _parse_args(argv)
        suites = [_norm_suite(s) for s in args.suite]
        if len(set(suites)) != len(suites):
            raise Usage(f"a --suite is named twice: {suites}")
        allowed: dict[str, set[str] | None] = {s: set() for s in suites}
        for suite in (_norm_suite(s) for s in args.any_skip):
            if suite not in allowed:
                raise Usage(f"--any-skip {suite}: not a --suite")
            allowed[suite] = None
        for entry in args.allow_skip:
            suite, sep, reason = entry.partition("=")
            suite = _norm_suite(suite)
            if not sep or not reason:
                raise Usage(f"--allow-skip {entry!r}: expected SUITE=REASON")
            if suite not in allowed:
                raise Usage(f"--allow-skip {entry!r}: {suite} is not a --suite")
            if allowed[suite] is None:
                raise Usage(f"--allow-skip {entry!r}: {suite} already has --any-skip")
            allowed[suite].add(reason)
        paths = find_reports(args.paths)
        docs = [load_report(p) for p in paths]
    except Usage as exc:
        print(f"check_test_shards: {exc}", file=sys.stderr)
        return 2
    except BadReport as exc:
        print(f"check_test_shards: refusing a bad report: {exc}", file=sys.stderr)
        return 2

    if not docs:
        print("check_test_shards: no shard report found in " + " ".join(args.paths))
        return 1
    failed = False
    for suite in suites:
        mine = [d for d in docs if _norm_suite(d["suite"]) == suite]
        problems, proven = check_suite(suite, mine, allowed[suite])
        if problems:
            failed = True
            for problem in problems:
                print(f"PROBLEM: {problem}")
        else:
            print(
                f"{suite}: {len(mine)} shards, {proven} collected, each ran exactly once"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
