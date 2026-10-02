"""``User`` declares ``ix_users_email_lower`` once, however often it is read (#343).

``__table_args__`` is a ``declared_attr``: every read after mapping runs it
again, and an ``Index`` over a mapped column attaches itself to the table as it
is built.  Built naively, one read of ``User.__table_args__`` (several model
tests do exactly that) left the table with two indexes of the same name, and
the next ``create_all`` -- the test database's, a fresh bootstrap's -- failed
with ``relation "ix_users_email_lower" already exists``.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from backend.app.models.user import EMAIL_LOWER_INDEX, User

pytestmark = [pytest.mark.unit]


def _named() -> list:
    return [i for i in User.__table__.indexes if i.name == EMAIL_LOWER_INDEX]


@pytest.mark.regression
def test_reading_table_args_does_not_add_a_second_index():
    (index,) = _named()
    for _ in range(3):
        args = User.__table_args__
        assert args[0] is index
    assert _named() == [index]


def test_the_index_is_declared_in_table_args_beside_the_schema():
    args = User.__table_args__
    assert len(args) == 2
    assert args[0].name == EMAIL_LOWER_INDEX and args[0].unique
    assert args[1] == {"schema": User.__table__.schema}
    ddl = str(CreateIndex(args[0]).compile(dialect=postgresql.dialect()))
    assert ddl.startswith(f"CREATE UNIQUE INDEX {EMAIL_LOWER_INDEX} ON ")
    assert ddl.endswith("users (lower(email))")
