"""Unit-tree fixtures, shared with the core unit tree.

``backend/tests/unit/conftest.py`` replaces ``logging.getLogger`` for every
unit test (``mock_logging_handler``, autouse).  The modules' unit tests were
written under that fixture and keep it: re-exported here because pytest does
not apply a sibling tree's conftest.
"""

from backend.tests.unit.conftest import mock_logging_handler
