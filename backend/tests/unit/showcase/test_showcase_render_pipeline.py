"""The showcase render's refusals before any encode, and what it leaves behind (#1066).

These run the real ``pipeline.render`` on synthetic capture directories that
it must refuse before ffmpeg or a browser is needed, so they run in the CI
unit job. The full render, with Chromium, ffmpeg and OCR, is tamper-tested on
a developer's machine with ``showcase.render.synthetic``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from showcase import contract
from showcase.render import pipeline
from showcase.render.gates import Refused
from showcase.render.workdir import WorkDir

from backend.tests.unit.showcase.capture_dirs import edit_json, make_capture

pytestmark = [pytest.mark.unit]


@pytest.fixture
def plenty_of_disk(monkeypatch):
    """These tests are about the capture, not this machine's free space."""
    monkeypatch.setattr(pipeline, "check_disk", lambda paths, floor: {})


def refused(capture, out, work=None, **kwargs) -> Refused:
    with pytest.raises(Refused) as caught:
        pipeline.render(capture, out, work, **kwargs)
    return caught.value


def test_needles_are_deleted_even_when_the_capture_is_refused(tmp_path, plenty_of_disk):
    capture = make_capture(tmp_path / "capture", frame_size=(1280, 720))
    error = refused(capture, tmp_path / "out")
    assert error.gate == "capture"
    assert "raw frame 000001.jpg is 1280x720; the page area is 1920x940" in str(error)
    assert not (capture / "needles.txt").exists()
    assert not (tmp_path / "render").exists()


def test_a_capture_gate_not_ok_is_refused(tmp_path, plenty_of_disk):
    capture = make_capture(tmp_path / "capture")
    edit_json(capture / "manifest.json", lambda m: m["gates"]["10"].update(ok=False))
    error = refused(capture, tmp_path / "out")
    assert "capture gate 10 is not ok" in str(error)
    assert not (capture / "needles.txt").exists()


