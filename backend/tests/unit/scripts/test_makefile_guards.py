"""The Makefile's core-checkout guards, and the shape that made them not guard.

``test-modules`` and ``lock-modules`` are the two targets that only make sense
in a full checkout.  Both were written as::

    target:
    	@test -d modules/... \\
    		|| { echo "this is a core checkout"; exit 0; }
    	<the command>

Make runs every recipe *line* in its own shell and this makefile has no
``.ONESHELL:``, so that ``exit 0`` ends the guard's shell and the next line
runs regardless.  On a core checkout -- what ``scripts/core_build.sh``
produces and what a release ships -- ``make test-modules`` printed the guard
message and then ran pytest against a missing path (exit 4), and ``test``
depends on it, so ``make test`` was red on every core checkout before the
frontend suite ever started.  ``make lock`` failed the same way.

These tests drive the real ``Makefile`` with a stand-in interpreter, so they
need neither the modules nor a network:

* the *behaviour*: both targets in a tree with no ``modules/`` must exit 0
  **and** must not have run their command (the stand-in fails loudly if it is
  invoked), and in a tree that has one they must run it;
* the *shape*: no recipe in the makefile may end a non-final line with
  ``exit 0``, which is the bug as a rule rather than as two instances.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
MAKEFILE = REPO_ROOT / "Makefile"

requires_make = pytest.mark.skipif(
    shutil.which("make") is None, reason="make is not installed"
)


def _stand_in(path: Path, marker: Path, *, exit_code: int) -> None:
    """Write an executable that records its argv in *marker* and exits *exit_code*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{marker}"\nexit {exit_code}\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _tree(tmp_path: Path, *, with_modules: bool, exit_code: int) -> tuple[Path, Path]:
    """A minimal tree holding the real Makefile; returns ``(root, marker)``.

    ``venv/bin/python`` and ``venv/bin/uv`` are stand-ins: every invocation is
    appended to the marker file.  With ``exit_code=1`` an invocation also fails
    the target, so a guard that does not guard shows up twice over.
    """
    root = tmp_path / ("full" if with_modules else "core")
    root.mkdir()
    shutil.copy2(MAKEFILE, root / "Makefile")
    marker = root / "invocations.txt"
    _stand_in(root / "venv" / "bin" / "python", marker, exit_code=exit_code)
    _stand_in(root / "venv" / "bin" / "uv", marker, exit_code=exit_code)
    (root / "backend" / "requirements").mkdir(parents=True)
    (root / "backend" / "requirements.txt").write_text("", encoding="utf-8")
    if with_modules:
        (root / "modules" / "backend" / "tests").mkdir(parents=True)
        (root / "modules" / "requirements.txt").write_text("", encoding="utf-8")
    return root, marker


def _make(root: Path, target: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("MAKEFLAGS", None)
    env.pop("MAKELEVEL", None)
    return subprocess.run(
        ["make", target],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


@requires_make
class TestCoreCheckoutGuards:
    @pytest.mark.regression
    @pytest.mark.parametrize(
        ("target", "forbidden"),
        [("test-modules", "pytest"), ("lock-modules", "pip compile")],
    )
    def test_guard_stops_the_command_on_a_core_checkout(
        self, tmp_path, target, forbidden
    ):
        """No ``modules/``: the target says so, exits 0, and runs nothing."""
        root, marker = _tree(tmp_path, with_modules=False, exit_code=1)
        result = _make(root, target)
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert "core checkout" in output, output
        invoked = marker.read_text() if marker.exists() else ""
        assert forbidden not in invoked, (
            f"the guard printed its message and ran the command anyway: {invoked!r}"
        )
        assert invoked == "", f"nothing should have been invoked, got {invoked!r}"

    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            ("test-modules", "-m pytest modules/backend/tests"),
            ("lock-modules", "pip compile modules/requirements.txt"),
        ],
    )
    def test_the_command_still_runs_with_the_modules_present(
        self, tmp_path, target, expected
    ):
        """The guard must not swallow the command in a full checkout."""
        root, marker = _tree(tmp_path, with_modules=True, exit_code=0)
        result = _make(root, target)
        assert result.returncode == 0, result.stdout + result.stderr
        invoked = marker.read_text() if marker.exists() else ""
        assert expected in invoked, invoked

    @pytest.mark.parametrize("target", ["test-modules", "lock-modules"])
    def test_a_failing_command_still_fails_the_target(self, tmp_path, target):
        """Guarding must not turn a real failure into a green target."""
        root, _ = _tree(tmp_path, with_modules=True, exit_code=1)
        assert _make(root, target).returncode != 0


class TestRecipeShape:
    """`exit 0` may only ever be the last thing a recipe does."""

    @pytest.mark.regression
    def test_no_recipe_exits_zero_before_its_last_line(self):
        text = MAKEFILE.read_text(encoding="utf-8")
        # At the start of a line: the words also appear in the comment on
        # `test-modules` that explains why this rule exists.
        if re.search(r"^\.ONESHELL:", text, re.M):  # pragma: no cover
            pytest.skip(".ONESHELL: makes a recipe one shell; the rule does not apply")

        # Logical recipe lines: a tab-indented line plus every line it
        # continues with a trailing backslash.
        recipes: list[list[str]] = []
        current: list[str] = []
        pending: list[str] = []
        for raw in text.splitlines():
            if raw.startswith("\t"):
                pending.append(raw)
                if raw.rstrip().endswith("\\"):
                    continue
                current.append(" ".join(part.strip() for part in pending))
                pending = []
                continue
            if pending:  # pragma: no cover - a recipe cannot end mid-continuation
                current.append(" ".join(part.strip() for part in pending))
                pending = []
            if current:
                recipes.append(current)
                current = []
        if current:
            recipes.append(current)

        offenders = [
            line
            for recipe in recipes
            for line in recipe[:-1]
            if re.search(r"(^|[;&|(\s])exit 0\b", line)
        ]
        assert not offenders, (
            "a recipe line ends in `exit 0` with another line after it; make "
            "runs each line in its own shell, so that exits the guard's shell "
            "and the next line runs anyway. Put the guard and the command in "
            "one `if ... fi` line: " + "; ".join(offenders)
        )


class TestTheOpenApiFixturesNameTheirProfile:
    """``make openapi`` writes three fixtures, and each describes a *profile*.

    The dashboard's URL-guard fixture is a full-profile dump: the guard test
    subtracts ``openapi.module-paths.json`` from it for a core run.  The
    command that writes it passed no ``--profile``, so it dumped whatever the
    checkout happened to load -- regenerate it from a core tree and the
    fixture quietly lost the modules' 62 paths, after which the core run
    subtracted them a second time and the full run stopped guarding the
    module URLs at all.
    """

    #: Every place that invokes the dumper.  Each must name a profile.
    INVOCATIONS = (
        Path("Makefile"),
        Path("frontend") / "package.json",
        # Its "Generated by" column is what people copy and paste.
        Path("docs") / "api" / "stability.md",
        # So is the dumper's own docstring.
        Path("backend") / "scripts" / "dump_openapi.py",
    )

    @pytest.mark.regression
    @pytest.mark.parametrize("relative", INVOCATIONS, ids=lambda p: str(p))
    def test_every_dump_openapi_invocation_names_a_profile(self, relative: Path):
        path = REPO_ROOT / relative
        if not path.is_file():
            pytest.skip(f"{relative} is not in this tree")
        for line in path.read_text().splitlines():
            if "dump_openapi" not in line:
                continue
            assert "--profile" in line, (
                f"{relative}: `{line.strip()}` dumps whichever profile the "
                f"checkout happens to load"
            )
