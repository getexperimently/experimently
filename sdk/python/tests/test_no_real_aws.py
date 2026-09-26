"""The conftest's ``_no_real_aws`` fixture is active in this suite.

Only pytest is installed where this runs in CI, so no boto3 here; the
backend's backend/tests/unit/test_no_real_aws.py covers boto3.
"""

import os
import shutil
import subprocess

UNSET = (
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_SESSION_TOKEN",
    "AWS_ROLE_ARN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
)


def test_aws_cli_runs_the_blocking_fake(_no_real_aws):
    fake = os.path.join(_no_real_aws, "aws")
    # Checked before the call, so a broken gate never runs the real CLI.
    assert shutil.which("aws") == fake

    result = subprocess.run(
        ["aws", "sts", "get-caller-identity"], capture_output=True, text=True
    )

    assert result.returncode == 97
    assert "NO-REAL-AWS" in result.stderr
    assert "Account" not in result.stdout


def test_the_credential_chain_holds_only_dummies():
    assert os.environ["AWS_ACCESS_KEY_ID"] == "no-real-aws-dummy"
    assert os.environ["AWS_SECRET_ACCESS_KEY"] == "no-real-aws-dummy"
    assert os.environ["AWS_EC2_METADATA_DISABLED"] == "true"
    for name in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
        assert not os.path.exists(os.environ[name]), name
    for name in UNSET:
        assert name not in os.environ, name
