"""The docs-journey runner's sign-in pacer (#939, D3b).

The compose stack allows 10 sign-ins a minute from one address, and every
journey of a run signs in from the same machine. ``docs_runner/pacer.py``
makes the runner wait before a sign-in that would be the eleventh in a minute.
These tests drive it with a fake clock (nothing really waits), and pin that the
runner asks it before each of its own sign-ins and each click on the
dashboard's Sign in button, and records every sign-in the browser sends.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER_ROOT = REPO_ROOT / "tests" / "acceptance" / "docs"
if str(RUNNER_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNNER_ROOT))

from docs_runner import pacer


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: List[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _pacer(clock: FakeClock) -> pacer.SignInPacer:
    return pacer.SignInPacer(clock=clock.clock, sleep=clock.sleep)


def test_the_limit_is_the_stacks_documented_one():
    assert (pacer.LIMIT, pacer.WINDOW_SECONDS) == (10, 60.0)
    source = (REPO_ROOT / "backend/app/middleware/rate_limiter.py").read_text()
    assert '"/api/v1/auth/login": (10, 60),' in source
    assert pacer.SIGN_IN_PATH == "/api/v1/auth/login"


def test_ten_sign_ins_in_a_minute_need_no_wait():
    clock = FakeClock()
    paced = _pacer(clock)
    for _ in range(10):
        assert paced.wait() == 0.0
        paced.record()
        clock.now += 1
    assert clock.slept == []


def test_the_eleventh_waits_until_the_oldest_is_a_minute_old():
    clock = FakeClock()
    paced = _pacer(clock)
    first = clock.now
    for _ in range(10):
        paced.wait()
        paced.record()
        clock.now += 2
    waited = paced.wait()
    assert clock.slept == [waited]
    assert waited > 0
    assert clock.now == pytest.approx(
        first + pacer.WINDOW_SECONDS + pacer.MARGIN_SECONDS
    )
    paced.record()
    # The window now holds ten again, the oldest the second sign-in.
    assert paced.wait() == pytest.approx(2.0)


def test_sign_ins_older_than_the_window_do_not_count():
    clock = FakeClock()
    paced = _pacer(clock)
    for _ in range(10):
        paced.record()
    clock.now += pacer.WINDOW_SECONDS + pacer.MARGIN_SECONDS + 0.5
    assert paced.wait() == 0.0
    assert clock.slept == []


def test_refused_sign_ins_count_too():
    """Twelve recorded in a burst: the next waits for the third oldest to age out."""
    clock = FakeClock()
    paced = _pacer(clock)
    for step in range(12):
        paced.record(at=clock.now + step)
    clock.now += 12
    waited = paced.wait()
    assert clock.now == pytest.approx(1000.0 + 2 + 60.0 + 1.0)
    assert waited == pytest.approx(1000.0 + 2 + 61.0 - 1012.0)


def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse((RUNNER_ROOT / "docs_runner" / "execute.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"execute.py has no {name}")


def _calls(node: ast.AST) -> List[str]:
    return [
        ast.unparse(call.func) for call in ast.walk(node) if isinstance(call, ast.Call)
    ]


def test_the_runner_paces_its_own_sign_in_before_sending_it():
    calls = _calls(_method("_headers"))
    assert "self.pacer.wait" in calls
    assert "self.pacer.record" in calls
    assert calls.index("self.pacer.wait") < calls.index("api.post")


def test_the_runner_paces_a_click_on_sign_in():
    source = ast.unparse(_method("_act"))
    assert "pacing.SIGN_IN_BUTTONS" in source
    assert source.index("self.pacer.wait()") < source.index(".click()")


def test_the_runner_records_every_sign_in_the_browser_sends():
    assert "self.pacer.record" in _calls(_method("_note_sign_in"))
    run = ast.unparse(_method("run"))
    assert "page.on('request', self._note_sign_in)" in run
