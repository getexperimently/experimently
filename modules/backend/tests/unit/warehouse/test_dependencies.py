"""sqlglot ships with the full image; duckdb is a test tool and never ships.

* ``sqlglot`` is a runtime dependency of the query builder's re-parse, so it
  is pinned in ``modules/requirements.txt`` and its hashed lock, which is what
  the full image installs.  The builder imports it inside a guard that
  refuses every query when it is absent, so a missing pin would not fail
  loudly at import -- it would refuse every analysis.  This file and the
  docker-smoke step are what make it loud.
* ``duckdb`` runs the statements' semantics in the tests.  It is pinned in
  ``modules/requirements-test.txt`` and nowhere an image reads.
"""

from __future__ import annotations

import ast
import re
from importlib import metadata
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[5]
MODULES_APP = ROOT / "modules" / "backend" / "app"
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", re.MULTILINE)


def _pins(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    return {m.group(1).lower(): m.group(2) for m in _PIN.finditer(text)}


def test_sqlglot_is_a_pinned_runtime_dependency_of_the_full_image():
    runtime = _pins(ROOT / "modules" / "requirements.txt")
    lock = _pins(ROOT / "modules" / "requirements.lock")
    assert "sqlglot" in runtime
    assert lock.get("sqlglot") == runtime["sqlglot"]
    assert metadata.version("sqlglot") == runtime["sqlglot"]


def test_duckdb_is_test_only():
    test_pins = _pins(ROOT / "modules" / "requirements-test.txt")
    assert "duckdb" in test_pins
    assert metadata.version("duckdb") == test_pins["duckdb"]
    for shipped in (
        ROOT / "modules" / "requirements.txt",
        ROOT / "modules" / "requirements.lock",
        ROOT / "backend" / "requirements" / "runtime.txt",
        ROOT / "backend" / "requirements" / "runtime.lock",
        ROOT / "backend" / "requirements.txt",
    ):
        assert "duckdb" not in _pins(shipped), shipped


def _imports(path: Path) -> list[tuple[str, bool]]:
    """``(module, guarded)`` for every import; guarded = inside a ``try``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, bool]] = []

    def visit(node: ast.AST, guarded: bool) -> None:
        for child in ast.iter_child_nodes(node):
            inner = guarded or isinstance(node, ast.Try)
            if isinstance(child, ast.Import):
                found.extend((alias.name, inner) for alias in child.names)
            elif isinstance(child, ast.ImportFrom) and child.module:
                found.append((child.module, inner))
            visit(child, inner)

    visit(tree, False)
    return found


def test_no_application_module_imports_duckdb():
    offenders = [
        str(path.relative_to(ROOT))
        for path in MODULES_APP.rglob("*.py")
        for module, _ in _imports(path)
        if module.split(".")[0] == "duckdb"
    ]
    assert offenders == []


def test_sqlglot_is_imported_only_by_the_builder_and_only_guarded():
    uses = [
        (str(path.relative_to(ROOT)), guarded)
        for path in MODULES_APP.rglob("*.py")
        for module, guarded in _imports(path)
        if module.split(".")[0] == "sqlglot"
    ]
    assert uses == [
        ("modules/backend/app/services/warehouse_query_builder.py", True),
        ("modules/backend/app/services/warehouse_query_builder.py", True),
    ]


#: Google's client libraries.  The BigQuery connector signs its own assertion
#: with PyJWT and speaks REST through the warehouse client, so none of these
#: is needed, and each would bring its own HTTP stack and token handling.
GOOGLE_CLIENT_PACKAGES = (
    "google-auth",
    "google-auth-oauthlib",
    "google-api-core",
    "google-cloud-bigquery",
    "google-cloud-core",
)
GOOGLE_CLIENT_MODULES = (
    "google.auth",
    "google.oauth2",
    "google.cloud",
    "google.api_core",
)


def test_no_google_client_library_ships():
    for shipped in (
        ROOT / "modules" / "requirements.txt",
        ROOT / "modules" / "requirements.lock",
        ROOT / "backend" / "requirements" / "runtime.txt",
        ROOT / "backend" / "requirements" / "runtime.lock",
    ):
        pins = _pins(shipped)
        for package in GOOGLE_CLIENT_PACKAGES:
            assert package not in pins, (shipped, package)


def test_no_application_module_imports_a_google_client_library():
    offenders = [
        (str(path.relative_to(ROOT)), module)
        for path in MODULES_APP.rglob("*.py")
        for module, _ in _imports(path)
        if module in GOOGLE_CLIENT_MODULES
        or module.startswith(tuple(m + "." for m in GOOGLE_CLIENT_MODULES))
    ]
    assert offenders == []


def test_the_bigquery_connector_signs_with_pyjwt_from_the_image_lock():
    """PyJWT signs the assertion; it must be in what the image installs."""
    assert "pyjwt" in _pins(ROOT / "backend" / "requirements" / "runtime.lock")
    imported = {m for m, _ in _imports(MODULES_APP / "warehouse" / "bigquery.py")}
    assert "jwt" in imported


#: Snowflake's client libraries.  The Snowflake connector signs its own JWT
#: with PyJWT and speaks the SQL API through the warehouse client, so none of
#: these is needed, and each would bring its own HTTP stack.
SNOWFLAKE_CLIENT_PACKAGES = (
    "snowflake-connector-python",
    "snowflake-sqlalchemy",
    "snowflake-snowpark-python",
)


def test_no_snowflake_client_library_ships():
    for shipped in (
        ROOT / "modules" / "requirements.txt",
        ROOT / "modules" / "requirements.lock",
        ROOT / "backend" / "requirements" / "runtime.txt",
        ROOT / "backend" / "requirements" / "runtime.lock",
    ):
        pins = _pins(shipped)
        for package in SNOWFLAKE_CLIENT_PACKAGES:
            assert package not in pins, (shipped, package)


def test_no_application_module_imports_a_snowflake_client_library():
    offenders = [
        (str(path.relative_to(ROOT)), module)
        for path in MODULES_APP.rglob("*.py")
        for module, _ in _imports(path)
        if module.split(".")[0] == "snowflake"
    ]
    assert offenders == []


def test_the_snowflake_connector_signs_with_pyjwt_from_the_image_lock():
    assert "pyjwt" in _pins(ROOT / "backend" / "requirements" / "runtime.lock")
    imported = {m for m, _ in _imports(MODULES_APP / "warehouse" / "snowflake.py")}
    assert "jwt" in imported
