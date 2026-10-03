"""Every job that assumes the AWS role keeps its session for as long as it can run.

`aws-actions/configure-aws-credentials` asks STS for a one-hour session unless
`role-duration-seconds` says otherwise. A deploy job may run for 160 minutes,
so without it the credentials expire mid-job with ``ExpiredToken`` -- after
the first mutations, with nothing before then to say so.

For each job with a step that uses the action, this pins

    timeout-minutes * 60  <=  role-duration-seconds  <=  10800

The lower bound: the session outlives the job. A job with no
``timeout-minutes`` gets GitHub's default of 360 minutes, which no allowed
session covers, so it fails here. The upper bound is the ``MaxSessionDuration``
that docs/deployment/iam-permissions.md tells each environment role to have;
a request above the role's maximum fails at "Configure AWS credentials".

The scan covers every workflow and local action, so a new file that assumes
the role is held to the same rule.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
GITHUB = REPO_ROOT / ".github"
WORKFLOWS = GITHUB / "workflows"
ACTIONS = GITHUB / "actions"

ACTION = "aws-actions/configure-aws-credentials"
GITHUB_DEFAULT_TIMEOUT_MINUTES = 360
ROLE_MAX_SESSION_SECONDS = 10800

pytestmark = pytest.mark.skipif(
    not WORKFLOWS.is_dir(), reason="this tree has no .github/workflows"
)


def _yaml_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted([*directory.rglob("*.yml"), *directory.rglob("*.yaml")])


def _assumes_role(step: dict[str, Any]) -> bool:
    uses = step.get("uses")
    return isinstance(uses, str) and uses.split("@", 1)[0] == ACTION


def _role_jobs() -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
    """(file, job, job, step) for every step that assumes the role."""
    found = []
    for path in _yaml_files(WORKFLOWS):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, job in (document.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if _assumes_role(step):
                    found.append((path.name, name, job, step))
    return found


ROLE_JOBS = _role_jobs()


def test_the_three_aws_workflows_are_found():
    # Not vacuous: a parser that found nothing would pass every case below.
    files = {file for file, _, _, _ in ROLE_JOBS}
    assert {"deploy.yml", "rollback.yml", "db-migrate.yml"} <= files, files


def test_no_local_action_assumes_the_role():
    # A composite action's step has no job timeout of its own to compare
    # against; if one starts assuming the role, this test has to learn which
    # jobs call it.
    offenders = []
    for path in _yaml_files(ACTIONS):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        steps = (document.get("runs") or {}).get("steps") or []
        offenders += [
            str(path.relative_to(REPO_ROOT)) for s in steps if _assumes_role(s)
        ]
    assert not offenders, offenders


@pytest.mark.regression
@pytest.mark.parametrize(
    ("file", "name", "job", "step"),
    ROLE_JOBS,
    ids=[f"{file}:{name}" for file, name, _, _ in ROLE_JOBS],
)
def test_the_aws_session_lasts_as_long_as_the_job(file, name, job, step):
    timeout = job.get("timeout-minutes", GITHUB_DEFAULT_TIMEOUT_MINUTES)
    assert isinstance(timeout, int), f"{file}:{name} timeout-minutes is {timeout!r}"

    duration = (step.get("with") or {}).get("role-duration-seconds")
    assert duration is not None, (
        f"{file}:{name} assumes the role without role-duration-seconds, so its "
        f"session is the default 3600 s against a {timeout}-minute job"
    )
    assert isinstance(duration, int), (
        f"{file}:{name} role-duration-seconds is {duration!r}"
    )

    assert timeout * 60 <= duration, (
        f"{file}:{name}: timeout-minutes {timeout} ({timeout * 60} s) outlives "
        f"role-duration-seconds {duration}"
    )
    assert duration <= ROLE_MAX_SESSION_SECONDS, (
        f"{file}:{name}: role-duration-seconds {duration} is above the role's "
        f"MaxSessionDuration {ROLE_MAX_SESSION_SECONDS}"
    )
