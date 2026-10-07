"""Unit-tree fixtures, shared with the core unit tree.

``backend/tests/unit/conftest.py`` restores the root logger after every unit
test (``restore_root_logger``, autouse).  Re-exported here because pytest does
not apply a sibling tree's conftest.
"""

from backend.tests.unit.conftest import restore_root_logger
