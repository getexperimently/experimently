"""The three requirements files must agree, and something must watch them all.

``backend/requirements.txt`` is the superset every CI job and every developer
venv installs.  ``backend/requirements/runtime.txt`` (+ ``.lock``) is the
subset the shipped image installs, and its own header says "Keep the pins
identical to backend/requirements.txt".  Nothing enforced that, and Dependabot
watched only ``/backend`` -- whose pip file fetcher sees ``requirements.txt``
at that directory's root, not ``requirements/runtime.txt`` below it and not
referenced by any ``-r``.  A security bump could therefore land in
``requirements.txt``, go green, and ship an image still running the old
version.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
SCRIPT = REPO_ROOT / "scripts" / "check_requirements_lock.py"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture
def checker():
    if not SCRIPT.is_file():
        pytest.skip("this tree has no scripts/check_requirements_lock.py")
    import check_requirements_lock

    return check_requirements_lock


class TestTheSupersetCheck:
    @staticmethod
    def _write(tmp_path: Path, name: str, body: str) -> Path:
        path = tmp_path / name
        path.write_text(body)
        return path

    @pytest.mark.regression
    def test_a_pin_bumped_in_one_file_only_is_reported(self, checker, tmp_path):
        """The Dependabot shape: requirements.txt moves, runtime.txt does not."""
        subset = self._write(tmp_path, "runtime.txt", "fastapi==0.141.1\n")
        superset = self._write(tmp_path, "requirements.txt", "fastapi==0.142.0\n")
        problems = checker.check_superset(subset, superset, every_pin=True)
        assert len(problems) == 1
        assert "fastapi" in problems[0]
        assert "0.141.1" in problems[0] and "0.142.0" in problems[0]

    @pytest.mark.regression
    def test_a_runtime_pin_absent_from_the_superset_is_reported(
        self, checker, tmp_path
    ):
        subset = self._write(tmp_path, "runtime.txt", "watchtower==3.4.0\n")
        superset = self._write(tmp_path, "requirements.txt", "fastapi==0.141.1\n")
        problems = checker.check_superset(subset, superset, every_pin=True)
        assert len(problems) == 1
        assert "watchtower" in problems[0]

    def test_module_only_pins_are_allowed_to_be_module_only(self, checker, tmp_path):
        """python3-saml and the warehouse drivers belong nowhere but
        modules/requirements.txt, so that pair compares shared pins only."""
        subset = self._write(
            tmp_path, "modules.txt", "python3-saml==1.16.0\nrequests==2.34.2\n"
        )
        superset = self._write(tmp_path, "requirements.txt", "requests==2.34.2\n")
        assert checker.check_superset(subset, superset, every_pin=False) == []
        assert checker.check_superset(subset, superset, every_pin=True) != []

    def test_the_real_tree_is_consistent(self, checker, capsys):
        assert checker.main() == 0, capsys.readouterr().out


@pytest.mark.skipif(
    not DEPENDABOT.is_file(), reason="this tree has no .github/dependabot.yml"
)
class TestDependabotCoverage:
    @staticmethod
    def _pip_directories() -> set[str]:
        config = yaml.safe_load(DEPENDABOT.read_text())
        directories: set[str] = set()
        for update in config["updates"]:
            if update["package-ecosystem"] != "pip":
                continue
            if "directory" in update:
                directories.add(update["directory"])
            directories.update(update.get("directories", []))
        return directories

    @pytest.mark.regression
    def test_the_files_the_image_installs_are_watched(self):
        """`/backend` does not cover `backend/requirements/runtime.txt`:
        Dependabot's pip fetcher reads the `.txt`/`.in` files at the named
        directory's root plus whatever a `-r` pulls in, and nothing pulls in
        runtime.txt."""
        directories = self._pip_directories()
        assert "/backend/requirements" in directories, (
            "nothing watches backend/requirements/runtime.txt, the only pin "
            f"file the shipped image installs; pip entries: {sorted(directories)}"
        )

    def test_every_pinned_requirements_file_in_the_tree_is_covered(self):
        """A requirements file nobody watches is a dependency nobody updates.

        Files that pin nothing of their own are skipped: the repository root's
        `requirements.txt` is one `-r backend/requirements.txt` line, and
        pointing Dependabot at it would only duplicate the `/backend` entry's
        pull requests.
        """
        import check_requirements_lock as checker

        directories = self._pip_directories()
        uncovered = []
        for path in sorted(REPO_ROOT.glob("**/requirements*.txt")):
            relative = path.relative_to(REPO_ROOT)
            parts = relative.parts
            if any(
                part in {"venv", ".venv", "node_modules", "build", "tests", "dist"}
                for part in parts
            ):
                continue
            if not checker.read_pins(path):
                continue  # a pointer file, nothing of its own to bump
            watched = "/" + "/".join(parts[:-1]) if len(parts) > 1 else "/"
            if watched not in directories:
                uncovered.append(str(relative))
        assert not uncovered, f"no Dependabot pip entry covers: {uncovered}"
