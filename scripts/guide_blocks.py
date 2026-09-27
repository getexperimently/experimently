#!/usr/bin/env python3
"""Extract the marked shell blocks of an install guide, so CI runs the page itself.

The ``chart-kind`` job (``.github/workflows/chart-kind.yml``) runs the blocks
of ``docs/self-hosting/kubernetes.md`` on a kind cluster, exactly as a reader
would paste them. It never keeps a copy of them: a copy is what drifts. A
block is marked by an HTML comment on the line directly above its fence,
which the site does not show::

    <!-- chart-kind: secrets -->
    ```bash
    kubectl create secret generic ...
    ```

Usage::

    python3 scripts/guide_blocks.py PAGE --expect secrets,install --out DIR

writes ``DIR/<name>.sh`` for every marked block and exits 0 only when:

* every ``bash`` fence on the page is marked, so a block cannot be added to the
  page without the job either running it or failing. Fences are found at any
  indentation (a list item's) and with backticks or tildes;
* no fence is unlabelled, tagged (``{.bash ...}``) or in another shell dialect
  (``sh``, ``shell``, ``zsh``, ``console``, ...): each of those would be a
  command on the page that nothing runs;
* every marker sits directly above a ``bash`` fence, and names a block once;
* the marked names, in page order, equal ``--expect`` exactly -- the job's own
  list of what it runs, so a block that is renamed or dropped fails here
  instead of silently not running.

Every problem is reported at once, one line each, and the exit status is 1.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import List, Tuple

MARKER = re.compile(r"^[ \t]*<!-- chart-kind: ([a-z][a-z0-9-]*) -->[ \t]*$")
LOOSE_MARKER = re.compile(r"chart-kind:")
# A fence at any indentation (inside a list item it is indented), of backticks
# or tildes, three or more. The closing fence is the same character, at least
# as long, with nothing after it.
FENCE_OPEN = re.compile(r"^([ \t]*)(`{3,}|~{3,})[ \t]*(.*?)[ \t]*$")
# Shell dialects other than bash: a block in one of them would be neither run
# nor marked, so they are refused on this page; write `bash`, with a marker.
OTHER_SHELLS = frozenset(
    {
        "sh",
        "shell",
        "zsh",
        "console",
        "shell-session",
        "sh-session",
        "shellsession",
        "ksh",
        "fish",
        "powershell",
        "ps1",
        "pwsh",
        "bat",
        "cmd",
    }
)


def _closes(line: str, fence: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= len(fence) and set(stripped) == {fence[0]}


def extract(text: str, page: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Return ``([(name, body), ...], problems)`` for one page's text.

    Every fence names a language. ``bash`` needs a marker; other shell
    dialects and an unlabelled fence are refused (use ``text`` for output);
    any other language (``text``, ``json``, ``yaml``, ...) is left alone.
    """
    lines = text.splitlines()
    blocks: List[Tuple[str, str]] = []
    problems: List[str] = []
    pending: Tuple[str, int] | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        opened = FENCE_OPEN.match(line)
        if opened:
            indent, fence, info_string = opened.groups()
            info = info_string.split()[0] if info_string else ""
            body: List[str] = []
            j = i + 1
            while j < len(lines) and not _closes(lines[j], fence):
                body_line = lines[j]
                body.append(
                    body_line[len(indent) :]
                    if body_line.startswith(indent)
                    else body_line
                )
                j += 1
            if j == len(lines):
                problems.append(f"{page}:{i + 1}: a fence that never closes")
            if not info:
                problems.append(
                    f"{page}:{i + 1}: a fence with no language; name one "
                    "(`bash` with a marker to run it, `text` for output)"
                )
            elif info.startswith("{"):
                problems.append(
                    f"{page}:{i + 1}: a tagged fence '{info_string}'; this page's blocks "
                    "are plain `bash` with a '<!-- chart-kind: NAME -->' marker"
                )
            elif info.lower() in OTHER_SHELLS:
                problems.append(
                    f"{page}:{i + 1}: a '{info}' block is neither run nor checked; "
                    "write it as `bash` with a '<!-- chart-kind: NAME -->' marker"
                )
            if info == "bash":
                if pending is None:
                    problems.append(
                        f"{page}:{i + 1}: a bash block with no '<!-- chart-kind: NAME -->' "
                        "line directly above it; every shell block on this page is run by "
                        "the chart-kind job"
                    )
                else:
                    blocks.append((pending[0], "\n".join(body) + "\n"))
            elif pending is not None:
                problems.append(
                    f"{page}:{pending[1]}: marker '{pending[0]}' is above a "
                    f"'{info or 'unlabelled'}' fence, not a bash block"
                )
            pending = None
            i = j + 1
            continue
        if pending is not None:
            problems.append(
                f"{page}:{pending[1]}: marker '{pending[0]}' is not directly above a bash block"
            )
            pending = None
        marked = MARKER.match(line)
        if marked:
            pending = (marked.group(1), i + 1)
        elif LOOSE_MARKER.search(line):
            problems.append(
                f"{page}:{i + 1}: a malformed marker; write exactly '<!-- chart-kind: NAME -->' "
                "on its own line"
            )
        i += 1
    if pending is not None:
        problems.append(
            f"{page}:{pending[1]}: marker '{pending[0]}' is not directly above a bash block"
        )

    seen: set[str] = set()
    for name, _ in blocks:
        if name in seen:
            problems.append(f"{page}: block '{name}' is marked more than once")
        seen.add(name)
    return blocks, problems


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("page", type=pathlib.Path)
    parser.add_argument(
        "--expect",
        required=True,
        help="the block names the caller runs, comma-separated, in page order",
    )
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)

    page = str(args.page)
    blocks, problems = extract(args.page.read_text(encoding="utf-8"), page)
    names = [name for name, _ in blocks]
    expected = [name for name in args.expect.split(",") if name]
    if names != expected:
        problems.append(
            f"{page}: the marked blocks are {names}; the job runs {expected}. "
            "Change both together."
        )
    for name, body in blocks:
        if not body.strip():
            problems.append(f"{page}: block '{name}' is empty")

    if problems:
        for problem in problems:
            print(f"refused: {problem}", file=sys.stderr)
        print(f"{len(problems)} problem(s)", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    for name, body in blocks:
        (args.out / f"{name}.sh").write_text(body, encoding="utf-8")
        print(f"{page}: block '{name}' -> {args.out / (name + '.sh')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
