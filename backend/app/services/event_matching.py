"""
Shared rules for recognising conversion events.

Producers disagree on ``Event.event_type``:

* ``EventService.track_conversion`` writes ``event_type="conversion"`` and
  ``event_name=<metric event name>``.
* The public tracking API (``POST /api/v1/tracking/track``/``batch``) and every
  SDK write the event's own name in both columns (``event_type="purchase"``,
  ``event_name="purchase"``) — ``event_type`` is free text there.

A metric is therefore matched on ``event_name`` only; ``event_type`` is used
just to exclude exposure rows.  Every analysis path (results engine, streaming
results, bandit scheduler, segment breakdowns) must use these helpers so the
same event is counted the same way everywhere.

A binary conversion metric counts **converting users**, not conversion events:
a user assigned to a variant who sent one or more matching conversion events
counts once (#233).  ``count_converting_users`` is that one definition, and
every analysis path that reports ``conversions`` next to a ``sample_size`` of
assigned users must use it (or, in raw SQL, ``CONVERTING_USERS_SQL``), so the
numerator can never exceed the denominator.
"""

from typing import Any, Iterable, List, Optional, Set, Tuple

from sqlalchemy import String, and_, any_, bindparam, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from backend.app.models.assignment import Assignment
from backend.app.models.event import Event, EventType

#: ``event_type`` values that record that a user *saw* a variant, never a conversion.
EXPOSURE_EVENT_TYPES = (EventType.EXPOSURE.value, "experiment_exposure")

#: SQL fragment for raw ``text()`` queries; binds ``:event_name``.
CONVERSION_SQL_PREDICATE = (
    "event_name = :event_name AND event_type NOT IN ('exposure', 'experiment_exposure')"
)

#: Raw-SQL form of ``count_converting_users`` for ``text()`` queries over an
#: ``events e`` alias joined to ``assignments a`` with ``CONVERTING_USERS_JOIN``.
CONVERTING_USERS_SQL = "COUNT(DISTINCT e.user_id)"

#: The join that restricts events to users assigned to the event's variant.
CONVERTING_USERS_JOIN = (
    "a.experiment_id = e.experiment_id "
    "AND a.user_id = e.user_id "
    "AND a.variant_id = e.variant_id"
)


def conversion_event_filter(event_name: Optional[str]):
    """
    SQLAlchemy criterion selecting the conversion events of one metric.

    With a metric ``event_name`` the criterion is
    ``Event.event_name == event_name AND event_type not an exposure``.
    Without one (experiment has no metric rows) it falls back to the legacy
    ``event_type == "conversion"`` convention.
    """
    if not event_name:
        return Event.event_type == EventType.CONVERSION.value
    return and_(
        Event.event_name == event_name,
        Event.event_type.notin_(EXPOSURE_EVENT_TYPES),
    )


def any_conversion_event_filter(event_names: Iterable[Optional[str]]):
    """
    Criterion selecting conversion events for *any* of the given metric names.

    Used for experiment-wide totals.  Falls back to the legacy convention when
    the list is empty.
    """
    names = [name for name in event_names if name]
    if not names:
        return Event.event_type == EventType.CONVERSION.value
    return and_(
        Event.event_name.in_(names),
        Event.event_type.notin_(EXPOSURE_EVENT_TYPES),
    )


#: How many user ids one assignment lookup binds as a single array.
ASSIGNMENT_LOOKUP_CHUNK = 10_000


def _assigned_pairs(
    db: Session, experiment_id: Any, user_ids: Iterable[str]
) -> Set[Tuple[str, str]]:
    """
    ``(variant_id, user_id)`` of the assignments these users have in the experiment.

    The conversion counts below never join ``events`` to ``assignments`` in
    SQL.  Without planner statistics -- a freshly seeded database, before
    autovacuum has analysed it -- PostgreSQL can run that join as a nested
    loop over a sequential scan, which took more than 8 s on 30,000 users in
    CI and blocked the live-results stream (#233).  Instead the converting
    users are read from ``events`` alone, and their assignments are looked up
    here by the unique ``(experiment_id, user_id)`` index, a bounded number of
    ids at a time.
    """
    ids = list(user_ids)
    pairs: Set[Tuple[str, str]] = set()
    for i in range(0, len(ids), ASSIGNMENT_LOOKUP_CHUNK):
        chunk = ids[i : i + ASSIGNMENT_LOOKUP_CHUNK]
        rows = (
            db.query(Assignment.variant_id, Assignment.user_id)
            .filter(
                Assignment.experiment_id == experiment_id,
                Assignment.user_id
                == any_(bindparam("user_ids", chunk, type_=ARRAY(String))),
            )
            .all()
        )
        pairs.update((str(variant_id), str(user_id)) for variant_id, user_id in rows)
    return pairs


