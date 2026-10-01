"""Each integration test gets ``app.dependency_overrides`` back as it found it.

``restore_dependency_overrides`` (``backend/tests/integration/conftest.py``)
snapshots the app-global overrides before each test and restores them after
(#571).  These tests run in file order, which is pytest's default: the first
of each pair changes the overrides and does not clean up, the second checks
what it finds.  Without the fixture, ``test_2`` and ``test_4`` fail.
"""

import pytest

from backend.app.main import app

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def _module_dependency():  # pragma: no cover - never resolved
    return "module"


def _test_dependency():  # pragma: no cover - never resolved
    return "test"


def _module_override():  # pragma: no cover - never resolved
    return "module override"


def _test_override():  # pragma: no cover - never resolved
    return "test override"


@pytest.fixture(scope="module")
def module_override():
    """An override installed before the tests, as a module fixture would."""
    app.dependency_overrides[_module_dependency] = _module_override
    yield
    app.dependency_overrides.pop(_module_dependency, None)


@pytest.fixture
def clears_on_teardown():
    """Clears every override on teardown, as the role-client fixtures do."""
    yield
    app.dependency_overrides.clear()


def test_1_installs_an_override_and_leaves_it(module_override):
    app.dependency_overrides[_test_dependency] = _test_override
    assert app.dependency_overrides[_module_dependency] is _module_override


def test_2_the_previous_tests_override_is_gone(module_override):
    assert _test_dependency not in app.dependency_overrides
    assert app.dependency_overrides[_module_dependency] is _module_override


def test_3_a_fixture_clears_everything(module_override, clears_on_teardown):
    app.dependency_overrides[_test_dependency] = _test_override


def test_4_the_module_fixtures_override_is_back(module_override):
    assert app.dependency_overrides.get(_module_dependency) is _module_override
    assert _test_dependency not in app.dependency_overrides
