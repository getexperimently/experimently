"""The core model registry must never carry a module's table.

``backend/app/models/__init__.py`` imports the core models only; the modules'
models join ``Base.metadata`` through ``hooks.register_model_module()`` (see
``backend/app/modules_loader.py``).

This is the gate the coupling report (``docs/planning/``, §9) asks for on day
one, because the failure mode is invisible: if any core module imports a
module's model — directly, or by importing a service that does — package
semantics put the module tables straight back on ``Base.metadata`` and
``create_all`` keeps producing them.  Nothing errors; the core build just
quietly ships the modules' schema.

Every assertion runs in a **fresh interpreter**.  It has to: this repository's
own test suite loads the seven module model modules through the seam in
``backend/tests/conftest.py`` so the modules' suites have their tables, so
``Base.metadata`` inside a running pytest session is deliberately polluted.
What matters is what ``import backend.app.models`` produces on its own, which
is what ``db/bootstrap.py`` and alembic's ``env.py`` get.

Unlike ``test_core_boundary.py``, this is a hard gate today — it must be green
now and stay green.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from backend.tests.smoke.modules_manifest import REPO_ROOT, load

pytestmark = pytest.mark.smoke


def _run_in_fresh_interpreter(source: str) -> dict:
    """Run *source* in a new Python process and return the JSON it prints."""
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, (
        f"child interpreter failed ({proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    # The app logs on import; the JSON payload is the last line.
    return json.loads(proc.stdout.strip().splitlines()[-1])


_REGISTRY_PROBE = """
    import json

    from sqlalchemy.orm import configure_mappers

    from backend.app.models import register_core_models

    Base = register_core_models()
    configure_mappers()
    print(json.dumps({
        "tables": sorted(t.split(".")[-1] for t in Base.metadata.tables),
        "unresolved": [],
    }))
"""


class TestCoreModelRegistry:
    def test_manifest_lists_the_module_tables(self):
        """Guard the guard: a manifest we failed to parse must not pass."""
        tables = load().tables
        assert len(tables) >= 12, (
            "modules-manifest.txt's MODULE TABLES section did not parse — the metadata "
            f"assertion below would be vacuous. Parsed: {tables}"
        )

    def test_metadata_holds_no_module_table(self):
        """``Base.metadata`` ∩ MODULE_TABLES == ∅ in a fresh interpreter."""
        module_tables = set(load().tables)
        result = _run_in_fresh_interpreter(_REGISTRY_PROBE)
        found = sorted(module_tables.intersection(result["tables"]))
        assert not found, (
            "backend.app.models registered module tables: "
            f"{found}\n"
            "Something in the core import graph reaches a module's model. "
            "Find it with:\n"
            "  python -X importtime -c 'import backend.app.models' 2>&1 "
            "| grep -E 'workspace|custom_role|sso_config|baa_config|"
            "phi_audit_log|warehouse_connection|integration_config'"
        )

    def test_mappers_configure_without_the_module_models(self):
        """No core relationship or ForeignKey needs a module's table.

        ``configure_mappers()`` inside the probe raises if one does — which is
        exactly what the two ``workspace_id`` ``ForeignKey`` constraints did
        before they were reduced to bare indexed UUID columns.
        """
        result = _run_in_fresh_interpreter(_REGISTRY_PROBE)
        assert result["tables"], "no tables registered at all"

    def test_workspace_id_columns_survive_without_their_foreign_key(self):
        """The columns stay; only the constraints went (report §2)."""
        result = _run_in_fresh_interpreter("""
            import json

            from backend.app.models import register_core_models
            from backend.app.models.experiment import Experiment
            from backend.app.models.feature_flag import FeatureFlag

            register_core_models()
            out = {}
            for name, model in (("experiments", Experiment), ("feature_flags", FeatureFlag)):
                column = model.__table__.columns["workspace_id"]
                out[name] = {
                    "nullable": column.nullable,
                    "indexed": bool(column.index),
                    "foreign_keys": sorted(str(fk.target_fullname) for fk in column.foreign_keys),
                }
            print(json.dumps(out))
        """)
        for table, column in result.items():
            assert column["foreign_keys"] == [], (
                f"{table}.workspace_id still has a ForeignKey "
                f"({column['foreign_keys']}) into the workspaces module's table"
            )
            assert column["nullable"] is True, (
                f"{table}.workspace_id must stay nullable"
            )
            assert column["indexed"] is True, f"{table}.workspace_id must stay indexed"
