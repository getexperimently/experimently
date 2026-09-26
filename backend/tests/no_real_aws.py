"""No test can reach real AWS credentials or the real ``aws`` binary.

A pytest plugin, loaded for every pytest session whose rootdir is the
repository root by ``conftest.py`` at the root (``pytest_plugins``). That is
every Python suite CI runs except the two SDKs, which have their own rootdir
(``sdk/*/pyproject.toml``) and carry a copy of this in their own conftest;
``backend/tests/unit/test_no_real_aws.py`` keeps the copies in step and proves
each root actually loads it.

Why: during a tamper test a unit test whose guard was deliberately broken sent
a real ``aws deploy stop-deployment``. It failed only because that machine had
no valid credentials. On a developer machine that does hold them it would have
acted on a real account.

What it does, at ``pytest_configure`` (before collection, so before any
import-time client or session fixture) and again before every test (a test may
leave the environment dirty):

* the credential chain, for the CLI and boto3 alike, holds only dummies:
  ``AWS_ACCESS_KEY_ID``/``AWS_SECRET_ACCESS_KEY`` are set to a dummy (set,
  not removed -- moto and the other mocks need *some* credentials),
  ``AWS_CONFIG_FILE``/``AWS_SHARED_CREDENTIALS_FILE`` point at files that do
  not exist (so ``~/.aws`` is never read), every other source of credentials
  (profile, session token, assume-role, web identity, container, IMDS) is
  unset or disabled;
* a failing ``aws`` is first on ``PATH``. It appends its arguments to
  ``calls.log`` beside itself, prints :data:`MARKER` and exits
  :data:`FAKE_EXIT`. A test that installs its own fake ``aws`` prepends its
  directory to ``PATH`` after this has run, so its fake wins.

It does not touch ``AWS_DEFAULT_REGION``/``AWS_REGION`` or any endpoint
variable: those are not credentials, and tests set them deliberately.

What it cannot reach: a subprocess started with a hand-built environment that
drops these variables but keeps ``HOME``. Such a subprocess would read
``~/.aws`` again if it used boto3. It would still find the fake ``aws`` if it
inherited ``PATH``.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

import pytest

MARKER = "NO-REAL-AWS"
FAKE_EXIT = 97
DUMMY_CREDENTIAL = "no-real-aws-dummy"

# Set to a dummy value: present, so mocks work, and worthless to a real endpoint.
DUMMY = {
    "AWS_ACCESS_KEY_ID": DUMMY_CREDENTIAL,
    "AWS_SECRET_ACCESS_KEY": DUMMY_CREDENTIAL,
    "AWS_EC2_METADATA_DISABLED": "true",
}

# Pointed at a path that does not exist: neither the CLI nor botocore reads ~/.aws.
MISSING_FILES = ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE")

# Removed: every other way botocore or the CLI finds credentials.
UNSET = (
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",  # botocore's legacy alias for AWS_SESSION_TOKEN
    "AWS_CREDENTIAL_EXPIRATION",
    "AWS_ROLE_ARN",
    "AWS_ROLE_SESSION_NAME",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
)

FAKE_AWS = f"""#!/bin/sh
# Installed by backend/tests/no_real_aws.py: no test may run the real aws CLI.
printf '%s\\n' "$*" >> "$(dirname "$0")/calls.log"
echo "{MARKER}: the aws CLI is blocked in tests (called: aws $*)." >&2
echo "{MARKER}: put your own fake aws first on PATH." >&2
exit {FAKE_EXIT}
"""


def _install_fake(bin_dir: Path) -> None:
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _isolate(mp: pytest.MonkeyPatch, bin_dir: Path) -> None:
    for name, value in DUMMY.items():
        mp.setenv(name, value)
    for name in MISSING_FILES:
        mp.setenv(name, str(bin_dir / "missing" / name.lower()))
    for name in UNSET:
        mp.delenv(name, raising=False)
    path = os.environ.get("PATH", "")
    if path.split(os.pathsep, 1)[0] != str(bin_dir):
        mp.setenv("PATH", f"{bin_dir}{os.pathsep}{path}" if path else str(bin_dir))


_session: pytest.MonkeyPatch | None = None
_bin_dir: Path | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Before collection: covers import-time clients and session fixtures."""
    global _session, _bin_dir
    _bin_dir = Path(tempfile.mkdtemp(prefix="no-real-aws-"))
    _install_fake(_bin_dir)
    _session = pytest.MonkeyPatch()
    _isolate(_session, _bin_dir)


def pytest_unconfigure(config: pytest.Config) -> None:
    global _session, _bin_dir
    if _session is not None:
        _session.undo()
        _session = None
    if _bin_dir is not None:
        shutil.rmtree(_bin_dir, ignore_errors=True)
        _bin_dir = None


@pytest.fixture(autouse=True)
def _no_real_aws(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per test: re-applied, in case an earlier test left AWS_* behind.

    Returns the directory holding the fake ``aws`` (and its ``calls.log``).
    """
    assert _bin_dir is not None, "backend.tests.no_real_aws was not configured"
    _isolate(monkeypatch, _bin_dir)
    return _bin_dir
