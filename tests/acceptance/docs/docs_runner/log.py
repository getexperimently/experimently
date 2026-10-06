"""The run's results log: JSON Lines, one line per step, the same keys on every line.

``KEYS`` is the line, in order; a change to them is a change of the log's
contract with whatever reads it:

* ``run``, ``sha``: the run's id and the commit it ran;
* ``stack``, ``guide``: the journey's stack and its guide (a nav path);
* ``step``, ``step_id``, ``heading``: the step's number, its id, and the heading
  of the guide section it follows (the step's ``doc`` anchor);
* ``action``: what was done (a field's value is never written);
* ``expected``, ``failure_signature``: from the journey file, written before
  the run;
* ``result``: PASS, FAIL or NOT RUN, and ``reason`` for NOT RUN;
* ``observed``: one line, what was seen;
* ``snapshot``: the file holding what was seen (a screenshot, with the page's
  ARIA snapshot beside it under the same name and ``.aria.yml``; for an api
  step, the status and the values at the expected JSON paths), or "";
* ``expected_snapshot``: the file holding the expected ARIA snapshot, or
  ``structural only`` when the step expects no ARIA snapshot, or "" when it
  expects nothing here (``ref: doc-examples``);
* ``ms``: how long the step took.

Files are named relative to the run directory.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Mapping, Tuple

from docs_runner import registry

KEYS: Tuple[str, ...] = (
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
PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT RUN"
RESULTS = (PASS, FAIL, NOT_RUN)
STRUCTURAL_ONLY = "structural only"


class BadRecord(ValueError):
    """A line that is not a results-log line."""


@dataclass(frozen=True)
class Record:
    run: str
    sha: str
    stack: str
    guide: str
    step: int
    step_id: str
    heading: str
    action: str
    expected: str
    failure_signature: str
    result: str
    reason: str
    observed: str
    snapshot: str
    expected_snapshot: str
    ms: int

    def __post_init__(self) -> None:
        if self.result not in RESULTS:
            raise BadRecord(f"result {self.result!r} is not one of {RESULTS}")
        if self.result == NOT_RUN:
            if not registry.is_known(self.reason):
                raise BadRecord(
                    f"NOT RUN reason {self.reason!r} is not in the registry"
                )
        elif self.reason:
            raise BadRecord(f"a {self.result} step has no reason ({self.reason!r})")
        if not isinstance(self.step, int) or self.step < 1:
            raise BadRecord(f"step {self.step!r} is not a step number")
        if not isinstance(self.ms, int) or self.ms < 0:
            raise BadRecord(f"ms {self.ms!r} is not a duration")
        for key in KEYS:
            value = getattr(self, key)
            if isinstance(value, str) and "\n" in value:
                raise BadRecord(f"{key} is more than one line")

    def line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def parse_line(text: str) -> Record:
    data = json.loads(text)
    if not isinstance(data, dict) or tuple(data) != KEYS:
        got = list(data) if isinstance(data, dict) else type(data).__name__
        raise BadRecord(f"keys {got} are not the log's keys {list(KEYS)}")
    return Record(**data)


class Log:
    """Appends records to the run's ``results.jsonl``, one flushed line each."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: Record) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.line() + "\n")


def read(path: Path) -> List[Record]:
    if not path.exists():
        return []
    records = []
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip():
            continue
        try:
            records.append(parse_line(text))
        except (BadRecord, ValueError, TypeError) as error:
            raise BadRecord(f"{path.name} line {number}: {error}") from None
    return records


def run_directory(environ: Mapping[str, str], repo_root: Path) -> Path:
    """``DOCS_JOURNEY_RUN_DIR``, or a new temporary directory when it is unset.

    ValueError when it is inside *repo_root*: a run writes nothing into the
    tree.
    """
    raw = environ.get("DOCS_JOURNEY_RUN_DIR", "")
    if not raw:
        return Path(tempfile.mkdtemp(prefix="docs-journeys-run-"))
    path = Path(raw).expanduser().resolve()
    root = repo_root.resolve()
    if path == root or root in path.parents:
        raise ValueError(
            f"DOCS_JOURNEY_RUN_DIR={raw} is inside the repository; a run writes"
            " nothing into the tree, so give a directory outside it"
        )
    path.mkdir(parents=True, exist_ok=True)
    return path
