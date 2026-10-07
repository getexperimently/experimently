"""``scripts/docs_journeys_report.py recordings``: the presence check that makes
T138's "recordings R1-R8 in that run's artifacts" mechanical.

``docs-journeys.yml`` runs it last in every run that records. It fails the run
unless every walkthrough R1-R8 has a recording that is not pending, and each
such recording's ``recordings/<name>.webm`` is in the run directory, not
empty, a 1280x720 WebM whose header gives a length above zero and within its
``max_seconds``; a pending one must not be there, nor any file that is no
walkthrough's. Each check fires here on its own planted defect, against WebM
headers built the way Chromium's recorder writes them (EBML header, a segment
whose Info holds the timestamp scale and a float Duration, then Tracks).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import Dict, Optional

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import docs_journeys_report as check

NAMES = {
    "R1-quick-start": 180,
    "R2-docker-guide": 90,
    "R3-experiment-wizard": 120,
    "R4-power-analysis": 60,
    "R5-reading-results": 60,
    "R6-feature-flag": 120,
    "R7-docs-site": 60,
    "R8-onboarding": 90,
}


def _registry_text(drop: str = "", pending: Optional[str] = None) -> str:
    tables = []
    for name, limit in NAMES.items():
        if name == drop:
            continue
        lines = [
            f"[{name}]",
            f'walkthrough = "{name.split("-")[0]}"',
            'guide = "x.md"',
            f"max_seconds = {limit}",
            'shows = "x"',
        ]
        if name == pending:
            lines.append('pending = "later"')
        tables.append("\n".join(lines))
    tables.append(
        "\n".join(
            [
                "[R5-srm-warning]",
                'walkthrough = "R5"',
                'guide = "guides/user-guide.md"',
                "max_seconds = 60",
                'shows = "x"',
                'pending = "the dataset lands later"',
            ]
        )
    )
    return "\n\n".join(tables) + "\n"


# ---------------------------------------------------------------------------
# A WebM header, as Chromium's recorder writes one
# ---------------------------------------------------------------------------
def _id(value: int) -> bytes:
    length = (value.bit_length() + 7) // 8
    return value.to_bytes(length, "big")


def _size(n: int) -> bytes:
    return bytes([0x01]) + n.to_bytes(7, "big")  # an 8-byte size, as libwebm writes


def _element(element: int, payload: bytes) -> bytes:
    return _id(element) + _size(len(payload)) + payload


def webm(
    seconds: float = 4.2,
    width: int = 1280,
    height: int = 720,
    doc_type: bytes = b"webm",
    scale: int = 1_000_000,
    duration: Optional[bytes] = None,
    unknown_segment: bool = False,
) -> bytes:
    header = _element(
        0x1A45DFA3, _element(0x4286, b"\x01") + _element(0x4282, doc_type)
    )
    if duration is None:
        duration = struct.pack(">d", seconds * 1e9 / scale)
    info = _element(
        0x1549A966,
        _element(0x2AD7B1, scale.to_bytes(3, "big")) + _element(0x4489, duration),
    )
    video = _element(0xE0, _element(0xB0, _id(width)) + _element(0xBA, _id(height)))
    tracks = _element(0x1654AE6B, _element(0xAE, _element(0xD7, b"\x01") + video))
    cluster = _element(0x1F43B675, _element(0xE7, b"\x00") + b"\xa3\x81\x00")
    body = _element(0x114D9B74, b"") + info + tracks + cluster
    if unknown_segment:
        return header + _id(0x18538067) + b"\x01\xff\xff\xff\xff\xff\xff\xff" + body
    return header + _element(0x18538067, body)


def test_the_header_reader_reads_what_it_is_given():
    assert check.webm_facts(webm(4.2)) == pytest.approx((4.2, 1280, 720))
    assert check.webm_facts(webm(2.0, scale=1_000)) == pytest.approx((2.0, 1280, 720))
    assert check.webm_facts(webm(7.5, unknown_segment=True))[0] == pytest.approx(7.5)
    four = check.webm_facts(webm(duration=struct.pack(">f", 2480.0)))
    assert four == pytest.approx((2.48, 1280, 720))


@pytest.mark.parametrize(
    "data, fragment",
    [
        pytest.param(b"not a video", "no EBML header", id="not-ebml"),
        pytest.param(webm(doc_type=b"matroska"), "not a WebM", id="matroska"),
        pytest.param(webm()[:60], "cut short", id="cut-short"),
        pytest.param(webm(duration=b"\x00\x01"), "not a float", id="bad-duration"),
    ],
)
def test_the_header_reader_refuses_what_is_not_a_webm(data, fragment):
    with pytest.raises(check.WebmError, match=fragment):
        check.webm_facts(data)


# ---------------------------------------------------------------------------
# The check, green and then each planted defect
# ---------------------------------------------------------------------------
def _run(tmp_path: Path, files: Dict[str, bytes], registry: str) -> tuple:
    run = tmp_path / "run"
    (run / "recordings").mkdir(parents=True)
    for name, data in files.items():
        (run / "recordings" / name).write_bytes(data)
    path = tmp_path / "recordings.toml"
    path.write_text(registry, encoding="utf-8")
    return run, path


def _all() -> Dict[str, bytes]:
    return {f"{name}.webm": webm(5.0) for name in NAMES}


def _main(capsys, run: Path, registry: Path) -> tuple:
    status = check.main(
        ["recordings", "--run-dir", str(run), "--registry", str(registry)], env={}
    )
    return status, capsys.readouterr().out


def test_every_walkthrough_present_passes_and_says_what_it_read(tmp_path, capsys):
    run, registry = _run(tmp_path, _all(), _registry_text())
    status, out = _main(capsys, run, registry)
    assert status == 0, out
    assert "R4-power-analysis: " in out and "5.0 s of at most 60 s, 1280x720" in out
    assert "R5-srm-warning: pending" in out
    assert "walkthroughs: 8 required, 1 pending, 0 problem(s)" in out
    assert "::error" not in out


def _files_without(name: str) -> Dict[str, bytes]:
    files = _all()
    del files[f"{name}.webm"]
    return files


PLANTS = [
    pytest.param(
        _files_without("R4-power-analysis"),
        _registry_text(),
        "R4-power-analysis is missing from recordings/",
        id="a-recording-missing",
    ),
    pytest.param(
        {**_all(), "R2-docker-guide.webm": b""},
        _registry_text(),
        "R2-docker-guide is empty",
        id="a-recording-empty",
    ),
    pytest.param(
        {**_all(), "R7-docs-site.webm": webm(61.0)},
        _registry_text(),
        "R7-docs-site is 61.0 s, longer than 60 s",
        id="a-recording-too-long",
    ),
    pytest.param(
        {**_all(), "R3-experiment-wizard.webm": webm(5.0, 800, 450)},
        _registry_text(),
        "R3-experiment-wizard is 800x450, not 1280x720",
        id="a-recording-at-another-size",
    ),
    pytest.param(
        {**_all(), "R1-quick-start.webm": webm(0.0)},
        _registry_text(),
        "R1-quick-start has no length",
        id="a-recording-of-no-length",
    ),
    pytest.param(
        {**_all(), "R6-feature-flag.webm": b"PK\x03\x04 a zip"},
        _registry_text(),
        "R6-feature-flag is not a WebM recording this check can read",
        id="a-recording-that-is-not-webm",
    ),
    pytest.param(
        {**_all(), "R5-srm-warning.webm": webm(5.0)},
        _registry_text(),
        "R5-srm-warning is recorded, but recordings.toml marks it pending",
        id="a-pending-recording-made",
    ),
    pytest.param(
        {**_all(), "R9-extra.webm": webm(5.0)},
        _registry_text(),
        "recordings/R9-extra.webm is not a walkthrough of recordings.toml",
        id="a-stray-recording",
    ),
    pytest.param(
        _files_without("R4-power-analysis"),
        _registry_text(drop="R4-power-analysis"),
        "walkthrough R4 has no recording in recordings.toml that is not pending",
        id="a-walkthrough-dropped-from-the-registry",
    ),
    pytest.param(
        _files_without("R8-onboarding"),
        _registry_text(pending="R8-onboarding"),
        "walkthrough R8 has no recording in recordings.toml that is not pending",
        id="a-walkthrough-marked-pending",
    ),
]


@pytest.mark.parametrize("files, registry_text, fragment", PLANTS)
def test_each_planted_defect_fails_the_check(
    tmp_path, capsys, files, registry_text, fragment
):
    run, registry = _run(tmp_path, files, registry_text)
    status, out = _main(capsys, run, registry)
    assert status == 1
    assert f"::error title=Docs journeys recordings::{fragment}" in out


def test_a_run_with_no_recordings_directory_fails(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    registry = tmp_path / "recordings.toml"
    registry.write_text(_registry_text(), encoding="utf-8")
    status, out = _main(capsys, run, registry)
    assert status == 1
    assert out.count("is missing from recordings/") == 8


def test_an_unreadable_registry_fails(tmp_path, capsys):
    run, registry = _run(tmp_path, _all(), "[R1-quick-start\n")
    status, out = _main(capsys, run, registry)
    assert status == 1 and "::error title=Docs journeys recordings::" in out


def test_the_check_prints_names_and_numbers_only(tmp_path, capsys):
    """Public text: the log names walkthroughs and counts, never a path outside."""
    files = _files_without("R4-power-analysis")
    run, registry = _run(tmp_path, files, _registry_text())
    _, out = _main(capsys, run, registry)
    assert str(tmp_path) not in out
