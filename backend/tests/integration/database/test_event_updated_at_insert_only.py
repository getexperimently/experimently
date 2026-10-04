"""
``events.updated_at`` is set once, on insert, and an ORM update leaves it (#217).

CUPED reads a user's history only if the server stored it before the user
was assigned (``events.updated_at < assigned_at``).  That holds only while
``updated_at`` keeps meaning "received at".  ``BaseModel.updated_at`` carries
``onupdate=datetime.utcnow``, so ``Event`` declares its own column without
it: a future ORM update of an event (re-tagging, scrubbing) must not move the
time later and silently drop that history from every covariate.

The override is Python-side only; the column is unchanged, so autogenerate
stays empty (``test_autogenerate_is_empty.py``) and there is no migration.
"""

import uuid
from datetime import datetime, timedelta

import pytest

from backend.app.models.event import Event

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]


def test_the_event_column_has_no_onupdate():
    column = Event.__table__.c.updated_at
    assert column.onupdate is None
    assert column.default is not None


@pytest.mark.regression
def test_an_orm_update_of_an_event_leaves_updated_at_as_it_was(db_session):
    received = datetime.utcnow() - timedelta(days=3)
    event = Event(
        event_type="purchase",
        event_name="purchase",
        user_id=f"insert-only-{uuid.uuid4().hex[:10]}",
        created_at=received.isoformat(),
        updated_at=received,
    )
    db_session.add(event)
    db_session.commit()
    try:
        event.event_metadata = {"scrubbed": True}
        event.value = 2.0
        db_session.commit()
        db_session.refresh(event)

        assert event.value == 2.0
        assert event.updated_at == received
    finally:
        db_session.rollback()
        db_session.query(Event).filter(Event.id == event.id).delete(
            synchronize_session=False
        )
        db_session.commit()
