"""The production deploy must choose its profile out loud.

The deploy workflow (``deploy.yml``; production-only before #138) built the API image with a hard-coded ``--target core`` and
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

This workflow builds exactly two images, each with the requested profile: the
API's (`--target <profile>`) and, since #69, the dashboard's
(`--build-arg EXPERIMENTLY_PROFILE=<profile>`; its Dockerfile has no stage per
profile). An earlier dashboard build pushed to `experimentation-platform/
frontend`, a repository nothing creates, and never succeeded (#195); the one
here pushes to `experimentation-platform/web`, which the CDK imports.

So the profile is an input with a guard, not a default, and these checks pin
that shape.  They are cheap text/YAML reads on purpose -- no Docker, no AWS --
so they run in the ordinary unit job.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"

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

    @pytest.mark.regression
    def test_the_workflow_builds_exactly_the_two_images_the_cdk_imports(self):
        """The API's and the dashboard's, from the release, into the two
        repositories the stacks import (#69).

        #195 was a dashboard build that pushed to `experimentation-platform/
        frontend`, which nothing creates, so it failed and took every job after
        it down. The dashboard build here pushes to
        `experimentation-platform/web`, the repository `stacks/names.py` names
        and the stacks import (infrastructure/tests/test_ecr_repository_agrees.py
        checks the pair against the CDK).
        """
        text = WORKFLOW.read_text()
        assert "ECR_FRONTEND_REPO" not in text, (
            "the dead frontend ECR repository is referenced again (#195)"
        )
        assert "experimentation-platform/frontend" not in text

        runs = _run_text()
        builds = re.findall(r"-f\s+(\S*Dockerfile)", runs)
        assert builds == [
            "release/backend/Dockerfile",
            "release/frontend/Dockerfile",
        ], f"the deploy should build the API image then the dashboard's, got {builds}"
        env = _workflow()["env"]
        assert env["ECR_BACKEND_REPO"] == "experimentation-platform/backend"
        assert env["ECR_DASHBOARD_REPO"] == "experimentation-platform/web"

    @pytest.mark.regression
    def test_the_dashboard_image_is_built_for_the_requested_profile(self):
        """Its Dockerfile's default is `core`: without the build-arg a full
        deploy would ship a core dashboard, and `--target full` does not exist
        in frontend/Dockerfile (the build fails)."""
        (step,) = [s for s in _steps("deploy") if s.get("id") == "web-image"]
        code = step["run"]
        assert '--build-arg EXPERIMENTLY_PROFILE="$PROFILE"' in code
        assert "--target" not in code
        # And the label check refuses an image labelled with another profile.
        assert '"$built" != "$PROFILE"' in code

    @pytest.mark.regression
    def test_core_cannot_be_deployed_without_acknowledging_the_unsigned_log(self):
        inputs = _workflow()["on"]["workflow_dispatch"]["inputs"]
        assert "accept_unsigned_audit_log" in inputs
        assert inputs["accept_unsigned_audit_log"]["default"] is False

        guard = next(
            (
                step
                for step in _steps("preflight")
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
        """A refused deployment should not have assumed the environment's role.

        The guard is in `preflight`, a job that never assumes one, and the only
        job that does needs `preflight` -- so a refusal ends the run before any
        credential exists.
        """
        jobs = _workflow()["jobs"]
        steps = _steps("preflight")
        assert any(
            isinstance(step.get("run"), str)
            and "accept_unsigned_audit_log" in yaml.dump(step.get("env", {}))
            for step in steps
        ), "the profile guard is not in preflight"
        assert "configure-aws-credentials" not in yaml.dump(jobs["preflight"])
        assuming = [
            name
            for name, job in jobs.items()
            if "configure-aws-credentials" in yaml.dump(job)
        ]
        assert assuming, "no job assumes a role, so this checked nothing"
        for name in assuming:
            assert "preflight" in str(jobs[name].get("needs", "")), (
                f"job {name} assumes the role without waiting for the guard"
            )

    def test_the_built_image_is_checked_against_the_requested_profile(self):
        """`--target` and the stage's own label must agree before the push."""
        runs = _run_text()
        assert "io.experimently.profile" in runs, (
            "nothing verifies that the image built is the profile requested"
        )
