"""Every program the showcase render starts gets an allow-listed environment (#1066, EM condition 10).

ffmpeg, ffprobe, tesseract, swiftc, the Vision reader and Chromium need a
search path, a home and a temporary directory. A cloud profile, a token or a
database address in the caller's shell must reach none of them. The exact key
set is pinned, a sentinel and ``AWS_PROFILE`` set in the parent are absent,
and every ``subprocess.run`` and the browser launch in the render pass the
list (read from the source, so a new call without it fails here).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from showcase.render import children

pytestmark = [pytest.mark.unit]

RENDER = Path(children.__file__).parent


def test_the_allow_list_is_exactly_these_keys():
    assert children.CHILD_ENV_KEYS == (
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "DEVELOPER_DIR",
        "SDKROOT",
        "TESSDATA_PREFIX",
    )


def test_a_cloud_profile_and_a_sentinel_do_not_reach_a_child(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "staging")
    monkeypatch.setenv("SHOWCASE_SENTINEL", "must-not-pass")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = children.child_env()
    assert "AWS_PROFILE" not in env and "SHOWCASE_SENTINEL" not in env
    assert env["PATH"] == "/usr/bin:/bin"
    assert set(env) <= set(children.CHILD_ENV_KEYS)


def calls(name: str):
    tree = ast.parse((RENDER / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def is_named(call: ast.Call, attribute: str) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr == attribute


@pytest.mark.parametrize("name", sorted(p.name for p in RENDER.glob("*.py")))
def test_every_subprocess_gets_the_allow_list(name):
    for call in calls(name):
        if is_named(call, "run") or is_named(call, "Popen") or is_named(call, "launch"):
            keywords = {k.arg: k.value for k in call.keywords}
            assert "env" in keywords, (
                f"{name}:{call.lineno} starts a program without env="
            )
            value = keywords["env"]
            assert (
                isinstance(value, ast.Call)
                and getattr(value.func, "id", "") == "child_env"
            ), f"{name}:{call.lineno} passes an env that is not child_env()"


def test_the_scan_finds_the_calls_it_checks():
    found = sum(
        1 for p in RENDER.glob("*.py") for c in calls(p.name) if is_named(c, "run")
    )
    assert found >= 10, found
