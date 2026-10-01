"""``normalize_event_timestamp``: one UTC format, so text order is time order (#235).

Expected strings are written out by hand from the offsets.
"""

import random
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models.event import normalize_event_timestamp
from backend.app.services.event_service import _to_iso_timestamp

pytestmark = [pytest.mark.unit]


@pytest.mark.regression
@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("2026-10-01T01:00:00+02:00", "2026-09-30T23:00:00+00:00"),
        ("2026-09-30T23:00:00-02:00", "2026-10-01T01:00:00+00:00"),
        ("2026-01-01T10:00:00+05:30", "2026-01-01T04:30:00+00:00"),
        ("2026-01-01T05:00:00Z", "2026-01-01T05:00:00+00:00"),
        ("2026-01-01T05:00:00", "2026-01-01T05:00:00+00:00"),
        ("2026-01-01T05:00:00.25+01:00", "2026-01-01T04:00:00.250000+00:00"),
        (
            datetime(2026, 10, 1, 1, 0, tzinfo=timezone(timedelta(hours=2))),
            "2026-09-30T23:00:00+00:00",
        ),
        (datetime(2021, 6, 1, 12, 0, 0), "2021-06-01T12:00:00+00:00"),
    ],
)
def test_timestamps_are_written_as_utc(given, expected):
    assert normalize_event_timestamp(given) == expected
    assert _to_iso_timestamp(given) == expected


def test_normalising_twice_changes_nothing():
    once = normalize_event_timestamp("2026-10-01T01:00:00.5+02:00")
    assert normalize_event_timestamp(once) == once


@pytest.mark.parametrize("bad", ["yesterday", "2026-13-01T00:00:00Z", 1700000000])
def test_an_unreadable_timestamp_is_refused(bad):
    with pytest.raises(ValueError):
        normalize_event_timestamp(bad)


def test_text_order_is_time_order():
    """The format has two shapes (with and without microseconds); sorting the
    normalised strings must sort the instants, across offsets and shapes."""
    rng = random.Random(235)
    base = datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc)
    moments = []
    for _ in range(500):
        instant = base + timedelta(
            seconds=rng.randint(-3, 3), microseconds=rng.choice([0, 1, 500000])
        )
        offset = timezone(timedelta(minutes=rng.choice([-600, -30, 0, 330, 120])))
        moments.append(instant.astimezone(offset))

    by_text = sorted(moments, key=normalize_event_timestamp)

    assert [m.timestamp() for m in by_text] == sorted(m.timestamp() for m in moments)
