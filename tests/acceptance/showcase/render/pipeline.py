"""Render one capture directory into the finished video, its captions and its review page.

The order matters, and each step is a gate that refuses rather than warns:

1. ``disk``: at least ``contract.DISK_FLOOR_BYTES`` free where the work and
   the output go (checked again before the OCR decode).
2. ``capture``: ``contract.validate_capture_dir`` accepts the directory, which
   includes gate 3 (every frame is a real 1920x940 page, never one the encode
   would scale up) and every capture gate ok.
3. ``7`` (text): no caption or card text holds a needle.
4. ``17``: every caption, as Chromium draws it, is at least 36 px, on at
   most two lines, none wider than the band allows.
5. ``7`` (self-test): every OCR engine reads a made-up canary back.
6. The encode, to ``<out>/<slug>.mp4.partial``.
7. ``1`` and ``2``: length, format, faststart. ``11``: no black page outside
   the cards. ``4``: the WebVTT file, parsed back strictly, matches the cue
   sheet. ``5``: every burned-in caption is read back from the frames.
   ``7`` and ``U4``: OCR of every distinct frame of the finished video.
8. The review page, the sha256-named files, and only then the renames.

needles.txt is deleted on every path out of ``render``, pass or refuse, once
the render has started; its values live only in memory, and only until the
review page has been checked against them. A refusal deletes everything this
render made: the ``.partial`` files, the review page and the work directory
(an output directory it had to create is left, empty).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from showcase import contract
from showcase.render import encode, ocr, probe, review, templates, timeline, vtt
from showcase.render.chromium import Chromium, caption_problems
from showcase.render.gates import GateLog, Refused


@dataclass(frozen=True)
class RenderResult:
    mp4: Path
    vtt: Path
    review: Path
    mp4_sha256: str
    vtt_sha256: str
    gates: Dict[str, Dict[str, Any]]


def git_checkout_above(path: Path) -> Optional[Path]:
    """The git checkout a path is inside, if any (a ``.git`` in it or an ancestor)."""
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _existing(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path


def check_disk(paths: Dict[str, Path], floor: int) -> Dict[str, int]:
    """Free bytes where each labelled path lives; refuse below the floor."""
    readings = {
        label: shutil.disk_usage(_existing(path)).free for label, path in paths.items()
    }
    low = [
        f"{free / 1024**3:.2f} GiB free for the {label} directory; the floor is {floor / 1024**3:.2f} GiB"
        for label, free in readings.items()
        if free < floor
    ]
    if low:
        raise Refused("disk", low)
    return readings


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _remove(path: Path, *, allowed: Iterable[Path]) -> None:
    """Delete a file or tree, only if it is one of the paths this render made."""
    if path not in list(allowed):
        raise RuntimeError(f"refusing to delete {path}: not a path this render made")
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _place(partial: Path, final: Path) -> None:
    """Move a finished file into place; never over an existing one."""
    os.link(partial, final)
    partial.unlink()


def render(
    capture_dir: Path,
    out_dir: Path,
    work_dir: Optional[Path] = None,
    *,
    disk_floor: int = contract.DISK_FLOOR_BYTES,
) -> RenderResult:
    capture_dir = Path(capture_dir).resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    work = (
        Path(work_dir).expanduser().resolve()
        if work_dir
        else capture_dir.parent / "render"
    )
    floor = max(disk_floor, contract.DISK_FLOOR_BYTES)
    needles_path = capture_dir / "needles.txt"
    log = GateLog()
    owned: List[Path] = []
    made_work = False
    try:
        for label, path in (("output", out_dir), ("work", work)):
            checkout = git_checkout_above(path)
            if checkout is not None:
                raise Refused(
                    "paths",
                    f"the {label} directory {path} is inside the git checkout at {checkout}; "
                    "rendered videos and frames never go into a repository",
                )
        if work.exists() and any(work.iterdir()):
            raise Refused(
                "paths",
                f"the work directory {work} is not empty; give the render an empty or new one",
            )
        log.passed(
            "disk",
            {
                "free_bytes": check_disk({"output": out_dir, "work": work}, floor),
                "floor_bytes": floor,
            },
        )

        try:
            capture = contract.validate_capture_dir(capture_dir)
        except contract.CaptureRefused as exc:
            raise Refused("capture", exc.problems) from exc
        sheet = capture.sheet
        log.passed(
            "3",
            {
                "frames_checked": len(capture.frames),
                "frame_size": f"{contract.PAGE_W}x{contract.PAGE_H}",
            },
        )
        log.passed(
            "capture",
            {
                "cues": len(sheet.cues),
                "capture_gates": len(capture.manifest.gates),
                "needles": capture.needle_count,
            },
        )
        needles = contract.read_needles(needles_path)

        missing_tools = [
            tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None
        ]
        if missing_tools:
            raise Refused("tools", f"{', '.join(missing_tools)} not found on PATH")
        missing = probe.missing_filters()
        if missing:
            raise Refused("tools", f"this ffmpeg lacks the filters {missing}")

        out_dir.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)
        made_work = True
        partial_mp4 = out_dir / f"{sheet.slug}.mp4.partial"
        partial_vtt = out_dir / f"{sheet.slug}.vtt.partial"
        partial_review = out_dir / f"{sheet.slug}-review.partial"
        owned = [partial_mp4, partial_vtt, partial_review]
        for stale in owned:
            if stale.exists() or stale.is_symlink():
                _remove(stale, allowed=owned)

        out_cues = timeline.output_cues(sheet)
        recording_frames = sheet.capture_frames
        total_frames = contract.video_frames(sheet.duration_ms)

        text_hits = [
            f"cue {cue.number}'s caption holds needle {n} of {len(needles)}"
            for cue in out_cues
            for n in review.holds_needle(cue.text, needles)
        ] + [
            f"a card's text holds needle {n} of {len(needles)}"
            for text in templates.card_texts(sheet.title, sheet.version)
            for n in review.holds_needle(text, needles)
        ]
        if text_hits:
            raise Refused("7", text_hits)

        pngs = work / "png"
        pngs.mkdir()
        band_files = [pngs / f"cue-{cue.number:02d}.png" for cue in out_cues]
        with Chromium() as browser:
            problems: List[str] = []
            fonts = []
            for cue, path in zip(out_cues, band_files):
                metrics = browser.caption(cue.lines, path)
                fonts.append(metrics["font_px"])
                problems += caption_problems(cue.number, metrics, len(cue.lines))
            log.require(
                "17",
                problems,
                {
                    "captions": len(band_files),
                    "font_px": min(fonts, default=0),
                    "max_lines": contract.MAX_CUE_LINES,
                },
            )
            empty_band = pngs / "band-empty.png"
            browser.caption((), empty_band)
            title_png, end_png = pngs / "title.png", pngs / "end.png"
            browser.card(templates.title_card_html(sheet.title), title_png)
            browser.card(templates.end_card_html(sheet.version), end_png)
            try:
                found = ocr.engines(work)
            except ocr.OcrError as exc:
                raise Refused("7", f"{exc}; scan not run") from exc
            canary = ocr.self_test(found, ocr.canary_drawer(browser), work)

        seq_dir = work / "sequence"
        encode.build_sequences(
            capture.frames_dir,
            [frame.file for frame in capture.frames],
            timeline.frame_schedule(capture.frames, recording_frames),
            band_files,
            timeline.band_schedule(sheet.cues, recording_frames),
            empty_band,
            seq_dir,
        )
        argv = encode.ffmpeg_argv(
            title_png, seq_dir, end_png, recording_frames, partial_mp4
        )
        try:
            encode.encode(argv, work / "ffmpeg.log")
        except RuntimeError as exc:
            raise Refused("encode", str(exc)) from exc
        shutil.rmtree(seq_dir)

        try:
            info = probe.ffprobe(partial_mp4)
        except (RuntimeError, ValueError) as exc:
            raise Refused("2", f"ffprobe could not read the encode ({exc})") from exc
        problems, numbers = probe.length_problems(
            info, f"{sheet.slug}.mp4", total_frames
        )
        log.require("1", problems, numbers)
        problems, numbers = probe.format_problems(info, total_frames)
        boxes = probe.top_level_boxes(partial_mp4)
        problems += probe.faststart_problems(boxes)
        numbers["boxes"] = boxes
        log.require("2", problems, numbers)
        try:
            black = probe.blackdetect(partial_mp4)
        except RuntimeError as exc:
            raise Refused("11", str(exc)) from exc
        log.require(
            "11", probe.black_problems(black, total_frames), {"black_intervals": black}
        )

        vtt_text = vtt.write_vtt(out_cues)
        partial_vtt.write_text(vtt_text, encoding="utf-8")
        try:
            parsed = vtt.parse_vtt(partial_vtt.read_text(encoding="utf-8"))
            problems = vtt.check_vtt(parsed, out_cues, total_frames)
        except vtt.VttError as exc:
            parsed, problems = [], [str(exc)]
        log.require("4", problems, {"cues": len(parsed), "cue_sheet": len(out_cues)})

        log.passed("5", ocr.check_captions(partial_mp4, out_cues, found, work))
        scan_numbers, u4_numbers = ocr.scan(
            partial_mp4,
            total_frames,
            needles,
            found,
            work,
            lambda: log.passed(
                "disk-ocr",
                {"free_bytes": check_disk({"work": work}, floor), "floor_bytes": floor},
            ),
        )
        scan_numbers["engines"] = [engine.name for engine in found]
        scan_numbers["canary_similarity"] = canary
        log.passed("7", scan_numbers)
        log.passed("U4", u4_numbers)

        mp4_sha, vtt_sha = sha256(partial_mp4), sha256(partial_vtt)
        names = contract.output_names(sheet.slug, mp4_sha)
        finals = {key: out_dir / name for key, name in names.items()}
        existing = [str(p) for p in finals.values() if p.exists() or p.is_symlink()]
        if existing:
            raise Refused(
                "output",
                f"{existing} already exist; the render never overwrites a finished file",
            )

        partial_review.mkdir()
        focus = {number: cue.focus for number, cue in enumerate(sheet.cues, start=1)}
        wanted = review.contact_frames(out_cues, focus)
        images = encode.extract_frames(
            partial_mp4,
            [w["frame"] for w in wanted],
            work / "contact",
            scale="960:540",
            ext="jpg",
        )
        contact = []
        for want, cue, image in zip(wanted, out_cues, images):
            name = f"cue-{cue.number:02d}.jpg"
            shutil.move(str(image), partial_review / name)
            contact.append(
                review.ContactFrame(
                    number=cue.number,
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                    text=cue.text,
                    image=name,
                    focus=want["focus"],
                )
            )
        page = review.review_html(
            sheet=sheet,
            manifest=capture.manifest,
            names=names,
            mp4_sha256=mp4_sha,
            vtt_sha256=vtt_sha,
            contact=contact,
            render_gates=log.gates,
        )
        hits = review.holds_needle(page, needles)
        if hits:
            raise Refused("7", f"the review page would hold needles {hits}")
        (partial_review / "index.html").write_text(page, encoding="utf-8")
        (partial_review / "gates.json").write_text(
            json.dumps(
                {"render": log.gates, "capture": capture.manifest.gates}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )

        _place(partial_vtt, finals["vtt"])
        _place(partial_mp4, finals["mp4"])
        partial_review.rename(finals["review"])
        return RenderResult(
            mp4=finals["mp4"],
            vtt=finals["vtt"],
            review=finals["review"],
            mp4_sha256=mp4_sha,
            vtt_sha256=vtt_sha,
            gates=log.gates,
        )
    except BaseException:
        for path in owned:
            if path.exists() or path.is_symlink():
                _remove(path, allowed=owned)
        raise
    finally:
        if needles_path.exists() or needles_path.is_symlink():
            needles_path.unlink()
        if made_work and work.exists():
            _remove(work, allowed=[work])
