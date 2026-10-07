"""The unit tree's logging: ``caplog`` sees the records code under test emits.

``backend/tests/unit/conftest.py`` once replaced ``logging.getLogger`` with a
mock for every unit test. From pytest 9.1 that left ``caplog`` empty in every
unit test, and twelve tests that read it failed.
"""

import logging

import pytest

# Made at import, as the application's module loggers are.
_PROBE = logging.getLogger("backend.tests.unit.probe")


@pytest.mark.regression
def test_getlogger_is_not_replaced():
    assert logging.getLogger() is logging.root
    assert logging.getLogger("backend.tests.unit.probe") is _PROBE


@pytest.mark.regression
def test_caplog_sees_a_module_loggers_record(caplog):
    _PROBE.warning("probe line")

    assert "probe line" in caplog.text
