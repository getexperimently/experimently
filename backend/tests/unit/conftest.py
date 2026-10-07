"""Fixtures for every unit test.

``modules/backend/tests/unit/conftest.py`` re-exports them for the modules'
unit tests, since pytest does not apply a sibling tree's conftest.
"""

import logging

import pytest


@pytest.fixture(autouse=True)
def restore_root_logger():
    """Hand the root logger to the next test as this one found it.

    Code under test reconfigures the root logger: ``setup_logging()`` and
    ``configure_logging()`` replace its handlers and set its level, and
    importing ``backend.app.core.logging`` or ``backend.app.main`` runs one of
    them. The handlers and the level are put back after each test.

    ``logging.getLogger`` itself is not replaced. ``caplog`` attaches its
    handler to whatever ``logging.getLogger()`` returns, so a mock there leaves
    ``caplog`` empty in every unit test (pytest 9.1 and later).
    """
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
