"""The production deploy must choose its profile out loud.

``deploy-prod.yml`` built the API image with a hard-coded ``--target core`` and
tagged it ``:latest``.  On main that was harmless -- the ``ce`` target still
carried every module, and the registration installed ``AuditSigningService``
unconditionally, so production *did* sign its compliance audit events.  On this
layout ``core`` means an image with no ``modules/`` directory at all: the
modules' registration never runs, ``hooks.audit_signer`` stays
``NullAuditSigner``, and every SOC 2 / ISO 27001 event is written with
``hmac_signature = NULL`` -- which ``NullAuditSigner.verify()`` then reports as
intact.  Nothing signalled it: ``abort_if_modules_broken()`` only fires for a
*broken* package, ``/health/ready`` answers 200 with ``profile: core``, and no
job pushed a ``full`` image anywhere.

So the profile is an input with a guard, not a default, and these checks pin
that shape.  They are cheap text/YAML reads on purpose -- no Docker, no AWS --
so they run in the ordinary unit job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml"

#: A distribution that does not ship the workflows has nothing here to check.
pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file(), reason="this tree has no .github/workflows"
)


def _workflow() -> Dict[str, Any]:
    # PyYAML parses the bare `on:` key as the boolean True.
    document = yaml.safe_load(WORKFLOW.read_text())
    document["on"] = document.pop(True, document.get("on"))
    return document


def _steps(job: str) -> list[Dict[str, Any]]:
    return _workflow()["jobs"][job]["steps"]


def _run_text() -> str:
    """Every `run:` script in the workflow, concatenated."""
    return "\n".join(
        step["run"]
        for job in _workflow()["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step.get("run"), str)
    )


class TestTheProfileIsAnExplicitInput:
    @pytest.mark.regression
    def test_the_workflow_takes_a_profile_input_defaulting_to_full(self):
        inputs = _workflow()["on"]["workflow_dispatch"]["inputs"]
        assert "profile" in inputs, (
            "the deploy has no profile input: whichever --target the build step "
            "happens to name is what production gets"
        )
        profile = inputs["profile"]
        assert profile["type"] == "choice"
        assert set(profile["options"]) == {"core", "full"}
        assert profile["default"] == "full", (
            "the default must be the profile that signs the compliance audit log"
        )

    @pytest.mark.regression
    def test_nothing_hard_codes_the_target(self):
        runs = _run_text()
        assert "--target core" not in runs, (
            "the image target is hard-coded; it must come from inputs.profile"
        )
        assert "--target full" not in runs
        assert "--target" in runs
        assert "EXPERIMENTLY_PROFILE=core" not in runs, (
            "the dashboard's profile is hard-coded; it must follow the API image"
        )

    @pytest.mark.regression
    def test_core_cannot_be_deployed_without_acknowledging_the_unsigned_log(self):
        inputs = _workflow()["on"]["workflow_dispatch"]["inputs"]
        assert "accept_unsigned_audit_log" in inputs
        assert inputs["accept_unsigned_audit_log"]["default"] is False

        guard = next(
            (
                step
                for step in _steps("pre-deployment-checks")
                if isinstance(step.get("run"), str)
                and "accept_unsigned_audit_log" in yaml.dump(step.get("env", {}))
            ),
            None,
        )
        assert guard is not None, (
            "no step reads accept_unsigned_audit_log, so ticking it (or not) "
            "changes nothing"
        )
        assert "exit 1" in guard["run"], "the guard does not fail the deployment"

    def test_the_guard_runs_before_any_aws_credential_is_issued(self):
        """A refused deployment should not have assumed the production role."""
        steps = _steps("pre-deployment-checks")
        names = [str(step.get("name", step.get("uses", ""))) for step in steps]
        guard = next(
            i
            for i, step in enumerate(steps)
            if isinstance(step.get("run"), str)
            and "accept_unsigned_audit_log" in yaml.dump(step.get("env", {}))
        )
        aws = next(
            i
            for i, step in enumerate(steps)
            if "configure-aws-credentials" in str(step.get("uses", ""))
        )
        assert guard < aws, f"guard at {guard}, AWS credentials at {aws}: {names}"

    def test_the_built_image_is_checked_against_the_requested_profile(self):
        """`--target` and the stage's own label must agree before the push."""
        runs = _run_text()
        assert "io.experimently.profile" in runs, (
            "nothing verifies that the image built is the profile requested"
        )
