"""Wiring smoke tests for the modules.

The modules' halves of ``backend/tests/smoke/test_wiring.py``: the tests
that import a module's model or service directly.  They lived there marked
``@pytest.mark.modules`` while the modules were still in ``backend/``; after
the move (issue #89) an import of ``modules.backend.app.models.workspace``
from a core file is exactly the crossing ``test_core_boundary.py`` gates, so
they live here instead.  The OpenAPI-path checks (workspaces and warehouse
routes present in the schema) stay in the core file: they import nothing
from the modules package and are skipped there in a core build.

Usage:
    source venv/bin/activate
    export APP_ENV=test TESTING=true
    python -m pytest modules/backend/tests/smoke/test_modules_wiring.py -v
"""

import pytest

pytestmark = pytest.mark.smoke


class TestModuleDatabaseColumns:
    def test_sso_config_model_has_required_columns(self):
        """EP-037 SSO config model wiring check."""
        from modules.backend.app.models.sso_config import SSOConfig

        col_names = {c.key for c in SSOConfig.__table__.columns}
        for required in ("provider_type", "entity_id", "sso_url"):
            assert required in col_names, f"sso_configs.{required} column missing"


class TestModuleServiceImports:
    def test_workspace_service_imports(self):
        from modules.backend.app.services.workspace_service import WorkspaceService

        assert WorkspaceService is not None


class TestModuleModelImports:
    def test_workspace_model_table_name(self):
        from modules.backend.app.models.workspace import Workspace

        assert Workspace.__tablename__ == "workspaces"

    def test_workspace_member_model_table_name(self):
        from modules.backend.app.models.workspace import WorkspaceMember

        assert WorkspaceMember.__tablename__ == "workspace_members"

    def test_workspace_enums_exist(self):
        from modules.backend.app.models.workspace import (
            WorkspaceMemberRole,
            WorkspacePlan,
        )

        assert len(WorkspacePlan) >= 3
        assert len(WorkspaceMemberRole) >= 5
