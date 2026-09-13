"""``scripts/check_modules_register.py`` and the CI job that runs it.

Round 2 moved ``defusedxml`` out of ``backend/requirements.txt`` while
``modules/backend/app/services/sso_service.py`` still imports it unguarded.
Every Python job installs that file and only that file, so the registration
broke everywhere at once -- and said so only as ``pytest.exit(3)`` with zero
tests collected, which is not a message anyone can act on.  No local run could
see it either: a developer venv has every package.

So there is now a job whose whole purpose is that environment, and a script
that states the expectation in one place.  These checks pin both.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "check_modules_register.py"
GATE = REPO_ROOT / ".github" / "workflows" / "pr-qa-gate.yml"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture
def check():
    if not SCRIPT.is_file():
        pytest.skip("this tree has no scripts/check_modules_register.py")
    import check_modules_register

    return check_modules_register


@pytest.mark.skipif(
    not (REPO_ROOT / "modules").is_dir(), reason="core checkout: no modules/"
)
class TestTheCheckItself:
    def test_it_passes_on_a_full_checkout(self):
        """Run as CI runs it: a fresh interpreter, no test harness.

        In-process is not an option for the happy path -- this suite patches
        ``logging.getLogger``, so the script's own log capture would see
        nothing and report a failure that is not there.
        """
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "APP_ENV": "test", "TESTING": "true"},
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "audit signer: AuditSigningService" in completed.stdout
        assert "loader said: Modules loaded" in completed.stdout

    @pytest.mark.regression
    def test_it_fails_when_the_registration_failed(self, check, monkeypatch, capsys):
        """The shape of the ``defusedxml`` break: modules/ present, import
        raises, loader records the failure and runs the core profile."""
        from backend.app import modules_loader

        monkeypatch.setattr(modules_loader, "load_modules", lambda **_: False)
        monkeypatch.setattr(
            modules_loader,
            "modules_failure",
            lambda: "No module named 'defusedxml'",
        )
        assert check.main() == 1
        assert "defusedxml" in capsys.readouterr().out

    @pytest.mark.regression
    def test_it_fails_when_the_routers_registered_but_never_mounted(
        self, check, monkeypatch, capsys
    ):
        """The failure this job exists to catch, and the one it could not see.

        Registering the module routers and mounting them are two steps
        (``modules_loader.mount_module_routers``), and the second fails on its
        own: the process keeps serving the core API while every module route
        404s.  The check used to call ``load_modules(force=True)`` *first*, and
        ``_load()`` opens with ``_failure = None`` -- so the mount failure
        recorded during the import was wiped, and a forced registration never
        re-runs the mounting, so it could not be recorded again.  Nothing else
        noticed either: every registry still answers as if the modules were
        serving, and ``abort_if_modules_broken()`` only logs under the
        ``APP_ENV=test`` this script sets.
        """
        from backend.app import modules_loader

        failure = (
            "mounting the modules' routers raised AttributeError: module "
            "'integrations' has no attribute 'public_router'"
        )
        monkeypatch.setattr(modules_loader, "_state", True)
        monkeypatch.setattr(modules_loader, "_failure", failure)

        def load_and_clear(force=False, with_routers=True):
            # Exactly what the real `_load()` does on its first line.
            modules_loader._failure = None
            return True

        monkeypatch.setattr(modules_loader, "load_modules", load_and_clear)

        assert check.main() == 1
        assert failure in capsys.readouterr().out

    @pytest.mark.regression
    def test_it_fails_when_the_application_serves_no_module_route(
        self, check, monkeypatch, capsys
    ):
        """The registries are a claim; the route table is the observation."""
        from backend.app import modules_loader

        def load_and_log(force=False, with_routers=True):
            modules_loader.logger.info("Modules loaded (from %s)", "modules")
            return True

        monkeypatch.setattr(modules_loader, "load_modules", load_and_log)
        monkeypatch.setattr(modules_loader, "modules_failure", lambda: None)
        monkeypatch.setattr(
            check, "iter_route_paths", lambda app: ["/api/v1/experiments", "/health"]
        )

        assert check.main() == 1
        out = capsys.readouterr().out
        assert "serves no route under" in out
        assert "/api/v1/workspaces" in out

    def test_every_module_route_prefix_is_really_mounted(self, check):
        """MODULE_ROUTE_PREFIXES is the contract, so it has to be true here."""
        from backend.app.main import app

        paths = set(check.iter_route_paths(app))
        assert paths, "no routes could be read off the application"
        for prefix in check.MODULE_ROUTE_PREFIXES:
            assert any(path.startswith(prefix) for path in paths), (
                f"nothing is mounted under {prefix!r}; if the registration "
                "dropped it, drop it from MODULE_ROUTE_PREFIXES too"
            )

    def test_it_fails_when_the_audit_signer_is_the_null_one(
        self, check, monkeypatch, capsys
    ):
        """A registration can report success and still leave compliance
        events unsigned; that is the state production must never reach
        without asking for it."""
        from backend.app import modules_loader
        from backend.app.core import hooks

        # The registration installs the real signer, so a forced reload would
        # undo the patch: this is a registration that *claims* success.
        monkeypatch.setattr(modules_loader, "load_modules", lambda **_: True)
        monkeypatch.setattr(modules_loader, "modules_failure", lambda: None)
        monkeypatch.setattr(hooks, "audit_signer", hooks.NullAuditSigner())
        assert check.main() == 1
        assert "NullAuditSigner" in capsys.readouterr().out


@pytest.mark.skipif(not GATE.is_file(), reason="this tree has no .github/workflows")
class TestTheCIJob:
    @staticmethod
    def _job() -> dict:
        jobs = yaml.safe_load(GATE.read_text())["jobs"]
        for job in jobs.values():
            for step in job.get("steps", []):
                if "check_modules_register.py" in str(step.get("run", "")):
                    return job
        raise AssertionError(
            "no PR-gate job runs scripts/check_modules_register.py: nothing "
            "proves the modules register on backend/requirements.txt alone"
        )

    @pytest.mark.regression
    def test_a_pr_job_proves_the_modules_register(self):
        assert self._job()["steps"]

    @pytest.mark.regression
    def test_that_job_installs_backend_requirements_and_nothing_else(self):
        """The point of the job is what is *missing* from its interpreter."""
        installs = [
            str(step.get("run", ""))
            for step in self._job()["steps"]
            if "pip install" in str(step.get("run", ""))
        ]
        assert installs, "the job installs nothing"
        joined = "\n".join(installs)
        assert "backend/requirements.txt" in joined
        assert "modules/requirements.txt" not in joined, (
            "installing the modules' own pins defeats the job: it exists to "
            "prove the registration survives WITHOUT them"
        )
        assert "requirements/dev.txt" not in joined

    def test_that_job_also_runs_the_smoke_suite(self):
        runs = "\n".join(str(step.get("run", "")) for step in self._job()["steps"])
        assert "backend/tests/smoke" in runs
