"""The modules' integration tests restore ``app.dependency_overrides`` too.

The fixture is defined in ``backend/tests/integration/conftest.py`` and only
applies here because this tree's conftest re-exports it (#571).  The core
tree's ``test_dependency_overrides_restored.py`` tests what it does.
"""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def test_the_restoring_fixture_runs_for_every_test_here(request):
    assert "restore_dependency_overrides" in request.fixturenames
