"""What a reader of a run sees: a report per guide, and the run's summary.

Per guide (UX D11.2), in Markdown and in HTML: a verdict line, one sentence
saying whether a reader following the guide can finish it, the table of steps
(what the guide says to do, what was expected before the run, what was seen,
the result) and, for each FAIL, the expected snapshot and the observed snapshot
side by side. A FAIL whose expected or observed snapshot is missing is refused
(``ReportError``): a report that drops one of the two would leave the reader
comparing against nothing.

The run's summary (``summary.md``, also the job summary): the counts, one row
per guide that ran, every page of the inventory not covered by a journey that
ran, with its class and reason, and how each flow of #939 is verified.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from docs_runner import registry
from docs_runner.log import FAIL, NOT_RUN, STRUCTURAL_ONLY, Record

#: The longest snapshot shown inline; the file itself is always complete.
SNAPSHOT_LINES = 200


class ReportError(ValueError):
    """The records cannot be reported honestly."""


@dataclass(frozen=True)
class GuideRun:
    """One journey's outcome in this run."""

    journey: str
    guide: str
    title: str
    stack: str
    records: Tuple[Record, ...] = ()
    #: The journey file was refused before any step ran: why, one line each.
    refused: Tuple[str, ...] = ()
    #: The run itself stopped before the steps (the stack did not come up).
    error: str = ""


@dataclass(frozen=True)
class Verdict:
    word: str  # PASS | FAIL | PARTIAL
    line: str  # "PASS", "FAIL at step 3", "PARTIAL: 2 not run"
    sentence: str
    first_failure: Optional[Record] = None


def verdict(run: GuideRun) -> Verdict:
    if run.refused:
        return Verdict(
            "FAIL",
            "FAIL: the journey file was refused",
            "The runner refused the journey file, so no step ran.",
        )
    if run.error:
        return Verdict(
            "FAIL",
            "FAIL before step 1",
            f"No step ran: {run.error}",
        )
    if not run.records:
        return Verdict("FAIL", "FAIL: no step ran", "The journey recorded no step.")
    failed = [record for record in run.records if record.result == FAIL]
    if failed:
        first = failed[0]
        return Verdict(
            "FAIL",
            f"FAIL at step {first.step}",
            "A reader following this guide cannot finish it."
            f' First failing step: {first.step}, "{first.heading}".',
            first,
        )
    not_run = [
        record
        for record in run.records
        if record.result == NOT_RUN and record.reason != registry.DOC_EXAMPLES
    ]
    if not_run:
        reasons = sorted({record.reason for record in not_run})
        return Verdict(
            "PARTIAL",
            f"PARTIAL: {len(not_run)} not run",
            "A reader following this guide can finish the steps that ran;"
            f" {len(not_run)} not run ({', '.join(reasons)}).",
        )
    by_doc_examples = sum(
        1 for record in run.records if record.reason == registry.DOC_EXAMPLES
    )
    tail = (
        f" {by_doc_examples} step(s) are run by Doc Examples instead."
        if by_doc_examples
        else ""
    )
    return Verdict(
        "PASS", "PASS", "A reader following this guide can finish it." + tail
    )


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------
@dataclass
class _Side:
    caption: str
    image: str = ""
    texts: List[Tuple[str, str]] = field(default_factory=list)  # (file, contents)


def _read(run_dir: Path, name: str) -> str:
    lines = (run_dir / name).read_text(encoding="utf-8").splitlines()
    if len(lines) > SNAPSHOT_LINES:
        lines = lines[:SNAPSHOT_LINES] + [f"... ({name} has the rest)"]
    return "\n".join(lines)


def _sides(record: Record, run_dir: Path) -> Tuple[_Side, _Side]:
    """The expected and the observed snapshot of a FAIL, or ReportError."""
    where = f"{record.guide} step {record.step} ({record.step_id})"
    if not record.expected_snapshot:
        raise ReportError(f"{where}: FAIL with no expected snapshot")
    if not record.snapshot:
        raise ReportError(f"{where}: FAIL with no observed snapshot")
    expected = _Side(f"Expected: {record.expected}")
    if record.expected_snapshot != STRUCTURAL_ONLY:
        if not (run_dir / record.expected_snapshot).is_file():
            raise ReportError(
                f"{where}: the expected snapshot {record.expected_snapshot} is missing"
            )
        expected.texts.append(
            (record.expected_snapshot, _read(run_dir, record.expected_snapshot))
        )
    else:
        expected.caption = f"Expected (structural only): {record.expected}"
    if not (run_dir / record.snapshot).is_file():
        raise ReportError(
            f"{where}: the observed snapshot {record.snapshot} is missing"
        )
    seen = _Side(f"Seen: {record.observed}")
    if record.snapshot.endswith(".png"):
        seen.image = record.snapshot
        aria = record.snapshot[: -len(".png")] + ".aria.yml"
        if (run_dir / aria).is_file():
            seen.texts.append((aria, _read(run_dir, aria)))
    else:
        seen.texts.append((record.snapshot, _read(run_dir, record.snapshot)))
    return expected, seen


