"""The two new security gates, tested by breaking what they guard.

``scripts/audit_dependencies.py`` and ``scripts/check_node_licences.py`` are
blocking CI steps: one decides whether a dependency advisory stops a merge, the
other whether a licence does. CLAUDE.md is explicit that "when you add or
change a gate, break the thing it guards and watch it fail", and that a
rehearsal repeated by hand belongs in CI. These are those rehearsals.

Neither test runs ``pip-audit`` or ``license-checker``: both are slow and need
the network, and neither is the thing under test. The *decision logic* is --
which advisories are accepted, which exceptions are stale, which licence
expressions satisfy an allow-list -- so the tools are stubbed at the one
function that calls them and the logic is exercised directly.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]

# `regression` as well as `unit`: every case here encodes a specific defect this
# change fixed -- id-only exception matching, an unparsed review_by, a discarded
# exit status, list-valued and object-valued `licenses`, a frontend-only licence
# scope, a gate that passed on an uninstalled tree -- and CLAUDE.md requires a
# bug fix to carry a test that `pytest -m regression` selects.
pytestmark = [pytest.mark.unit, pytest.mark.regression]


def load(name: str) -> ModuleType:
    """Import a script from scripts/ by path (they are not a package)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# scripts/audit_dependencies.py
# ---------------------------------------------------------------------------


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return load("audit_dependencies")


def write_ignores(module: ModuleType, tmp_path: Path, entries: str) -> None:
    path = tmp_path / "dependency-audit.toml"
    path.write_text(textwrap.dedent(entries), encoding="utf-8")
    module.IGNORE_FILE = path


def stub_advisories(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    by_file: dict[str, list[tuple[str, str, str]]],
) -> None:
    """Replace pip-audit with a table of findings, keyed by requirements path."""

    def fake(requirements: Path) -> list:
        return [module.Advisory(t) for t in by_file.get(Path(requirements).name, [])]

    monkeypatch.setattr(module, "run_pip_audit", fake)
    # Only files that exist are scanned; point both tiers at real ones.
    monkeypatch.setattr(
        module, "SHIPPED_FILES", (Path("backend/requirements/runtime.lock"),)
    )
    monkeypatch.setattr(
        module, "DEVELOPMENT_FILES", (Path("backend/requirements.txt"),)
    )


