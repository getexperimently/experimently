"""The Community/Enterprise boundary: no CE file may reach an EE module.

Reads ``ee-manifest.txt`` and walks the AST of every Python file under
``backend/{app,scripts,lambda,tests}`` that the manifest does *not* list,
failing on three kinds of crossing:

1. **imports** — ``import backend.app.services.sso_service``,
   ``from backend.app.models.workspace import Workspace``, relative forms, and
   the post-move ``ee.``-prefixed spellings;
2. **string literals naming an Enterprise module** — ``patch()`` targets,
   ``monkeypatch.setattr`` targets, ``importlib.import_module`` arguments,
   dotted-path settings.  *Every* string constant is inspected, not just call
   arguments: ``backend/tests/integration/api/test_hipaa_api.py`` makes 38
   ``patch()`` calls of which only 13 pass a literal — the rest go through
   class-level constants (``self._SVC_CREATE``), and a test that looked only at
   call arguments would pass that file while it is still fully EE-coupled
   (``docs/planning/ee-coupling-report.md`` §7).  Module- and class-level
   ``NAME = "..."`` assignments are additionally resolved so that the *report*
   names the ``patch()`` call site, not only the constant;
3. **schema** — ``Base.metadata.tables`` intersecting the manifest's EE tables.

STATUS: EXPECTED TO FAIL.  Nothing has moved to ``ee/`` yet (issue #89), so the
Community tree still imports Enterprise modules on purpose — ``api/api.py``
mounts the eleven unmoved Enterprise routers, ``tests/conftest.py`` creates
their tables, and 40-odd Enterprise test files sit in ``backend/tests``.  The
failures below are the remaining work list, printed file by file.

The tests are therefore ``xfail(strict=False)``: they report, they do not
block.  **When issue #89 lands and the files move to ``ee/``, delete the
``pytestmark`` xfail below and this becomes a hard gate.**  Do not weaken an
assertion to make it pass — the only legitimate way to green is to cut the
crossing.
"""

from __future__ import annotations

import ast
import pathlib
import textwrap
from collections import defaultdict
from typing import Dict, Iterable, Iterator, List, NamedTuple, Optional, Set, Tuple

import pytest

from backend.tests.smoke.ee_manifest import REPO_ROOT, load

# ---------------------------------------------------------------------------
# Flip this to a hard gate when issue #89 moves the Enterprise files to ee/:
# delete the two `pytest.mark.xfail` marks below (keep `pytest.mark.smoke`).
# ---------------------------------------------------------------------------
_EXPECTED_TO_FAIL = pytest.mark.xfail(
    strict=False,
    reason=(
        "Enterprise modules have not moved to ee/ yet (issue #89); the "
        "crossings listed in the failure message are the remaining work."
    ),
)

pytestmark = pytest.mark.smoke

#: Trees that must contain no Community -> Enterprise reference.
SCAN_ROOTS = ("backend/app", "backend/scripts", "backend/lambda", "backend/tests")

#: Files whose whole purpose is to name Enterprise paths.
SELF_REFERENTIAL = {
    "backend/tests/smoke/ee_manifest.py",
    "backend/tests/smoke/test_ce_boundary.py",
    "backend/tests/smoke/test_core_model_registry.py",
}


class Crossing(NamedTuple):
    path: str
    line: int
    kind: str  # "import" | "literal"
    detail: str
    target: str


# ---------------------------------------------------------------------------
# Manifest -> matchers
# ---------------------------------------------------------------------------


def _manifest():
    return load()


def _ee_module_matcher(manifest) -> Tuple[Set[str], Tuple[str, ...]]:
    """Return ``(exact modules, dotted directory prefixes)``."""
    exact = manifest.module_paths()
    prefixes = []
    for _repo_path, dotted in manifest.path_prefixes():
        if not dotted.startswith(("backend.", "infrastructure.", "ee.")):
            continue
        prefixes.append(dotted + ".")
        prefixes.append("ee." + dotted + ".")
    return exact, tuple(sorted(set(prefixes)))


def _match_module(
    dotted: str, exact: Set[str], prefixes: Tuple[str, ...]
) -> Optional[str]:
    """The Enterprise module *dotted* names, or None."""
    if not dotted:
        return None
    if dotted in exact:
        return dotted
    for prefix in prefixes:
        if dotted.startswith(prefix):
            return prefix.rstrip(".")
    # A dotted path *into* an EE module: "...hipaa_service.HIPAAService.create".
    parts = dotted.split(".")
    for cut in range(len(parts) - 1, 1, -1):
        candidate = ".".join(parts[:cut])
        if candidate in exact:
            return candidate
    return None