def _side_html(side: _Side) -> str:
    parts = [f"<p><strong>{html.escape(side.caption)}</strong></p>"]
    if side.image:
        name = html.escape(side.image, quote=True)
        parts.append(f'<p><img src="{name}" alt="{name}" width="640"></p>')
    for name, text in side.texts:
        parts.append(
            f"<p><code>{html.escape(name)}</code></p><pre>{html.escape(text)}</pre>"
        )
    return "\n".join(parts)


def _side_by_side(record: Record, run_dir: Path) -> str:
    expected, seen = _sides(record, run_dir)
    return (
        "<table>\n<tr><th>Expected (written before the run)</th><th>Seen</th></tr>\n"
        f'<tr><td valign="top">\n{_side_html(expected)}\n</td>'
        f'<td valign="top">\n{_side_html(seen)}\n</td></tr>\n</table>\n'
        f"<p>Failure, as written before the run: {html.escape(record.failure_signature)}</p>"
    )


# ---------------------------------------------------------------------------
# Per guide
# ---------------------------------------------------------------------------
def _cell(text: str) -> str:
    return html.escape(" ".join(text.split()), quote=False).replace("|", "&#124;")


def _result(record: Record) -> str:
    return f"NOT RUN ({record.reason})" if record.result == NOT_RUN else record.result


WHAT_TO_DO = (
    "What to do: compare the two snapshots. Fix the guide if the product does what"
    " its API reference says, fix the product if the guide does, and decide when"
    " neither says."
)


def guide_markdown(run: GuideRun, run_dir: Path, *, date: str, sha: str) -> str:
    result = verdict(run)
    lines = [
        f"# {run.title} ({run.guide}), {date}, commit {sha}: {result.line}",
        "",
        result.sentence,
        "",
    ]
    if run.refused:
        lines += ["The journey file was refused:", ""]
        lines += [f"- {_cell(problem)}" for problem in run.refused]
        return "\n".join(lines) + "\n"
    if run.error:
        return "\n".join(lines) + "\n"
    lines += [
        "| Step | What the guide says to do | Expected (written before the run) | Seen | Result |",
        "|---|---|---|---|---|",
    ]
    for record in run.records:
        seen = _cell(record.observed)
        if record.snapshot:
            seen += f" ([{_cell(record.snapshot)}]({record.snapshot}))"
        lines.append(
            f"| {record.step} | {_cell(record.heading)}: {_cell(record.action)}"
            f" | {_cell(record.expected)} | {seen} | {_result(record)} |"
        )
    failed = [record for record in run.records if record.result == FAIL]
    for record in failed:
        lines += [
            "",
            f'## Step {record.step}, "{_cell(record.heading)}": FAIL',
            "",
            _side_by_side(record, run_dir),
        ]
    if failed:
        lines += ["", WHAT_TO_DO]
    return "\n".join(lines) + "\n"


