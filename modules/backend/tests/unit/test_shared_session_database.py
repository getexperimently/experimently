"""One pytest session builds the test database once, in either tree.

``modules/backend/tests/conftest.py`` re-exports the core session fixtures --
``test_db`` above all -- because pytest applies a conftest only to its own
directory path and ``backend/tests/conftest.py`` is a sibling, not an ancestor.
Re-exporting does not share the *cache*: pytest builds one FixtureDef per
conftest that defines the name, and session scope caches per FixtureDef.  Both
trees are in ``testpaths``, so any session that spans them crosses from one to
the other mid-session and used to enter the fixture body a second time:
``pg_terminate_backend()`` on every connection to the database, ``DROP
DATABASE``, ``CREATE DATABASE``, ~50 tables rebuilt -- underneath everything
the first half had open.  ``make test`` hides it (separate sessions); an IDE
run, ``pytest -k`` across both trees, or ``pytest backend/tests/unit
modules/backend/tests`` does not.
"""

from __future__ import annotations

import pytest

from backend.tests import conftest as core_conftest

# No `modules` marker: nothing in this tree carries one.  A core build has no
# `modules/` directory at all, so this file does not exist there, and the
# conftest beside it exits the session when the registration is missing.


@pytest.mark.regression
def test_the_session_database_is_built_once(test_db):
    """Two assertions, because either alone leaves a hole.

    The counter catches the real bug -- in a session that spans both trees it
    was 2 -- but only in such a session.  Entering the fixture body again
    catches the guard's removal in any session, and does it the way the second
    FixtureDef would: the same function object, called a second time.
    """
    assert core_conftest._SESSION_DB_BUILDS == 1, (
        "the test database was built more than once in this session: "
        "a second session-scoped FixtureDef ran the builder again and "
        "dropped the database under the tests that were already using it"
    )

    # pytest wraps a fixture function so that calling it is an error; the
    # generator underneath is what a second FixtureDef would run.
    builder = getattr(core_conftest.test_db, "__wrapped__", core_conftest.test_db)
    second = builder()
    try:
        assert next(second) is test_db, (
            "entering test_db a second time built a new engine instead of "
            "handing back the one this session is using"
        )
        assert core_conftest._SESSION_DB_BUILDS == 1
    finally:
        second.close()


def test_the_modules_conftest_reexports_the_core_fixture(test_db):
    """The re-export is by name, so the two FixtureDefs wrap one function.

    That is what makes the module global in ``backend/tests/conftest.py``
    shared between them, and therefore what makes the guard work.
    """
    from modules.backend.tests import conftest as modules_conftest

    assert modules_conftest.test_db is core_conftest.test_db
    assert core_conftest._SESSION_ENGINE is test_db