def _converters(
    db: Session, experiment_id: Any, variant_id: Any, criterion: Any
) -> List[Tuple[str, Any]]:
    """``(user_id, first matching created_at)`` per user with an event matching
    ``criterion`` tagged with ``variant_id``; read from ``events`` alone."""
    rows = (
        db.query(Event.user_id, func.min(Event.created_at))
        .filter(
            Event.experiment_id == experiment_id,
            Event.variant_id == variant_id,
            criterion,
        )
        .group_by(Event.user_id)
        .all()
    )
    return [(str(user_id), first) for user_id, first in rows]


def _assigned_matching(
    db: Session, experiment_id: Any, variant_id: Any, criterion: Any
) -> List[Tuple[str, Any]]:
    """The users of ``variant_id`` with an event matching ``criterion`` who are
    assigned to that variant."""
    converters = _converters(db, experiment_id, variant_id, criterion)
    pairs = _assigned_pairs(db, experiment_id, (user_id for user_id, _ in converters))
    variant = str(variant_id)
    return [(u, first) for u, first in converters if (variant, u) in pairs]


def _assigned_converters(
    db: Session, experiment_id: Any, variant_id: Any, event_name: Optional[str]
) -> List[Tuple[str, Any]]:
    """The converters of ``variant_id`` who are assigned to that variant."""
    return _assigned_matching(
        db, experiment_id, variant_id, conversion_event_filter(event_name)
    )


def count_assigned_users_matching(
    db: Session, experiment_id: Any, variant_id: Any, criterion: Any
) -> int:
    """
    Number of users assigned to ``variant_id`` with an event matching ``criterion``.

    ``count_converting_users`` with the event criterion supplied by the
    caller: the same users-not-events count, the same restriction to users
    assigned to the variant the event is tagged with, and the same query
    shape (no SQL join of ``events`` to ``assignments``).  The bandit
    scheduler uses it for an experiment with no metric configured, where
    every event other than an experiment view is a success; everything else calls
    ``count_converting_users``.
    """
    return len(_assigned_matching(db, experiment_id, variant_id, criterion))


def count_converting_users(
    db: Session,
    experiment_id: Any,
    variant_id: Any,
    event_name: Optional[str],
) -> int:
    """
    Number of users assigned to ``variant_id`` with at least one conversion.

    This is the numerator of every conversion rate the analysis endpoints
    report: a user who purchased three times counts once, and an event from a
    user with no assignment to that variant does not count, so the result is
    never larger than the variant's assignment count.
    """
    return len(_assigned_converters(db, experiment_id, variant_id, event_name))


def count_converting_users_any(
    db: Session,
    experiment_id: Any,
    event_names: Iterable[Optional[str]],
) -> int:
    """Users in the experiment with a conversion on *any* of the given metrics."""
    rows = (
        db.query(Event.variant_id, Event.user_id)
        .filter(
            Event.experiment_id == experiment_id,
            any_conversion_event_filter(event_names),
        )
        .distinct()
        .all()
    )
    events = {(str(variant_id), str(user_id)) for variant_id, user_id in rows}
    pairs = _assigned_pairs(db, experiment_id, {user_id for _, user_id in events})
    return len({user_id for variant_id, user_id in events & pairs})


def first_conversion_times(
    db: Session,
    experiment_id: Any,
    variant_id: Any,
    event_name: Optional[str],
) -> List[str]:
    """
    The ``created_at`` of each converting user's *first* conversion.

    One entry per user counted by ``count_converting_users``.  Bucketing these
    by day gives the users who converted for the first time that day, so the
    running sum of a daily series equals the converting-user total.
    """
    return [
        first
        for _, first in _assigned_converters(db, experiment_id, variant_id, event_name)
        if first is not None
    ]


def converting_user_ids(
    db: Session,
    experiment_id: Any,
    variant_id: Any,
    event_name: Optional[str],
) -> Set[str]:
    """
    The users ``count_converting_users`` counts, as a set of ids.

    The same definition: a user assigned to ``variant_id`` with at least one
    conversion tagged with that variant.  CUPED's outcome is read with it, so
    its converters are exactly ``/results``' (#217).
    """
    return {
        user_id
        for user_id, _ in _assigned_converters(
            db, experiment_id, variant_id, event_name
        )
    }
