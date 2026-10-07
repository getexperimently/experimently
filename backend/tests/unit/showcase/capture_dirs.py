"""Synthetic capture directories for the showcase unit tests (#1066).

The frames are JPEG headers with no image data: ``contract.jpeg_size`` reads
only the frame header, so the size checks run without an image library. The
tests that need real pixels (the render's encode and OCR) run on the
developer's machine through ``showcase.render.synthetic``, not here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from showcase import contract

NEEDLES = ["ZEBRA-VALUE-987-ALPHA", "QUOKKA-VALUE-123-BRAVO"]

#: Ten captions, each up long enough to read, 0.2 s apart, covering 50 s.
CUE_TEXTS = [
    "One command starts the whole stack on your machine.",
    "Open the dashboard in your browser.",
    "Sign in with the demo admin account.",
    "Your experiments, each with its status at a glance.",
    "Results give the lift and the p-value.",
    "And a recommended winner when there is one.",
    "Flags roll out in stages.",
    "With a safety check alongside.",
    "Every change is logged.",
    "That is the whole loop.",
]
CUE_MS = 4780
CUE_GAP_MS = 200
DURATION_MS = 50_000


def jpeg_bytes(width: int, height: int, *, progressive: bool = False) -> bytes:
    """A JPEG start, an APP0 segment and a frame header: enough for jpeg_size."""
    app0 = (
        b"\xff\xe0"
        + (16).to_bytes(2, "big")
        + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    sof = (
        (b"\xff\xc2" if progressive else b"\xff\xc0")
        + (17).to_bytes(2, "big")
        + b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def default_cues() -> List[Dict[str, Any]]:
    cues = []
    for index, text in enumerate(CUE_TEXTS):
        start = CUE_GAP_MS + index * (CUE_MS + CUE_GAP_MS)
        cues.append(
            {
                "start_ms": start,
                "end_ms": start + CUE_MS,
                "text": text,
                "focus": {"x": 100, "y": 100, "w": 400, "h": 60} if index % 2 else None,
            }
        )
    return cues


def default_manifest() -> Dict[str, Any]:
    return {
        "ref": "v0.26.3",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "next_version": "16.3.5",
        "lock_next_version": "16.3.8",
        "profile": "core",
        "viewport": {
            "width": contract.PAGE_W,
            "height": contract.PAGE_H,
            "device_scale_factor": 1,
        },
        "zoom": 4 / 3,
        "page_h": contract.PAGE_H,
        "band_h": contract.BAND_H,
        "gates": {
            name: {"ok": True, "numbers": {"checks": 1}}
            for name in contract.REQUIRED_CAPTURE_GATES
        },
    }


def make_capture(
    root: Path,
    *,
    cues: Optional[List[Dict[str, Any]]] = None,
    duration_ms: int = DURATION_MS,
    frame_times: Optional[List[int]] = None,
    frame_size: tuple = (contract.PAGE_W, contract.PAGE_H),
    manifest: Optional[Dict[str, Any]] = None,
    needles: Optional[List[str]] = None,
) -> Path:
    """Write a capture directory that validates, unless an argument plants a defect."""
    root.mkdir(parents=True, exist_ok=True)
    frames_dir = root / "frames"
    frames_dir.mkdir(exist_ok=True)
    times = (
        frame_times if frame_times is not None else [0, 10_000, 20_000, 30_000, 40_000]
    )
    lines = []
    for number, t_ms in enumerate(times, start=1):
        name = f"{number:06d}.jpg"
        (frames_dir / name).write_bytes(jpeg_bytes(*frame_size))
        lines.append(json.dumps({"file": name, "t_ms": t_ms}))
    (root / "frames.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sheet = {
        "slug": "01-getting-started",
        "title": "Get started",
        "version": "v0.26.3",
        "duration_ms": duration_ms,
        "cues": cues if cues is not None else default_cues(),
    }
    (root / "cues.json").write_text(json.dumps(sheet, indent=2), encoding="utf-8")
    needles_path = root / "needles.txt"
    needles_path.write_text(
        "\n".join(needles if needles is not None else NEEDLES) + "\n", encoding="utf-8"
    )
    os.chmod(needles_path, 0o600)
    (root / "manifest.json").write_text(
        json.dumps(manifest or default_manifest(), indent=2), encoding="utf-8"
    )
    return root


def edit_json(path: Path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")
