"""The module docstrings that describe the integration webhooks say what the API does.

The same sweep as `backend/tests/unit/docs/test_integrations_docs_claims.py`,
over the three module files whose docstrings describe the webhooks (one of them
is also the OpenAPI description of the Salesforce route). It lives here, not in
the core test, because a core file may not name a module path
(`backend/tests/smoke/test_core_boundary.py`).
"""

from __future__ import annotations

import pytest

from backend.tests.unit.docs.test_integrations_docs_claims import REPO_ROOT, _hits

pytestmark = [pytest.mark.unit, pytest.mark.regression]

MODULE_FILES = (
    "modules/backend/app/api/v1/endpoints/integrations.py",
    "modules/backend/app/services/integrations/salesforce_service.py",
    "modules/backend/app/services/integrations/webhook_auth.py",
)


def test_the_module_docstrings_say_what_the_api_does() -> None:
    paths = [REPO_ROOT / rel for rel in MODULE_FILES]
    missing = [rel for rel, path in zip(MODULE_FILES, paths) if not path.is_file()]
    assert not missing, f"the sweep did not find {missing}: it is broken, not clean"
    hits = list(_hits(paths))
    assert not hits, "\n".join(hits)
