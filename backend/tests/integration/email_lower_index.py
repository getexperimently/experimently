"""Build a case pair in the shared test schema, and prove the index came back.

Not a test module.  Since #343 the database refuses two accounts whose
addresses differ only in letter case (``ix_users_email_lower``).  The few
tests that are *about* such a pair -- what an existing database built by an
administrator, SQL or a restore may hold -- build it inside
:func:`without_email_lower_index`, which drops the index, and in ``finally``
deletes the rows the test registered and re-creates the index from the
model's own definition.

``db_session`` commits for real (there is no outer transaction to roll back),
so a drop that is not undone stays dropped for the rest of the session and
every later test that relies on the index runs without it.
:func:`email_lower_index_survives_the_session` is the backstop: a
session-scoped autouse fixture -- import it into each module that uses the
context manager -- whose teardown asserts the index is in the test schema
with exactly its definition.
"""

from __future__ import annotations

import contextlib
from typing import Iterator, List

import pytest
from sqlalchemy import Index, text
from sqlalchemy.orm import Session

from backend.app.models.user import User

INDEX = "ix_users_email_lower"


def _index() -> Index:
    (index,) = [i for i in User.__table__.indexes if i.name == INDEX]
    return index


def indexdef(connection, schema: str) -> str | None:
    """``pg_indexes.indexdef`` of the index in *schema*, or ``None``."""
    return connection.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = :schema AND tablename = 'users' "
            "AND indexname = :index"
        ),
        {"schema": schema, "index": INDEX},
    ).scalar()


def expected_indexdef(schema: str) -> str:
    return (
        f"CREATE UNIQUE INDEX {INDEX} ON {schema}.users "
        "USING btree (lower((email)::text))"
    )


@contextlib.contextmanager
def without_email_lower_index(db_session: Session) -> Iterator[List]:
    """Drop the index; yield a list for the ids of the rows the test adds.

    On the way out -- pass or fail -- those rows are deleted and the index is
    re-created.  A row the test adds and does not register blocks the
    re-create, which fails loudly here rather than later.
    """
    added: List = []
    db_session.rollback()
    _index().drop(db_session.connection())
    db_session.commit()
    try:
        yield added
    finally:
        db_session.rollback()
        if added:
            db_session.query(User).filter(User.id.in_(added)).delete(
                synchronize_session=False
            )
            db_session.commit()
        _index().create(db_session.connection())
        db_session.commit()


def _oid(db_session: Session, name: str) -> int:
    return db_session.execute(
        text(
            "SELECT c.oid FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = :name"
        ),
        {"schema": User.__table__.schema, "name": name},
    ).scalar_one()


def make_the_exact_email_index_fire_first(db_session: Session) -> None:
    """Order the two unique indexes as on a database the migration upgraded.

    PostgreSQL checks unique indexes in OID order, so an identical-case
    duplicate is reported by whichever of the two was created first.  On a
    migrated database that is the exact index on ``email`` (the lower index is
    added later); a ``create_all`` schema may have them the other way round,
    and then an identical-case collision names ``ix_users_email_lower`` too --
    which would let a 409 mapping keyed on that one name pass.  Re-creating
    the lower index (no row changes) makes it the newer of the two.
    """
    db_session.rollback()
    exact = db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = :schema AND tablename = 'users' "
            "AND indexdef LIKE 'CREATE UNIQUE INDEX % USING btree (email)'"
        ),
        {"schema": User.__table__.schema},
    ).scalar_one()
    if _oid(db_session, INDEX) < _oid(db_session, exact):
        _index().drop(db_session.connection())
        _index().create(db_session.connection())
        db_session.commit()
    assert _oid(db_session, exact) < _oid(db_session, INDEX)
    db_session.rollback()


@pytest.fixture(scope="session", autouse=True)
def email_lower_index_survives_the_session(test_db) -> Iterator[None]:
    """Teardown: the index is in the test schema, exactly as the model has it.

    Depends on ``test_db`` so that it is set up after it and torn down before
    the database is dropped.
    """
    yield
    schema = User.__table__.schema
    with test_db.connect() as conn:
        found = indexdef(conn, schema)
    assert found == expected_indexdef(schema), (
        f"{INDEX} is missing or changed in {schema} at the end of the session: "
        "a test dropped it and did not re-create it"
    )
