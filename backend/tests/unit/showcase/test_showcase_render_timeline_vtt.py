"""The showcase render's timeline and WebVTT file (#1066; gate 4).

The capture's frames arrive only when the page changes; the render holds each
one until the next is due, in whole frames, and takes every caption time from
the same frame counts for the burned-in band and the WebVTT file. The strict
parser is the gate: ffprobe accepts a broken WebVTT file and exits 0.
"""

from __future__ import annotations

import pytest
from showcase import contract
from showcase.render import timeline, vtt

from backend.tests.unit.showcase.capture_dirs import default_cues

pytestmark = [pytest.mark.unit]


def frames(*times):
    return [
        contract.Frame(file=f"{i + 1:06d}.jpg", t_ms=t) for i, t in enumerate(times)
    ]


def sheet(cues=None, duration_ms=50_000):
    raw = cues if cues is not None else default_cues()
    return contract.CueSheet(
        slug="01-getting-started",
        title="Get started",
        version="v0.26.3",
        duration_ms=duration_ms,
        cues=tuple(
            contract.Cue(c["start_ms"], c["end_ms"], c["text"], None) for c in raw
        ),
    )


# --- Constant frame rate ------------------------------------------------------------


def test_each_frame_is_held_until_the_next_is_due():
    # frames at 0, 100 ms and 1 s: output frames are 33.3 ms apart
    shown = timeline.frame_schedule(frames(0, 100, 1000), 32)
    assert shown[:3] == [0, 0, 0]  # 0, 33, 67 ms
    assert shown[3] == 1  # 100 ms exactly: the new frame is due
    assert shown[29] == 1 and shown[30] == 2  # 966.7 ms, then 1000 ms
    assert shown[-1] == 2  # the last frame holds to the end


def test_the_first_frame_covers_the_start():
    assert timeline.frame_schedule(frames(15, 2000), 3) == [0, 0, 0]


def test_an_idle_tail_is_held_not_dropped():
    # One frame, then nothing for 50 s: every output frame shows it.
    shown = timeline.frame_schedule(frames(0), 1500)
    assert len(shown) == 1500 and set(shown) == {0}


def test_the_band_shows_each_cue_for_its_frames_only():
    s = sheet()
    band = timeline.band_schedule(s.cues, s.capture_frames)
    first, second = s.cues[0], s.cues[1]
    assert band[: first.start_frame] == [None] * first.start_frame
    assert set(band[first.start_frame : first.end_frame]) == {0}
    assert set(band[first.end_frame : second.start_frame]) == {None}
    assert band[second.start_frame] == 1


def test_output_cues_are_shifted_by_the_title_card():
    out = timeline.output_cues(sheet())
    assert out[0].start_frame == contract.TITLE_FRAMES + contract.frames_for_ms(200)
    assert out[0].start_ms == contract.TITLE_CARD_MS + 200
    assert out[0].lines == ("One command starts the whole stack on your", "machine.")


def test_cards_take_their_fixed_frames():
    title, end = timeline.card_ranges(1710)
    assert title == (0, 90) and end == (1590, 1710)


# --- WebVTT ---------------------------------------------------------------------------


def good():
    s = sheet()
    out = timeline.output_cues(s)
    return out, vtt.write_vtt(out), contract.video_frames(s.duration_ms)


def test_the_written_file_parses_back_to_the_burned_in_cues():
    out, text, total = good()
    assert text.startswith(
        "WEBVTT\n\n1\n00:00:03.200 --> 00:00:07.967\nOne command starts the whole stack on your\n"
    )
    parsed = vtt.parse_vtt(text)
    assert vtt.check_vtt(parsed, out, total) == []
    assert [(c.start_ms, c.end_ms) for c in parsed] == [
        (c.start_ms, c.end_ms) for c in out
    ]


@pytest.mark.parametrize(
    "plant, message",
    [
        (
            lambda t: t.replace(" --> ", " -> ", 1),
            "is not 'HH:MM:SS.mmm --> HH:MM:SS.mmm'",
        ),
        (lambda t: t.replace("WEBVTT\n\n", "", 1), "not 'WEBVTT'"),
        (lambda t: "﻿" + t, "byte-order mark"),
        (lambda t: t + "\n", "exactly one line break"),
        (lambda t: t.replace("\n", "\r\n"), "carriage returns"),
        (lambda t: t.replace("\n\n2\n", "\n\n7\n", 1), "block 2 is numbered '7'"),
    ],
)
def test_a_malformed_file_is_refused(plant, message):
    _, text, _ = good()
    with pytest.raises(vtt.VttError, match=message):
        vtt.parse_vtt(plant(text))


def test_overlapping_cues_are_refused():
    out, text, total = good()
    parsed = vtt.parse_vtt(text)
    shifted = list(parsed)
    shifted[4] = vtt.VttCue(
        identifier="5",
        start_ms=parsed[3].end_ms - 100,
        end_ms=parsed[4].end_ms,
        lines=parsed[4].lines,
    )
    problems = vtt.check_vtt(shifted, out, total)
    assert "cues 4 and 5 overlap by 0.100 s" in problems


def test_a_long_caption_held_too_briefly_is_refused():
    out, text, total = good()
    parsed = vtt.parse_vtt(text)
    lines = (
        "Captions this long take time to read: each",
        "word has to land before the next one comes",
    )
    caption = " ".join(lines)
    assert len(caption) == 85 and contract.reading_time_ms(caption) == 6167
    short = list(parsed)
    short[0] = vtt.VttCue(
        identifier="1",
        start_ms=parsed[0].start_ms,
        end_ms=parsed[0].start_ms + 2000,
        lines=lines,
    )
    problems = vtt.check_vtt(short, out, total)
    assert "cue 1: 85 characters in 2.000 s, needs 6.167 s" in problems, problems
    assert "cue 1's text differs from the burned-in caption" in problems


def test_a_missing_cue_is_counted():
    out, text, total = good()
    parsed = vtt.parse_vtt(text)[:-1]
    problems = vtt.check_vtt(parsed, out, total)
    assert "9 cues parsed, the cue sheet has 10" in problems


def test_a_shifted_file_does_not_match_the_burned_in_band():
    out, text, total = good()
    parsed = [
        vtt.VttCue(
            identifier=c.identifier,
            start_ms=c.start_ms + 1500,
            end_ms=c.end_ms + 1500,
            lines=c.lines,
        )
        for c in vtt.parse_vtt(text)
    ]
    problems = vtt.check_vtt(parsed, out, total)
    assert any("the burned-in caption is at 3200-7967 ms" in p for p in problems), (
        problems
    )


def test_timestamps_are_zero_padded_milliseconds():
    assert vtt.timestamp(0) == "00:00:00.000"
    assert vtt.timestamp(3_723_004) == "01:02:03.004"
