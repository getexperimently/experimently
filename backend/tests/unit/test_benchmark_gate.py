"""The ``benchmark`` gate: skipped by default, run on RUN_BENCHMARKS=1, and
``-m benchmark`` without the variable refused rather than passing empty (#409).

Each case runs a real pytest session in a subprocess over a two-test file, so
what is asserted is what a CI job would see: the exit status and the outcome
of each test.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

PROBE = """
import pytest

def test_plain():
    pass

@pytest.mark.benchmark
def test_timed():
    # Fails when it runs, so "it ran" is visible in the exit status.
    assert False, "BENCHMARK-RAN"
"""


def _run(tmp_path: Path, env_value: str | None, *args: str):
    (tmp_path / "test_probe.py").write_text(PROBE)
    env = {k: v for k, v in os.environ.items() if k != "RUN_BENCHMARKS"}
    if env_value is not None:
        env["RUN_BENCHMARKS"] = env_value
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "backend.tests.benchmark_gate",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:cov",
            "--rootdir",
            str(tmp_path),
            "-c",
            os.devnull,
            "-rA",
            *args,
            str(tmp_path / "test_probe.py"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.regression
def test_benchmarks_are_skipped_by_default(tmp_path):
    result = _run(tmp_path, None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASSED" in result.stdout and "test_plain" in result.stdout
    assert "SKIPPED" in result.stdout and "RUN_BENCHMARKS=1" in result.stdout
    assert "BENCHMARK-RAN" not in result.stdout


@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
def test_only_the_value_1_enables_them(tmp_path, value):
    result = _run(tmp_path, value)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BENCHMARK-RAN" not in result.stdout


def test_run_benchmarks_1_runs_them(tmp_path):
    result = _run(tmp_path, "1")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BENCHMARK-RAN" in result.stdout


def test_selecting_benchmarks_without_the_variable_is_refused(tmp_path):
    """The nightly job's own invocation, misconfigured, must not pass empty."""
    result = _run(tmp_path, None, "-m", "benchmark")
    assert result.returncode == 4, result.stdout + result.stderr
    assert "RUN_BENCHMARKS=1" in result.stdout + result.stderr
