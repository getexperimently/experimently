"""The shipped API image takes Debian's updates at build time.

The ``runtime`` stage of ``backend/Dockerfile`` (the parent of ``core`` and
``full``, the two images release.yml publishes and security-scan.yml runs Trivy
over) starts from ``python:*-slim``. That base is rebuilt on its own schedule,
so between a Debian security release and the rebuild it ships the old
package. With OpenSSL 3.5.7-1~deb13u2 (fixed in deb13u3) that turned the
required "Security Scan Summary" check red on every pull request: Trivy fails
on any HIGH with a fix available, and the image never asked apt for the fix.

The guard: the runtime stage's apt layer runs ``apt-get upgrade`` after
``apt-get update`` and before it installs anything. The end-to-end proof is a
built image scanned by Trivy; this is the cheap check that fails the moment
the upgrade is dropped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"


def _stage_instructions(text: str, stage: str) -> list[str]:
    """The instructions of one named stage, continuation lines joined."""
    joined = re.sub(r"\\\n", " ", text)
    instructions: list[str] = []
    current: str | None = None
    for raw in joined.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"FROM\s+\S+\s+AS\s+(\S+)", line, re.IGNORECASE)
        if match:
            current = match.group(1)
            continue
        if current == stage:
            instructions.append(line)
    return instructions


@pytest.mark.unit
@pytest.mark.regression
def test_runtime_stage_upgrades_debian_packages_before_installing():
    runs = [
        i
        for i in _stage_instructions(DOCKERFILE.read_text(), "runtime")
        if i.upper().startswith("RUN ")
    ]
    apt_runs = [r for r in runs if "apt-get install" in r]
    assert apt_runs, "the runtime stage has no apt-get install layer to check"
    for run in apt_runs:
        update = run.find("apt-get update")
        upgrade = run.find("apt-get upgrade -y")
        install = run.find("apt-get install")
        assert 0 <= update < upgrade < install, (
            "the runtime stage must run `apt-get update && apt-get upgrade -y` before "
            "`apt-get install`, so the shipped image carries Debian's security fixes "
            f"even when the python:*-slim base lags behind them:\n{run}"
        )


@pytest.mark.unit
def test_core_and_full_both_inherit_the_runtime_stage():
    """The upgrade covers both published images only while both build FROM runtime."""
    froms = re.findall(
        r"^FROM\s+(\S+)\s+AS\s+(\S+)",
        DOCKERFILE.read_text(),
        re.IGNORECASE | re.MULTILINE,
    )
    parents = {name: base for base, name in froms}
    assert parents.get("core") == "runtime", parents
    assert parents.get("full") == "runtime", parents
