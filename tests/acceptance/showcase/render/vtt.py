"""The WebVTT file: written from the cue sheet, then read back by a strict parser (gate 4).

ffprobe is no check here: it exits 0 on a file with no ``WEBVTT`` header and a
``->`` arrow, and on a cue that ends before it starts (measured with ffmpeg
8.0.1). So the render parses the file it wrote with the rules below and
compares every cue with the cue sheet: the same count, times and text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from showcase import contract
from showcase.render.timeline import OutputCue

_TIMING = re.compile(
    r"^(?P<h1>[0-9]{2}):(?P<m1>[0-5][0-9]):(?P<s1>[0-5][0-9])\.(?P<ms1>[0-9]{3})"
    r" --> "
    r"(?P<h2>[0-9]{2}):(?P<m2>[0-5][0-9]):(?P<s2>[0-5][0-9])\.(?P<ms2>[0-9]{3})$"
)


@dataclass(frozen=True)
class VttCue:
    identifier: str
    start_ms: int
    end_ms: int
    lines: Tuple[str, ...]


class VttError(ValueError):
    pass


def timestamp(ms: int) -> str:
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def write_vtt(cues: Sequence[OutputCue]) -> str:
    blocks = ["WEBVTT"]
    for cue in cues:
        blocks.append(
            "\n".join(
                [
                    str(cue.number),
                    f"{timestamp(cue.start_ms)} --> {timestamp(cue.end_ms)}",
                    *cue.lines,
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def _ms(match: re.Match, suffix: str) -> int:
    return (
        int(match[f"h{suffix}"]) * 3_600_000
        + int(match[f"m{suffix}"]) * 60_000
        + int(match[f"s{suffix}"]) * 1000
        + int(match[f"ms{suffix}"])
    )


def parse_vtt(text: str) -> List[VttCue]:
    """Parse the subset of WebVTT the render writes; anything else is an error."""
    if text.startswith("﻿"):
        raise VttError("the file starts with a byte-order mark")
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise VttError("the file must end with exactly one line break")
    if "\r" in text:
        raise VttError("the file has carriage returns")
    blocks = text[:-1].split("\n\n")
    if blocks[0] != "WEBVTT":
        raise VttError(
            f"the header is {blocks[0].splitlines()[0]!r}, not 'WEBVTT'"
            if blocks[0]
            else "no header"
        )
    cues: List[VttCue] = []
    for number, block in enumerate(blocks[1:], start=1):
        lines = block.split("\n")
        if len(lines) < 3 or any(not line.strip() for line in lines):
            raise VttError(
                f"block {number} is not an identifier, a timing line and text"
            )
        identifier, timing, payload = lines[0], lines[1], tuple(lines[2:])
        if identifier != str(number):
            raise VttError(f"block {number} is numbered {identifier!r}")
        match = _TIMING.match(timing)
        if not match:
            raise VttError(
                f"cue {number}: timing line {timing!r} is not 'HH:MM:SS.mmm --> HH:MM:SS.mmm'"
            )
        if any("-->" in line for line in payload):
            raise VttError(f"cue {number}: its text holds '-->'")
        cues.append(
            VttCue(
                identifier=identifier,
                start_ms=_ms(match, "1"),
                end_ms=_ms(match, "2"),
                lines=payload,
            )
        )
    return cues


def check_vtt(
    parsed: Sequence[VttCue], expected: Sequence[OutputCue], total_frames: int
) -> List[str]:
    """Every rule the cue sheet obeyed, checked again on the file as written."""
    problems: List[str] = []
    if len(parsed) != len(expected):
        problems.append(f"{len(parsed)} cues parsed, the cue sheet has {len(expected)}")
    title_end = contract.ms_for_frames(contract.TITLE_FRAMES)
    end_start = contract.ms_for_frames(total_frames - contract.END_FRAMES)
    previous_end = title_end
    for number, cue in enumerate(parsed, start=1):
        if cue.end_ms <= cue.start_ms:
            problems.append(f"cue {number} ends at or before it starts")
        if cue.start_ms < previous_end and number > 1:
            problems.append(
                f"cues {number - 1} and {number} overlap by {(previous_end - cue.start_ms) / 1000:.3f} s"
            )
        elif cue.start_ms - previous_end > contract.MAX_CUE_GAP_MS:
            where = (
                "the title card and cue 1"
                if number == 1
                else f"cues {number - 1} and {number}"
            )
            problems.append(
                f"{(cue.start_ms - previous_end) / 1000:.3f} s without a caption between {where}; "
                f"at most {contract.MAX_CUE_GAP_MS / 1000:.3f} s"
            )
        if cue.start_ms < title_end or cue.end_ms > end_start:
            problems.append(
                f"cue {number} is not between the title card and the end card"
            )
        text = " ".join(cue.lines)
        need = contract.reading_time_ms(text)
        if cue.end_ms - cue.start_ms < need:
            problems.append(
                f"cue {number}: {len(text)} characters in {(cue.end_ms - cue.start_ms) / 1000:.3f} s, "
                f"needs {need / 1000:.3f} s"
            )
        if len(cue.lines) > contract.MAX_CUE_LINES or any(
            len(line) > contract.MAX_LINE_CHARS for line in cue.lines
        ):
            problems.append(
                f"cue {number} has more than {contract.MAX_CUE_LINES} lines of {contract.MAX_LINE_CHARS}"
            )
        previous_end = cue.end_ms
    if parsed and end_start - parsed[-1].end_ms > contract.MAX_CUE_GAP_MS:
        problems.append(
            f"{(end_start - parsed[-1].end_ms) / 1000:.3f} s without a caption before the end card; "
            f"at most {contract.MAX_CUE_GAP_MS / 1000:.3f} s"
        )
    for number, (got, want) in enumerate(zip(parsed, expected), start=1):
        if (got.start_ms, got.end_ms) != (want.start_ms, want.end_ms):
            problems.append(
                f"cue {number} is at {got.start_ms}-{got.end_ms} ms; the burned-in caption is at "
                f"{want.start_ms}-{want.end_ms} ms"
            )
        if got.lines != want.lines:
            problems.append(f"cue {number}'s text differs from the burned-in caption")
    return problems
