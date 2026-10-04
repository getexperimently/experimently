"""
CUPED's covariate window, against PostgreSQL (#217).

``event_matching.covariate_user_ids`` decides, per user, whether they sent the
covariate event before their assignment:

* the event happened in ``[assigned_at - lookback, assigned_at)``: an event at
  the moment of assignment is excluded (W1);
* the server stored it before the assignment, ``events.updated_at <
  assigned_at`` (the receive guard);
* any tag counts, and one copy is enough: a key-less ``track()`` fanned out to
  three tags is still X = 1 (W5);
* the bounds are bound through ``UTCTimestampString`` (W4), and the
  comparison is naive UTC with naive UTC, which holds under a Los Angeles
  process time zone and session (W3, in ``test_cuped_results_api.py``
  through the route);
* a stored ``created_at`` that cannot be read is skipped and counted, never
  raised.

Every case runs twice: with an assignment time that has a fraction of a
second and one that has none, the two shapes ``created_at`` is stored in.
"""

import ast
import inspect
import textwrap
import uuid
from datetime import datetime, timedelta

import pytest

from backend.app.models.event import Event, EventType
from backend.app.services import event_matching
from backend.app.services.event_matching import covariate_user_ids

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

EVENT = "purchase"


@pytest.fixture
def rows(db_session):
    """Events a test adds here are deleted after it."""
    added = []
    yield added
    db_session.rollback()
    ids = [e.id for e in added]
    if ids:
        db_session.query(Event).filter(Event.id.in_(ids)).delete(
            synchronize_session=False
        )
        db_session.commit()


def _event(
    user_id,
    happened,
    received,
    *,
    event_name=EVENT,
    event_type=None,
    experiment_id=None,
    variant_id=None,
):
    return Event(
        event_type=event_type or event_name,
        event_name=event_name,
        user_id=user_id,
        experiment_id=experiment_id,
        variant_id=variant_id,
        created_at=happened if isinstance(happened, str) else happened.isoformat(),
        updated_at=received,
    )


#: (case, offset of the event from the assignment, expected X)
BOUNDARY = [
    ("at_assignment", timedelta(0), 0),
    ("one_microsecond_before", -timedelta(microseconds=1), 1),
    ("three_hours_before_same_day", -timedelta(hours=3), 1),
    ("previous_day", -timedelta(days=1), 1),
    ("one_microsecond_after", timedelta(microseconds=1), 0),
    ("lookback_start", -timedelta(days=7), 1),
    ("before_lookback", -timedelta(days=7, microseconds=1), 0),
]


@pytest.mark.regression
@pytest.mark.parametrize(
    "fraction", [500_000, 0], ids=["with_fraction", "whole_second"]
)
def test_w1_boundary_table(db_session, rows, fraction):
    # 15:00 UTC, so "three hours before" is the same UTC day.
    assigned = datetime(2026, 9, 20, 15, 0, 0, fraction)
    prefix = uuid.uuid4().hex[:8]
    assigned_at = {}
    for case, offset, _ in BOUNDARY:
        user = f"w1-{prefix}-{case}"
        assigned_at[user] = assigned
        happened = assigned + offset
        rows.append(_event(user, happened, assigned - timedelta(days=8)))
    # A user assigned a day later widens the query's own upper bound, so the
    # boundary is decided by each user's window, not by the query's.
    assigned_at[f"w1-{prefix}-later"] = assigned + timedelta(days=1)
    db_session.add_all(rows)
    db_session.commit()

    found, skipped = covariate_user_ids(db_session, assigned_at, EVENT, 7)

    got = {case: int(f"w1-{prefix}-{case}" in found) for case, _, _ in BOUNDARY}
    assert got == {case: x for case, _, x in BOUNDARY}
    assert skipped == 0


@pytest.mark.regression
@pytest.mark.parametrize(
    "fraction", [500_000, 0], ids=["with_fraction", "whole_second"]
)
def test_receive_guard_stored_after_assignment_is_not_history(
    db_session, rows, fraction
):
    """created_at a day before the assignment, but received after it: X = 0."""
    assigned = datetime(2026, 9, 20, 15, 0, 0, fraction)
    prefix = uuid.uuid4().hex[:8]
    early, backfilled, at = (f"guard-{prefix}-{n}" for n in ("early", "late", "at"))
    happened = assigned - timedelta(days=1)
    rows.extend(
        [
            _event(early, happened, assigned - timedelta(microseconds=1)),
            _event(backfilled, happened, assigned + timedelta(hours=2)),
            _event(at, happened, assigned),
        ]
    )
    db_session.add_all(rows)
    db_session.commit()

    found, _ = covariate_user_ids(
        db_session, dict.fromkeys((early, backfilled, at), assigned), EVENT, 7
    )

    assert found == {early}


