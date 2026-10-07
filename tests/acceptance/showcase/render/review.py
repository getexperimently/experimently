"""The review page: what a person watches and checks before a video is approved.

One static HTML file beside its contact-sheet images, readable offline:

* the video itself (``../<name>.mp4``), with the WebVTT file as a track;
* the sha256 of the MP4 and of the WebVTT file (an approval names these);
* the five-item watch checklist;
* a contact sheet: one frame per cue, 0.5 s in, with its time, its text, its
  reading speed, and an empty column for the source that makes the caption
  true (U2 and U6 are checked here, by a person);
* every render gate's numbers and every capture gate's numbers.

It is built only after every gate passed, from frames of the finished video,
and the render refuses to write it if it holds any needle.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from showcase import contract
from showcase.render import templates
from showcase.render.ocr import normalise

CHECKLIST = (
    "Watch it once full-screen, at normal speed, with the sound off.",
    "Watch it once on a phone. Every caption and every number should be readable.",
    "Check that the demo data reads as made up: no real person, company or address.",
    f"Open the end card's address ({templates.SITE}) and check that it is the right site.",
    "Check each caption's claim against the product, and each number against the page it is shown over.",
)

#: How long into each cue its contact-sheet frame is taken.
CONTACT_OFFSET_FRAMES = contract.FPS // 2


@dataclass(frozen=True)
class ContactFrame:
    number: int
    start_ms: int
    end_ms: int
    text: str
    image: str
    focus: Optional[contract.Focus]

    @property
    def seconds(self) -> float:
        return (self.end_ms - self.start_ms) / 1000

    @property
    def chars_per_second(self) -> float:
        return len(self.text) / self.seconds if self.seconds else 0.0


def _numbers(value: Any) -> str:
    return html.escape(json.dumps(value, sort_keys=True, ensure_ascii=False))


def _gate_rows(gates: Mapping[str, Mapping[str, Any]]) -> str:
    return "".join(
        f"<tr><td>{html.escape(name)}</td><td>{'ok' if entry.get('ok') else 'NOT OK'}</td>"
        f"<td><code>{_numbers(entry.get('numbers', {}))}</code></td></tr>"
        for name, entry in gates.items()
    )


def review_html(
    *,
    sheet: contract.CueSheet,
    manifest: contract.Manifest,
    names: Mapping[str, str],
    mp4_sha256: str,
    vtt_sha256: str,
    contact: List[ContactFrame],
    render_gates: Mapping[str, Mapping[str, Any]],
) -> str:
    title = f"{sheet.title} ({sheet.slug}) review"
    facts = [
        ("Video", names["mp4"]),
        ("Captions", names["vtt"]),
        ("MP4 sha256", mp4_sha256),
        ("WebVTT sha256", vtt_sha256),
        ("Version shown", sheet.version),
        ("Ref", manifest.ref),
        ("Commit", manifest.commit),
        ("Profile", manifest.profile),
        (
            "next (installed / lockfile)",
            f"{manifest.next_version} / {manifest.lock_next_version}",
        ),
        ("Zoom", f"{manifest.zoom:g}"),
        (
            "Length",
            f"{contract.ms_for_frames(contract.video_frames(sheet.duration_ms)) / 1000:.3f} s",
        ),
    ]
    fact_rows = "".join(
        f"<tr><th>{html.escape(k)}</th><td><code>{html.escape(v)}</code></td></tr>"
        for k, v in facts
    )
    checklist = "".join(
        f'<li><label><input type="checkbox"> {html.escape(item)}</label></li>'
        for item in CHECKLIST
    )
    sheet_rows = "".join(
        "<tr>"
        f"<td>{frame.number}</td>"
        f'<td><img src="{html.escape(frame.image)}" alt="cue {frame.number}" width="480" height="270"></td>'
        f"<td>{frame.start_ms / 1000:.3f}-{frame.end_ms / 1000:.3f} s<br>{frame.seconds:.2f} s, "
        f"{frame.chars_per_second:.1f} characters a second</td>"
        f"<td>{html.escape(frame.text)}</td>"
        f"<td>{'-' if frame.focus is None else html.escape(f'{frame.focus.x:g},{frame.focus.y:g} {frame.focus.w:g}x{frame.focus.h:g}')}</td>"
        "<td></td>"
        "</tr>"
        for frame in contact
    )
    extra = {k: v for k, v in manifest.raw.items() if k not in contract.MANIFEST_KEYS}
    extra_block = (
        f"<h2>Capture measurements</h2><pre>{_numbers(extra)}</pre>" if extra else ""
    )
    css = (
        "body{font-family:-apple-system,system-ui,sans-serif;margin:24px auto;max-width:1100px;padding:0 16px;"
        "color:#0F172A;background:#FFFFFF}"
        "video{width:100%;max-width:1100px;background:#000}"
        "table{border-collapse:collapse;width:100%;margin:12px 0 28px}"
        "th,td{border-bottom:1px solid #E2E8F0;padding:6px 8px;text-align:left;vertical-align:top;font-size:14px}"
        "code,pre{font-family:ui-monospace,Menlo,monospace;font-size:12px;white-space:pre-wrap;word-break:break-all}"
        "img{display:block;max-width:100%;height:auto}"
        "li{margin:6px 0}"
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{css}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f'<video controls preload="metadata" src="../{html.escape(names["mp4"])}">'
        f'<track kind="captions" srclang="en" label="English" src="../{html.escape(names["vtt"])}"></video>'
        f"<table>{fact_rows}</table>"
        f"<h2>Before approving</h2><ol>{checklist}</ol>"
        "<h2>Contact sheet</h2>"
        "<table><tr><th>#</th><th>Frame (0.5 s in)</th><th>Time</th><th>Caption</th><th>Focus</th>"
        f"<th>Source (doc line or code)</th></tr>{sheet_rows}</table>"
        f"<h2>Render gates</h2><table><tr><th>Gate</th><th></th><th>Numbers</th></tr>{_gate_rows(render_gates)}</table>"
        f"<h2>Capture gates</h2><table><tr><th>Gate</th><th></th><th>Numbers</th></tr>{_gate_rows(manifest.gates)}</table>"
        f"{extra_block}"
        "</body></html>\n"
    )


def holds_needle(text: str, needles: List[str]) -> List[int]:
    """Which needles (by number) a text holds, as written or with its separators dropped."""
    folded = normalise(text)
    return [
        number
        for number, needle in enumerate(needles, start=1)
        if needle in text or (normalise(needle) and normalise(needle) in folded)
    ]


def contact_frames(
    cues, focus: Dict[int, Optional[contract.Focus]]
) -> List[Dict[str, Any]]:
    """Which output frame each cue's contact-sheet image comes from."""
    return [
        {
            "number": cue.number,
            "frame": cue.start_frame + CONTACT_OFFSET_FRAMES,
            "focus": focus.get(cue.number),
        }
        for cue in cues
    ]
