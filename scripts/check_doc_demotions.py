#!/usr/bin/env python3
"""Fail a pull request that stops running a documentation example it used to run.

    python3 scripts/check_doc_demotions.py --base-ref REF [--labels JSON]
    python3 scripts/check_doc_demotions.py --base-file OLD.toml [--head-file NEW.toml] [--labels JSON]

``scripts/doc_examples.toml`` records, per enrolled document, how many of its
shell examples execute (``exec``). Retagging an ``exec`` block as ``skip`` and
lowering the number in the same diff satisfies ``doc_examples.py --check``, so
that check alone cannot see an example quietly stop running. This one can: it
compares every document's ``exec`` on the pull request with the same
document's on the base branch, and fails if any document's number fell. A
document that left ``[[document]]`` altogether (removed, moved to ``pending``
or ``[[exempt]]``, or renamed) counts as falling to 0. The comparison is per
document, never by totals, so one page gaining an example cannot pay for
another losing one.

A demotion that is intended is allowed by the pull request label
``docs-demotion`` (``--labels``, the JSON array of label names that the
workflow reads from the event payload). The demotions are still printed.

It fails closed. The base is read with ``git show REF:scripts/doc_examples.toml``,
and a ref that does not resolve, a missing file, or TOML that cannot be read
on either side is an error, never "no demotions". The label does not waive an
unreadable base: it acknowledges a demotion someone has seen, and nobody has
seen one that could not be measured.

Where it runs: the ``regression-guard`` job (``.github/workflows/regression-guard.yml``),
on every pull request to main, including documentation-only ones, and again on
``labeled``/``unlabeled``. It does not run on push.

Exit status: 0 no demotion, or every demotion labelled; 1 a demotion without
the label; 2 a side, or the labels, could not be read.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TOML_PATH = "scripts/doc_examples.toml"
LABEL = "docs-demotion"


class Unreadable(Exception):
    """A side of the comparison, or the label list, could not be read."""


def exec_counts(text: str, side: str) -> Dict[str, int]:
    """Map each ``[[document]]`` path to its ``exec`` count."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise Unreadable(
            f"the {side} {TOML_PATH} is not valid TOML: {error}"
        ) from error
    documents = data.get("document", [])
    if not isinstance(documents, list):
        raise Unreadable(
            f"the {side} {TOML_PATH}: [[document]] is not a list of tables"
        )
    counts: Dict[str, int] = {}
    for index, document in enumerate(documents):
        path = document.get("path") if isinstance(document, dict) else None
        count = document.get("exec") if isinstance(document, dict) else None
        if not isinstance(path, str) or not path:
            raise Unreadable(
                f"the {side} {TOML_PATH}: document {index + 1} has no path"
            )
        # bool is an int subclass; `exec = true` is not a count.
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise Unreadable(
                f"the {side} {TOML_PATH}: {path} has no whole-number exec count"
            )
        if path in counts:
            raise Unreadable(f"the {side} {TOML_PATH}: {path} is enrolled twice")
        counts[path] = count
    return counts


def demotions(base: Dict[str, int], head: Dict[str, int]) -> List[Tuple[str, int, int]]:
    """Every document whose exec count fell, as (path, base, head); absent is 0."""
    return [
        (path, before, head.get(path, 0))
        for path, before in sorted(base.items())
        if head.get(path, 0) < before
    ]


def read_base(ref: str, cwd: Optional[Path] = None) -> str:
    """The base branch's toml, via ``git show``; any failure is Unreadable."""
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{TOML_PATH}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise Unreadable(f"cannot run git to read the base: {error}") from error
    if result.returncode != 0:
        raise Unreadable(
            f"cannot read {TOML_PATH} at the base ({ref}): "
            f"{result.stderr.strip() or 'git show exited ' + str(result.returncode)}"
        )
    return result.stdout


def labelled(labels_json: str) -> bool:
    try:
        labels = json.loads(labels_json)
    except json.JSONDecodeError as error:
        raise Unreadable(
            f"the pull request labels are not a JSON array: {error}"
        ) from error
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise Unreadable(
            f"the pull request labels are not a JSON array of names: {labels_json}"
        )
    return any(name.lower() == LABEL for name in labels)


def annotate(level: str, message: str) -> str:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return f"::{level} file={TOML_PATH}::{message}"
    return f"{level}: {message}"


def run(base_text: str, head_text: str, labels_json: str) -> Tuple[int, List[str]]:
    """The verdict and the lines to print; raises Unreadable."""
    base = exec_counts(base_text, "base")
    head = exec_counts(head_text, "pull request's")
    is_labelled = labelled(labels_json)
    dropped = demotions(base, head)
    if not dropped:
        return 0, [
            f"No documentation example stopped running ({len(base)} documents on the base)."
        ]
    level = "warning" if is_labelled else "error"
    lines = []
    for path, before, after in dropped:
        gone = "" if path in head else " (no longer enrolled)"
        lines.append(
            annotate(
                level,
                f"{path}: exec {before} -> {after} against the base{gone}; "
                f"label the pull request {LABEL} if this is intended",
            )
        )
    if is_labelled:
        lines.append(f"Labelled `{LABEL}`: {len(dropped)} demotion(s) accepted.")
        return 0, lines
    lines.append(
        f"{len(dropped)} document(s) run fewer examples than on the base. If that is "
        f"intended, add the `{LABEL}` label and say why in the description; the "
        "check re-runs when the label is added."
    )
    return 1, lines


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--base-ref", help="a git ref whose scripts/doc_examples.toml is the base"
    )
    source.add_argument("--base-file", type=Path, help="the base toml, as a file")
    parser.add_argument("--head-file", type=Path, default=Path(TOML_PATH))
    parser.add_argument(
        "--labels", default="[]", help="JSON array of the pull request's labels"
    )
    args = parser.parse_args(argv)
    try:
        if args.base_ref is not None:
            if not args.base_ref.strip():
                raise Unreadable("--base-ref is empty: the base commit is unknown")
            base_text = read_base(args.base_ref)
        else:
            try:
                base_text = args.base_file.read_text(encoding="utf-8")
            except OSError as error:
                raise Unreadable(f"cannot read the base toml: {error}") from error
        try:
            head_text = args.head_file.read_text(encoding="utf-8")
        except OSError as error:
            raise Unreadable(f"cannot read the pull request's toml: {error}") from error
        status, lines = run(base_text, head_text, args.labels)
    except Unreadable as error:
        print(
            annotate(
                "error", f"{str(error).rstrip('.')}. Refusing to report no demotions."
            )
        )
        return 2
    print("\n".join(lines))
    return status


if __name__ == "__main__":
    sys.exit(main())
