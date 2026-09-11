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
"""

from typing import Iterable, Optional

from sqlalchemy import and_

from backend.app.models.event import Event, EventType

#: ``event_type`` values that record that a user *saw* a variant, never a conversion.
EXPOSURE_EVENT_TYPES = (EventType.EXPOSURE.value, "experiment_exposure")

#: SQL fragment for raw ``text()`` queries; binds ``:event_name``.
CONVERSION_SQL_PREDICATE = (
    "event_name = :event_name "
    "AND event_type NOT IN ('exposure', 'experiment_exposure')"
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