def guide_html(run: GuideRun, run_dir: Path, *, date: str, sha: str) -> str:
    result = verdict(run)
    title = f"{run.title} ({run.guide}), {date}, commit {sha}: {result.line}"
    body = [f"<h1>{html.escape(title)}</h1>", f"<p>{html.escape(result.sentence)}</p>"]
    if run.refused:
        body.append("<p>The journey file was refused:</p><ul>")
        body += [f"<li>{html.escape(problem)}</li>" for problem in run.refused]
        body.append("</ul>")
    elif run.records:
        body.append(
            "<table><tr><th>Step</th><th>What the guide says to do</th>"
            "<th>Expected (written before the run)</th><th>Seen</th><th>Result</th></tr>"
        )
        for record in run.records:
            seen = html.escape(record.observed)
            if record.snapshot:
                name = html.escape(record.snapshot, quote=True)
                seen += f' (<a href="{name}">{name}</a>)'
            body.append(
                f"<tr><td>{record.step}</td>"
                f"<td>{html.escape(record.heading)}: {html.escape(record.action)}</td>"
                f"<td>{html.escape(record.expected)}</td><td>{seen}</td>"
                f"<td>{html.escape(_result(record))}</td></tr>"
            )
        body.append("</table>")
        failed = [record for record in run.records if record.result == FAIL]
        for record in failed:
            body.append(
                f"<h2>Step {record.step}, &quot;{html.escape(record.heading)}&quot;:"
                " FAIL</h2>"
            )
            body.append(_side_by_side(record, run_dir))
        if failed:
            body.append(f"<p>{html.escape(WHAT_TO_DO)}</p>")
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:sans-serif;margin:16px}table{border-collapse:collapse}"
        "td,th{border:1px solid #999;padding:4px;vertical-align:top}"
        "pre{white-space:pre-wrap;max-width:640px}</style></head>\n<body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def not_covered(
    inventory: Mapping[str, Any], ran: Sequence[GuideRun]
) -> List[Tuple[str, str, str]]:
    """(page, class, reason) for every inventory page no journey covered in this run."""
    ran_ids = {run.journey for run in ran}
    rows = []
    for page, entry in sorted(inventory.get("pages", {}).items()):
        cls = str(entry.get("class", ""))
        reason = str(entry.get("reason", ""))
        if cls == "journey":
            journey = entry.get("journey", "")
            if journey in ran_ids:
                continue
            if entry.get("pending") is True:
                reason = f"journey {journey}: pending, expectations not written yet; {reason}"
            else:
                reason = f"journey {journey}: not run in this run; {reason}"
        rows.append((page, cls, reason))
    return rows


def summary_markdown(
    runs: Sequence[GuideRun],
    inventory: Mapping[str, Any],
    *,
    date: str,
    sha: str,
) -> str:
    verdicts: Dict[str, Verdict] = {run.journey: verdict(run) for run in runs}
    counts = dict.fromkeys(("PASS", "FAIL", "PARTIAL"), 0)
    for result in verdicts.values():
        counts[result.word] += 1
    pages = inventory.get("pages", {})
    missing = not_covered(inventory, runs)
    if counts["FAIL"] or not runs:
        overall = "FAIL"
    elif counts["PARTIAL"]:
        overall = "PARTIAL"
    else:
        overall = "PASS"
    lines = [
        f"# Docs journeys, {date}, commit {sha}: {overall}, {len(runs)} guide(s) run",
        f"Guides: {counts['PASS']} pass, {counts['FAIL']} fail, {counts['PARTIAL']}"
        f" partial of {len(pages)} in the nav. Not covered: {len(missing)}"
        " page(s), listed below.",
        "",
    ]
    if runs:
        lines += ["| Guide | Journey | Stack | Result |", "|---|---|---|---|"]
        for run in runs:
            lines.append(
                f"| {_cell(run.title)} ({_cell(run.guide)}) | {_cell(run.journey)}"
                f" | {_cell(run.stack)} | {_cell(verdicts[run.journey].line)} |"
            )
        lines.append("")
    lines += ["## Not covered in this run", ""]
    if missing:
        lines += ["| Page | Class | Reason |", "|---|---|---|"]
        lines += [
            f"| {_cell(page)} | {_cell(cls)} | {_cell(reason)} |"
            for page, cls, reason in missing
        ]
    else:
        lines.append("Every page in the nav was covered.")
    lines += ["", "## How each flow of #939 is verified", ""]
    flows = inventory.get("flow", [])
    lines += [
        "| Flow | Journeys (this run) | Pages | Classes | Note |",
        "|---|---|---|---|---|",
    ]
    for flow in flows:
        journeys = ", ".join(
            f"{journey} ({verdicts[journey].line if journey in verdicts else 'not run'})"
            for journey in flow.get("journeys", [])
        )
        lines.append(
            f"| {_cell(flow.get('text', ''))} | {_cell(journeys)}"
            f" | {_cell(', '.join(flow.get('pages', [])))}"
            f" | {_cell(', '.join(flow.get('classes', [])))}"
            f" | {_cell(flow.get('note', ''))} |"
        )
    return "\n".join(lines) + "\n"
