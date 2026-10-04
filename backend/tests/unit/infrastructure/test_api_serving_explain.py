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

`--explain` (first argument only) adds one last stdout line naming why the
exit is what it is. With it, each case's output is the golden plus exactly
that line; without it, the golden.

Every case runs the script as a subprocess against the fake `aws` of
test_forward_deploy_completes, first on PATH, with no credentials.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys

import pytest

from .test_forward_deploy_completes import (
    AFTER,
    BEFORE,
    BLUE,
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
    _services,
    _split,
    _task_set,
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


# --- --explain -------------------------------------------------------------------

#: The word each case must explain itself with.
WORDS = {
    "old-primary": "primary-other",
    "split": "listener-split",
    "wrong-group": "listener-other",
    "other-arn": "primary-other",
    "family-revision": "serving",
    "same-family-other-revision": "primary-other",
    "other-family-same-revision": "primary-other",
    "family-not-arn": "unknown",
    "serving": "serving",
    "null-weight": "unknown",
    "missing-aws": "unknown",
    # `--explain` first, and four arguments after it: the usage error.
    "fourth-argument": "unknown",
}
EXIT_FOR_WORD = {
    "serving": 0,
    "primary-other": 1,
    "listener-split": 1,
    "listener-other": 3,
    "unknown": 2,
}


def _module():
    spec = importlib.util.spec_from_file_location("api_serving", SERVING)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_word_is_reached_and_none_other():
    assert set(WORDS) == set(CASES)
    assert set(WORDS.values()) == _module().EXPLAIN_WORDS == set(EXIT_FOR_WORD)


@pytest.mark.parametrize("case", list(CASES))
def test_explain_adds_one_last_stdout_line_and_nothing_else(serving, case):
    services, rules, argv = CASES[case]
    code, stdout, stderr = serving(services, rules, ["--explain", *argv])
    golden_code, golden_stdout, golden_stderr = GOLDEN[case]
    assert (code, stdout, stderr) == (
        golden_code,
        golden_stdout + f"explain: {WORDS[case]}\n",
        golden_stderr,
    )
    assert re.fullmatch(
        r"explain: (serving|primary-other|listener-split|listener-other|unknown)",
        stdout.splitlines()[-1],
    )
    assert EXIT_FOR_WORD[WORDS[case]] == code


@pytest.mark.parametrize(
    "argv",
    [
        [CLUSTER, "--explain", SERVICE, NEW],
        [CLUSTER, SERVICE, "--explain", NEW],
    ],
    ids=["second", "third"],
)
def test_explain_anywhere_but_first_is_the_usage_error(serving, argv):
    assert serving(AFTER, RULES_GREEN, argv) == GOLDEN["fourth-argument"]


#: Run 37176250648's summary, read 1 of 12, verbatim from its log.
CAPTURED_37176250648 = (
    "serving: experimentation-backend-staging:2 is the PRIMARY task set and the "
    "/api/* rule forwards to blue alone"
)
#: That run's target, with the account masked in the log replaced.
TARGET_37176250648 = "arn:aws:ecs:us-west-2:123456789012:task-definition/experimentation-backend-staging:2"


@pytest.mark.parametrize("flag", [[], ["--explain"]], ids=["default", "explain"])
def test_the_captured_serving_line_of_a_real_run_is_reproduced(serving, flag):
    services = _services(_task_set(TARGET_37176250648, BLUE, "PRIMARY"))
    code, stdout, stderr = serving(
        services, RULES_BLUE, [*flag, CLUSTER, SERVICE, TARGET_37176250648]
    )
    assert (code, stderr) == (0, "")
    assert stdout.splitlines()[0] == CAPTURED_37176250648
    assert stdout.splitlines()[-1] == (
        "explain: serving"
        if flag
        else (
            "live API target group: blue; the next cdk deploy of the Fargate stack "
            "takes -c api_live_target_group=blue"
        )
    )


@pytest.mark.parametrize(
    "services, rules, arn, expected",
    [
        (AFTER, RULES_GREEN, NEW, (0, "serving")),
        (BEFORE, RULES_BLUE, NEW, (1, "primary-other")),
        (AFTER, _split(50, 50), NEW, (1, "listener-split")),
        (AFTER, RULES_BLUE, NEW, (3, "listener-other")),
        (AFTER, RULES_GREEN, "experimentation-backend-staging", (2, "unknown")),
    ],
    ids=["serving", "primary-other", "listener-split", "listener-other", "unknown"],
)
def test_verdict_keeps_its_three_tuple(services, rules, arn, expected):
    """shift_traffic.py unpacks `verdict()` into three names; the word stays
    in the private `_verdict()`."""
    module = _module()
    responses = tick("InProgress", services, rules)

    def aws(argv):
        return json.loads(json.dumps(responses[" ".join(argv[:2])]))

    three = module.verdict(aws, CLUSTER, SERVICE, arn)
    four = module._verdict(aws, CLUSTER, SERVICE, arn)
    assert len(three) == 3
    assert three == four[:3]
    assert (four[0], four[3]) == expected
