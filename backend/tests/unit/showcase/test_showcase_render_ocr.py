"""The showcase render's OCR decisions (#1066; gates 5, 7 and U4).

The OCR engines themselves run only on a developer's machine. What is pinned
here is every decision made from their text: the fuzzy needle match (with the
misreadings measured on this project's frames: ``_`` read as a space, ``b``
read as ``o``, ``1`` read as ``l``), the key and token shapes, the forbidden
phrases, the caption read-back, and that an engine which fails or reads
nothing stops the scan instead of passing it.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from showcase import contract
from showcase.render import encode, ocr
from showcase.render.gates import Refused
from showcase.render.timeline import OutputCue

pytestmark = [pytest.mark.unit]

NEEDLE = "VALUE-3F9A1C07B2E4D586"


def brute_distance(pattern: str, text: str) -> int:
    """Semi-global edit distance by the textbook table, to check Myers against."""
    previous = [0] * (len(text) + 1)
    for i, p in enumerate(pattern, start=1):
        current = [i] + [0] * len(text)
        for j, t in enumerate(text, start=1):
            current[j] = min(
                previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (p != t)
            )
        previous = current
    return min(previous)


def test_myers_matches_the_textbook_table():
    rng = random.Random(1066)
    for _ in range(400):
        pattern = "".join(rng.choice("abcde") for _ in range(rng.randint(1, 30)))
        text = "".join(rng.choice("abcde") for _ in range(rng.randint(0, 80)))
        assert ocr.best_distance(pattern, text) == brute_distance(pattern, text), (
            pattern,
            text,
        )


def test_normalise_folds_what_ocr_confuses():
    assert ocr.normalise("O0@ 1lI| fT 2Z 5S 8B _-:") == "ooollllttzzssbb"
    assert (
        ocr.normalise("eptk_demo_shoplab")
        == ocr.normalise("EPTK DEMO SHOPLAB")
        == "eptkdemoshoplab"
    )


@pytest.mark.parametrize(
    "ocr_text",
    [
        f"Shown once: {NEEDLE}",
        "Shown once: VALUE 3F9A1C07B2E4D586",  # dash read as a space
        "Shown once: VALUE-3F9AlC07B2E4D5B6",  # 1 read as l, 8 as B
        "shown VALUE-3F9A1C07B2E4D5",  # cut off at the edge: a part of it
        "VALUE-3F9A1C0\n7B2E4D586",  # wrapped onto two lines
    ],
)
def test_a_needle_is_found_through_misreadings(ocr_text):
    found = ocr.findings(ocr_text, [NEEDLE, "OTHER-VALUE-XYZXYZXYZ"])
    assert [gate for gate, _ in found] == ["7"]
    assert found[0][1].startswith("needle 1 of 2 at ")
    for _, what in found:
        assert NEEDLE not in what and "3F9A" not in what


def test_ordinary_dashboard_text_is_not_a_needle():
    text = (
        "Experimently Experiments Feature Flags Admin\nHomepage hero copy test Active 2 variants 12,408 users\n"
        "Checkout button colour Draft 3 variants\nAPI key eptk_ab12... created today\nSign in as admin@demo.com"
    )
    assert ocr.findings(text, [NEEDLE, "Demo1234!x"]) == []


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Header eptk_shown_in_full_here", "key-shaped"),
        ("eptk wholevalue", "key-shaped"),
        ("shown eyJ" + "abcdefghij" * 2, "token-shaped"),
        ("Live view Disconnected", "forbidden text 'disconnected'"),
        ("Open http://localhost:28401 in a browser", "forbidden text 'localhost'"),
        ("Something  went\nwrong", "forbidden text 'something went wrong'"),
    ],
)
def test_shapes_and_forbidden_phrases_are_found(text, expected):
    found = ocr.findings(text, [NEEDLE])
    assert any(expected in what for _, what in found), found


@pytest.mark.parametrize(
    "text",
    [
        "Header eptk_3ny\u0431vjeep4w47pu723gccx5m",  # Vision read the 6 as Cyrillic be (measured)
        "Header eptk_gbj fqu9uSxkyemgms fms jbes",  # tesseract split the value with spaces (measured)
    ],
)
def test_a_key_is_found_through_measured_misreadings(text):
    assert [g for g, _ in ocr.findings(text, [NEEDLE])] == ["7"]


@pytest.mark.parametrize(
    "text",
    [
        "Changes we kept keep every flag in step",  # 'kept keep' holds e-p-t-k only across a space
        "They just add a variant and the rest follows without any extra work at all",
        "API key eptk_ab12... created today",
    ],
)
def test_ordinary_words_are_not_key_or_token_shaped(text):
    assert ocr.findings(text, [NEEDLE]) == []


def test_the_key_list_display_is_not_key_shaped():
    for shown in ("API key eptk_ab12... created", "eptk_ab12…", "eptk ab12 ..."):
        assert ocr.findings(shown, [NEEDLE]) == [], shown


def test_forbidden_text_belongs_to_u4_and_credentials_to_7():
    gates = {g for g, _ in ocr.findings(f"Disconnected {NEEDLE}", [NEEDLE])}
    assert gates == {"7", "U4"}


def test_a_long_needle_is_matched_in_pieces():
    long_needle = "eyJ" + "A1b2C3d4E5f6G7h8I9j0" * 5
    pieces = ocr.chunks(ocr.normalise(long_needle))
    assert len(pieces) > 1 and all(len(p) == ocr.CHUNK for p in pieces)
    # 30 characters of it on screen is enough
    assert (
        ocr.needle_similarity(
            ocr.normalise(long_needle), ocr.normalise(long_needle[10:40])
        )
        >= 0.99
    )


# --- Engines that fail never pass --------------------------------------------------------------


class FakeEngine(ocr.Engine):
    def __init__(self, name, answer):
        super().__init__(name=name, binary="fake")
        self.answer = answer

    def read(self, paths):
        return self.answer(paths)


def test_a_crashed_engine_stops_the_scan():
    def crash(paths):
        raise ocr.OcrError("tesseract exited 1 on frame-000123.png")

    with pytest.raises(Refused) as caught:
        ocr._read(FakeEngine("tesseract", crash), [Path("a.png")], "7")
    assert (
        "OCR failed (tesseract: tesseract exited 1 on frame-000123.png); the scan is not counted"
        in str(caught.value)
    )


def test_an_engine_that_skips_a_frame_stops_the_scan():
    with pytest.raises(
        Refused, match="vision read 1 of 2 frames; the scan is not counted"
    ):
        ocr._read(
            FakeEngine("vision", lambda paths: {paths[0]: "text"}),
            [Path("a.png"), Path("b.png")],
            "7",
        )


def test_the_self_test_refuses_an_engine_that_reads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(encode, "png_to_h264_and_back", lambda png, work: png)
    blind = FakeEngine("tesseract", lambda paths: dict.fromkeys(paths, ""))
    with pytest.raises(Refused) as caught:
        ocr.self_test(
            [blind], lambda needle, key, path: path.write_bytes(b"png"), tmp_path
        )
    text = str(caught.value)
    assert (
        "OCR self-test: tesseract read the canary at 0.00 (needs 0.70); scan not run"
        in text
    )
    assert "did not see the key-shaped canary; scan not run" in text


def test_the_self_test_passes_an_engine_that_reads_the_canary(tmp_path, monkeypatch):
    monkeypatch.setattr(encode, "png_to_h264_and_back", lambda png, work: png)
    drawn = {}

    def draw(needle, key, path):
        drawn["text"] = f"Shown once: {needle}\nHeader {key}"
        path.write_bytes(b"png")

    reader = FakeEngine("vision", lambda paths: dict.fromkeys(paths, drawn["text"]))
    assert ocr.self_test([reader], draw, tmp_path) == {"vision": 1.0}


def test_no_engine_at_all_is_a_refusal(tmp_path):
    with pytest.raises(Refused, match="no OCR engine"):
        ocr.self_test([], lambda *a: None, tmp_path)


def test_an_empty_needle_list_is_refused_before_decoding(tmp_path):
    with pytest.raises(Refused, match="0 needles: refusing to scan"):
        ocr.scan(tmp_path / "v.mp4", 1710, [], [], tmp_path, lambda: None)


# --- Gate 5: the burned-in captions ---------------------------------------------------------------


CUES = [
    OutputCue(
        number=1,
        start_frame=96,
        end_frame=239,
        lines=("One command starts the whole stack.",),
    ),
    OutputCue(
        number=2,
        start_frame=245,
        end_frame=388,
        lines=("Open the dashboard in your browser.",),
    ),
]


def test_caption_samples_are_inside_each_cue_and_after_it():
    samples = ocr.caption_samples(CUES)
    assert samples == [
        (105, 1, "start"),
        (229, 1, "end"),
        (316, 1, "after"),
        (254, 2, "start"),
        (378, 2, "end"),
    ]


def test_captions_read_back_pass():
    read = {
        105: ["One command starts the whole stack."],
        229: ["One command starts the whole stack."],
    }
    read.update(
        {
            316: ["Open the dashboard in your browser."],
            254: ["Open the dashboard in your browser."],
        }
    )
    read[378] = ["Open the dashbcard in your browser."]
    problems, numbers = ocr.caption_problems(CUES, ocr.caption_samples(CUES), read)
    assert problems == [] and numbers["confirmed"] == 2


def test_a_missing_caption_layer_is_refused():
    read = {frame: [""] for frame, _, _ in ocr.caption_samples(CUES)}
    problems, numbers = ocr.caption_problems(CUES, ocr.caption_samples(CUES), read)
    assert "cue 1 not in the frame at 3.500 s (similarity 0.00)" in problems
    assert numbers["confirmed"] == 0


def test_a_caption_that_stays_too_long_is_refused():
    read = {
        frame: ["One command starts the whole stack."]
        for frame, _, _ in ocr.caption_samples(CUES)
    }
    problems, _ = ocr.caption_problems(CUES, ocr.caption_samples(CUES), read)
    assert (
        "cue 1 still in the frame at 10.533 s, during cue 2 (similarity 1.00)"
        in problems
    )
    assert any(p.startswith("cue 2 not in the frame") for p in problems)


def test_contract_fps_is_the_one_the_samples_assume():
    assert ocr.CAPTION_SAMPLE_FRAMES == round(0.3 * contract.FPS)
