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

from typing import Any, Iterable, List, Optional

from sqlalchemy import and_, distinct, func
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


def _assigned_conversions(db: Session, *columns: Any) -> Any:
    """Conversion events joined to the assignment of the same user and variant."""
    return db.query(*columns).join(
        Assignment,
        and_(
            Assignment.experiment_id == Event.experiment_id,
            Assignment.user_id == Event.user_id,
            Assignment.variant_id == Event.variant_id,
        ),
    )


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
    return (
        _assigned_conversions(db, func.count(distinct(Event.user_id)))
        .filter(
            Event.experiment_id == experiment_id,
            Event.variant_id == variant_id,
            conversion_event_filter(event_name),
        )
        .scalar()
        or 0
    )


def count_converting_users_any(
    db: Session,
    experiment_id: Any,
    event_names: Iterable[Optional[str]],
) -> int:
    """Users in the experiment with a conversion on *any* of the given metrics."""
    return (
        _assigned_conversions(db, func.count(distinct(Event.user_id)))
        .filter(
            Event.experiment_id == experiment_id,
            any_conversion_event_filter(event_names),
        )
        .scalar()
        or 0
    )


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
    rows = (
        _assigned_conversions(db, func.min(Event.created_at))
        .filter(
            Event.experiment_id == experiment_id,
            Event.variant_id == variant_id,
            conversion_event_filter(event_name),
        )
        .group_by(Event.user_id)
        .all()
    )
    return [row[0] for row in rows if row[0] is not None]
