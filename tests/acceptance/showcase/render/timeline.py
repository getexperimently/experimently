"""The video's timeline in whole frames: which capture frame and which caption each output frame shows.

The screencast sends a frame only when the page changes, so the capture is a
variable-rate sequence. The render makes it constant 30 fps here, in Python,
by holding each capture frame until the next one is due: output frame ``k``
of the recording shows the last capture frame whose ``t_ms`` is at or before
``k / 30`` s (the first frame also covers the few milliseconds before it).
ffmpeg's concat demuxer is never used: its durations were measured wrong by
up to two seconds.

The title card comes first, so every caption's output frame is its recording
frame plus ``contract.TITLE_FRAMES``. The burned-in band and the WebVTT file
both take their times from ``output_cues``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from showcase import contract


@dataclass(frozen=True)
class OutputCue:
    number: int
    start_frame: int
    end_frame: int
    lines: Tuple[str, ...]

    @property
    def start_ms(self) -> int:
        return contract.ms_for_frames(self.start_frame)

    @property
    def end_ms(self) -> int:
        return contract.ms_for_frames(self.end_frame)

    @property
    def text(self) -> str:
        return " ".join(self.lines)


def frame_schedule(frames: Sequence[contract.Frame], count: int) -> List[int]:
    """For each of ``count`` output frames, the index of the capture frame it shows."""
    if not frames:
        raise ValueError("no capture frames")
    shown: List[int] = []
    current = 0
    for k in range(count):
        while (
            current + 1 < len(frames)
            and frames[current + 1].t_ms * contract.FPS <= k * 1000
        ):
            current += 1
        shown.append(current)
    return shown


def band_schedule(cues: Sequence[contract.Cue], count: int) -> List[Optional[int]]:
    """For each of ``count`` recording frames, the index of the cue on screen, or None."""
    band: List[Optional[int]] = [None] * count
    for index, cue in enumerate(cues):
        for k in range(max(cue.start_frame, 0), min(cue.end_frame, count)):
            if band[k] is not None:
                raise ValueError(f"cues {band[k] + 1} and {index + 1} share frame {k}")
            band[k] = index
    return band


def output_cues(sheet: contract.CueSheet) -> List[OutputCue]:
    """The cues as the finished video shows them, in output frames."""
    return [
        OutputCue(
            number=number,
            start_frame=contract.TITLE_FRAMES + cue.start_frame,
            end_frame=contract.TITLE_FRAMES + cue.end_frame,
            lines=cue.lines,
        )
        for number, cue in enumerate(sheet.cues, start=1)
    ]


def card_ranges(total_frames: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """The title and end cards' output frames, as half-open ranges."""
    return (0, contract.TITLE_FRAMES), (
        total_frames - contract.END_FRAMES,
        total_frames,
    )