def test_an_output_directory_inside_a_git_checkout_is_refused(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    capture = make_capture(tmp_path / "capture")
    error = refused(capture, checkout / "videos")
    assert error.gate == "paths"
    assert "inside the git checkout at" in str(
        error
    ) and "never go into a repository" in str(error)
    assert not (checkout / "videos").exists()
    assert not (capture / "needles.txt").exists()


def test_a_work_directory_with_something_in_it_is_refused_and_left_alone(tmp_path):
    capture = make_capture(tmp_path / "capture")
    work = tmp_path / "work"
    work.mkdir()
    (work / "keep.txt").write_text("not the render's", encoding="utf-8")
    error = refused(capture, tmp_path / "out", work)
    assert "is not empty" in str(error)
    assert (work / "keep.txt").read_text(encoding="utf-8") == "not the render's"


def test_the_disk_floor_refuses_before_anything_is_written(tmp_path):
    capture = make_capture(tmp_path / "capture")
    error = refused(capture, tmp_path / "out", disk_floor=1 << 60)
    assert error.gate == "disk"
    assert "GiB free for the output directory; the floor is" in str(error)
    assert not (tmp_path / "out").exists() and not (tmp_path / "render").exists()


def test_the_floor_can_be_raised_but_never_lowered(tmp_path, monkeypatch):
    seen = {}

    def check(paths, floor):
        seen["floor"] = floor
        raise Refused("disk", "stop here")

    monkeypatch.setattr(pipeline, "check_disk", check)
    refused(make_capture(tmp_path / "capture"), tmp_path / "out", disk_floor=1)
    assert seen["floor"] == contract.DISK_FLOOR_BYTES


def test_git_checkout_above_finds_the_nearest_checkout(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    assert (
        pipeline.git_checkout_above(tmp_path / "repo" / "a" / "b") == tmp_path / "repo"
    )
    assert pipeline.git_checkout_above(tmp_path / "elsewhere") is None


def test_placing_a_file_never_overwrites(tmp_path):
    partial, final = tmp_path / "v.mp4.partial", tmp_path / "v.mp4"
    partial.write_bytes(b"new")
    final.write_bytes(b"approved")
    with pytest.raises(FileExistsError):
        pipeline._place(partial, final)
    assert final.read_bytes() == b"approved" and partial.exists()


def test_the_needles_file_is_never_left_world_readable_by_the_fixture(tmp_path):
    capture = make_capture(tmp_path / "capture")
    assert oct(os.stat(capture / "needles.txt").st_mode & 0o777) == "0o600"


# --- Review round 1 (#1077): the output never shares the work directory's fate -------------------


class PastThePathsGate(Exception):
    pass


@pytest.fixture
def stop_after_paths(monkeypatch, plenty_of_disk):
    """Fail loudly if the render gets past the paths gate (before the fix, it did)."""

    def reached(root):
        raise PastThePathsGate(f"the render went on to read {root}")

    monkeypatch.setattr(pipeline.contract, "validate_capture_dir", reached)


def paths_refusal(capture, out, work) -> str:
    error = refused(capture, out, work)
    assert error.gate == "paths", error
    return str(error)


@pytest.mark.regression
def test_the_output_directory_cannot_be_the_work_directory(tmp_path, stop_after_paths):
    """``--out X --work X`` printed OK, then deleted the MP4, the VTT and the review page."""
    capture = make_capture(tmp_path / "capture")
    same = tmp_path / "videos"
    text = paths_refusal(capture, same, same)
    assert f"the output and work directories are both {same.resolve()}" in text
    assert not (capture / "needles.txt").exists()
    assert not same.exists()


@pytest.mark.regression
def test_directories_that_differ_only_by_case_are_the_same_directory(
    tmp_path, stop_after_paths
):
    """On the default macOS filesystem ``Videos`` and ``videos`` are one directory,
    so the render would delete its own output; the gate compares case-folded."""
    capture = make_capture(tmp_path / "capture")
    text = paths_refusal(capture, tmp_path / "Videos", tmp_path / "videos")
    assert "the output and work directories are both" in text
    nested = paths_refusal(capture, tmp_path / "Work" / "out", tmp_path / "work")
    assert "is inside the work directory" in nested


@pytest.mark.regression
def test_the_output_directory_cannot_be_inside_the_work_directory(
    tmp_path, stop_after_paths
):
    capture = make_capture(tmp_path / "capture")
    work = tmp_path / "work"
    text = paths_refusal(capture, work / "videos", work)
    assert "is inside the work directory" in text and "which the render deletes" in text


@pytest.mark.regression
def test_the_work_directory_cannot_be_inside_the_output_directory(
    tmp_path, stop_after_paths
):
    capture = make_capture(tmp_path / "capture")
    out = tmp_path / "videos"
    out.mkdir()
    (out / "approved.mp4").write_bytes(b"approved")
    text = paths_refusal(capture, out, out / "scratch")
    assert "is inside the output directory" in text
    assert (out / "approved.mp4").read_bytes() == b"approved"


@pytest.mark.regression
def test_the_work_directory_cannot_overlap_the_capture(tmp_path, stop_after_paths):
    capture = make_capture(tmp_path / "capture")
    text = paths_refusal(capture, tmp_path / "videos", capture / "render")
    assert "and the capture directory" in text and "overlap" in text


def test_the_output_and_work_directories_must_share_a_filesystem(
    tmp_path, monkeypatch, stop_after_paths
):
    capture = make_capture(tmp_path / "capture")
    out = tmp_path / "videos"
    monkeypatch.setattr(
        pipeline, "_device", lambda path: 2 if path == out.resolve() else 1
    )
    text = paths_refusal(capture, out, tmp_path / "work")
    assert "are on different filesystems" in text


@pytest.mark.regression
def test_a_disk_refusal_says_the_capture_must_be_made_again(tmp_path):
    capture = make_capture(tmp_path / "capture")
    error = refused(capture, tmp_path / "out", disk_floor=1 << 60)
    assert error.gate == "disk"
    assert str(error).endswith(
        "- needles.txt is deleted on every refusal, so this capture directory "
        "cannot be rendered again: re-capture needed"
    )
    assert error.problems[-1] == pipeline.RECAPTURE
    assert not (capture / "needles.txt").exists()


@pytest.mark.regression
def test_a_paths_refusal_says_the_capture_must_be_made_again(
    tmp_path, stop_after_paths
):
    capture = make_capture(tmp_path / "capture")
    same = tmp_path / "videos"
    assert paths_refusal(capture, same, same).endswith(
        "- needles.txt is deleted on every refusal, so this capture directory "
        "cannot be rendered again: re-capture needed"
    )


def test_a_work_directory_that_was_there_is_emptied_not_deleted(
    tmp_path, plenty_of_disk
):
    capture = make_capture(tmp_path / "capture", frame_size=(1280, 720))
    work = tmp_path / "work"
    work.mkdir()
    refused(capture, tmp_path / "out", work)
    assert work.is_dir() and not any(work.iterdir())


# --- WorkDir.remove: the render's one deletion (EM condition 7e) ------------------------------------


@pytest.fixture
def tree(tmp_path):
    work = tmp_path / "work"
    (work / "png").mkdir(parents=True)
    (work / "png" / "cue-01.png").write_bytes(b"png")
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / "needles.txt").write_text("VALUE-ONE-TWO-THREE\n", encoding="utf-8")
    (capture / "cues.json").write_text("{}", encoding="utf-8")
    out = tmp_path / "videos"
    out.mkdir()
    (out / "01-a-0123456789ab.mp4").write_bytes(b"approved")
    return work, capture, out


@pytest.mark.regression
def test_remove_deletes_inside_the_work_directory_and_the_needles_file(tree):
    work, capture, out = tree
    workdir = WorkDir(work, needles=capture / "needles.txt")
    workdir.remove(work / "png")
    workdir.remove(capture / "needles.txt")
    workdir.remove(capture / "needles.txt")  # already gone: nothing to do
    workdir.remove(work)
    assert not work.exists() and not (capture / "needles.txt").exists()
    assert (capture / "cues.json").exists() and (out / "01-a-0123456789ab.mp4").exists()


@pytest.mark.regression
def test_remove_refuses_anything_outside_the_work_directory(tree, tmp_path):
    work, capture, out = tree
    workdir = WorkDir(work, needles=capture / "needles.txt")
    for target in (
        out / "01-a-0123456789ab.mp4",
        out,
        capture / "cues.json",
        capture,
        tmp_path,
        work / ".." / "videos",
    ):
        with pytest.raises(Refused, match="is not in the work directory"):
            workdir.remove(target)
    assert (out / "01-a-0123456789ab.mp4").read_bytes() == b"approved"
    assert (capture / "cues.json").exists()


@pytest.mark.regression
def test_remove_refuses_a_work_directory_inside_a_git_checkout(tmp_path):
    """EM condition 7e: a path planted inside a repository is never deleted."""
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    work = checkout / "work"
    (work / "png").mkdir(parents=True)
    workdir = WorkDir(work, needles=tmp_path / "capture" / "needles.txt")
    for target in (work / "png", work, checkout / "README.md"):
        with pytest.raises(Refused, match="inside the git checkout"):
            workdir.remove(target)
    assert (work / "png").is_dir()


def test_remove_refuses_a_work_directory_that_is_the_home_or_the_root(tmp_path):
    for broad in (Path.home(), Path("/")):
        workdir = WorkDir(broad, needles=tmp_path / "needles.txt")
        # (a home directory that is itself a checkout is refused for that first)
        with pytest.raises(Refused, match="too broad|inside the git checkout"):
            workdir.remove(broad / "showcase-render-test-never-made")


def test_remove_deletes_a_link_never_what_it_points_to(tree):
    work, capture, out = tree
    (work / "to-videos").symlink_to(out, target_is_directory=True)
    (work / "to-cues").symlink_to(capture / "cues.json")
    workdir = WorkDir(work, needles=capture / "needles.txt")
    workdir.remove(work / "to-videos")
    workdir.remove(work / "to-cues")
    workdir.remove(work)
    assert (out / "01-a-0123456789ab.mp4").exists() and (capture / "cues.json").exists()


def test_a_link_from_the_work_directory_does_not_make_its_target_removable(tree):
    work, capture, out = tree
    (work / "to-videos").symlink_to(out, target_is_directory=True)
    workdir = WorkDir(work, needles=capture / "needles.txt")
    with pytest.raises(Refused, match="is not in the work directory"):
        workdir.remove(work / "to-videos" / "01-a-0123456789ab.mp4")
    assert (out / "01-a-0123456789ab.mp4").exists()


def test_the_finished_file_is_linked_in_and_survives_the_work_directory(tree):
    work, capture, out = tree
    partial = work / "01-a.mp4.partial"
    partial.write_bytes(b"new video")
    final = out / "01-a-fedcba987654.mp4"
    pipeline._place(partial, final)
    WorkDir(work, needles=capture / "needles.txt").remove(work)
    assert final.read_bytes() == b"new video"
