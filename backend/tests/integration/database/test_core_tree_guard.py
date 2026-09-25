"""``core_tree_guard.seal`` against planted finders.

``test_core_tree_isolation.py`` proves the guard works where it runs, as a core
tree's ``sitecustomize``; this file proves the branches no real environment
reaches today: a finder that resolves ``modules`` is removed, one that raises
stops the interpreter, and no failure leaves as anything but ``SystemExit`` --
the one exception ``site`` does not swallow from a ``sitecustomize``.

Each case calls ``seal`` directly, in a fresh interpreter with ``-S`` (no
``site``, so no ``.pth`` finders and no ``sitecustomize``): the test process
itself has already imported ``backend`` from the checkout, which is exactly
what the guard exists to refuse.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.regression]

GUARD = pathlib.Path(__file__).with_name("core_tree_guard.py")

_PRELUDE = """
import importlib.machinery, importlib.util, sys
spec = importlib.util.spec_from_file_location("core_tree_guard", {guard!r})
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

class Leaks:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "modules":
            return importlib.machinery.ModuleSpec("modules", None, origin="/checkout/modules")
        return None

class Raises:
    def find_spec(self, fullname, path=None, target=None):
        raise RuntimeError("finder exploded")

root = {root!r}
"""


def _call(tmp_path, body: str) -> subprocess.CompletedProcess:
    root = tmp_path / "core"
    (root / "backend").mkdir(parents=True, exist_ok=True)
    (root / "backend" / "__init__.py").write_text("", encoding="utf-8")
    script = _PRELUDE.format(guard=str(GUARD), root=str(root)) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_a_finder_that_resolves_modules_is_removed(tmp_path):
    process = _call(
        tmp_path,
        """
        leak = Leaks()
        sys.meta_path.append(leak)
        guard.seal(root)
        print("removed" if leak not in sys.meta_path else "kept")
        """,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == "removed"


def test_a_finder_that_raises_stops_the_interpreter(tmp_path):
    process = _call(tmp_path, "sys.meta_path.append(Raises()); guard.seal(root)")
    assert process.returncode != 0
    assert "core-tree guard: RuntimeError: finder exploded" in process.stderr


def test_any_internal_failure_leaves_as_system_exit(tmp_path):
    process = _call(
        tmp_path,
        """
        def broken(root):
            raise ValueError("unexpected")
        guard._foreign_finders = broken
        try:
            guard.seal(root)
        except SystemExit as exc:
            print("SystemExit:", exc)
        """,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.startswith("SystemExit: core-tree guard: ValueError")


def test_a_modules_directory_in_the_tree_stops_the_interpreter(tmp_path):
    (tmp_path / "core" / "modules").mkdir(parents=True)
    process = _call(tmp_path, "guard.seal(root)")
    assert process.returncode != 0
    assert "has a modules directory" in process.stderr
