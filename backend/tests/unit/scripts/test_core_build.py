"""`scripts/core_build.sh` — argument handling.

The script is the proof that a profile stands on its own, so the one thing it
must never do is report success without having run anything.  These tests
drive the real script; they stop at argument parsing, well before the copy
step, so they need no database, no gitleaks and no network.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "core_build.sh"

#: Every step name the script's own ALL_STEPS list carries.  `modules_tests`
#: is deliberately absent: it is only valid with --profile full.
_CORE_STEPS = [
    "copy",
    "strip",
    "reuse",
    "secrets",
    "import",
    "bootstrap",
    "unit",
    "integration",
    "smoke",
    "lambda",
    "frontend",
    "vectors",
    "licences",
]


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(_SCRIPT), *args], capture_output=True, text=True, timeout=60
    )


class TestStepValidation:
    @pytest.mark.regression
    @pytest.mark.parametrize("typo", ["unti", "units", "front-end", "licenses", ""])
    def test_unknown_step_is_a_usage_error(self, typo):
        """A step name nothing matches must not skip the build and exit 0.

        `--steps <typo>` used to select no step at all: every step reported
        "skipped" and the script still printed `core-build: OK`, so a typo in
        CI would have proved precisely nothing while looking green.
        """
        result = run("--steps", typo or "nope")
        assert result.returncode == 2, result.stdout + result.stderr
        assert "unknown step" in result.stderr
        # The error names the alternatives, so the typo is fixable from it.
        assert "known steps:" in result.stderr

    @pytest.mark.parametrize("step", _CORE_STEPS)
    def test_known_step_names_are_accepted(self, step):
        """Every name in the script's own step list passes validation.

        Validation happens before preflight, so a valid name gets as far as
        the tool check -- never exit 2.
        """
        result = run("--steps", step, "--help")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_modules_tests_needs_the_full_profile(self):
        """`modules_tests` only exists in the full sequence."""
        assert run("--steps", "modules_tests").returncode == 2
        assert (
            run("--profile", "full", "--steps", "modules_tests", "--help").returncode
            == 0
        )

    def test_unknown_profile_is_still_a_usage_error(self):
        result = run("--profile", "community")
        assert result.returncode == 2
        assert "--profile must be core or full" in result.stderr


def listed(*args: str) -> list[str]:
    """The steps ``--list-steps`` says this invocation would run."""
    result = run(*args, "--list-steps")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == "", result.stderr
    return result.stdout.split()


class TestStepSelection:
    """What `--steps` actually *selects*, not just what it accepts.

    Validation and selection used to read the filter differently: the
    validator stripped whitespace into a throwaway local while `want_step`
    matched the raw string.
    """

    def test_the_full_sequence_runs_without_a_filter(self):
        core = listed()
        assert core[0] == "copy" and core[1] == "strip"
        assert "modules_tests" not in core
        assert {
            "unit",
            "integration",
            "smoke",
            "lambda",
            "frontend",
            "licences",
        } <= set(core)
        assert "modules_tests" in listed("--profile", "full")

    @pytest.mark.regression
    @pytest.mark.parametrize(
        "spelling",
        ["unit,frontend", "unit, frontend", " unit , frontend ", "unit,\tfrontend"],
    )
    def test_whitespace_around_a_name_does_not_drop_it(self, spelling):
        """`--steps "unit, frontend"` selected `unit` and silently skipped ` frontend`.

        It validated (the check stripped whitespace), ran half of what was
        asked for, and exited 0 with `core-build: OK` -- a build that proved
        less than the command said.
        """
        assert listed("--steps", spelling) == ["copy", "strip", "unit", "frontend"]

    @pytest.mark.regression
    def test_the_environment_variable_is_normalised_too(self):
        result = subprocess.run(
            [str(_SCRIPT), "--list-steps"],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "CORE_BUILD_STEPS": "unit, frontend"},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.split() == ["copy", "strip", "unit", "frontend"]

    @pytest.mark.parametrize("filter_", [" , ", ",", "   "])
    def test_a_filter_that_names_nothing_is_a_usage_error(self, filter_):
        """Not "no filter, run everything", and not "nothing ran, OK"."""
        result = run("--steps", filter_)
        assert result.returncode == 2, result.stdout + result.stderr
        assert "names no step" in result.stderr

    def test_a_repeated_name_is_listed_once(self):
        assert listed("--steps", "unit,unit, unit") == ["copy", "strip", "unit"]

    def test_copy_and_strip_are_added_when_a_filter_omits_them(self):
        """A filtered run still needs a tree; asking for copy does not duplicate it."""
        assert listed("--steps", "licences") == ["copy", "strip", "licences"]
        assert listed("--steps", "copy,strip") == ["copy", "strip"]