def _match_literal(
    value: str, exact: Set[str], prefixes: Tuple[str, ...]
) -> Optional[str]:
    """The Enterprise module a string literal names, or None.

    Accepts both dotted module paths (``patch()`` targets) and repository
    paths (``backend/app/services/sso_service.py``).
    """
    if not value or len(value) < len("backend.app.x"):
        return None
    candidate = value.strip()
    if "/" in candidate:
        candidate = candidate.removesuffix(".py").replace("/", ".")
    if not candidate.startswith(("backend.", "infrastructure.", "ee.")):
        return None
    return _match_module(candidate, exact, prefixes)


# ---------------------------------------------------------------------------
# AST walking
# ---------------------------------------------------------------------------


def _module_name_for(path: pathlib.Path) -> str:
    """Dotted module name of *path*, relative to the repository root."""
    rel = path.relative_to(REPO_ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)


def _resolve_relative(module: Optional[str], level: int, path: pathlib.Path) -> str:
    """Absolute dotted path for a ``from . import x`` style import."""
    own = _module_name_for(path).split(".")
    if path.name != "__init__.py":
        own = own[:-1]
    base = own[: len(own) - (level - 1)] if level > 1 else own
    return ".".join([*base, module] if module else base)


def _string_constants(tree: ast.AST) -> Iterator[Tuple[int, str]]:
    """Every string constant in *tree*, including f-string literal parts."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    yield node.lineno, piece.value


def _string_symbols(tree: ast.AST) -> Dict[str, str]:
    """Module- and class-level ``NAME = "literal"`` assignments.

    This is the ``test_hipaa_api.py`` case: ``_SVC_CREATE`` is defined on the
    test class and every ``patch(self._SVC_CREATE)`` reaches Enterprise through
    it.  Both the bare name and the qualified ``Class._NAME`` spelling are
    recorded so a ``self._X`` / ``TestFoo._X`` reference resolves.
    """
    symbols: Dict[str, str] = {}

    def record(name: str, value: str, qualifier: Optional[str]) -> None:
        symbols[name] = value
        if qualifier:
            symbols[f"{qualifier}.{name}"] = value

    def scan(body: Iterable[ast.stmt], qualifier: Optional[str]) -> None:
        for node in body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            record(target.id, node.value.value, qualifier)
            elif isinstance(node, ast.AnnAssign) and isinstance(
                node.value, ast.Constant
            ):
                if isinstance(node.value.value, str) and isinstance(
                    node.target, ast.Name
                ):
                    record(node.target.id, node.value.value, qualifier)
            elif isinstance(node, ast.ClassDef):
                scan(node.body, node.name)

    scan(getattr(tree, "body", []), None)
    return symbols


def _attribute_path(node: ast.AST) -> Optional[str]:
    """Dotted source spelling of ``a.b.c`` / ``self._X``, or None."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


_PATCH_CALLS = {"patch", "setattr", "import_module", "patch.object"}