def run_audit(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> int:
    """The script's exit status, however it chose to report it.

    `main()` returns 0/1, but `load_ignores()` raises `SystemExit("message")` --
    a *string* code, which Python prints and exits 1 on. Treating any non-zero,
    non-integer code as failure is what a shell sees.
    """
    monkeypatch.setattr(sys, "argv", ["audit_dependencies.py"])
    try:
        return module.main()
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1


FUTURE = (date.today() + timedelta(days=365)).isoformat()


def test_a_clean_tree_passes(audit, monkeypatch, tmp_path) -> None:
    stub_advisories(audit, monkeypatch, {})
    write_ignores(audit, tmp_path, "")
    assert run_audit(audit, monkeypatch) == 0


def test_an_advisory_in_a_shipped_closure_fails(audit, monkeypatch, tmp_path) -> None:
    """The one rule with no exception: nothing shipped may carry an advisory."""
    stub_advisories(
        audit, monkeypatch, {"runtime.lock": [("thrift", "0.20.0", "PYSEC-1")]}
    )
    write_ignores(audit, tmp_path, "")
    assert run_audit(audit, monkeypatch) == 1


def test_a_shipped_advisory_cannot_be_excepted(audit, monkeypatch, tmp_path) -> None:
    """Even with an entry written for it -- the file must not be able to say yes."""
    stub_advisories(
        audit, monkeypatch, {"runtime.lock": [("thrift", "0.20.0", "PYSEC-1")]}
    )
    write_ignores(
        audit,
        tmp_path,
        f'''
        [[ignore]]
        id = "PYSEC-1"
        package = "thrift"
        reason = "we would rather not"
        review_by = "{FUTURE}"
        ''',
    )
    assert run_audit(audit, monkeypatch) == 1


def test_an_unlisted_development_advisory_fails(audit, monkeypatch, tmp_path) -> None:
    stub_advisories(
        audit, monkeypatch, {"requirements.txt": [("pytest", "7.4.2", "PYSEC-2")]}
    )
    write_ignores(audit, tmp_path, "")
    assert run_audit(audit, monkeypatch) == 1


def test_a_listed_development_advisory_passes(audit, monkeypatch, tmp_path) -> None:
    stub_advisories(
        audit, monkeypatch, {"requirements.txt": [("pytest", "7.4.2", "PYSEC-2")]}
    )
    write_ignores(
        audit,
        tmp_path,
        f'''
        [[ignore]]
        id = "PYSEC-2"
        package = "pytest"
        reason = "test runner, not shipped"
        review_by = "{FUTURE}"
        ''',
    )
    assert run_audit(audit, monkeypatch) == 0


def test_an_exception_for_the_wrong_package_fails(audit, monkeypatch, tmp_path) -> None:
    """The id matched but the package did not.

    Matching on the id alone let an entry written against one package silence an
    advisory that pip-audit attributes to another -- and the "does it ship?"
    check then compared the wrong name.
    """
    stub_advisories(
        audit, monkeypatch, {"requirements.txt": [("cryptography", "1.0", "PYSEC-2")]}
    )
    write_ignores(
        audit,
        tmp_path,
        f'''
        [[ignore]]
        id = "PYSEC-2"
        package = "pytest"
        reason = "test runner, not shipped"
        review_by = "{FUTURE}"
        ''',
    )
    assert run_audit(audit, monkeypatch) == 1


def test_a_stale_exception_fails(audit, monkeypatch, tmp_path) -> None:
    """An exception whose advisory no longer fires must be removed, not kept."""
    stub_advisories(audit, monkeypatch, {})
    write_ignores(
        audit,
        tmp_path,
        f'''
        [[ignore]]
        id = "PYSEC-GONE"
        package = "ecdsa"
        reason = "no longer reported"
        review_by = "{FUTURE}"
        ''',
    )
    assert run_audit(audit, monkeypatch) == 1


def test_an_expired_review_date_fails(audit, monkeypatch, tmp_path) -> None:
    stub_advisories(
        audit, monkeypatch, {"requirements.txt": [("pytest", "7.4.2", "PYSEC-2")]}
    )
    write_ignores(
        audit,
        tmp_path,
        """
        [[ignore]]
        id = "PYSEC-2"
        package = "pytest"
        reason = "test runner"
        review_by = "2020-01-01"
        """,
    )
    assert run_audit(audit, monkeypatch) == 1


def test_a_non_date_review_by_fails(audit, monkeypatch, tmp_path) -> None:
    stub_advisories(
        audit, monkeypatch, {"requirements.txt": [("pytest", "7.4.2", "PYSEC-2")]}
    )
    write_ignores(
        audit,
        tmp_path,
        """
        [[ignore]]
        id = "PYSEC-2"
        package = "pytest"
        reason = "test runner"
        review_by = "whenever"
        """,
    )
    assert run_audit(audit, monkeypatch) == 1


def test_an_empty_reason_fails(audit, monkeypatch, tmp_path) -> None:
    stub_advisories(
        audit, monkeypatch, {"requirements.txt": [("pytest", "7.4.2", "PYSEC-2")]}
    )
    write_ignores(
        audit,
        tmp_path,
        f'''
        [[ignore]]
        id = "PYSEC-2"
        package = "pytest"
        reason = ""
        review_by = "{FUTURE}"
        ''',
    )
    assert run_audit(audit, monkeypatch) == 1


def test_a_skipped_package_is_not_a_clean_audit(monkeypatch, tmp_path) -> None:
    """pip-audit reporting `skip_reason` must fail, not read as zero findings.

    This is what made `--strict` inert: the exit status was discarded and a
    package pip-audit could not resolve produced an empty `vulns` list, so the
    gate printed "no unaccepted advisories" while a package went unaudited.
    """
    module = load("audit_dependencies")
    payload = json.dumps(
        {
            "dependencies": [
                {"name": "mystery", "skip_reason": "Dependency not found on PyPI"}
            ]
        }
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout=payload, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as excinfo:
        module.run_pip_audit(ROOT / "backend" / "requirements.txt")
    assert "could not audit" in str(excinfo.value)


def test_every_deployed_closure_is_in_a_tier() -> None:
    """The Lambda closures are deployed to AWS and were in neither tier."""
    module = load("audit_dependencies")
    tiers = set(module.SHIPPED_FILES) | set(module.DEVELOPMENT_FILES)
    for lambda_dir in sorted((ROOT / "backend" / "lambda").iterdir()):
        requirements = lambda_dir / "requirements.txt"
        if requirements.is_file():
            relative = requirements.relative_to(ROOT)
            assert relative in tiers, (
                f"{relative} is deployed to AWS but no tier audits it"
            )


# ---------------------------------------------------------------------------
# scripts/check_node_licences.py
# ---------------------------------------------------------------------------


@pytest.fixture
def licences() -> ModuleType:
    return load("check_node_licences")


@pytest.mark.parametrize(
    "expression",
    [
        "MIT",
        "ISC",
        "Apache-2.0",
        "(MIT OR Apache-2.0)",
        "MIT OR GPL-3.0",  # a disjunction with one allowed term
        "MIT AND ISC",
        "BSD*",  # license-checker's inferred/non-SPDX marker
        "BSD",
    ],
)
def test_allowed_expressions(licences, expression: str) -> None:
    assert licences.is_allowed(expression), expression


@pytest.mark.parametrize(
    "expression",
    [
        "GPL-3.0",
        "AGPL-3.0",
        "SSPL-1.0",
        "MIT AND GPL-3.0",  # a conjunction is only as good as its worst term
        "UNLICENSED",
        "UNKNOWN",
        "",
    ],
)
def test_refused_expressions(licences, expression: str) -> None:
    assert not licences.is_allowed(expression), expression


def installed_tree(tmp_path: Path) -> Path:
    """A directory shaped like an installed npm package.

    `licences_of` refuses a tree with no node_modules, so a test that stubs the
    subprocess still has to satisfy that guard. Pointing it at the real
    `frontend/` is what the first version did, and it passed on a laptop and
    failed in CI -- the very privileged-environment mistake the guard exists to
    stop. A tmp_path costs nothing and is true everywhere.
    """
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.0"}')
    return tmp_path


def test_a_list_valued_licence_is_not_a_repr(licences, monkeypatch, tmp_path) -> None:
    """license-checker may return `["MIT", "ISC"]`.

    `str()` on that produced `"['MIT', 'ISC']"`, which matches nothing and
    failed the build on a correctly-licensed package.
    """
    payload = json.dumps({"legacy@1.0.0": {"licenses": ["MIT", "ISC"]}})

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=payload, stderr="")

    monkeypatch.setattr(licences.subprocess, "run", fake_run)
    found = licences.licences_of(installed_tree(tmp_path))
    assert found == {"legacy@1.0.0": "MIT OR ISC"}
    assert licences.is_allowed(found["legacy@1.0.0"])


def test_every_publishable_sdk_is_checked(licences) -> None:
    """The gate covers what is published, derived from the tree.

    It checked `frontend` alone at first, leaving the five SDKs that are
    actually redistributed to users ungated. Asserted against a fresh listing
    rather than a literal copy of the script's own list -- comparing a literal
    to a literal is how a seventh SDK slips through with every copy green.
    """
    from_tree = {
        f"sdk/{entry.name}"
        for entry in (ROOT / "sdk").iterdir()
        if entry.is_dir() and (entry / "package-lock.json").is_file()
    }
    assert from_tree, "no SDK has a package-lock.json -- the marker is wrong"
    assert from_tree | {"frontend"} == set(licences.NODE_PACKAGES)
    for relative in licences.NODE_PACKAGES:
        assert (ROOT / relative / "package.json").is_file(), relative


def test_an_uninstalled_tree_is_refused(licences, tmp_path) -> None:
    """No node_modules must fail, not report the root package and pass.

    license-checker exits 0 and emits exactly one entry -- the package
    itself -- for an uninstalled tree, which made the widened gate decorative
    in CI for every closure except the one the job happened to `npm ci`.
    """
    (tmp_path / "package.json").write_text('{"name": "x", "version": "1.0.0"}')
    with pytest.raises(SystemExit) as excinfo:
        licences.licences_of(tmp_path)
    assert "node_modules" in str(excinfo.value)


def test_a_legacy_object_licence_is_normalised(licences, monkeypatch, tmp_path) -> None:
    """`[{"type": "MIT", "url": ...}]` is the oldest manifest form.

    Joining `str(item)` over it produced a Python dict repr, which matches
    nothing -- so the gate blocked a merge on an MIT package.
    """
    payload = json.dumps(
        {"old@1.0.0": {"licenses": [{"type": "MIT", "url": "http://x"}]}}
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=payload, stderr="")

    monkeypatch.setattr(licences.subprocess, "run", fake_run)
    found = licences.licences_of(installed_tree(tmp_path))
    assert found == {"old@1.0.0": "MIT"}
    assert licences.is_allowed(found["old@1.0.0"])


def test_a_mixed_and_or_expression_is_refused(licences) -> None:
    """SPDX precedence is not implemented, so a mixed expression is refused.

    Splitting on " AND " first inverted precedence and accepted
    `MIT AND ISC OR GPL-3.0`. The comment claimed it was rejected; now it is.
    """
    for expression in (
        "MIT AND ISC OR GPL-3.0",
        "GPL-3.0 OR MIT AND ISC",
        "(MIT AND GPL-3.0) OR MIT",
    ):
        assert not licences.is_allowed(expression), expression