@pytest.mark.regression
def test_w5_a_fanned_out_copy_counts_once(db_session, rows, make_experiment):
    """One purchase stored under three tags (two experiments and none): X = 1."""
    assigned = datetime(2026, 9, 20, 15, 0, 0)
    first = make_experiment(name=f"fan-a-{uuid.uuid4().hex[:6]}")
    second = make_experiment(name=f"fan-b-{uuid.uuid4().hex[:6]}")
    user = f"w5-{uuid.uuid4().hex[:8]}"
    happened = assigned - timedelta(days=2)
    received = assigned - timedelta(days=2)
    rows.extend(
        [
            _event(user, happened, received, experiment_id=first.id),
            _event(user, happened, received, experiment_id=second.id),
        ]
    )
    db_session.add_all(rows)
    db_session.commit()

    found, _ = covariate_user_ids(db_session, {user: assigned}, EVENT, 7)

    # Two tagged copies and no untagged one: still history.
    assert found == {user}


def test_only_conversion_events_of_the_name_count(db_session, rows):
    """A variant-view row named after the metric, or another event, is not history."""
    assigned = datetime(2026, 9, 20, 15, 0, 0)
    prefix = uuid.uuid4().hex[:8]
    viewed, other = f"cv-{prefix}-viewed", f"cv-{prefix}-other"
    happened = assigned - timedelta(days=1)
    rows.extend(
        [
            _event(viewed, happened, happened, event_type=EventType.EXPOSURE.value),
            _event(other, happened, happened, event_name="page_view"),
        ]
    )
    db_session.add_all(rows)
    db_session.commit()

    found, _ = covariate_user_ids(
        db_session, dict.fromkeys((viewed, other), assigned), EVENT, 7
    )

    assert found == set()


@pytest.mark.regression
def test_an_unreadable_stored_timestamp_is_skipped_and_counted(db_session, rows):
    """Legacy rows can hold text that is not a timestamp: skipped, never raised.

    The value is written with raw SQL, as legacy rows were: the column's own
    type would refuse it on the way in.
    """
    from sqlalchemy import text

    from backend.app.core.database_config import get_schema_name

    assigned = datetime(2026, 10, 2, 12, 0, 0)
    prefix = uuid.uuid4().hex[:8]
    garbage, good = f"bad-{prefix}", f"good-{prefix}"
    rows.append(
        _event(good, assigned - timedelta(days=1), assigned - timedelta(days=1))
    )
    db_session.add_all(rows)
    db_session.commit()
    bad_id = uuid.uuid4()
    db_session.execute(
        text(
            f"INSERT INTO {get_schema_name()}.events (id, event_type, event_name, user_id, created_at, "
            "updated_at) VALUES (:id, :n, :n, :u, '2026-10-01 garbage', :r)"
        ),
        {"id": bad_id, "n": EVENT, "u": garbage, "r": assigned - timedelta(days=2)},
    )
    db_session.commit()
    rows.append(Event(id=bad_id))

    found, skipped = covariate_user_ids(
        db_session, {garbage: assigned, good: assigned}, EVENT, 7
    )

    assert found == {good}
    assert skipped == 1


def test_users_with_no_history_and_an_empty_input():
    assert covariate_user_ids(None, {}, EVENT, 7) == (set(), 0)
    assert covariate_user_ids(None, {"u": datetime(2026, 1, 1)}, "", 7) == (set(), 0)


def test_w4_every_bound_goes_through_the_columns_type():
    """The window bounds are ORM comparisons on ``Event.created_at``.

    Its ``UTCTimestampString`` type binds a ``datetime`` in the stored format,
    so a bound is never a hand-formatted string or a ``text()`` fragment (a
    ``str(datetime)`` has a space where the column has a ``T``, and loses the
    same-day rows).
    """
    source = textwrap.dedent(inspect.getsource(event_matching.covariate_user_ids))
    tree = ast.parse(source)
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert "text" not in calls
    assert "isoformat" not in calls
    assert "strftime" not in calls
    assert "str" not in {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and any(isinstance(a, ast.Name) and a.id in ("lower", "upper") for a in n.args)
    }
    compared = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and ast.unparse(node.left) == "Event.created_at"
    ]
    assert compared == ["Event.created_at >= lower", "Event.created_at < upper"]
