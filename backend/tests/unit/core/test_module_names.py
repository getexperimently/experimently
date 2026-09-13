"""The module-name contract: the registration, the API, the dashboard.

Three places have to spell the same ten names and have no other way to agree:
`KNOWN_MODULES` in `backend/app/core/hooks.py`, the names
`modules.register(hooks)` passes to `hooks.register_modules()`, and `MODULES`
in `frontend/src/services/modules.ts`. A typo in any of them is silent — the
dashboard simply hides a tab the deployment has. These tests are the only
thing that would catch it.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from backend.app.core import hooks
from backend.app.core.hooks import KNOWN_MODULES

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
MODULES_TS = REPO_ROOT / "frontend" / "src" / "services" / "modules.ts"
MANIFEST = REPO_ROOT / "modules-manifest.txt"
REGISTER = REPO_ROOT / "modules" / "backend" / "app" / "register.py"


def _dashboard_modules() -> list[str]:
    """The string values of the `MODULES` object in modules.ts, in order."""
    source = MODULES_TS.read_text(encoding="utf-8")
    block = re.search(
        r"export const MODULES = \{(.*?)\}\s*as const;", source, re.DOTALL
    )
    assert block, f"could not find `export const MODULES` in {MODULES_TS}"
    return re.findall(r"^\s*[A-Z_]+:\s*'([^']+)'", block.group(1), re.MULTILINE)


def _provided_modules() -> list[str]:
    """``PROVIDED_MODULES`` from the modules' registration.

    Read with :mod:`ast` rather than imported: ``backend/tests`` must not
    import ``modules.*`` (that is the boundary
    ``backend/tests/smoke/test_core_boundary.py`` enforces), and this check
    wants the literal anyway.
    """
    tree = ast.parse(REGISTER.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = (
            [node.target]
            if isinstance(node, ast.AnnAssign)
            else getattr(node, "targets", [])
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "PROVIDED_MODULES":
                return list(ast.literal_eval(node.value))
    raise AssertionError(f"no PROVIDED_MODULES assignment in {REGISTER}")


@pytest.fixture
def scratch_registry():
    """An empty module registry for the duration, then the real one back."""
    with hooks._lock:
        saved = list(hooks._installed_modules)
        hooks._installed_modules.clear()
    try:
        yield
    finally:
        with hooks._lock:
            hooks._installed_modules.clear()
            hooks._installed_modules.extend(saved)


@pytest.mark.regression
def test_the_dashboard_and_the_backend_name_the_same_modules():
    assert _dashboard_modules() == list(KNOWN_MODULES)


@pytest.mark.regression
@pytest.mark.skipif(not REGISTER.is_file(), reason="core checkout: no modules/")
def test_the_registration_provides_exactly_the_known_modules():
    """The third copy of the list, and the one nothing was checking.

    `PROVIDED_MODULES` is what `modules.register(hooks)` hands to
    `hooks.register_modules()`. `register_modules` rejects a name that is not
    in `KNOWN_MODULES` -- loudly, by failing the whole registration -- but
    nothing catches the other direction: drop a name from `PROVIDED_MODULES`
    and the module is simply never reported installed, so the dashboard hides
    a tab the deployment has and `GET /api/v1/modules` under-reports. Order
    matters too: both lists are read in order by `installed_modules()`.
    """
    assert _provided_modules() == list(KNOWN_MODULES)


def test_module_names_are_lowercase_identifiers():
    """They travel in a JSON response; keep them boring so no layer has to
    escape or case-fold them."""
    for name in KNOWN_MODULES:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name


def test_there_is_one_module_per_manifest_group():
    """`modules-manifest.txt` groups 1..10 are the modules; group 11 is the
    dashboard's implementation directory and 12 the registration. A group
    added without a module name is a group the API cannot report."""
    headings = re.findall(r"^# (\d+)\. (.+)$", MANIFEST.read_text(), re.MULTILINE)
    numbered = [int(n) for n, _title in headings]
    assert numbered == sorted(numbered), f"manifest groups out of order: {numbered}"
    module_groups = [n for n in numbered if n <= len(KNOWN_MODULES)]
    assert len(module_groups) == len(KNOWN_MODULES), (
        f"{len(module_groups)} module groups in modules-manifest.txt but "
        f"{len(KNOWN_MODULES)} names in KNOWN_MODULES"
    )


def test_no_duplicate_names():
    assert len(set(KNOWN_MODULES)) == len(KNOWN_MODULES)


@pytest.mark.parametrize("name", KNOWN_MODULES)
def test_register_modules_accepts_every_known_name(name, scratch_registry):
    hooks.register_modules([name])
    assert hooks.installed_modules() == (name,)


def test_register_modules_refuses_an_unknown_name(scratch_registry):
    """A typo must fail while the registration runs, not turn into a module
    the dashboard never shows."""
    with pytest.raises(ValueError) as excinfo:
        hooks.register_modules(["workspace"])  # singular; the real name is plural
    assert "unknown module name(s) ['workspace']" in str(excinfo.value)
    assert "workspaces" in str(excinfo.value)
    assert hooks.installed_modules() == ()


def test_installed_modules_follow_known_order_and_deduplicate(scratch_registry):
    hooks.register_modules(["split_url", "workspaces"])
    hooks.register_modules(["workspaces"])
    assert hooks.installed_modules() == ("workspaces", "split_url")


def test_reset_clears_the_installed_modules(scratch_registry):
    hooks.register_modules(["sso"])
    saved_signer = hooks.audit_signer
    with hooks._lock:
        saved = (
            list(hooks._router_registrars),
            list(hooks._model_modules),
            list(hooks._tags_metadata),
            dict(hooks._capabilities),
        )
    try:
        hooks.reset()
        assert hooks.installed_modules() == ()
    finally:
        with hooks._lock:
            hooks._router_registrars.extend(saved[0])
            hooks._model_modules.extend(saved[1])
            hooks._tags_metadata.extend(saved[2])
            hooks._capabilities.update(saved[3])
        hooks.set_audit_signer(saved_signer)
