"""`api_serving.py`'s default output is pinned byte for byte (#759).

`scripts/api_serving.py` is on the forward deploy's path: deploy.yml merges
its two streams and takes the last line, and `shift_traffic.py` imports
`verdict()`. Anything added to the script for the rollback's summary must
leave that output exactly as it is.

GOLDEN holds (exit, stdout, stderr), compared as three separate values, for
every case of test_forward_deploy_completes' `test_the_predicate_exit_codes`
plus serving, a null weight in the rule, a missing `aws` binary, a fourth
argument and one run through the command line. It was generated from
GOLDEN_SOURCE's `scripts/api_serving.py`, before anything in this file's pull
request changed the script, and is inlined here so that the change cannot
regenerate it. A merged capture would hide a line that moved from one stream
to the other; separate ones do not.

Every case runs the script as a subprocess against the fake `aws` of
test_forward_deploy_completes, first on PATH, with no credentials.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys

import pytest

from .test_forward_deploy_completes import (
    AFTER,
    BEFORE,
    CLUSTER,
    FAKE_AWS,
    NEW,
    OLD,
    RULES_BLUE,
    RULES_GREEN,
    SERVICE,
    SERVING,
    _no_aws_credentials,
    _null_weight,
    _split,
    tick,
)

#: The commit whose scripts/api_serving.py produced GOLDEN.
GOLDEN_SOURCE = "756885e9de204cd46bc7fab2b1ba88d685fd9de4"

#: id -> (services, rules, argv). None for services means "no fake aws on PATH".
CASES: dict[str, tuple[dict | None, dict | None, list[str]]] = {
    # test_the_predicate_exit_codes, in its order
    "old-primary": (BEFORE, RULES_BLUE, [CLUSTER, SERVICE, NEW]),
    "split": (AFTER, _split(50, 50), [CLUSTER, SERVICE, NEW]),
    "wrong-group": (AFTER, RULES_BLUE, [CLUSTER, SERVICE, NEW]),
    "other-arn": (AFTER, RULES_GREEN, [CLUSTER, SERVICE, OLD]),
    "family-revision": (
        AFTER,
        RULES_GREEN,
        [CLUSTER, SERVICE, "experimentation-backend-staging:43"],
    ),
    "same-family-other-revision": (
        AFTER,
        RULES_GREEN,
        [CLUSTER, SERVICE, "experimentation-backend-staging:42"],
    ),
    "other-family-same-revision": (
        AFTER,
        RULES_GREEN,
        [CLUSTER, SERVICE, "experimentation-dashboard-staging:43"],
    ),
    "family-not-arn": (
        AFTER,
        RULES_GREEN,
        [CLUSTER, SERVICE, "experimentation-backend-staging"],
    ),
    # and the rest
    "serving": (AFTER, RULES_GREEN, [CLUSTER, SERVICE, NEW]),
    "null-weight": (AFTER, _null_weight(), [CLUSTER, SERVICE, NEW]),
    "missing-aws": (None, None, [CLUSTER, SERVICE, NEW]),
    "fourth-argument": (AFTER, RULES_GREEN, [CLUSTER, SERVICE, NEW, "--explain"]),
}

GOLDEN: dict[str, tuple[int, str, str]] = {
    "old-primary": (
        1,
        "",
        "NOT YET: the PRIMARY task set runs experimentation-backend-staging:42, not experimentation-backend-staging:43\n",
    ),
    "split": (
        1,
        "",
        "NOT YET: the PRIMARY task set runs experimentation-backend-staging:43; the /api/* rule forwards to 2 target groups with weight: a CodeDeploy traffic shift is in progress. Wait for it to finish.\n",
    ),
    "wrong-group": (
        3,
        "",
        "WRONG: the PRIMARY task set runs experimentation-backend-staging:43, but the load balancer sends the API to blue but the tasks serving the current release are in green. The API route is already pointing at the wrong target group; no value of api_live_target_group is safe until that is repaired.\n",
    ),
    "other-arn": (
        1,
        "",
        "NOT YET: the PRIMARY task set runs experimentation-backend-staging:43, not experimentation-backend-staging:42\n",
    ),
    "family-revision": (
        0,
        "serving: experimentation-backend-staging:43 is the PRIMARY task set and the /api/* rule forwards to green alone\nlive API target group: green; the next cdk deploy of the Fargate stack takes -c api_live_target_group=green\n",
        "",
    ),
    "same-family-other-revision": (
        1,
        "",
        "NOT YET: the PRIMARY task set runs experimentation-backend-staging:43, not experimentation-backend-staging:42\n",
    ),
    "other-family-same-revision": (
        1,
        "",
        "NOT YET: the PRIMARY task set runs experimentation-backend-staging:43, not experimentation-dashboard-staging:43\n",
    ),
    "family-not-arn": (
        2,
        "",
        "UNKNOWN: 'experimentation-backend-staging' is not a task-definition revision ARN or family:n\n",
    ),
    "serving": (
        0,
        "serving: experimentation-backend-staging:43 is the PRIMARY task set and the /api/* rule forwards to green alone\nlive API target group: green; the next cdk deploy of the Fargate stack takes -c api_live_target_group=green\n",
        "",
    ),
    "null-weight": (
        2,
        "",
        "UNKNOWN: could not tell: TypeError: '>' not supported between instances of 'NoneType' and 'int'\n",
    ),
    "missing-aws": (
        2,
        "",
        "UNKNOWN: could not tell: FileNotFoundError: [Errno 2] No such file or directory: 'aws'\n",
    ),
    "fourth-argument": (
        2,
        "",
        "usage: api_serving.py <cluster> <service> <task-definition ARN>\n",
    ),
}


@pytest.fixture
def serving(tmp_path):
    """Return a runner: (services, rules, argv) -> (exit, stdout, stderr)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS.replace("{python}", sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    empty = tmp_path / "no-aws"
    empty.mkdir()
    state = tmp_path / "state"
    state.mkdir()

    def run(services: dict | None, rules: dict | None, argv: list[str]):
        if services is None:
            path = str(empty)
        else:
            path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            (state / "scenario.json").write_text(
                json.dumps({"responses": tick("InProgress", services, rules)})
            )
        result = subprocess.run(
            [sys.executable, str(SERVING), *argv],
            env=_no_aws_credentials(
                {**os.environ, "PATH": path, "FAKE_AWS_STATE": str(state)}
            ),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode, result.stdout, result.stderr

    return run


def test_the_golden_covers_every_case():
    assert set(GOLDEN) == set(CASES)


@pytest.mark.parametrize("case", list(CASES))
def test_the_default_output_is_byte_identical_to_the_golden(serving, case):
    assert serving(*CASES[case]) == GOLDEN[case]
