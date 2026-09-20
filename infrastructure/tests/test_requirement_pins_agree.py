"""The CDK's two requirement files must pin the same versions.

``infrastructure/cdk/requirements.txt`` is what a standalone
``pip install -r infrastructure/cdk/requirements.txt`` gets; ``backend/requirements.txt``
is what CI, the developer venv and therefore ``infrastructure/tests`` get.  Both
declare ``aws-cdk-lib``.  When they disagree, the ``cdk synth`` that CI runs and
the ``cdk synth`` an operator runs are two different programs -- which is how
this file's own subject went unnoticed: the CDK app's pins sat at 2.94.0 while
everything that actually executed used 2.268.0.

Dependabot watches the two files as separate ecosystems, so they drift one
merged pull request at a time rather than all at once.  This compares whatever
they happen to share, rather than a hand-written list of package names, so a
package added to both in future is covered without anyone remembering to add it
here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CDK_REQUIREMENTS = REPO_ROOT / "infrastructure" / "cdk" / "requirements.txt"
BACKEND_REQUIREMENTS = REPO_ROOT / "backend" / "requirements.txt"

# name, operator, version -- only exact `==` pins are comparable; a range in one
# file and a range in the other cannot disagree in a way this test can judge.
_PIN = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([^\s;#]+)")


def _pins(path: Path) -> dict[str, str]:
    """Return {canonical name: version} for every `name==version` line."""
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _PIN.match(line)
        if match:
            name, version = match.groups()
            # PEP 503 normalisation: Aws_CDK-Lib and aws-cdk-lib are one package.
            found[re.sub(r"[-_.]+", "-", name).lower()] = version
    return found


def test_the_pin_regex_reads_this_repository() -> None:
    """Guard against the comparison below passing on two empty dicts.

    Every failure mode of `_pins` -- a moved file, a renamed section, a regex
    that stops matching the file's actual syntax -- shows up as an empty or
    tiny mapping, and an empty mapping makes `test_shared_pins_agree` vacuous.
    """
    cdk_pins = _pins(CDK_REQUIREMENTS)
    backend_pins = _pins(BACKEND_REQUIREMENTS)

    assert "aws-cdk-lib" in cdk_pins, f"parsed {CDK_REQUIREMENTS} as {cdk_pins}"
    assert "aws-cdk-lib" in backend_pins, (
        f"no aws-cdk-lib pin in {BACKEND_REQUIREMENTS}"
    )
    assert len(backend_pins) > 50, f"only parsed {len(backend_pins)} pins from backend"


@pytest.mark.regression
def test_shared_pins_agree() -> None:
    """Any package pinned in both files must be pinned to the same version."""
    cdk_pins = _pins(CDK_REQUIREMENTS)
    backend_pins = _pins(BACKEND_REQUIREMENTS)

    shared = sorted(set(cdk_pins) & set(backend_pins))
    assert shared, "the two files share no exact pins -- has one been restructured?"

    disagreements = {
        name: (cdk_pins[name], backend_pins[name])
        for name in shared
        if cdk_pins[name] != backend_pins[name]
    }
    assert not disagreements, (
        "infrastructure/cdk/requirements.txt and backend/requirements.txt "
        "disagree on "
        + ", ".join(
            f"{name} ({cdk} vs {backend})"
            for name, (cdk, backend) in sorted(disagreements.items())
        )
        + ". Bump both in the same pull request: CI synthesises with the "
        "backend pin and an operator synthesises with the CDK one."
    )
