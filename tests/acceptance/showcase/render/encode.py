"""From frames and caption PNGs to one H.264 file.

The recording becomes two numbered sequences of the same length, built by
links, never copies: ``page/`` (the capture frame each output frame shows)
and ``band/`` (that frame's caption, or the empty band). ffmpeg pads each page
frame to 1920x1080 and overlays the band under it, then joins the title card,
the recording and the end card with the concat *filter* (each card trimmed to
its exact frame count), and encodes:

* libx264, ``-pix_fmt yuv420p`` (without it libx264 writes yuv444p, which
  many players refuse), BT.709 TV range (JPEG frames are full range);
* ``-movflags +faststart``, so the index comes before the media;
* no audio stream.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from showcase import contract
from showcase.render.children import child_env

FFMPEG = "ffmpeg"


def link(source: Path, target: Path) -> None:
    """A hard link where the filesystem allows one, else a symbolic link."""
    try:
        os.link(source, target)
    except OSError:
        os.symlink(source.resolve(), target)


def build_sequences(
    frames_dir: Path,
    frame_files: Sequence[str],
    schedule: Sequence[int],
    band_files: Sequence[Path],
    band_schedule: Sequence[Optional[int]],
    empty_band: Path,
    seq_dir: Path,
) -> int:
    """Write ``seq_dir/page/%06d.jpg`` and ``seq_dir/band/%06d.png``; return the frame count."""
    if len(schedule) != len(band_schedule):
        raise ValueError("the page and band schedules differ in length")
    page_dir, band_dir = seq_dir / "page", seq_dir / "band"
    page_dir.mkdir(parents=True)
    band_dir.mkdir(parents=True)
    for k, (frame_index, cue_index) in enumerate(zip(schedule, band_schedule), start=1):
        link(frames_dir / frame_files[frame_index], page_dir / f"{k:06d}.jpg")
        link(
            empty_band if cue_index is None else band_files[cue_index],
            band_dir / f"{k:06d}.png",
        )
    return len(schedule)


def ffmpeg_argv(
    title_png: Path,
    seq_dir: Path,
    end_png: Path,
    recording_frames: int,
    output: Path,
) -> List[str]:
    rate = str(contract.FPS)
    total = contract.TITLE_FRAMES + recording_frames + contract.END_FRAMES
    graph = ";".join(
        [
            f"[0:v]trim=end_frame={contract.TITLE_FRAMES},setpts=N/({rate}*TB),format=rgb24,setsar=1[title]",
            f"[1:v]format=rgb24,setsar=1,pad={contract.OUT_W}:{contract.OUT_H}:0:0:color=black[page]",
            "[2:v]format=rgb24,setsar=1[band]",
            f"[page][band]overlay=x=0:y={contract.PAGE_H}:eof_action=endall:format=rgb[recording]",
            f"[3:v]trim=end_frame={contract.END_FRAMES},setpts=N/({rate}*TB),format=rgb24,setsar=1[end]",
            "[title][recording][end]concat=n=3:v=1:a=0,"
            "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[video]",
        ]
    )
    return [
        FFMPEG,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-n",
        "-loop",
        "1",
        "-framerate",
        rate,
        "-i",
        str(title_png),
        "-framerate",
        rate,
        "-start_number",
        "1",
        "-i",
        str(seq_dir / "page" / "%06d.jpg"),
        "-framerate",
        rate,
        "-start_number",
        "1",
        "-i",
        str(seq_dir / "band" / "%06d.png"),
        "-loop",
        "1",
        "-framerate",
        rate,
        "-i",
        str(end_png),
        "-filter_complex",
        graph,
        "-map",
        "[video]",
        "-frames:v",
        str(total),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-r",
        rate,
        "-fps_mode",
        "cfr",
        "-color_range",
        "tv",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-movflags",
        "+faststart",
        "-an",
        "-f",
        "mp4",
        str(output),
    ]


def encode(argv: Sequence[str], log_path: Path) -> None:
    with open(log_path, "w", encoding="utf-8") as log:
        result = subprocess.run(
            list(argv),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
            env=child_env(),
        )
    if result.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-600:]
        raise RuntimeError(f"ffmpeg exited {result.returncode}: {tail}")


def png_to_h264_and_back(source: Path, work: Path) -> Path:
    """Put one PNG through the video's encode and decode it again (for the OCR canary)."""
    encoded = work / "canary.mp4"
    decoded = work / "canary-decoded.png"
    steps = [
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            "format=rgb24,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-frames:v",
            "1",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(encoded),
        ],
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(encoded),
            "-frames:v",
            "1",
            str(decoded),
        ],
    ]
    for argv in steps:
        result = subprocess.run(
            argv, capture_output=True, text=True, check=False, env=child_env()
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg exited {result.returncode}: {result.stderr.strip()[:300]}"
            )
    return decoded


def extract_frames(
    video: Path,
    indices: Sequence[int],
    out_dir: Path,
    *,
    crop_band: bool = False,
    scale: Optional[str] = None,
    ext: str = "png",
) -> List[Path]:
    """Decode the given output frames (0-based) to images, in the order given (sorted, unique)."""
    wanted = sorted(set(indices))
    if not wanted:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    select = "+".join(f"eq(n,{i})" for i in wanted)
    filters = [f"select='{select}'"]
    if crop_band:
        filters.append(f"crop={contract.OUT_W}:{contract.BAND_H}:0:{contract.PAGE_H}")
    if scale:
        filters.append(f"scale={scale}")
    argv = [
        FFMPEG,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(video),
        "-vf",
        ",".join(filters),
        "-fps_mode",
        "passthrough",
    ]
    if ext == "jpg":
        argv += ["-q:v", "3"]
    raw = out_dir / "raw"
    raw.mkdir()
    argv.append(str(raw / f"%06d.{ext}"))
    result = subprocess.run(
        argv, capture_output=True, text=True, check=False, env=child_env()
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg frame extraction exited {result.returncode}: {result.stderr.strip()[:300]}"
        )
    written = sorted(raw.iterdir())
    if len(written) != len(wanted):
        raise RuntimeError(
            f"ffmpeg wrote {len(written)} frames for {len(wanted)} requested"
        )
    renamed = []
    for index, path in zip(wanted, written):
        target = out_dir / f"frame-{index:06d}.{ext}"
        path.rename(target)
        renamed.append(target)
    raw.rmdir()
    return renamed
