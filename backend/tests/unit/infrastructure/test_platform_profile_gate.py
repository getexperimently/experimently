"""``_platform.yml`` must prove the profile it booted, not just read a word.

The reusable platform workflow boots the API and then asserts the profile the
caller asked for is the profile that answers.  It did that by reading
``.profile`` out of ``GET /api/v1/modules`` -- and that field alone cannot
answer the question.  Registering the module routers and *mounting* them are
two steps (``modules_loader.mount_module_routers``), and the second fails on
its own: the registration has succeeded, so the endpoint says ``full`` and
lists all ten modules, while not one module route is mounted and every one of
them 404s.  ``sdk-live-contract (full)`` would have been green on that.

So the assertion also reads the module list and asks a real module route.
These are cheap YAML reads; the behaviour they pin is exercised for real by
the job itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_platform.yml"

#: A distribution that does not ship the workflows has nothing here to check.
pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file(), reason="this tree has no .github/workflows"
)


def _assertion_step() -> Dict[str, Any]:
    document = yaml.safe_load(WORKFLOW.read_text())
    steps = document["jobs"]["platform"]["steps"]
    for step in steps:
        if "/api/v1/modules" in str(step.get("run", "")):
            return step
    raise AssertionError(
        "no step in _platform.yml asks GET /api/v1/modules: nothing checks "
        "that the profile the job booted is the profile it asked for"
    )


class TestTheProfileAssertion:
    def test_it_still_checks_the_profile(self):
        assert ".profile" in str(_assertion_step()["run"])

    @pytest.mark.regression
    def test_it_checks_more_than_the_profile(self):
        """`.profile` is the field a mount failure leaves lying."""
        run = str(_assertion_step()["run"])
        assert ".modules" in run, (
            "the assertion reads only .profile, which still says 'full' when "
            "the module routers registered and never mounted"
        )

    @pytest.mark.regression
    def test_it_asks_a_real_module_route(self):
        """The only observation that cannot be faked by a registry."""
        run = str(_assertion_step()["run"])
        assert "/api/v1/workspaces/" in run, (
            "nothing in the assertion proves a module route is actually "
            "served; every module route can 404 while this step is green"
        )
        assert "404" in run

    def test_it_asserts_in_both_directions(self):
        """A core job that booted the full API is the bug this started as."""
        run = str(_assertion_step()["run"])
        assert "the full profile reports no installed modules" in run
        assert "on the core profile: a module route is mounted" in run
