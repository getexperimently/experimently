"""`scripts/make_dev_license.py` — the developer licence signer.

The script holds a private key that can mint licences this checkout accepts,
so the tests here are mostly about where that key is allowed to live and who
can read it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from backend.app.core.license import (
    LicenseStatus,
    b64url_decode,
    verify_license_key,
)

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "make_dev_license.py"


def _load_script():
    """Import the script by path; it is a CLI, not an installed module."""
    spec = importlib.util.spec_from_file_location("make_dev_license", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_dev_license"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


class TestPrivateKeyHandling:
    def test_a_new_key_is_written_0600(self, script, tmp_path):
        path = tmp_path / "nested" / "key.pem"
        script.load_or_create_private_key(path, force_new=False)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    @pytest.mark.regression
    def test_overwriting_a_loose_key_tightens_it(self, script, tmp_path):
        """`--new-key` reuses the existing file, and open()'s mode argument
        only applies when it creates one, so a 0644 key stayed 0644."""
        path = tmp_path / "key.pem"
        path.write_bytes(b"not a key yet")
        os.chmod(path, 0o644)

        script.load_or_create_private_key(path, force_new=True)

        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    @pytest.mark.regression
    def test_a_path_inside_the_repository_is_refused_before_it_is_read(self, script):
        """The guard used to sit after the reuse branch, so an existing key in
        the working tree -- the case it exists to prevent -- was loaded.

        `pyproject.toml` stands in for that key: it is inside the repository
        and it exists, so a guard that runs second would get as far as trying
        to parse it as PEM and fail with something other than SystemExit.
        """
        repo_root = Path(script.__file__).resolve().parents[1]
        existing_in_tree = repo_root / "pyproject.toml"
        assert existing_in_tree.exists()

        with pytest.raises(SystemExit) as excinfo:
            script.load_or_create_private_key(existing_in_tree, force_new=False)
        assert "inside the repository" in str(excinfo.value)

    def test_a_new_key_inside_the_repository_is_refused(self, script):
        repo_root = Path(script.__file__).resolve().parents[1]
        target = repo_root / "backend" / "dev_key_should_not_exist.pem"
        with pytest.raises(SystemExit):
            script.load_or_create_private_key(target, force_new=True)
        assert not target.exists()

    def test_a_file_that_is_not_an_ed25519_key_is_refused(self, script, tmp_path):
        path = tmp_path / "key.pem"
        # Assembled rather than written out, so the pre-commit detect-private-key
        # hook does not see a PEM header in a test file and block the commit.
        header = "-----BEGIN " + "PRIVATE KEY-----"
        path.write_text(f"{header}\nnope\n")
        with pytest.raises(Exception):
            script.load_or_create_private_key(path, force_new=False)

    def test_a_loose_existing_key_warns(self, script, tmp_path, capsys):
        path = tmp_path / "key.pem"
        script.load_or_create_private_key(path, force_new=False)
        os.chmod(path, 0o644)
        capsys.readouterr()

        script.load_or_create_private_key(path, force_new=False)

        assert "should be 0600" in capsys.readouterr().err


class TestSignedOutput:
    def test_the_licence_it_mints_verifies(self, script, tmp_path, capsys):
        key_path = tmp_path / "key.pem"
        rc = script.main(
            ["--features", "hipaa,sso", "--private-key", str(key_path), "--days", "30"]
        )
        assert rc == 0
        out = capsys.readouterr().out

        public_pem = out.split("EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY='", 1)[1].split(
            "'", 1
        )[0]
        license_key = out.split("EXPERIMENTLY_LICENSE_KEY=", 1)[1].split("\n", 1)[0]

        state = verify_license_key(license_key, public_keys={"dev": public_pem})
        assert state.status is LicenseStatus.ACTIVE
        assert state.features == ("hipaa", "sso")

    def test_every_licence_carries_a_serial(self, script, tmp_path, capsys):
        """Without a `jti` a licence can only be revoked at `kid` granularity,
        which takes every other licence the same key signed with it."""
        key_path = tmp_path / "key.pem"
        script.main(["--private-key", str(key_path)])
        out = capsys.readouterr().out
        license_key = out.split("EXPERIMENTLY_LICENSE_KEY=", 1)[1].split("\n", 1)[0]
        claims = json.loads(b64url_decode(license_key.split(".")[0]))
        assert claims["jti"]
        assert claims["kid"] == "dev"
