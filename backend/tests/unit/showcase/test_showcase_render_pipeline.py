"""The showcase render's refusals before any encode, and what it leaves behind (#1066).

These run the real ``pipeline.render`` on synthetic capture directories that
it must refuse before ffmpeg or a browser is needed, so they run in the CI
unit job. The full render, with Chromium, ffmpeg and OCR, is tamper-tested on
a developer's machine with ``showcase.render.synthetic``.
"""

from __future__ import annotations

import os

import pytest
from showcase import contract
from showcase.render import pipeline
from showcase.render.gates import Refused

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


def test_the_render_deletes_only_what_it_made(tmp_path):
    mine, other = tmp_path / "mine.partial", tmp_path / "other.mp4"
    mine.write_bytes(b"x")
    other.write_bytes(b"y")
    pipeline._remove(mine, allowed=[mine])
    with pytest.raises(RuntimeError, match="not a path this render made"):
        pipeline._remove(other, allowed=[mine])
    assert not mine.exists() and other.exists()


def test_the_needles_file_is_never_left_world_readable_by_the_fixture(tmp_path):
    capture = make_capture(tmp_path / "capture")
    assert oct(os.stat(capture / "needles.txt").st_mode & 0o777) == "0o600"
