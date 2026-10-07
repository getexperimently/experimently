"""Made-up capture directories, to prove each render gate refuses what it should.

``python -m showcase.render.synthetic <dir> [options]`` writes a capture
directory that passes every gate: dashboard-like frames drawn by Chromium
(the page changes every 2.5 s, like a walkthrough), ten captions covering the
recording, two made-up needles, and a manifest with every capture gate ok.
Each option plants one defect instead:

``--plant-needle N``   draw needle 1 in frame N (gate 7 must refuse)
``--plant-part N:K``   draw only the first K characters of needle 1 in frame N
                       (gate 7, for K of 12 or more)
``--plant-faint N``    draw needle 1 in frame N in the OCR canary's faint style,
                       ``templates.FAINT_CANARY_PX`` px ``FAINT_CANARY_COLOUR`` (gate 7)
``--plant-key N``      draw a key-shaped value in frame N (gate 7)
``--plant-text N:T``   draw the text T in frame N (U4, for a forbidden phrase)
``--black N``          make frame N an all-black page (gate 11)
``--frame-size WxH``   draw every frame at another size (gate 3)

The needles are random for each directory and are never a real credential.
Nothing here starts a stack, and its output belongs in a scratch directory.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from showcase import contract
from showcase.render import templates
from showcase.render.chromium import Chromium

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
DURATION_MS = 50_000
FRAME_EVERY_MS = 2500
ROWS = [
    ("Homepage hero copy test", "Active", "2 variants", "12,408 users"),
    ("Checkout button colour", "Draft", "3 variants", "0 users"),
    ("Pricing page layout", "Completed", "2 variants", "48,120 users"),
    ("Onboarding email timing", "Paused", "2 variants", "3,977 users"),
]


def _cues() -> List[Dict[str, object]]:
    cue_ms, gap_ms = 4780, 200
    return [
        {
            "start_ms": gap_ms + i * (cue_ms + gap_ms),
            "end_ms": gap_ms + i * (cue_ms + gap_ms) + cue_ms,
            "text": text,
            "focus": {"x": 120, "y": 180 + 60 * (i % 4), "w": 1200, "h": 56},
        }
        for i, text in enumerate(CUE_TEXTS)
    ]


def page_html(
    step: int, extra: Optional[str] = None, black: bool = False, faint: bool = False
) -> str:
    if black:
        return (
            "<!doctype html><html><body style='margin:0;background:#000'></body></html>"
        )
    rows = "".join(
        f"<tr class='{'on' if i == step % len(ROWS) else ''}'>"
        + "".join(f"<td>{html.escape(c)}</td>" for c in row)
        + "</tr>"
        for i, row in enumerate(ROWS)
    )
    style = (
        f" style='font-family:inherit;font-size:{templates.FAINT_CANARY_PX}px;"
        f"color:{templates.FAINT_CANARY_COLOUR}'"
        if faint
        else ""
    )
    planted = f"<div class='planted'{style}>{html.escape(extra)}</div>" if extra else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body{margin:0;font-family:-apple-system,system-ui,sans-serif;color:#0F172A;background:#F8FAFC}"
        "header{height:84px;background:#FFFFFF;border-bottom:1px solid #E2E8F0;display:flex;align-items:center;"
        "padding:0 48px;gap:40px;font-size:20px}"
        "header b{font-size:24px}main{padding:40px 64px}h1{font-size:34px;margin:0 0 8px}"
        ".sub{color:#475569;font-size:20px;margin-bottom:28px}"
        "table{border-collapse:collapse;width:100%;background:#fff;font-size:20px}"
        "td{padding:16px 20px;border-bottom:1px solid #E2E8F0}tr.on td{background:#EFF6FF}"
        ".key{margin-top:28px;font-size:18px;color:#334155}"
        ".planted{margin-top:24px;font-family:ui-monospace,Menlo,monospace;font-size:18px}"
        "</style></head><body>"
        "<header><b>Experimently</b><span>Experiments</span><span>Feature Flags</span><span>Admin</span></header>"
        f"<main><h1>Experiments</h1><div class='sub'>Step {step + 1}: four experiments in the demo data</div>"
        f"<table>{rows}</table><div class='key'>API key eptk_ab12… created today</div>{planted}</main>"
        "</body></html>"
    )


def manifest() -> Dict[str, object]:
    return {
        "ref": "v0.26.3",
        "commit": "0" * 40,
        "next_version": "16.3.5",
        "lock_next_version": "16.3.8",
        "profile": "core",
        "viewport": dict(contract.VIEWPORT),
        "zoom": 4 / 3,
        "page_h": contract.PAGE_H,
        "band_h": contract.BAND_H,
        "gates": {
            name: {"ok": True, "numbers": {"synthetic": True}}
            for name in contract.REQUIRED_CAPTURE_GATES
        },
        "synthetic": True,
    }


def write(
    root: Path,
    *,
    plant_needle: Optional[int] = None,
    plant_part: Optional[Tuple[int, int]] = None,
    plant_faint: Optional[int] = None,
    plant_key: Optional[int] = None,
    plant_text: Optional[Dict[int, str]] = None,
    black: Optional[int] = None,
    frame_size: tuple = (contract.PAGE_W, contract.PAGE_H),
) -> Path:
    root.mkdir(parents=True, exist_ok=False)
    frames_dir = root / "frames"
    frames_dir.mkdir()
    needles = [
        "VALUE-" + secrets.token_hex(8).upper(),
        "VALUE-" + secrets.token_hex(8).upper(),
    ]
    key_like = "eptk_" + secrets.token_hex(12)
    lines = []
    with Chromium() as browser:
        for index, t_ms in enumerate(range(0, DURATION_MS, FRAME_EVERY_MS)):
            extra = None
            if index == plant_needle:
                extra = f"One-time password: {needles[0]}"
            elif plant_part and index == plant_part[0]:
                extra = f"Device code {needles[0][: plant_part[1]]}"
            elif index == plant_faint:
                extra = f"Last edited by {needles[0]}"
            elif index == plant_key:
                extra = f"X-API-Key: {key_like}"
            elif plant_text and index in plant_text:
                extra = plant_text[index]
            name = f"{index + 1:06d}.jpg"
            browser.page_jpeg(
                page_html(
                    index, extra, black=index == black, faint=index == plant_faint
                ),
                frames_dir / name,
                width=frame_size[0],
                height=frame_size[1],
            )
            lines.append(json.dumps({"file": name, "t_ms": t_ms}))
    (root / "frames.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sheet = {
        "slug": "01-synthetic",
        "title": "A synthetic walkthrough",
        "version": "v0.26.3",
        "duration_ms": DURATION_MS,
        "cues": _cues(),
    }
    (root / "cues.json").write_text(
        json.dumps(sheet, indent=2) + "\n", encoding="utf-8"
    )
    needles_path = root / "needles.txt"
    fd = os.open(needles_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(needles) + "\n")
    (root / "manifest.json").write_text(
        json.dumps(manifest(), indent=2) + "\n", encoding="utf-8"
    )
    return root


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m showcase.render.synthetic", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("dir", type=Path)
    parser.add_argument("--plant-needle", type=int)
    parser.add_argument("--plant-part", metavar="N:K")
    parser.add_argument("--plant-faint", type=int)
    parser.add_argument("--plant-key", type=int)
    parser.add_argument("--plant-text", action="append", default=[], metavar="N:TEXT")
    parser.add_argument("--black", type=int)
    parser.add_argument("--frame-size", default=f"{contract.PAGE_W}x{contract.PAGE_H}")
    args = parser.parse_args(argv)
    width, height = (int(v) for v in args.frame_size.split("x"))
    texts = {
        int(item.split(":", 1)[0]): item.split(":", 1)[1] for item in args.plant_text
    }
    root = write(
        args.dir,
        plant_needle=args.plant_needle,
        plant_part=(
            tuple(int(v) for v in args.plant_part.split(":"))
            if args.plant_part
            else None
        ),
        plant_faint=args.plant_faint,
        plant_key=args.plant_key,
        plant_text=texts,
        black=args.black,
        frame_size=(width, height),
    )
    sys.stdout.write(f"{root}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