def _indirect_targets(
    tree: ast.AST, symbols: Dict[str, str]
) -> Iterator[Tuple[int, str, str]]:
    """``patch(self._X)`` style calls resolved through *symbols*.

    Yields ``(lineno, source spelling, resolved literal)``.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = _attribute_path(node.func) or ""
        if func.split(".")[-1] not in _PATCH_CALLS:
            continue
        for arg in node.args:
            spelling = _attribute_path(arg)
            if not spelling:
                continue
            # `self._X` / `TestFoo._X` / `_X`
            for key in (
                spelling,
                spelling.split(".", 1)[-1],
                spelling.rsplit(".", 1)[-1],
            ):
                if key in symbols:
                    yield node.lineno, spelling, symbols[key]
                    break


def _iter_scanned_files(manifest) -> Iterator[pathlib.Path]:
    """Community Python files: everything under SCAN_ROOTS the manifest omits."""
    ee_files = {REPO_ROOT / p for p in manifest.paths}
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in SELF_REFERENTIAL:
                continue
            if path in ee_files:
                continue  # an Enterprise file may reference Enterprise modules
            if any(parent in ee_files for parent in path.parents):
                continue
            yield path


def _collect_crossings() -> Tuple[List[Crossing], List[Crossing]]:
    """Return ``(import crossings, literal crossings)`` across the CE tree."""
    manifest = _manifest()
    exact, prefixes = _ee_module_matcher(manifest)
    imports: List[Crossing] = []
    literals: List[Crossing] = []

    for path in _iter_scanned_files(manifest):
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - a broken file is its own bug
            imports.append(
                Crossing(rel, exc.lineno or 0, "import", f"unparseable: {exc}", "")
            )
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    hit = _match_module(alias.name, exact, prefixes)
                    if hit:
                        imports.append(
                            Crossing(
                                rel, node.lineno, "import", f"import {alias.name}", hit
                            )
                        )
            elif isinstance(node, ast.ImportFrom):
                base = (
                    _resolve_relative(node.module, node.level, path)
                    if node.level
                    else (node.module or "")
                )
                hit = _match_module(base, exact, prefixes)
                if hit:
                    names = ", ".join(a.name for a in node.names)
                    imports.append(
                        Crossing(
                            rel,
                            node.lineno,
                            "import",
                            f"from {base} import {names}",
                            hit,
                        )
                    )
                    continue
                for alias in node.names:
                    sub = f"{base}.{alias.name}" if base else alias.name
                    hit = _match_module(sub, exact, prefixes)
                    if hit:
                        imports.append(
                            Crossing(
                                rel,
                                node.lineno,
                                "import",
                                f"from {base} import {alias.name}",
                                hit,
                            )
                        )

        seen: Set[Tuple[int, str]] = set()
        for lineno, value in _string_constants(tree):
            hit = _match_literal(value, exact, prefixes)
            if hit and (lineno, value) not in seen:
                seen.add((lineno, value))
                literals.append(Crossing(rel, lineno, "literal", repr(value), hit))

        symbols = _string_symbols(tree)
        for lineno, spelling, value in _indirect_targets(tree, symbols):
            hit = _match_literal(value, exact, prefixes)
            if hit and (lineno, value) not in seen:
                seen.add((lineno, value))
                literals.append(
                    Crossing(rel, lineno, "literal", f"{spelling} -> {value!r}", hit)
                )

    return imports, literals


def _report(title: str, crossings: List[Crossing]) -> str:
    by_file: Dict[str, List[Crossing]] = defaultdict(list)
    for crossing in crossings:
        by_file[crossing.path].append(crossing)
    lines = [
        f"{title}: {len(crossings)} crossing(s) in {len(by_file)} file(s).",
        "",
        "Each line is a Community file reaching an Enterprise module listed in",
        "ee-manifest.txt. Cut the crossing (a hook, a move, or a deletion) —",
        "do not relax this test.",
        "",
    ]
    for rel in sorted(by_file):
        hits = by_file[rel]
        lines.append(f"  {rel}  ({len(hits)})")
        for crossing in sorted(hits, key=lambda c: c.line)[:8]:
            lines.append(
                f"      :{crossing.line}  {crossing.detail}   -> {crossing.target}"
            )
        if len(hits) > 8:
            lines.append(f"      ... and {len(hits) - 8} more")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_manifest_is_readable():
    """Hard gate: a manifest we cannot parse makes every check below vacuous."""
    manifest = _manifest()
    assert manifest.paths, "ee-manifest.txt listed no paths"
    assert len(manifest.tables) >= 12, (
        f"EE TABLES section did not parse: {manifest.tables}"
    )
    exact, _prefixes = _ee_module_matcher(manifest)
    assert "backend.app.services.sso_service" in exact
    assert "ee.backend.app.services.sso_service" in exact


@pytest.mark.enterprise
@pytest.mark.regression
def test_every_manifest_path_exists():
    """A manifest entry that resolves to nothing silently shrinks the boundary.

    Enterprise-only by construction: a Community build has deleted every path
    the manifest names, so the question makes no sense there.

    Two `ee/`-prefixed entries once named files that did not exist anywhere,
    so the licence-gate group protected nothing — and the scanner, which
    derives module names from these paths, had two dead matchers.
    """
    manifest = _manifest()
    missing = [p for p in manifest.paths if not (REPO_ROOT / p).exists()]
    assert not missing, (
        "ee-manifest.txt names paths that do not exist:\n  "
        + "\n  ".join(missing)
        + "\n\nEntries are repository-relative and pre-move (no `ee/` prefix "
        "until the physical move lands)."
    )


def test_manifest_paths_are_pre_move():
    """The format is explicit: paths as the tree sits today, so the boundary
    test works before the `git mv` to `ee/`."""
    manifest = _manifest()
    premature = [p for p in manifest.paths if p.startswith("ee/")]
    assert not premature, (
        "ee-manifest.txt lists post-move paths; it documents its own format as "
        f"pre-move: {premature}"
    )


def test_string_scanner_resolves_class_level_constants():
    """Hard gate on the scanner itself — the trap named in report §7.

    ``backend/tests/integration/api/test_hipaa_api.py`` makes 38 ``patch()``
    calls and only 13 pass a literal; the other 25 go through class-level
    constants.  A scanner that inspected call arguments alone would call that
    file clean.  The snippet below is that shape in miniature: the constant
    itself must be found, and the ``patch(self._SVC)`` call site must be
    reported too, so the failure message points at the line to change.
    """
    source = textwrap.dedent(
        """
        from unittest.mock import patch


        class TestSomething:
            _SVC = "backend.app.services.sso_service.SSOService.create"

            def test_it(self):
                with patch(self._SVC):
                    pass
        """
    )
    tree = ast.parse(source)
    exact, prefixes = _ee_module_matcher(_manifest())

    direct = [
        v for _line, v in _string_constants(tree) if _match_literal(v, exact, prefixes)
    ]
    assert direct, "the class-level constant itself was not detected"

    symbols = _string_symbols(tree)
    assert "_SVC" in symbols and "TestSomething._SVC" in symbols

    indirect = [
        (line, spelling)
        for line, spelling, value in _indirect_targets(tree, symbols)
        if _match_literal(value, exact, prefixes)
    ]
    assert indirect == [(9, "self._SVC")], (
        f"patch(self._SVC) was not resolved through the class constant: {indirect}"
    )


#: URL prefixes owned by the Enterprise routers listed in ee-manifest.txt
#: (sections 2, 5, 6, 7, 8, 9 and 1).  ``/compliance`` is absent on purpose:
#: ``GET /compliance/audit-events`` is Community and must keep answering.
_ENTERPRISE_PREFIXES = (
    "/workspaces",
    "/hipaa",
    "/rbac",
    "/counters",
    "/etl",
    "/warehouse",
    "/integrations",
    "/auth/sso",
)


def _router_paths(router) -> Iterator[str]:
    """Every path *router* serves.

    FastAPI >= 0.141 does not flatten ``include_router`` calls: it keeps a lazy
    ``_IncludedRouter`` entry with no ``.path``, whose
    ``effective_route_contexts`` carry the fully prefixed paths.  Both shapes
    are handled, exactly as ``test_wiring.py::_iter_http_routes`` does.
    """
    from fastapi.routing import APIRoute

    for route in router.routes:
        if isinstance(route, APIRoute):
            yield route.path
            continue
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            contexts = contexts() if callable(contexts) else contexts
            for ctx in contexts:
                yield ctx.path
        elif hasattr(route, "path"):
            yield route.path


def test_register_core_routers_mounts_no_enterprise_route():
    """Hard gate on the router seam.

    The Enterprise routers are still mounted by the application (through
    ``_register_unmoved_enterprise_routers``), but they must arrive there and
    nowhere else: ``register_core_routers`` is what a Community build calls,
    and it alone has to yield a Community-only surface.
    """
    from fastapi import APIRouter

    from backend.app.api.api import register_core_routers

    router = APIRouter()
    register_core_routers(router)
    paths = set(_router_paths(router))
    leaked = sorted(
        path
        for path in paths
        for prefix in _ENTERPRISE_PREFIXES
        if path == prefix or path.startswith(prefix + "/")
    )
    assert not leaked, f"register_core_routers mounted Enterprise routes: {leaked}"
    assert any(path.startswith("/experiments") for path in paths), (
        "register_core_routers mounted no Community routes at all"
    )


@_EXPECTED_TO_FAIL
def test_no_community_file_imports_an_enterprise_module():
    imports, _literals = _collect_crossings()
    if imports:
        print("\n" + _report("CE -> EE imports", imports))
        pytest.fail(_report("CE -> EE imports", imports))


@_EXPECTED_TO_FAIL
def test_no_community_file_names_an_enterprise_module_in_a_string():
    _imports, literals = _collect_crossings()
    if literals:
        print("\n" + _report("CE -> EE string literals", literals))
        pytest.fail(_report("CE -> EE string literals", literals))


def test_metadata_holds_no_enterprise_table():
    """Mirrors the hard gate in ``test_core_model_registry.py``.

    It is in this file too so that one test module answers "is the boundary
    clean?" end to end.  A hard gate, not an xfail: it probes a fresh
    interpreter, so it is order-independent, and it has passed since
    ``models/__init__.py`` stopped importing the Enterprise models.  (It was
    marked ``xfail(strict=False)`` with the two above, which meant it XPASSed
    every run and could never turn CI red.)
    """
    from backend.tests.smoke.test_core_model_registry import (
        _REGISTRY_PROBE,
        _run_in_fresh_interpreter,
    )

    ee_tables = set(_manifest().tables)
    result = _run_in_fresh_interpreter(_REGISTRY_PROBE)
    found = sorted(ee_tables.intersection(result["tables"]))
    assert not found, f"Community Base.metadata carries Enterprise tables: {found}"
